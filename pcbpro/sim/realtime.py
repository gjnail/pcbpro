"""Real-time audio model of a board (the nodal DK method).

The circuit is built exactly as for offline rendering (guitar source with pickup impedance on the input net, 1 M amp
load on the output). Every linear part (resistors, pots at their current setting, capacitors and inductors as
trapezoidal companions at the audio step) is folded into constant matrices once; per sample only the nonlinear
devices (diodes, BJTs, FETs, op-amps, triodes, pentodes) are solved, with a small Newton iteration over their port
voltages:

    v     = Dz z + Du u + d0 + F i(v)        nonlinear port voltages (solved per sample)
    z'    = Az z + Au u + a0 + Ai i(v)       capacitor / inductor history (state update)
    y     = Yz z + Yu u + y0 + Yi i(v)       output voltage

Other nonlinear blocks (regulators, sensors, ...) are linearised around the DC operating point and event devices
are frozen in their operating-point state, which is what they do in an audio path. The per-sample loop is compiled
with numba; ``oversample`` runs the circuit at 2x / 4x the audio rate with polyphase anti-alias filters.
"""
from __future__ import annotations

import math
import os

import numpy as np

from . import ics
from .devices import BJT, FET, GMIN, VT, Behavioral, Capacitor, CapacitorGroup, Diode, EventDevice, Inductor, \
    VoltageSource, Waveform
from .tubes import KNEE_W, PLATE_FLOOR, VT_LIMIT, Pentode, Triode


def _numba():
    """Import numba with a writable cache folder (the frozen app's own folder may be read-only)."""
    if "NUMBA_CACHE_DIR" not in os.environ:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        os.environ["NUMBA_CACHE_DIR"] = os.path.join(base, "PCBPro", "numba_cache")
    import numba
    return numba


nb = _numba()
# numba's on-disk cache needs the .py sources, which a frozen (PyInstaller) build does not ship: compile at start there
_CACHE = not getattr(__import__("sys"), "frozen", False)


def njit(*args, **kw):
    kw["cache"] = kw.get("cache", True) and _CACHE
    return nb.njit(*args, **kw)

T_DIODE, T_BJT, T_FET, T_OPAMP, T_TRIODE, T_PENTODE = 0, 1, 2, 3, 4, 5
FM = {"reassoc", "contract"}  # let the dense loops vectorise (sums in any order, fused multiply-add); no other fast-math
P_STEP = 3  # port kind: plain Newton step limit (the limit is stored in pvcrit)
P_PLATE = 4  # port kind: plate / screen: step limit, and a downward step stops at PLATE_FLOOR of the voltage
MAX_IT = 60  # Newton iterations per sample before giving up on that sample
CHORD_GRID, CHORD_PLATE = 10.0, 150.0  # largest predicted change of a tube's grid / plate port per sample
GMIN_K = GMIN


# --------------------------------------------------------------------------- compiled kernel

@njit(cache=True, nogil=True, inline="always")
def _sp(z):
    if z > 35.0:
        return z
    if z < -35.0:
        return math.exp(z)
    return math.log1p(math.exp(z))


@njit(cache=True, nogil=True, inline="always")
def _sig(z):
    if z >= 0.0:
        return 1.0 / (1.0 + math.exp(-min(z, 700.0)))
    e = math.exp(max(z, -700.0))
    return e / (1.0 + e)


@njit(cache=True, nogil=True, inline="always")
def _lexp(x):
    if x > 80.0:
        e = math.exp(80.0)
        return e * (1.0 + x - 80.0), e
    e = math.exp(x)
    return e, e


@njit(cache=True, nogil=True, inline="always")
def _grid(vgk, gg, gc, gxi):
    z = gc * vgk
    if z < -25.0:  # well below conduction: < 1e-15 A
        return 0.0, 0.0
    L = _sp(z) / gc
    pw = L ** (gxi - 1.0)
    return gg * pw * L, gg * gxi * pw * _sig(z)


