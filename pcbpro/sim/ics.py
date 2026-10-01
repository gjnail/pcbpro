"""Behavioural IC models: op-amps, comparators, 555 timers, linear regulators, references, sensors, opto-couplers,
relays and the LM386 audio amplifier."""
from __future__ import annotations

import math

from .devices import (GMIN, NEWTON, R_OFF, Behavioral, EventDevice, Inductor, sig, smin, sp, stamp_emf,
                      stamp_g)


# --------------------------------------------------------------------------- op-amps

class OpAmp(Behavioral):
    """Behavioural op-amp: slew-limited transconductance into an internal pole node X (Rx || Cx to ground, added by
    the builder), anti-windup clamp on X, smooth output clamp to the rails minus headroom, current-limited output
    stage that draws its current from the supply pins. Terminals: in+, in-, out, V+, V-, X."""
    kind = "opamp"

    def __init__(self, inp, inn, out, vp, vn, xn, a0=1e5, gbw=1e6, sr=0.5e6, hh=1.5, hl=1.5, rout=50.0, ilim=0.03,
                 rx=1e6, part=None, name="", vmax=36.0):
        super().__init__((inp, inn, out, vp, vn, xn), part, name)
        self.gx = 1.0 / rx
        self.gm = a0 / rx
        self.cx = 1.0 / (2 * math.pi * rx * (gbw / a0))
        self.rx = rx
        self.imax = sr * self.cx
        self.hh, self.hl, self.rout, self.ilim = hh, hl, rout, ilim
        self.w, self.wc, self.gc = 0.01, 0.05, 1.0
        self.vmax = vmax

    def func(self, V):
        return self._eval(V)[0]

    def jac(self, V):
        return self._eval(V)

    def _eval(self, V):
        vip, vin, vo, vpp, vnn, X = V
        d = vip - vin
        th = math.tanh(self.gm * d / self.imax)
        igm = self.imax * th
        digm = self.gm * (1.0 - th * th)
        wc, gc = self.wc, self.gc
        z1 = (X - (vpp + 0.3)) / wc
        z2 = ((vnn - 0.3) - X) / wc
        icl = gc * wc * (sp(z1) - sp(z2))
        s1, s2 = sig(z1), sig(z2)
        lo, hi = vnn + self.hl, vpp - self.hh
        dlo = (0.0, 1.0)  # d/dV+, d/dV-
        dhi = (1.0, 0.0)
        if hi < lo:  # unpowered or below the minimum supply: sit in the middle
            lo = hi = 0.5 * (vpp + vnn)
            dlo = dhi = (0.5, 0.5)
        w = self.w
        za, zb = (X - lo) / w, (X - hi) / w
        T = lo + w * sp(za) - w * sp(zb)
        sa, sb = sig(za), sig(zb)
        dT_dX = sa - sb
        dT_dvp = (1 - sa) * dlo[0] + sb * dhi[0]
        dT_dvn = (1 - sa) * dlo[1] + sb * dhi[1]
        io = (T - vo) / self.rout
        tq = math.tanh(io / self.ilim)
        I = self.ilim * tq
        q = (1.0 - tq * tq) / self.rout
        if NEWTON["it"] < 12:
            q = max(q, 0.02 / self.rout)  # floor: keeps Newton moving in current limit
        dI = (0.0, 0.0, -q, q * dT_dvp, q * dT_dvn, q * dT_dX)
        ss = sig(I / 1e-4)
        dss = ss * (1.0 - ss) / 1e-4
        kp = ss + I * dss
        kn = (1.0 - ss) - I * dss
        cur = [0.0, 0.0, -I, I * ss, I * (1.0 - ss), -igm + icl]
        zero = [0.0] * 6
        J = [zero, zero, [-v for v in dI], [kp * v for v in dI], [kn * v for v in dI],
             [-digm, digm, 0.0, -gc * s1, -gc * s2, gc * (s1 + s2)]]
        return cur, J

    def observe(self, x):
        V = [float(x[n]) for n in self.nodes]
        I = -self._eval(V)[0][2]
        return {"v": V[2], "i": I, "p": self.power(x), "supply": V[3] - V[4]}


