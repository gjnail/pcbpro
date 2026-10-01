"""Vacuum tube (valve) models: triodes and pentodes / beam tetrodes for the circuit simulator.

Plate current follows Norman Koren's equations (1996). They are smooth, valid from cut-off to grid conduction, and
widely used for guitar-amp simulation:

    triode   E1 = Vpk / kp * ln(1 + exp(kp * (1/mu + Vgk / sqrt(kvb + Vpk^2))))
             Ip = E1^ex / kg1
    pentode  E1 = Vg2k / kp * ln(1 + exp(kp * (1/mu + Vg1k / Vg2k)))
             Ip = 2 E1^ex / kg1 * atan(Vpk / kvb),   Ig2 = (Vg2k / mu + Vg1k)^ex / kg2

Grid current (positive grid) is a smooth power law (after Cohen and Helie, 2010): Ig = Gg * (softplus(c Vgk) / c)^xi.
That gives the blocking distortion of overdriven stages with coupling capacitors.

The constants are the published Koren sets where known (12AX7, 12AT7, 12AU7, ECC88 and the power tubes); the other
triodes were fitted to their datasheet gm and plate resistance. ``kg1`` / ``kg2`` are then calibrated so that every tube
draws its datasheet current at the datasheet bias point, so bias voltages in the simulation match real amps.
Plate-to-grid capacitance (the Miller capacitance) is added by the netlist builder as an ordinary capacitor.
"""
from __future__ import annotations

import math

from .devices import Device, sig, sp, stamp_terms

# name: (mu, ex, kg1, kp, kvb, cgp_pF, (Vp, Vg, Ip_mA) datasheet point)
TRIODES = {
    "12AX7": (100.0, 1.4, 1060.0, 600.0, 300.0, 1.7, (250.0, -2.0, 1.2)),
    "12AT7": (60.0, 1.35, 460.0, 300.0, 300.0, 1.5, (250.0, -2.0, 10.0)),
    "12AU7": (21.5, 1.3, 1180.0, 84.0, 300.0, 1.5, (250.0, -8.5, 10.5)),
    "12AY7": (40.0, 1.325, 982.0, 725.0, 300.0, 1.3, (250.0, -4.0, 3.0)),
    "5751": (64.8, 1.2, 909.0, 573.7, 300.0, 1.4, (250.0, -3.0, 1.0)),
    "ECC88": (33.0, 1.3, 330.0, 320.0, 300.0, 1.4, (90.0, -1.3, 15.0)),
    "6SN7": (23.5, 1.3, 537.0, 103.0, 300.0, 4.0, (250.0, -8.0, 9.0)),
    "6SL7": (71.8, 1.2, 745.0, 359.1, 300.0, 2.8, (250.0, -2.0, 2.3)),
    "6C4": (18.7, 1.325, 880.0, 88.1, 300.0, 1.6, (250.0, -8.5, 10.5)),
}

# name: (mu, ex, kg1, kg2, kp, kvb, (Vp, Vg2, Vg1, Ip_mA, Ig2_mA) datasheet point)
PENTODES = {
    "EL84": (19.0, 1.35, 600.0, 4500.0, 200.0, 24.0, (250.0, 250.0, -7.3, 48.0, 5.5)),
    "6V6GT": (10.7, 1.31, 1672.0, 4500.0, 41.16, 12.7, (250.0, 250.0, -12.5, 45.0, 4.5)),
    "6AQ5": (10.7, 1.31, 1672.0, 4500.0, 41.16, 12.7, (250.0, 250.0, -12.5, 45.0, 4.5)),
    "6L6GC": (8.7, 1.35, 1460.0, 4500.0, 48.0, 12.0, (250.0, 250.0, -14.0, 72.0, 5.0)),
    "5881": (8.7, 1.35, 1460.0, 4500.0, 48.0, 12.0, (250.0, 250.0, -14.0, 70.0, 5.0)),
    "KT66": (6.8, 1.35, 900.0, 4500.0, 40.0, 12.0, (250.0, 250.0, -15.0, 85.0, 6.0)),
    "EL34": (11.0, 1.35, 650.0, 4200.0, 60.0, 24.0, (250.0, 250.0, -13.5, 100.0, 14.9)),
    "KT88": (8.8, 1.35, 730.0, 4200.0, 32.0, 16.0, (250.0, 250.0, -15.0, 140.0, 8.0)),
    "6550": (7.9, 1.35, 890.0, 4200.0, 60.0, 24.0, (250.0, 250.0, -14.0, 140.0, 12.0)),
    "EF86": (40.0, 1.35, 2500.0, 8000.0, 200.0, 30.0, (250.0, 140.0, -2.0, 3.0, 0.6)),
}