@njit(cache=True, nogil=True)
def _eval(types, pst, cst, prs, prm, v, cur, J):
    """Currents of every nonlinear device and their derivatives with respect to the port voltages."""
    J[:, :] = 0.0
    for d in range(types.shape[0]):
        t = types[d]
        p = pst[d]
        c = cst[d]
        q = prs[d]
        if t == 0:  # diode: port v = Va - Vk, current a -> k
            is_, nvt, bv, ibv, nbvt = prm[q], prm[q + 1], prm[q + 2], prm[q + 3], prm[q + 4]
            vd = v[p]
            e, de = _lexp(vd / nvt)
            i = is_ * (e - 1.0) + GMIN_K * vd
            g = is_ * de / nvt + GMIN_K
            if bv > 0.0:
                eb, deb = _lexp(-(vd + bv) / nbvt)
                i -= ibv * eb
                g += ibv * deb / nbvt
            cur[c] = i
            J[c, p] = g
        elif t == 1:  # BJT: ports vbe, vbc; currents ic (C -> E), ib (B -> E)
            pol, is_, bf, br, vaf, nfvt, nrvt = (prm[q], prm[q + 1], prm[q + 2], prm[q + 3], prm[q + 4],
                                                 prm[q + 5], prm[q + 6])
            be = pol * v[p]
            bc = pol * v[p + 1]
            ef, def_ = _lexp(be / nfvt)
            er, der = _lexp(bc / nrvt)
            If = is_ * (ef - 1.0) + GMIN_K * be
            gf = is_ * def_ / nfvt + GMIN_K
            Ir = is_ * (er - 1.0) + GMIN_K * bc
            gr = is_ * der / nrvt + GMIN_K
            kraw = 1.0 - bc / vaf
            if kraw > 0.25:
                k = kraw
                dk = -1.0 / vaf
            else:
                k = 0.25
                dk = 0.0
            ic = (If - Ir) * k - Ir / br
            ib = If / bf + Ir / br
            cur[c] = pol * ic
            cur[c + 1] = pol * ib
            J[c, p] = gf * k
            J[c, p + 1] = -gr * k + (If - Ir) * dk - gr / br
            J[c + 1, p] = gf / bf
            J[c + 1, p + 1] = gr / br
        elif t == 2:  # FET: ports vgs, vds; current id (D -> S)
            pol, vth, kk, lam, w = prm[q], prm[q + 1], prm[q + 2], prm[q + 3], prm[q + 4]
            vgs = pol * v[p]
            vds = pol * v[p + 1]
            rev = vds < 0.0
            if rev:
                a = vgs - vds
                b = -vds
            else:
                a = vgs
                b = vds
            z = (a - vth) / w
            vov = w * _sp(z)
            s = _sig(z)
            cl = 1.0 + lam * b
            if b < vov:
                i = kk * (vov * b - 0.5 * b * b) * cl
                gm = kk * b * cl * s
                gds = kk * (vov - b) * cl + kk * (vov * b - 0.5 * b * b) * lam
            else:
                i = 0.5 * kk * vov * vov * cl
                gm = kk * vov * cl * s
                gds = 0.5 * kk * vov * vov * lam
            gm += GMIN_K
            gds += GMIN_K
            if rev:
                cur[c] = -pol * i
                J[c, p] = -gm
                J[c, p + 1] = gm + gds
            else:
                cur[c] = pol * i
                J[c, p] = gm
                J[c, p + 1] = gds
        elif t == 4:  # triode (Koren): ports vgk, vpk; currents ig (G -> K), ip (P -> K)
            mu, ex, kg1, kp, kvb, gg, gc, gxi = (prm[q], prm[q + 1], prm[q + 2], prm[q + 3], prm[q + 4], prm[q + 5],
                                                 prm[q + 6], prm[q + 7])
            vgk = v[p]
            vpk = v[p + 1]
            s = math.sqrt(kvb + vpk * vpk)
            a = kp * (1.0 / mu + vgk / s)
            L = _sp(a)
            g = _sig(a)
            e1 = vpk * L / kp
            if e1 > 0.0:
                pw = e1 ** (ex - 1.0) / kg1
                ip = pw * e1
                k = ex * pw
                J[c + 1, p] = k * vpk * g / s
                J[c + 1, p + 1] = k * (L / kp - g * vgk * vpk * vpk / (s * s * s)) + GMIN_K
            else:
                ip = 0.0
                J[c + 1, p + 1] = GMIN_K
            cur[c + 1] = ip + GMIN_K * vpk
            ig, dig = _grid(vgk, gg, gc, gxi)
            cur[c] = ig + GMIN_K * vgk
            J[c, p] = dig + GMIN_K
        elif t == 5:  # pentode (Koren): ports vg1k, vg2k, vpk; currents ig1 (G1 -> K), ig2 (G2 -> K), ip (P -> K)
            mu, ex, kg1, kg2, kp, kvb, gg, gc, gxi = (prm[q], prm[q + 1], prm[q + 2], prm[q + 3], prm[q + 4],
                                                      prm[q + 5], prm[q + 6], prm[q + 7], prm[q + 8])
            vg1 = v[p]
            vg2 = v[p + 1]
            vpk = v[p + 2]
            s2 = math.sqrt(vg2 * vg2 + 1.0)
            ds2 = vg2 / s2
            a = kp * (1.0 / mu + vg1 / s2)
            L = _sp(a)
            g = _sig(a)
            e1 = vg2 * L / kp
            if vpk <= 0.0:  # the plate knee, rounded off as in tubes.plate_eff
                vp, dvp = 0.0, 0.0
            elif vpk < KNEE_W:
                vp, dvp = vpk * vpk / (2.0 * KNEE_W), vpk / KNEE_W
            else:
                vp, dvp = vpk - 0.5 * KNEE_W, 1.0
            at = math.atan(vp / kvb)
            dat = dvp / kvb / (1.0 + (vp / kvb) ** 2)
            if e1 > 0.0:
                pw = 2.0 * e1 ** (ex - 1.0) / kg1
                base = pw * e1
                db = ex * pw
                ip = base * at
                J[c + 2, p] = db * (vg2 * g / s2) * at
                J[c + 2, p + 1] = db * (L / kp - vg2 * g * vg1 * ds2 / (s2 * s2)) * at
                J[c + 2, p + 2] = base * dat + GMIN_K
            else:
                ip = 0.0
                J[c + 2, p + 2] = GMIN_K
            cur[c + 2] = ip + GMIN_K * vpk
            qq = vg2 / mu + vg1
            if qq > 0.0:
                pw = qq ** (ex - 1.0) / kg2
                cur[c + 1] = pw * qq + GMIN_K * vg2
                dq = ex * pw
                J[c + 1, p] = dq
                J[c + 1, p + 1] = dq / mu + GMIN_K
            else:
                cur[c + 1] = GMIN_K * vg2
                J[c + 1, p + 1] = GMIN_K
            ig, dig = _grid(vg1, gg, gc, gxi)
            cur[c] = ig + GMIN_K * vg1
            J[c, p] = dig + GMIN_K
        else:  # op-amp: ports vd, X, vo; currents igm (0 -> X), icl (X -> 0), ip (V+ -> out), in (V- -> out)
            # the supply rails are taken as constant (their bias-point voltages) in the audio path
            gm, imax, wc, gc, hl, hh, w, rout, ilim = (prm[q], prm[q + 1], prm[q + 2], prm[q + 3], prm[q + 4],
                                                       prm[q + 5], prm[q + 6], prm[q + 7], prm[q + 8])
            vpp, vnn = prm[q + 9], prm[q + 10]
            vd, X, vo = v[p], v[p + 1], v[p + 2]
            th = math.tanh(gm * vd / imax)
            cur[c] = imax * th
            J[c, p] = gm * (1.0 - th * th)
            z1 = (X - (vpp + 0.3)) / wc
            z2 = ((vnn - 0.3) - X) / wc
            s1 = _sig(z1)
            s2 = _sig(z2)
            cur[c + 1] = gc * wc * (_sp(z1) - _sp(z2))
            J[c + 1, p + 1] = gc * (s1 + s2)
            lo = vnn + hl
            hi = vpp - hh
            if hi < lo:
                lo = 0.5 * (vpp + vnn)
                hi = lo
            za = (X - lo) / w
            zb = (X - hi) / w
            T = lo + w * _sp(za) - w * _sp(zb)
            sa = _sig(za)
            sb = _sig(zb)
            dT_dX = sa - sb
            io = (T - vo) / rout
            tq = math.tanh(io / ilim)
            I = ilim * tq
            qd = (1.0 - tq * tq) / rout
            ss = _sig(I / 1e-4)
            dss = ss * (1.0 - ss) / 1e-4
            kp = ss + I * dss
            kn = (1.0 - ss) - I * dss
            cur[c + 2] = I * ss
            cur[c + 3] = I * (1.0 - ss)
            dIX = qd * dT_dX
            dIo = -qd
            J[c + 2, p + 1] = kp * dIX
            J[c + 2, p + 2] = kp * dIo
            J[c + 3, p + 1] = kn * dIX
            J[c + 3, p + 2] = kn * dIo