class Comparator(EventDevice):
    """Open-collector comparator (LM393 / LM339): the output transistor to V- turns on when in- > in+.
    Terminals: in+, in-, out, V+, V-."""
    kind = "comparator"

    def __init__(self, inp, inn, out, vp, vn, part=None, name="", ron=50.0, hyst=2e-3, vmin=2.0):
        super().__init__((inp, inn, out, vp, vn), part, name)
        self.ron, self.hyst, self.vmin = ron, hyst, vmin

    def next_state(self, x):
        vip, vin, _, vp, vn = (float(x[n]) for n in self.nodes)
        if vp - vn < self.vmin:
            return 0
        d = vin - vip
        if self.state == 0 and d > self.hyst / 2:
            return 1
        if self.state == 1 and d < -self.hyst / 2:
            return 0
        return self.state

    def thresholds(self, x):
        vip, vin, _, vp, vn = (float(x[n]) for n in self.nodes)
        return [vin - vip - self.hyst / 2, vin - vip + self.hyst / 2, vp - vn - self.vmin]

    def stamp_step(self, A, b, t, h, mode):
        if self.state:
            stamp_emf(A, b, self.nodes[2], self.nodes[4], 1.0 / self.ron, 0.05)
        else:
            stamp_g(A, self.nodes[2], self.nodes[4], 1.0 / R_OFF)

    def currents(self, x):
        out, vn = self.nodes[2], self.nodes[4]
        i = (x[out] - x[vn] - 0.05) / self.ron if self.state else 0.0
        return [0.0, 0.0, i, 0.0, -i]

    def observe(self, x):
        return {"state": self.state, "i": self.currents(x)[2], "p": self.power(x)}


# --------------------------------------------------------------------------- 555 timer

class Timer555(EventDevice):
    """Behavioural 555: comparators at CTRL and the 1/3 tap (``mid``, an internal node of the 3 x 5k divider the
    builder adds), SR latch with dominant reset pin and trigger, discharge transistor, totem-pole output.
    Terminals: GND, TRIG, OUT, RESET, CTRL, THR, DIS, VCC, MID."""
    kind = "timer555"

    def __init__(self, gnd, trig, out, rst, ctrl, thr, dis, vcc, mid, cmos=False, part=None, name=""):
        super().__init__((gnd, trig, out, rst, ctrl, thr, dis, vcc, mid), part, name)
        self.cmos = cmos
        if cmos:
            self.drop_h, self.rout_h, self.drop_l, self.rout_l, self.vrst, self.vmin = 0.0, 50.0, 0.0, 20.0, 1.1, 1.5
        else:
            self.drop_h, self.rout_h, self.drop_l, self.rout_l, self.vrst, self.vmin = 1.4, 8.0, 0.1, 8.0, 0.7, 3.0
        self.r_dis = 10.0

    def next_state(self, x):
        gnd, trig, _, rst, ctrl, thr, _, vcc, mid = (float(x[n]) for n in self.nodes)
        if vcc - gnd < self.vmin or rst - gnd < self.vrst:
            return 0
        if trig < mid:
            return 1
        if thr > ctrl:
            return 0
        return self.state

    def thresholds(self, x):
        gnd, trig, _, rst, ctrl, thr, _, vcc, mid = (float(x[n]) for n in self.nodes)
        return [trig - mid, thr - ctrl, rst - gnd - self.vrst, vcc - gnd - self.vmin]

    def stamp_step(self, A, b, t, h, mode):
        gnd, out, dis, vcc = self.nodes[0], self.nodes[2], self.nodes[6], self.nodes[7]
        if self.state:
            stamp_emf(A, b, vcc, out, 1.0 / self.rout_h, self.drop_h)
            stamp_g(A, dis, gnd, 1.0 / R_OFF)
        else:
            stamp_emf(A, b, out, gnd, 1.0 / self.rout_l, self.drop_l)
            stamp_g(A, dis, gnd, 1.0 / self.r_dis)

    def currents(self, x):
        gnd, trig, out, rst, ctrl, thr, dis, vcc, mid = self.nodes
        cur = [0.0] * 9
        if self.state:
            i = (x[vcc] - x[out] - self.drop_h) / self.rout_h
            cur[7] += i
            cur[2] -= i
        else:
            i = (x[out] - x[gnd] - self.drop_l) / self.rout_l
            cur[2] += i
            cur[0] -= i
            idis = (x[dis] - x[gnd]) / self.r_dis
            cur[6] += idis
            cur[0] -= idis
        return cur

    def observe(self, x):
        return {"state": self.state, "i": -self.currents(x)[2], "p": self.power(x)}