# grid conduction (Cohen & Helie, 12AX7); power tubes scale with their perveance
GRID = (6.06e-4, 13.9, 1.354)
VT_LIMIT = (50.0, 400.0)  # largest Newton step per iteration: grid ports, plate / screen ports
PLATE_FLOOR = 0.3  # above 20 V a plate / screen step goes down at most to this fraction of the voltage
KNEE_W = 2.0  # volts: the pentode plate term is rounded off below this, so Ip and its slope are continuous at 0 V


def plate_eff(vpk):
    """Plate voltage seen by the pentode's atan(Vp / kvb) term: 0 below 0 V, quadratic up to KNEE_W, then linear."""
    if vpk <= 0.0:
        return 0.0, 0.0
    if vpk < KNEE_W:
        return vpk * vpk / (2.0 * KNEE_W), vpk / KNEE_W
    return vpk - 0.5 * KNEE_W, 1.0


def _e1_triode(vgk, vpk, mu, kp, kvb):
    s = math.sqrt(kvb + vpk * vpk)
    a = kp * (1.0 / mu + vgk / s)
    L = sp(a)
    g = sig(a)
    e1 = vpk * L / kp
    de_dvg = vpk * g / s
    de_dvp = L / kp - g * vgk * vpk * vpk / (s * s * s)
    return e1, de_dvg, de_dvp


def triode_current(vgk, vpk, prm):
    """(ip, ig, dip_dvgk, dip_dvpk, dig_dvgk) for one triode section."""
    mu, ex, kg1, kp, kvb, gg, gc, gxi = prm
    e1, dg, dp = _e1_triode(vgk, vpk, mu, kp, kvb)
    if e1 > 0.0:
        ip = e1 ** ex / kg1
        k = ex * e1 ** (ex - 1.0) / kg1
        dip_g, dip_p = k * dg, k * dp
    else:
        ip = dip_g = dip_p = 0.0
    ig, dig = grid_current(vgk, gg, gc, gxi)
    return ip, ig, dip_g, dip_p, dig


def grid_current(vgk, gg, gc, gxi):
    z = gc * vgk
    if z < -25.0:  # well below conduction: < 1e-15 A (the real-time kernel cuts off at the same point)
        return 0.0, 0.0
    L = sp(z) / gc
    if L <= 0.0:
        return 0.0, 0.0
    ig = gg * L ** gxi
    return ig, gg * gxi * L ** (gxi - 1.0) * sig(z)