@njit(cache=True, nogil=True, fastmath=FM)
def _lu(A, piv, n):
    """In-place LU factorisation with partial pivoting (row permutation in piv)."""
    for k in range(n):
        p = k
        best = abs(A[k, k])
        for r in range(k + 1, n):
            a = abs(A[r, k])
            if a > best:
                best = a
                p = r
        piv[k] = p
        if p != k:
            for c in range(n):
                t = A[k, c]
                A[k, c] = A[p, c]
                A[p, c] = t
        if abs(A[k, k]) < 1e-300:
            A[k, k] = 1e-300
        inv = 1.0 / A[k, k]
        for r in range(k + 1, n):
            f = A[r, k] * inv
            A[r, k] = f
            if f != 0.0:
                for c in range(k + 1, n):
                    A[r, c] -= f * A[k, c]


@njit(cache=True, nogil=True, fastmath=FM)
def _lu_solve(A, piv, b, n):
    for k in range(n):
        p = piv[k]
        if p != k:
            t = b[k]
            b[k] = b[p]
            b[p] = t
    for k in range(n):
        s = b[k]
        for c in range(k):
            s -= A[k, c] * b[c]
        b[k] = s
    for k in range(n - 1, -1, -1):
        s = b[k]
        for c in range(k + 1, n):
            s -= A[k, c] * b[c]
        b[k] = s / A[k, k]