# --------------------------------------------------------------------------- regulators and references

class Regulator(Behavioral):
    """Linear regulator. Terminals: IN, REF, OUT (+ EN). Fixed parts: REF is the ground pin and the output sits at
    REF + vset. Adjustable parts: REF is the ADJ pin, vset the reference (1.25 V), quiescent current to OUT.
    The pass element only sources current, limited to ilim; pol = -1 for negative regulators (79xx)."""
    kind = "regulator"

    def __init__(self, vin, ref, vout, en=None, vset=5.0, vdo=1.2, rout=0.05, ilim=1.0, iq=5e-3, adj=False, pol=1,
                 part=None, name="", vmax=20.0):
        nodes = (vin, ref, vout) + ((en,) if en is not None else ())
        super().__init__(nodes, part, name)
        self.vset, self.vdo, self.rout, self.ilim, self.iq, self.adj, self.pol = vset, vdo, rout, ilim, iq, adj, pol
        self.has_en = en is not None
        self.i0 = 1e-4
        self.vmax = vmax

    def func(self, V):
        return self._eval(V)[0]

    def jac(self, V):
        return self._eval(V)

    def begin(self, x):
        self._vold = [float(x[n]) for n in self.nodes]
        self._lim = [0.5, 0.5, 0.5, 0.5]
        self._dir = [0, 0, 0, 0]

    def stamp_nl(self, A, b, x):
        # limit how far the input/output operating point moves per Newton iteration: the pass element is flat in
        # cut-off and in current limit, so unlimited steps ping-pong between the two (light or no load). The limit
        # halves whenever the direction reverses, homing in on the narrow regulating window.
        V = [float(x[n]) for n in self.nodes]
        old = getattr(self, "_vold", None)
        limited = False
        if old is not None:
            for k in (0, 2):
                d = V[k] - old[k]
                sgn = 1 if d > 0 else (-1 if d < 0 else 0)
                if sgn and sgn == -self._dir[k]:
                    self._lim[k] = max(self._lim[k] * 0.5, 1e-6)
                elif sgn:
                    self._lim[k] = min(self._lim[k] * 1.5, 0.5)
                if sgn:
                    self._dir[k] = sgn
                if abs(d) > self._lim[k]:
                    V[k] = old[k] + self._lim[k] * sgn
                    limited = True
        self._vold = V
        I, J = self._eval(V)
        from .devices import stamp_terms
        stamp_terms(A, b, self.nodes, I, J, V)
        return limited

    def _eval(self, V):
        p = self.pol
        vin, vr, vo = p * V[0], p * V[1], p * V[2]
        w = 0.02
        a, b = vr + self.vset, vin - self.vdo
        target = smin(a, b, w)
        da, db = sig((b - a) / w), sig((a - b) / w)  # d target / d a, d b
        g = 1.0 / self.rout
        u = (target - vo) * g
        I1 = self.i0 * sp(u / self.i0)
        th = math.tanh(I1 / self.ilim)
        I = self.ilim * th
        # dI/d(target - vo); the floor keeps Newton moving through the cut-off and current-limit regions
        dI = g * sig(u / self.i0) * (1.0 - th * th)
        if NEWTON["it"] < 12:
            dI = max(dI, 0.02 * g)
        k = len(V)
        dIdv = [0.0] * k
        dIdv[0] = dI * db
        dIdv[1] = dI * da
        dIdv[2] = -dI
        if self.has_en:
            ref = vr if not self.adj else vo - self.vset
            ze = (p * V[3] - ref - 1.0) / 0.05
            s_en = sig(ze)
            ds = s_en * (1 - s_en) / 0.05
            dIdv = [d * s_en for d in dIdv]
            dIdv[3] = I * ds
            if self.adj:
                dIdv[2] -= I * ds
            else:
                dIdv[1] -= I * ds
            I *= s_en
        zq = (vin - (vo if self.adj else vr) - 0.8) / 0.1
        sq = sig(zq)
        iq = self.iq * sq
        diq = self.iq * sq * (1 - sq) / 0.1
        dq = [0.0] * k
        dq[0] = diq
        dq[2 if self.adj else 1] = -diq
        if self.adj:
            cur = [I + iq, 0.0, -I - iq]
            J = [[dIdv[c] + dq[c] for c in range(k)], [0.0] * k, [-dIdv[c] - dq[c] for c in range(k)]]
        else:
            # internal feedback divider: a 100 k load from OUT to the ground pin
            gb = 1e-5
            ib = gb * (vo - vr)
            cur = [I + iq, -iq - ib, -I + ib]
            J = [[dIdv[c] + dq[c] for c in range(k)], [-dq[c] for c in range(k)], [-dIdv[c] for c in range(k)]]
            J[1][1] += gb
            J[1][2] -= gb
            J[2][1] -= gb
            J[2][2] += gb
        if self.has_en:
            cur.append(0.0)
            J.append([0.0] * k)
        return [p * c for c in cur], J

    def observe(self, x):
        V = [float(x[n]) for n in self.nodes]
        I = -self.func(V)[2] * self.pol
        return {"v": V[2] - V[1], "i": I, "p": self.power(x), "vin": V[0] - V[1]}