def pentode_current(vg1k, vg2k, vpk, prm):
    """(ip, ig2, ig1, dip/d(vg1k, vg2k, vpk), dig2/d(vg1k, vg2k), dig1_dvg1k) for one pentode."""
    mu, ex, kg1, kg2, kp, kvb, gg, gc, gxi = prm
    s2 = math.sqrt(vg2k * vg2k + 1.0)  # Vg2k in the denominator, kept away from zero
    ds2 = vg2k / s2
    a = kp * (1.0 / mu + vg1k / s2)
    L = sp(a)
    g = sig(a)
    e1 = vg2k * L / kp
    de_g1 = vg2k * g / s2
    de_g2 = L / kp - vg2k * g * vg1k * ds2 / (s2 * s2)
    vp, dvp = plate_eff(vpk)
    at = math.atan(vp / kvb)
    dat = dvp / kvb / (1.0 + (vp / kvb) ** 2)
    if e1 > 0.0:
        base = 2.0 * e1 ** ex / kg1
        dbase = 2.0 * ex * e1 ** (ex - 1.0) / kg1
        ip = base * at
        d1, d2, d3 = dbase * de_g1 * at, dbase * de_g2 * at, base * dat
    else:
        ip = d1 = d2 = d3 = 0.0
    q = vg2k / mu + vg1k
    if q > 0.0:
        ig2 = q ** ex / kg2
        dq = ex * q ** (ex - 1.0) / kg2
        e1g, e2g = dq, dq / mu
    else:
        ig2 = e1g = e2g = 0.0
    ig1, dig1 = grid_current(vg1k, gg, gc, gxi)
    return ip, ig2, ig1, d1, d2, d3, e1g, e2g, dig1


# --------------------------------------------------------------------------- calibration

def _calibrated() -> tuple[dict, dict]:
    tri, pen = {}, {}
    for name, (mu, ex, kg1, kp, kvb, cgp, (vp, vg, ip_ma)) in TRIODES.items():
        prm = [mu, ex, kg1, kp, kvb] + list(GRID)
        ip = triode_current(vg, vp, prm)[0]
        prm[2] = kg1 * ip / (ip_ma * 1e-3)  # Ip scales with 1 / kg1
        tri[name] = (tuple(prm), cgp * 1e-12)
    for name, (mu, ex, kg1, kg2, kp, kvb, (vp, vg2, vg1, ip_ma, ig2_ma)) in PENTODES.items():
        gg = GRID[0] * (8.0 if name not in ("EF86",) else 1.0)  # power tubes conduct more grid current
        prm = [mu, ex, kg1, kg2, kp, kvb, gg, GRID[1], GRID[2]]
        r = pentode_current(vg1, vg2, vp, prm)
        prm[2] = kg1 * r[0] / (ip_ma * 1e-3)
        prm[3] = kg2 * r[1] / (ig2_ma * 1e-3)
        pen[name] = tuple(prm)
    return tri, pen


TRIODE_PRM, PENTODE_PRM = _calibrated()


def model_for(tube_name: str) -> tuple[str, tuple] | None:
    """("triode", (params, cgp)) or ("pentode", params) for a tube type from ``pcbpro.amp.tubes``."""
    if tube_name in TRIODE_PRM:
        return "triode", TRIODE_PRM[tube_name]
    if tube_name in PENTODE_PRM:
        return "pentode", PENTODE_PRM[tube_name]
    return None


# --------------------------------------------------------------------------- devices

class _Tube(Device):
    nonlinear = True
    group = None

    def __init__(self, nodes, prm, part=None, name="", pa_max: float = 0.0):
        super().__init__(nodes, part, name)
        self.prm = tuple(prm)
        self.pa_max = pa_max
        self.vlast: list[float] | None = None
        self.dlast: list[float] | None = None

    def begin(self, x):
        self.vlast = None
        self.dlast = None

    def _ports(self, V) -> list[float]:
        raise NotImplementedError

    def _limit(self, ports: list[float]) -> tuple[list[float], bool]:
        """SPICE-style step limiting on the port voltages between Newton iterations."""
        if self.vlast is None:
            self.vlast = ports
            return ports, False
        out, steps, limited = [], [], False
        for k, (vn, vo) in enumerate(zip(ports, self.vlast)):
            lim = VT_LIMIT[0] if k == 0 else VT_LIMIT[1]
            d = vn - vo
            dl = self.dlast[k] if self.dlast is not None else 0.0
            if d * dl < 0.0 and abs(d) > 0.1 and abs(d) > 0.5 * abs(dl):
                d = math.copysign(0.5 * abs(dl), d)  # reversed: at most half the last step (no two-cycles)
                limited = True
            if k > 0 and vo > 20.0 and vo + d < PLATE_FLOOR * vo:  # do not leap across the plate knee
                d = (PLATE_FLOOR - 1.0) * vo
                limited = True
            if abs(d) > lim:
                d = math.copysign(lim, d)
                limited = True
            out.append(vo + d)
            steps.append(d)
        self.vlast, self.dlast = out, steps
        return out, limited