@njit(cache=True, nogil=True)
def _limit(v, dv, pkind, pnvt, pvcrit, M, dprev, abstol=1e-7, reltol=1e-5):
    """Apply a Newton update with junction (pnjlim) and step limiting; returns (worst error ratio, limited).

    ``dprev`` holds the previous step of each port: a tube port whose step reverses direction takes half a step."""
    worst = 0.0
    limited = False
    for m in range(M):
        vo = v[m]
        vn = vo + dv[m]
        if pkind[m] >= 3:  # tubes: pvcrit holds the largest step per iteration
            d = vn - vo
            if pkind[m] == 4 and vo > 20.0 and vo + d < PLATE_FLOOR * vo:  # do not leap across the plate knee
                d = (PLATE_FLOOR - 1.0) * vo
                limited = True
            if d * dprev[m] < 0.0 and abs(d) > 0.1 and abs(d) > 0.5 * abs(dprev[m]):
                d = 0.5 * abs(dprev[m]) * (1.0 if d > 0.0 else -1.0)  # reversed: at most half the last step
                limited = True
            if abs(d) > pvcrit[m]:
                d = pvcrit[m] if d > 0.0 else -pvcrit[m]
                limited = True
            vn = vo + d
        elif pkind[m] != 0:  # junction: SPICE pnjlim (in forward polarity: kind 2 = PNP)
            sg = 1.0 if pkind[m] == 1 else -1.0
            a_o, a_n = sg * vo, sg * vn
            nvt = pnvt[m]
            if a_n > pvcrit[m] and abs(a_n - a_o) > 2.0 * nvt:
                if a_o > 0.0:
                    arg = 1.0 + (a_n - a_o) / nvt
                    a_n = a_o + nvt * math.log(arg) if arg > 0.0 else pvcrit[m]
                else:
                    a_n = nvt * math.log(max(a_n / nvt, 1e-300))
                vn = sg * a_n
                limited = True
        elif abs(vn - vo) > 1.0:
            vn = vo + (1.0 if vn > vo else -1.0)
            limited = True
        dv[m] = vn - vo
        dprev[m] = vn - vo
        d_ = abs(vn - vo)
        tol = abstol + reltol * abs(vn)
        if d_ / tol > worst:
            worst = d_ / tol
        v[m] = vn
    return worst, limited