class ShuntRef(Behavioral):
    """TL431-style programmable shunt: sinks cathode -> anode current when V(REF) - V(A) > vref.
    Terminals: REF, A, K."""
    kind = "shuntref"

    def __init__(self, ref, a, k, vref=2.495, g=2.0, part=None, name=""):
        super().__init__((ref, a, k), part, name)
        self.vref, self.g = vref, g

    def func(self, V):
        vref, va, vk = V
        w = 0.004
        drive = self.g * w * sp((vref - va - self.vref) / w)
        sat = sig((vk - va - 1.2) / 0.1)
        i = drive * sat + GMIN * (vk - va)
        return [0.0, -i, i]


class Sensor(Behavioral):
    """Analog temperature sensor output (LM35: 10 mV/C, TMP36: 0.5 V + 10 mV/C). Terminals: VS, OUT, GND.
    ``temp`` is a live control."""
    kind = "sensor"

    def __init__(self, vs, out, gnd, slope=0.01, offset=0.0, temp=25.0, part=None, name=""):
        super().__init__((vs, out, gnd), part, name)
        self.slope, self.offset, self.temp = slope, offset, temp

    def func(self, V):
        vs, vo, vg = V
        on = sig((vs - vg - 2.5) / 0.1)
        target = vg + (self.offset + self.slope * self.temp) * on
        I = (target - vo) / 100.0
        I = 0.01 * math.tanh(I / 0.01)
        ss = sig(I / 1e-5)
        iq = 60e-6 * on
        return [I * ss + iq, -I, I * (1 - ss) - iq]


class CurrentSensorOut(Behavioral):
    """Hall current sensor output (ACS712): VCC/2 + sensitivity * I, with I sensed across the conductor resistance.
    Terminals: IP+, IP-, OUT, VCC, GND."""
    kind = "currentsensor"

    def __init__(self, ip, im, out, vcc, gnd, sens=0.185, rsense=1.2e-3, part=None, name=""):
        super().__init__((ip, im, out, vcc, gnd), part, name)
        self.sens, self.rsense = sens, rsense

    def func(self, V):
        ip, im, vo, vcc, vg = V
        on = sig((vcc - vg - 3.0) / 0.1)
        target = vg + (0.5 * (vcc - vg) + self.sens * (ip - im) / self.rsense) * on
        I = (target - vo) / 100.0
        I = 0.01 * math.tanh(I / 0.01)
        ss = sig(I / 1e-5)
        iq = 10e-3 * on
        return [0.0, 0.0, -I, I * ss + iq, I * (1 - ss) - iq]