class Triode(_Tube):
    """One triode section: nodes (plate, grid, cathode)."""
    kind = "triode"

    def _ports(self, V):
        p, g, k = V
        return [g - k, p - k]

    def _eval(self, vgk, vpk):
        ip, ig, dpg, dpp, dgg = triode_current(vgk, vpk, self.prm)
        # currents into the terminals (plate, grid, cathode)
        I = [ip, ig, -ip - ig]
        Jp = [dpp, dpg, -dpp - dpg]  # d ip / d(Vp, Vg, Vk)
        Jg = [0.0, dgg, -dgg]
        J = [Jp, Jg, [-(a + b) for a, b in zip(Jp, Jg)]]
        return I, J

    def stamp_nl(self, A, b, x):
        V = [float(x[n]) for n in self.nodes]
        (vgk, vpk), limited = self._limit(self._ports(V))
        k = V[2]
        Vl = [vpk + k, vgk + k, k]  # linearise at the limited point
        I, J = self._eval(vgk, vpk)
        stamp_terms(A, b, self.nodes, I, J, Vl)
        return limited

    def currents(self, x):
        V = [float(x[n]) for n in self.nodes]
        vgk, vpk = self._ports(V)
        return self._eval(vgk, vpk)[0]

    def observe(self, x):
        V = [float(x[n]) for n in self.nodes]
        vgk, vpk = self._ports(V)
        ip, ig = triode_current(vgk, vpk, self.prm)[:2]
        return {"v": vpk, "vgk": vgk, "i": ip, "ig": ig, "p": ip * vpk + ig * vgk}

    def power(self, x):
        return self.observe(x)["p"]


class Pentode(_Tube):
    """Pentode or beam tetrode: nodes (plate, screen, grid, cathode). The suppressor is taken as tied to the cathode."""
    kind = "pentode"

    def _ports(self, V):
        p, g2, g1, k = V
        return [g1 - k, g2 - k, p - k]

    def _eval(self, vg1k, vg2k, vpk):
        ip, ig2, ig1, d1, d2, d3, e1g, e2g, dig1 = pentode_current(vg1k, vg2k, vpk, self.prm)
        # terminals (plate, screen, grid, cathode); derivative columns in the same order
        Jp = [d3, d2, d1, -(d1 + d2 + d3)]
        Js = [0.0, e2g, e1g, -(e1g + e2g)]
        Jg = [0.0, 0.0, dig1, -dig1]
        Jk = [-(a + b + c) for a, b, c in zip(Jp, Js, Jg)]
        return [ip, ig2, ig1, -(ip + ig2 + ig1)], [Jp, Js, Jg, Jk]

    def stamp_nl(self, A, b, x):
        V = [float(x[n]) for n in self.nodes]
        (vg1k, vg2k, vpk), limited = self._limit(self._ports(V))
        k = V[3]
        I, J = self._eval(vg1k, vg2k, vpk)
        stamp_terms(A, b, self.nodes, I, J, [vpk + k, vg2k + k, vg1k + k, k])
        return limited

    def currents(self, x):
        V = [float(x[n]) for n in self.nodes]
        return self._eval(*self._ports(V))[0]

    def observe(self, x):
        V = [float(x[n]) for n in self.nodes]
        vg1k, vg2k, vpk = self._ports(V)
        ip, ig2, ig1 = pentode_current(vg1k, vg2k, vpk, self.prm)[:3]
        return {"v": vpk, "vgk": vg1k, "i": ip, "ig2": ig2, "ig": ig1, "p": ip * vpk,
                "p_screen": ig2 * vg2k}

    def power(self, x):
        o = self.observe(x)
        return o["p"] + o["p_screen"]