@njit(cache=True, nogil=True, fastmath=FM)
def process(u_in, y_out, z, v, pprev, LU, piv, Az, Au, a0, Ai, Dz, Du, d0, F, Yz, Yu, y0, Yi, types, pst, cst, npt,
            ncu, prs, prm, pkind, pnvt, pvcrit, stats, abstol=2e-5, reltol=2e-4, lazy=False):
    """Run the circuit over a block of input samples (volts) and write the output voltages.

    Each sample starts from a chord prediction (the last converged Jacobian applied to the change of the linear
    drive p), then Newton iterates on the nonlinear port voltages. With ``lazy`` (circuits of tubes and diodes only)
    the Jacobian is refactorised only when the steps stop shrinking fast; high-gain blocks (op-amps, transistors)
    can be ill-conditioned enough to fool that test, so they always take full Newton steps."""
    S = z.shape[0]
    M = v.shape[0]
    C = F.shape[1]
    ND = types.shape[0]
    cur = np.zeros(C)
    J = np.zeros((C, M))
    p = np.empty(M)
    r = np.empty(M)
    zn = np.empty(S)
    dprev = np.zeros(M)
    for n in range(u_in.shape[0]):
        u = u_in[n]
        for m in range(M):
            s = d0[m] + Du[m] * u
            for k in range(S):
                s += Dz[m, k] * z[k]
            p[m] = s
        if M > 0 and stats[2] > 0.0:  # chord prediction
            for m in range(M):
                r[m] = p[m] - pprev[m]
            _lu_solve(LU, piv, r, M)
            if lazy:  # tubes: a prediction of a huge jump means the old Jacobian no longer applies (a tube
                sc = 1.0  # switched between cut-off and conduction): scale it back to a plausible step
                for m in range(M):
                    if pkind[m] >= 3:
                        cap = CHORD_GRID if pkind[m] == 3 else CHORD_PLATE
                        if abs(r[m]) * sc > cap:
                            sc = cap / abs(r[m])
                if sc < 1.0:
                    for m in range(M):
                        r[m] *= sc
            dprev[:] = 0.0
            _limit(v, r, pkind, pnvt, pvcrit, M, dprev)
        for m in range(M):
            pprev[m] = p[m]
        conv = M == 0
        iters = 0
        dprev[:] = 0.0
        refac = stats[2] == 0.0 or not lazy
        prev_w = 1e300
        for it in range(MAX_IT):
            if M == 0:
                break
            iters += 1
            _eval(types, pst, cst, prs, prm, v, cur, J)
            rw = 0.0  # residual (volts) against the tolerance: a chord step alone cannot prove convergence
            for m in range(M):
                s = p[m] - v[m]
                for cc in range(C):
                    s += F[m, cc] * cur[cc]
                r[m] = s
                a_ = abs(s) / (abstol + reltol * abs(v[m]))
                if a_ > rw:
                    rw = a_
            fresh = refac
            if refac:  # factorise the Jacobian; otherwise iterate on the last factorisation (chord steps)
                for m in range(M):
                    for mm in range(M):
                        LU[m, mm] = 0.0
                    LU[m, m] = 1.0
                for d in range(ND):  # J is block-diagonal by device: only its own ports feed its currents
                    p0 = pst[d]
                    c0 = cst[d]
                    for j in range(npt[d]):
                        col = p0 + j
                        for cc in range(c0, c0 + ncu[d]):
                            jv = J[cc, col]
                            if jv != 0.0:
                                for m in range(M):
                                    LU[m, col] -= F[m, cc] * jv
                _lu(LU, piv, M)
                stats[2] = 1.0
                stats[3] += 1.0
            _lu_solve(LU, piv, r, M)
            worst, limited = _limit(v, r, pkind, pnvt, pvcrit, M, dprev, abstol, reltol)
            if worst <= 1.0 and not limited and (fresh or rw <= 10.0):
                conv = True
                for d in range(ND):  # first-order update of the currents to the final voltages
                    for cc in range(cst[d], cst[d] + ncu[d]):
                        s = 0.0
                        for j in range(pst[d], pst[d] + npt[d]):
                            s += J[cc, j] * r[j]
                        cur[cc] += s
                break
            # keep chord-stepping only while the steps shrink fast (then the error is well below the step)
            refac = not lazy or limited or worst > 0.2 * prev_w or it >= 8 or (not fresh and rw > 10.0)
            prev_w = worst
        stats[1] += iters
        if not conv:
            stats[0] += 1.0
            _eval(types, pst, cst, prs, prm, v, cur, J)
        y = y0 + Yu * u
        for k in range(S):
            y += Yz[k] * z[k]
        for cc in range(C):
            y += Yi[cc] * cur[cc]
        for k in range(S):
            s = a0[k] + Au[k] * u
            for kk in range(S):
                s += Az[k, kk] * z[kk]
            for cc in range(C):
                s += Ai[k, cc] * cur[cc]
            zn[k] = s
        for k in range(S):
            z[k] = zn[k]
        y_out[n] = y


@njit(cache=True, nogil=True, fastmath=FM)
def fir_up(x, h, hist, R, out):
    """Polyphase interpolation by R (h designed at the oversampled rate, gain R folded in)."""
    L = hist.shape[0]
    taps = h.shape[0]
    for n in range(x.shape[0]):
        for k in range(L - 1, 0, -1):
            hist[k] = hist[k - 1]
        hist[0] = x[n]
        for ph in range(R):
            s = 0.0
            j = 0
            tt = ph
            while tt < taps and j < L:
                s += h[tt] * hist[j]
                tt += R
                j += 1
            out[n * R + ph] = s * R


@njit(cache=True, nogil=True, fastmath=FM)
def fir_down(x, h, hist, R, out):
    """Low-pass filter then keep every R-th sample."""
    taps = h.shape[0]
    pos = 0
    for n in range(x.shape[0]):
        for k in range(taps - 1, 0, -1):
            hist[k] = hist[k - 1]
        hist[0] = x[n]
        if n % R == R - 1:
            s = 0.0
            for k in range(taps):
                s += h[k] * hist[k]
            out[pos] = s
            pos += 1


@njit(cache=True, nogil=True)
def dcblock(y, out, a, state):
    """One-pole DC blocker; state = [previous input, previous output]."""
    px, py = state[0], state[1]
    for i in range(y.shape[0]):
        v = y[i]
        py = a * py + v - px
        px = v
        out[i] = py
    state[0], state[1] = px, py


def lowpass(R: int, taps_per_phase: int = 16) -> np.ndarray:
    """Kaiser-windowed sinc anti-alias / anti-image filter for an R-times oversampled stream."""
    n = R * taps_per_phase
    t = np.arange(n) - (n - 1) / 2
    fc = 0.45 / R
    h = 2 * fc * np.sinc(2 * fc * t) * np.kaiser(n, 8.0)
    return h / h.sum()