class AudioAmp(Behavioral):
    """LM386-style amplifier: output biased at VS/2, gain 20 (or 200 with pins 1-8 bypassed), inputs referenced to
    ground through 50k (added by the builder). Terminals: IN-, IN+, GND, OUT, VS."""
    kind = "audioamp"

    def __init__(self, inn, inp, gnd, out, vs, gain=20.0, part=None, name=""):
        super().__init__((inn, inp, gnd, out, vs), part, name)
        self.gain = gain

    def func(self, V):
        vin, vip, vg, vo, vs = V
        lo, hi = vg + 0.6, vs - 0.6
        if hi < lo:
            lo = hi = 0.5 * (vg + vs)
        x = 0.5 * (vs + vg) + self.gain * (vip - vin)
        w = 0.02
        T = lo + w * sp((x - lo) / w) - w * sp((x - hi) / w)
        I = (T - vo) / 0.2
        I = 0.6 * math.tanh(I / 0.6)
        ss = sig(I / 1e-4)
        iq = 4e-3 * sig((vs - vg - 3.0) / 0.2)
        return [0.0, 0.0, I * (1 - ss) - iq, -I, I * ss + iq]


# --------------------------------------------------------------------------- opto-couplers and relays

class OptoOutput(Behavioral):
    """Photo-transistor of an opto-coupler. The LED current is sensed across a 1 ohm resistor (KS -> K) that the
    builder puts in series with the LED. Terminals: KS, K, C, E."""
    kind = "opto"

    def __init__(self, ks, k, c, e, ctr=1.0, rsense=1.0, part=None, name=""):
        super().__init__((ks, k, c, e), part, name)
        self.ctr, self.rsense = ctr, rsense

    def func(self, V):
        ks, k, c, e = V
        i_led = max(0.0, (ks - k) / self.rsense)
        vce = c - e
        sat = math.tanh(0.05 * sp(vce / 0.05) / 0.12)
        i = self.ctr * i_led * sat + 1e-9 * vce
        return [0.0, 0.0, i, -i]


class SensedSwitch(EventDevice):
    """Contacts that close while a sensed current exceeds a threshold: logic-output opto-couplers, triac drivers
    (sense resistor between nodes ``sense``) and relays (inductor branch current). ``contacts`` (a, b) pairs,
    ``positions[state]`` = indices of the closed contacts."""
    kind = "sensedswitch"

    def __init__(self, contacts, positions, i_on, i_off, sense=None, rsense=1.0, inductor: Inductor | None = None,
                 part=None, name="", r_on=0.05, delay=0.0):
        nodes = sorted({n for pair in contacts for n in pair} | set(sense or ()))
        super().__init__(nodes, part, name)
        self.contacts, self.positions = contacts, positions
        self.i_on, self.i_off = i_on, i_off
        self.sense, self.rsense, self.inductor = sense, rsense, inductor
        self.r_on = r_on

    def sensed(self, x) -> float:
        if self.inductor is not None:
            return abs(float(x[self.inductor.br[0]]))
        a, c = self.sense
        return (float(x[a]) - float(x[c])) / self.rsense

    def next_state(self, x):
        i = self.sensed(x)
        if self.state == 0 and i > self.i_on:
            return 1
        if self.state == 1 and i < self.i_off:
            return 0
        return self.state

    def thresholds(self, x):
        i = self.sensed(x)
        return [i - self.i_on, i - self.i_off]

    def stamp_step(self, A, b, t, h, mode):
        closed = self.positions[self.state]
        for j, (a, c) in enumerate(self.contacts):
            stamp_g(A, a, c, 1.0 / (self.r_on if j in closed else R_OFF))

    def observe(self, x):
        return {"state": self.state, "i": self.sensed(x)}