# --------------------------------------------------------------------------- compilation

class RealtimeError(RuntimeError):
    pass


class RealtimeModel:
    """A board compiled for real-time processing. ``process_block(volts_in) -> volts_out``."""

    def __init__(self, project, in_net: str = "IN", out_net: str = "OUT", controls: dict | None = None,
                 rate: float = 48000.0, oversample: int = 2):
        from .audio import build_for_audio
        from .engine import Simulator
        self.rate, self.R = float(rate), int(oversample)
        self.h = 1.0 / (self.rate * self.R)
        ck, src, n_in, n_out = build_for_audio(project, in_net, out_net, controls, Waveform("dc", v=0.0))
        self.ck, self.src, self.n_out = ck, src, n_out
        self.sim = sim = Simulator(ck)
        for s_ in sim.sources:
            s_.ramping = False
        self.x_op = sim.start_op().copy()
        self.notes: list[str] = []
        self._classify()
        self.stats = np.zeros(4)  # non-converged samples, Newton iterations, factorisation valid, factorisations
        self.tol = (2e-5, 2e-4)  # Newton step tolerance (V, relative): the error left is ~ step^2
        self.recompile()
        self._init_state()
        if self.R > 1:
            self.h_aa = lowpass(self.R)
            per = len(self.h_aa) // self.R + 1
            self.up_hist = np.zeros(per)
            self.down_hist = np.zeros(len(self.h_aa))

    # ------------------------------------------------------------------ device partition
    def _classify(self):
        sim = self.sim
        self.caps = list(sim.capgroup.caps) if sim.capgroup is not None else []
        self.inds = [d for d in sim.singles if isinstance(d, Inductor)]
        nl = []
        linearised = []
        for d in self.ck.devices:
            if isinstance(d, (Diode, BJT, FET, ics.OpAmp, Triode, Pentode)):
                nl.append(d)
            elif isinstance(d, Behavioral):
                linearised.append(d)
        self.nl = nl
        self.linearised = linearised
        frozen = [d for d in sim.events]
        if linearised:
            self.notes.append("Linearised at the bias point: " + ", ".join(sorted({d.name or d.kind for d in
                                                                                   linearised})))
        if frozen:
            self.notes.append("Held in their DC state: " + ", ".join(sorted({d.name or d.kind for d in frozen})))
        # port / current layout
        types, pst, cst, prs, prm = [], [], [], [], []
        ports: list[tuple] = []  # (+node, -node, kind, nvt, vcrit)
        currents: list[tuple] = []  # (from node, to node)
        for d in nl:
            types.append({Diode: T_DIODE, BJT: T_BJT, FET: T_FET, Triode: T_TRIODE, Pentode: T_PENTODE}.get(
                type(d), T_OPAMP))
            pst.append(len(ports))
            cst.append(len(currents))
            prs.append(len(prm))
            if isinstance(d, Diode):
                a, k = d.nodes
                nvt = d.n * VT
                vcrit = nvt * math.log(nvt / (math.sqrt(2.0) * d.is_))
                ports.append((a, k, 1, nvt, vcrit))
                currents.append((a, k))
                prm += [d.is_, nvt, d.bv, d.ibv, d.nbv * VT]
            elif isinstance(d, BJT):
                c, b, e = d.nodes
                nfvt, nrvt = d.nf * VT, d.nr * VT
                jk = 1 if d.pol > 0 else 2
                ports.append((b, e, jk, nfvt, nfvt * math.log(nfvt / (math.sqrt(2.0) * d.is_))))
                ports.append((b, c, jk, nrvt, nrvt * math.log(nrvt / (math.sqrt(2.0) * d.is_))))
                currents += [(c, e), (b, e)]
                prm += [float(d.pol), d.is_, d.bf, d.brev, d.vaf if d.vaf > 0 else 1e12, nfvt, nrvt]
            elif isinstance(d, Triode):
                pl, g, k = d.nodes
                ports += [(g, k, P_STEP, 0.0, VT_LIMIT[0]), (pl, k, P_PLATE, 0.0, VT_LIMIT[1])]
                currents += [(g, k), (pl, k)]
                prm += list(d.prm)
            elif isinstance(d, Pentode):
                pl, g2, g1, k = d.nodes
                ports += [(g1, k, P_STEP, 0.0, VT_LIMIT[0]), (g2, k, P_PLATE, 0.0, VT_LIMIT[1]),
                          (pl, k, P_PLATE, 0.0, VT_LIMIT[1])]
                currents += [(g1, k), (g2, k), (pl, k)]
                prm += list(d.prm)
            elif isinstance(d, FET):
                dd, g, s = d.nodes
                ports += [(g, s, 0, 0.0, 0.0), (dd, s, 0, 0.0, 0.0)]
                currents.append((dd, s))
                prm += [float(d.pol), d.vth, d.k, d.lam, d.nsub * VT]
            else:
                inp, inn, out, vp, vn, X = d.nodes
                ports += [(inp, inn, 0, 0.0, 0.0), (X, 0, 0, 0.0, 0.0), (out, 0, 0, 0.0, 0.0)]
                currents += [(0, X), (X, 0), (vp, out), (vn, out)]
                prm += [d.gm, d.imax, d.wc, d.gc, d.hl, d.hh, d.w, d.rout, d.ilim, float(self.x_op[vp]),
                        float(self.x_op[vn])]
        self.types = np.array(types, dtype=np.int64)
        self.lazy = bool(types) and all(t in (T_DIODE, T_TRIODE, T_PENTODE) for t in types) and \
            any(t in (T_TRIODE, T_PENTODE) for t in types)
        self.npt = np.array([(pst + [len(ports)])[i + 1] - pst[i] for i in range(len(pst))], dtype=np.int64)
        self.ncu = np.array([(cst + [len(currents)])[i + 1] - cst[i] for i in range(len(cst))], dtype=np.int64)
        self.pst = np.array(pst, dtype=np.int64)
        self.cst = np.array(cst, dtype=np.int64)
        self.prs = np.array(prs, dtype=np.int64)
        self.prm = np.array(prm, dtype=np.float64)
        self.ports, self.currents = ports, currents
        self.pkind = np.array([p[2] for p in ports], dtype=np.int64)
        self.pnvt = np.array([p[3] for p in ports], dtype=np.float64)
        self.pvcrit = np.array([p[4] for p in ports], dtype=np.float64)

    # ------------------------------------------------------------------ matrices
    def recompile(self):
        """(Re)build the state-space matrices, e.g. after a knob moved. The state is kept."""
        sim, h = self.sim, self.h
        N = sim.N
        G = sim.A0.copy()
        c0 = sim.b0.copy()
        caps_set = set(map(id, self.caps))
        for d in sim.steppers:
            if isinstance(d, CapacitorGroup):
                d.stamp_matrix(G, h, "trap")
            elif isinstance(d, Inductor):
                d.stamp_matrix(G, h, "trap")
            elif isinstance(d, VoltageSource):
                if d is not self.src:
                    c0[d.br[0]] += d.value(1.0)
            elif hasattr(d, "stamp_rhs"):
                d.stamp_rhs(c0, 1.0, h, "trap")
            else:  # switches, pots, frozen event devices, MCU pins
                d.stamp_step(G, c0, 1.0, h, "trap")
        for d in self.linearised:
            d.begin(self.x_op)
            d.stamp_nl(G, c0, self.x_op)
        del caps_set
        n = N - 1
        Gr = G[1:, 1:]
        try:
            Ainv = np.linalg.inv(Gr)
        except np.linalg.LinAlgError:
            raise RealtimeError("The circuit matrix is singular (floating section)") from None

        def col(entries):
            vec = np.zeros(n)
            for node, val in entries:
                if node > 0:
                    vec[node - 1] += val
            return vec

        S = len(self.caps) + len(self.inds)
        Bz = np.zeros((n, S))
        W = np.zeros((S, n))
        for j, cap in enumerate(self.caps):
            a, k = cap.nodes
            Bz[:, j] = col([(a, 1.0), (k, -1.0)])
            W[j] = col([(a, 4.0 * cap.c / h), (k, -4.0 * cap.c / h)])
        for j, ind in enumerate(self.inds):
            jj = len(self.caps) + j
            kb = ind.br[0]
            Bz[kb - 1, jj] = -1.0
            W[jj, kb - 1] = 2.0 * (2.0 * ind.l / h)
        Bu = np.zeros(n)
        Bu[self.src.br[0] - 1] = 1.0
        K = np.zeros((n, len(self.currents)))
        for j, (fa, tb) in enumerate(self.currents):
            K[:, j] = col([(fa, -1.0), (tb, 1.0)])
        P = np.zeros((len(self.ports), n))
        for m, (pa, pb, *_r) in enumerate(self.ports):
            P[m] = col([(pa, 1.0), (pb, -1.0)])
        O = np.zeros(n)
        O[self.n_out - 1] = 1.0
        c0r = c0[1:]
        AB = Ainv @ np.column_stack([Bz, Bu, c0r, K])
        xz, xu, xc, xk = AB[:, :S], AB[:, S], AB[:, S + 1], AB[:, S + 2:]
        self.Dz, self.Du, self.d0, self.F = P @ xz, P @ xu, P @ xc, P @ xk
        self.Az = W @ xz - np.eye(S)
        self.Au, self.a0, self.Ai = W @ xu, W @ xc, W @ xk
        self.Yz, self.Yu, self.y0, self.Yi = O @ xz, float(O @ xu), float(O @ xc), O @ xk
        self.Ainv = Ainv
        if hasattr(self, "LU"):
            self.stats[2] = 0.0  # the matrices changed: no chord prediction from the old Jacobian
        # one tuple, swapped in a single assignment: the audio thread never sees half-updated matrices
        self._mats = tuple(np.ascontiguousarray(m) for m in (self.Az, self.Au, self.a0, self.Ai, self.Dz, self.Du,
                                                             self.d0, self.F, self.Yz)) + (
            float(self.Yu), float(self.y0), np.ascontiguousarray(self.Yi))

    def _init_state(self):
        x = self.x_op
        h = self.h
        z = []
        for cap in self.caps:
            a, k = cap.nodes
            z.append(2.0 * cap.c / h * float(x[a] - x[k]))
        for ind in self.inds:
            z.append(2.0 * ind.l / h * float(x[ind.br[0]]))
        self.z = np.array(z, dtype=np.float64)
        self.v = np.array([float(x[pa] - x[pb]) for pa, pb, *_r in self.ports], dtype=np.float64)
        M = len(self.v)
        self.pprev = np.zeros(M)
        self.LU = np.eye(M)
        self.piv = np.zeros(M, dtype=np.int64)
        self.stats[2] = 0.0  # no factorisation yet: no chord prediction on the first sample

    def set_control(self, key: str, value) -> bool:
        ctl = self.ck.control(key)
        if ctl is not None and ctl.apply(value):
            self.recompile()
            return True
        return False

    # ------------------------------------------------------------------ processing
    def run(self, u: np.ndarray) -> np.ndarray:
        """Process samples at the circuit rate (no resampling)."""
        u = np.ascontiguousarray(u, dtype=np.float64)
        y = np.empty_like(u)
        Az, Au, a0, Ai, Dz, Du, d0, F, Yz, Yu, y0, Yi = self._mats
        process(u, y, self.z, self.v, self.pprev, self.LU, self.piv, Az, Au, a0, Ai, Dz, Du, d0, F, Yz, Yu, y0, Yi,
                self.types, self.pst, self.cst, self.npt, self.ncu, self.prs, self.prm, self.pkind, self.pnvt,
                self.pvcrit, self.stats, self.tol[0], self.tol[1], self.lazy)
        return y

    def process_block(self, u: np.ndarray) -> np.ndarray:
        """Process audio-rate samples (volts in, volts out), oversampling internally."""
        u = np.ascontiguousarray(u, dtype=np.float64)
        if self.R == 1:
            return self.run(u)
        up = np.empty(len(u) * self.R)
        fir_up(u, self.h_aa, self.up_hist, self.R, up)
        yo = self.run(up)
        out = np.empty(len(u))
        fir_down(yo, self.h_aa, self.down_hist, self.R, out)
        return out

    def warm_up(self) -> None:
        """Trigger the JIT compilation (first call) without disturbing the state."""
        saved = [a.copy() for a in (self.z, self.v, self.pprev, self.LU, self.piv, self.stats)]
        uh, dh = (self.up_hist.copy(), self.down_hist.copy()) if self.R > 1 else (None, None)
        self.process_block(np.zeros(64))
        self.z, self.v, self.pprev, self.LU, self.piv, self.stats = saved
        if self.R > 1:
            self.up_hist, self.down_hist = uh, dh

    def benchmark(self, seconds: float = 0.1, level: float = 0.5) -> float:
        """CPU load (processing time / audio time) on a loud guitar chord, leaving the state as it was."""
        import time

        from .audio import guitar_clip
        saved = [a.copy() for a in (self.z, self.v, self.pprev, self.LU, self.piv, self.stats)]
        uh, dh = (self.up_hist.copy(), self.down_hist.copy()) if self.R > 1 else (None, None)
        clip = guitar_clip("Power chords", seconds, int(self.rate), level)
        t0 = time.perf_counter()
        for k in range(0, len(clip), 128):
            self.process_block(clip[k:k + 128])
        load = (time.perf_counter() - t0) / seconds
        self.z, self.v, self.pprev, self.LU, self.piv, self.stats = saved
        if self.R > 1:
            self.up_hist, self.down_hist = uh, dh
        return load

    def settle(self, seconds: float = 0.3) -> None:
        """Run silence through the circuit so the bias capacitors reach steady state."""
        self.run(np.zeros(int(seconds * self.rate * self.R)))

    @property
    def sizes(self) -> dict:
        return {"states": len(self.z), "ports": len(self.v), "currents": len(self.currents)}
