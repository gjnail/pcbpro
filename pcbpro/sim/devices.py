"""Circuit devices for the MNA engine.

Every device works on node indices (0 = ground) and, if it needs them, extra branch-current unknowns. The engine
calls, per transient step / Newton iteration:

  stamp_static(A, b)                  once: constant linear part
  stamp_step(A, b, t, h, mode)        every step: sources, reactive companions, state-dependent linear parts
  begin(x) / stamp_nl(A, b, x)        every Newton iteration (nonlinear devices); returns True if it limited
  accept(x, t, h, mode)               after a converged step
  step_ratio(x0, x1)                  > 1 means the step was too large for this device (local accuracy proxy)
  next_break(t)                       next time the device must land on exactly (pulse edges, ...)

Event devices (``event = True``) have a discrete ``state``: ``next_state(x)`` gives the state the solution x asks for
and ``thresholds(x)`` the signed quantities whose zero crossings change it, so the engine can land on the edge.
Semiconductors are vectorised: devices with a ``group`` class are stamped together with numpy.
mode is 'dc' (operating point: capacitors open, inductors shorted), 'be' (backward Euler) or 'trap'.
"""
from __future__ import annotations

import math

import numpy as np

VT = 0.025852  # thermal voltage at 27 C
GMIN = 1e-12
NEWTON = {"it": 0}  # current Newton iteration (behavioural blocks use quasi-Newton floors only early on)


# --------------------------------------------------------------------------- helpers

def sp(z: float) -> float:
    """Softplus log(1 + e^z), overflow-safe."""
    if z > 35.0:
        return z
    if z < -35.0:
        return math.exp(z)
    return math.log1p(math.exp(z))


def sig(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-min(z, 700.0)))
    e = math.exp(max(z, -700.0))
    return e / (1.0 + e)


def stamp_g(A, a: int, b: int, g: float) -> None:
    A[a, a] += g
    A[b, b] += g
    A[a, b] -= g
    A[b, a] -= g


def stamp_i(b, a: int, c: int, i: float) -> None:
    """Constant current i flowing out of node a, through the element, into node c."""
    b[a] -= i
    b[c] += i


def stamp_emf(A, b, p: int, n: int, g: float, e: float) -> None:
    """Conductance g between p and n with an opposing EMF e: current p->n = g * (Vp - Vn - e)."""
    stamp_g(A, p, n, g)
    b[p] += g * e
    b[n] -= g * e


def stamp_terms(A, b, nodes, I, J, V) -> None:
    """Linearised multi-terminal stamp. I[t] = current into the device at terminal t, J[t][u] = dI[t]/dV[u]."""
    k = len(nodes)
    for r in range(k):
        nr = nodes[r]
        Jr = J[r]
        rhs = I[r]
        for c in range(k):
            jv = Jr[c]
            if jv:
                A[nr, nodes[c]] += jv
                rhs -= jv * V[c]
        b[nr] -= rhs


def limexp(x: np.ndarray):
    """exp with a linear continuation above 80 (keeps Newton finite); returns (value, derivative)."""
    big = x > 80.0
    if not big.any():
        e = np.exp(x)
        return e, e
    xe = np.minimum(x, 80.0)
    e = np.exp(xe)
    val = np.where(big, e * (1.0 + x - 80.0), e)
    return val, e


def pnjlim(vnew: np.ndarray, vold: np.ndarray, vt: np.ndarray, vcrit: np.ndarray) -> np.ndarray:
    """SPICE junction voltage limiting (vectorised)."""
    m = (vnew > vcrit) & (np.abs(vnew - vold) > 2.0 * vt)
    if not m.any():
        return vnew
    out = vnew.copy()
    vo, vn, t, vc = vold[m], vnew[m], vt[m], vcrit[m]
    arg = 1.0 + (vn - vo) / t
    up = np.where(arg > 0, vo + t * np.log(np.maximum(arg, 1e-300)), vc)
    fresh = t * np.log(np.maximum(vn / t, 1e-300))
    out[m] = np.where(vo > 0, up, fresh)
    return out


# --------------------------------------------------------------------------- base

class Device:
    nonlinear = False
    event = False
    reactive = False
    group = None
    n_branches = 0
    kind = "device"

    def __init__(self, nodes, part: str | None = None, name: str = ""):
        self.nodes = [int(n) for n in nodes]
        self.part = part
        self.name = name
        self.br: list[int] = []

    def stamp_static(self, A, b) -> None:
        pass

    def stamp_step(self, A, b, t: float, h: float, mode: str) -> None:
        pass

    def begin(self, x) -> None:
        pass

    def stamp_nl(self, A, b, x) -> bool:
        return False

    def accept(self, x, t: float, h: float, mode: str) -> None:
        pass

    def step_ratio(self, x0, x1) -> float:
        return 0.0

    def next_break(self, t: float) -> float | None:
        return None

    def stamp_ac(self, C) -> None:
        """Frequency-dependent part for AC analysis: C (capacitance-like matrix, multiplied by j*omega)."""

    def currents(self, x) -> list[float]:
        """Current into the device at each terminal (for probes, power and stress checks)."""
        return [0.0] * len(self.nodes)

    def power(self, x) -> float:
        return sum(x[n] * i for n, i in zip(self.nodes, self.currents(x)))

    def observe(self, x) -> dict:
        return {}


class EventDevice(Device):
    """Device with a discrete state that changes at threshold crossings (comparators, 555, logic, relays)."""
    event = True

    def __init__(self, nodes, part=None, name=""):
        super().__init__(nodes, part, name)
        self.state = self.initial_state()
        self.changed_at = -1.0

    def initial_state(self):
        return 0

    def next_state(self, x):
        return self.state

    def thresholds(self, x) -> list[float]:
        return []

    def update(self, x, t: float) -> bool:
        s = self.next_state(x)
        if s != self.state:
            self.state = s
            self.changed_at = t
            self.on_change(t)
            return True
        return False

    def on_change(self, t: float) -> None:
        pass


# --------------------------------------------------------------------------- passives

class Resistor(Device):
    kind = "resistor"

    def __init__(self, a, c, r, part=None, name=""):
        super().__init__((a, c), part, name)
        self.r = max(float(r), 1e-6)

    def stamp_static(self, A, b):
        stamp_g(A, self.nodes[0], self.nodes[1], 1.0 / self.r)

    def stamp_ac(self, C):
        pass

    def currents(self, x):
        i = (x[self.nodes[0]] - x[self.nodes[1]]) / self.r
        return [i, -i]

    def power(self, x):
        v = x[self.nodes[0]] - x[self.nodes[1]]
        return v * v / self.r

    def observe(self, x):
        v = x[self.nodes[0]] - x[self.nodes[1]]
        return {"v": v, "i": v / self.r, "p": v * v / self.r}


class Capacitor(Device):
    """Linear capacitor. Integrated together with all other capacitors by CapacitorGroup."""
    reactive = True
    kind = "capacitor"

    def __init__(self, a, c, cap, part=None, name="", v0: float = 0.0, polarized=False, vmax: float | None = None):
        super().__init__((a, c), part, name)
        self.c = max(float(cap), 1e-18)
        self.v0 = v0
        self.polarized = polarized
        self.vmax = vmax
        self.group = CapacitorGroup
        self.v = v0  # state, kept in sync by the group
        self.i = 0.0

    def stamp_ac(self, C):
        stamp_g(C, self.nodes[0], self.nodes[1], self.c)

    def currents(self, x):
        return [self.i, -self.i]

    def power(self, x):
        return 0.0

    def observe(self, x):
        v = x[self.nodes[0]] - x[self.nodes[1]]
        return {"v": v, "i": self.i, "p": 0.0}


class CapacitorGroup:
    """All capacitors, integrated with numpy (trapezoidal / backward Euler companion models)."""
    nonlinear = False
    reactive = True
    event = False

    def __init__(self, caps: list[Capacitor], size: int):
        self.caps = caps
        self.a = np.array([c.nodes[0] for c in caps], dtype=np.int64)
        self.k = np.array([c.nodes[1] for c in caps], dtype=np.int64)
        self.c = np.array([c.c for c in caps])
        self.v = np.array([c.v0 for c in caps], dtype=float)
        self.i = np.zeros(len(caps))
        self.rows = np.concatenate([self.a, self.k, self.a, self.k])
        self.cols = np.concatenate([self.a, self.k, self.k, self.a])
        self.dv_abs, self.dv_rel = 0.05, 0.02

    def reset(self, x=None, uic=True):
        if uic or x is None:
            self.v = np.array([c.v0 for c in self.caps], dtype=float)
        else:
            self.v = x[self.a] - x[self.k]
        self.i[:] = 0.0
        self._sync()

    def stamp_step(self, A, b, t, h, mode):
        self.stamp_matrix(A, h, mode)
        self.stamp_rhs(b, t, h, mode)

    def stamp_matrix(self, A, h, mode):
        if mode == "dc":
            return
        g = (2.0 if mode == "trap" else 1.0) * self.c / h
        np.add.at(A, (self.rows, self.cols), np.concatenate([g, g, -g, -g]))

    def stamp_rhs(self, b, t, h, mode):
        if mode == "dc":
            return
        if mode == "trap":
            ieq = 2.0 * self.c / h * self.v + self.i
        else:
            ieq = self.c / h * self.v
        np.add.at(b, self.a, ieq)
        np.add.at(b, self.k, -ieq)

    def accept(self, x, t, h, mode):
        v1 = x[self.a] - x[self.k]
        if mode == "dc":
            self.i[:] = 0.0
        elif mode == "trap":
            self.i = 2.0 * self.c / h * (v1 - self.v) - self.i
        else:
            self.i = self.c / h * (v1 - self.v)
        self.v = v1
        self._sync()

    def _sync(self):
        for j, c in enumerate(self.caps):
            c.v = float(self.v[j])
            c.i = float(self.i[j])

    def step_ratio(self, x0, x1):
        v1 = x1[self.a] - x1[self.k]
        dv = np.abs(v1 - self.v)
        tol = self.dv_abs + self.dv_rel * np.maximum(np.abs(v1), np.abs(self.v))
        return float((dv / tol).max()) if len(dv) else 0.0


class Inductor(Device):
    reactive = True
    n_branches = 1
    kind = "inductor"

    def __init__(self, a, c, ind, part=None, name="", i0: float = 0.0, r_series: float = 0.0):
        super().__init__((a, c), part, name)
        self.l = max(float(ind), 1e-15)
        self.i0 = i0
        self.i = i0
        self.v = 0.0

    def reset(self, x=None, uic=True):
        self.i = self.i0 if (uic or x is None) else float(x[self.br[0]])
        self.v = 0.0

    def stamp_static(self, A, b):
        a, c, k = self.nodes[0], self.nodes[1], self.br[0]
        A[a, k] += 1.0
        A[c, k] -= 1.0
        A[k, a] += 1.0
        A[k, c] -= 1.0

    def stamp_step(self, A, b, t, h, mode):
        self.stamp_matrix(A, h, mode)
        self.stamp_rhs(b, t, h, mode)

    def stamp_matrix(self, A, h, mode):
        k = self.br[0]
        if mode == "dc":
            A[k, k] -= 1e-9  # keep loops of inductors and sources solvable
        else:
            A[k, k] -= (2.0 if mode == "trap" else 1.0) * self.l / h

    def stamp_rhs(self, b, t, h, mode):
        if mode == "dc":
            return
        k = self.br[0]
        if mode == "trap":
            b[k] -= 2.0 * self.l / h * self.i + self.v
        else:
            b[k] -= self.l / h * self.i

    def accept(self, x, t, h, mode):
        self.i = float(x[self.br[0]])
        self.v = float(x[self.nodes[0]] - x[self.nodes[1]])
        if mode == "dc":
            self.v = 0.0

    def step_ratio(self, x0, x1):
        i1 = float(x1[self.br[0]])
        return abs(i1 - self.i) / (1e-3 + 0.02 * max(abs(i1), abs(self.i)))

    def stamp_ac(self, C):
        k = self.br[0]
        C[k, k] -= self.l

    def currents(self, x):
        i = float(x[self.br[0]])
        return [i, -i]

    def observe(self, x):
        return {"v": float(x[self.nodes[0]] - x[self.nodes[1]]), "i": float(x[self.br[0]]), "p": 0.0}


class Transformer(Device):
    """Ideal multi-winding transformer. ``windings`` = [(a, b, turns)]; ``t`` is a "volts per turn" node.

    Each winding obeys V(a) - V(b) = turns * V(t), and its ampere-turns flow into node t, so whatever is connected
    between t and ground is the core referred to a one-turn winding: an inductor there is the magnetising inductance
    (L_primary / N_primary^2), a resistor the core loss. With nothing else on t the windings are ideal."""
    kind = "transformer"

    def __init__(self, windings: list[tuple[int, int, float]], t: int, part=None, name=""):
        nodes = [n for a, b, _ in windings for n in (a, b)] + [t]
        super().__init__(nodes, part, name)
        self.windings = [(int(a), int(b), float(n)) for a, b, n in windings]
        self.t = int(t)
        self.n_branches = len(windings)

    def stamp_static(self, A, b):
        t = self.t
        for (a, c, n), k in zip(self.windings, self.br):
            A[a, k] += 1.0  # winding current leaves node a, returns at node c
            A[c, k] -= 1.0
            A[k, a] += 1.0  # V(a) - V(c) - n V(t) = 0
            A[k, c] -= 1.0
            A[k, t] -= n
            A[t, k] -= n  # its ampere-turns drive the core node

    def currents(self, x):
        out = []
        for (a, c, n), k in zip(self.windings, self.br):
            i = float(x[k])
            out += [i, -i]
        return out + [0.0]

    def power(self, x):
        return 0.0

    def observe(self, x):
        k = self.br[-1]
        return {"v": float(x[self.windings[-1][0]] - x[self.windings[-1][1]]), "i": float(x[k]), "p": 0.0}


# --------------------------------------------------------------------------- sources

class Waveform:
    """Source value over time. kind: dc | sine | square | pulse | pwl | samples."""

    def __init__(self, kind: str = "dc", **p):
        self.kind = kind
        self.p = p
        if kind == "samples":
            self.data = np.asarray(p.get("data", []), dtype=float)
            self.rate = float(p.get("rate", 48000.0))

    def value(self, t: float) -> float:
        p, k = self.p, self.kind
        if k == "dc":
            return p.get("v", 0.0)
        if k == "sine":
            return p.get("offset", 0.0) + p.get("amp", 1.0) * math.sin(2 * math.pi * p.get("freq", 1e3) * t
                                                                       + math.radians(p.get("phase", 0.0)))
        if k == "square":
            f = p.get("freq", 1e3)
            ph = (t * f) % 1.0
            return p.get("hi", 1.0) if ph < p.get("duty", 0.5) else p.get("lo", 0.0)
        if k == "pulse":
            v1, v2 = p.get("v1", 0.0), p.get("v2", 1.0)
            td, tr, tf = p.get("delay", 0.0), p.get("rise", 1e-6), p.get("fall", 1e-6)
            pw, per = p.get("width", 1e-3), p.get("period", 0.0)
            if t < td:
                return v1
            tt = t - td
            if per > 0:
                tt %= per
            if tt < tr:
                return v1 + (v2 - v1) * tt / tr
            if tt < tr + pw:
                return v2
            if tt < tr + pw + tf:
                return v2 + (v1 - v2) * (tt - tr - pw) / tf
            return v1
        if k == "pwl":
            pts = p.get("points", [])
            if not pts:
                return 0.0
            if t <= pts[0][0]:
                return pts[0][1]
            for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
                if t0 <= t <= t1:
                    return v0 + (v1 - v0) * (t - t0) / max(t1 - t0, 1e-15)
            return pts[-1][1]
        if k == "samples":
            if not len(self.data):
                return 0.0
            pos = (t - p.get("start", 0.0)) * self.rate
            if pos <= 0:
                return float(self.data[0]) * p.get("gain", 1.0)
            i = int(pos)
            if i >= len(self.data) - 1:
                return float(self.data[-1]) * p.get("gain", 1.0) if not p.get("loop") else \
                    float(self.data[i % len(self.data)]) * p.get("gain", 1.0)
            f = pos - i
            return float(self.data[i] * (1 - f) + self.data[i + 1] * f) * p.get("gain", 1.0)
        return 0.0

    def next_break(self, t: float) -> float | None:
        p, k = self.p, self.kind
        eps = 1e-12
        if k == "square":
            f, d = p.get("freq", 1e3), p.get("duty", 0.5)
            n = math.floor(t * f)
            for c in (n + d, n + 1.0, n + 1.0 + d):
                tc = c / f
                if tc > t + eps:
                    return tc
        if k == "pulse":
            td, tr, tf = p.get("delay", 0.0), p.get("rise", 1e-6), p.get("fall", 1e-6)
            pw, per = p.get("width", 1e-3), p.get("period", 0.0)
            edges = [0.0, tr, tr + pw, tr + pw + tf]
            base = td
            if per > 0 and t > td:
                base = td + math.floor((t - td) / per) * per
            for cyc in range(2):
                for e in edges:
                    tc = base + cyc * per + e
                    if tc > t + eps:
                        return tc
                if per <= 0:
                    break
        if k == "pwl":
            for tp, _ in p.get("points", []):
                if tp > t + eps:
                    return tp
        return None

    def max_step(self) -> float | None:
        if self.kind == "sine":
            return 1.0 / (40.0 * max(self.p.get("freq", 1e3), 1e-3))
        if self.kind == "samples":
            return 1.0 / self.rate
        return None


class VoltageSource(Device):
    """Ideal voltage source (branch current = current into the + terminal from the circuit, negative when
    sourcing). ``ramp``: seconds over which the value rises from 0 at power-up."""
    n_branches = 1
    kind = "vsource"

    def __init__(self, a, c, wave: Waveform | float, part=None, name="", ramp: float = 0.0):
        super().__init__((a, c), part, name)
        self.wave = wave if isinstance(wave, Waveform) else Waveform("dc", v=float(wave))
        self.ramp = ramp
        self.scale = 1.0  # source stepping
        self.enabled = True
        self.ramping = False  # set by the simulator for a power-up start
        self.ac = 0.0  # AC magnitude for small-signal analysis

    def value(self, t: float) -> float:
        if not self.enabled:
            return 0.0
        v = self.wave.value(t)
        if self.ramping and self.ramp > 0 and t < self.ramp:
            v *= t / self.ramp
        return v * self.scale

    def stamp_static(self, A, b):
        a, c, k = self.nodes[0], self.nodes[1], self.br[0]
        A[a, k] += 1.0
        A[c, k] -= 1.0
        A[k, a] += 1.0
        A[k, c] -= 1.0

    def stamp_step(self, A, b, t, h, mode):
        b[self.br[0]] += self.value(t)

    def stamp_matrix(self, A, h, mode):
        pass

    def stamp_rhs(self, b, t, h, mode):
        b[self.br[0]] += self.value(t)

    def next_break(self, t):
        if self.ramping and self.ramp > 0 and t < self.ramp - 1e-12:
            return self.ramp
        return self.wave.next_break(t)

    def currents(self, x):
        i = float(x[self.br[0]])
        return [i, -i]

    def observe(self, x):
        return {"v": float(x[self.nodes[0]] - x[self.nodes[1]]), "i": -float(x[self.br[0]]),
                "p": -float(x[self.br[0]]) * float(x[self.nodes[0]] - x[self.nodes[1]])}


class CurrentSource(Device):
    kind = "isource"

    def __init__(self, a, c, wave: Waveform | float, part=None, name=""):
        super().__init__((a, c), part, name)
        self.wave = wave if isinstance(wave, Waveform) else Waveform("dc", v=float(wave))
        self.scale = 1.0

    def stamp_step(self, A, b, t, h, mode):
        stamp_i(b, self.nodes[0], self.nodes[1], self.wave.value(t) * self.scale)

    def stamp_matrix(self, A, h, mode):
        pass

    def stamp_rhs(self, b, t, h, mode):
        stamp_i(b, self.nodes[0], self.nodes[1], self.wave.value(t) * self.scale)

    def next_break(self, t):
        return self.wave.next_break(t)

    def currents(self, x):
        return [0.0, 0.0]


# --------------------------------------------------------------------------- switches and pots

R_ON = 0.02
R_OFF = 1e9


class Switch(Device):
    """A set of contacts; ``positions[state]`` lists the (a, b) node pairs that are closed in that state."""
    kind = "switch"

    def __init__(self, contacts: list[tuple[int, int]], positions: list[list[int]], part=None, name="",
                 momentary=False, state: int = 0, r_on: float = R_ON):
        nodes = sorted({n for pair in contacts for n in pair})
        super().__init__(nodes, part, name)
        self.contacts = contacts
        self.positions = positions
        self.momentary = momentary
        self.state = state
        self.r_on = r_on

    def closed(self, j: int) -> bool:
        return j in self.positions[self.state % len(self.positions)]

    def stamp_step(self, A, b, t, h, mode):
        for j, (a, c) in enumerate(self.contacts):
            stamp_g(A, a, c, 1.0 / (self.r_on if self.closed(j) else R_OFF))

    def contact_current(self, x, j: int) -> float:
        a, c = self.contacts[j]
        return (x[a] - x[c]) / (self.r_on if self.closed(j) else R_OFF)

    def power(self, x):
        return sum(self.contact_current(x, j) * (x[a] - x[c]) for j, (a, c) in enumerate(self.contacts))

    def observe(self, x):
        cur = [self.contact_current(x, j) for j in range(len(self.contacts))]
        return {"i": max(cur, key=abs) if cur else 0.0, "p": self.power(x), "state": self.state}


def taper(pos: float, kind: str) -> float:
    """Resistance fraction between pin 1 and the wiper for a knob position 0 (fully CCW) .. 1 (fully CW)."""
    pos = min(max(pos, 0.0), 1.0)
    if kind == "A":  # audio / log: ~10 % at the half-way point
        return (10.0 ** (2.0 * pos) - 1.0) / 99.0
    if kind == "C":  # reverse log
        return 1.0 - (10.0 ** (2.0 * (1.0 - pos)) - 1.0) / 99.0
    return pos


class Potentiometer(Device):
    kind = "pot"

    def __init__(self, a, w, c, r_total, taper_kind="B", pos=0.5, part=None, name=""):
        super().__init__((a, w, c), part, name)
        self.r = max(float(r_total), 1.0)
        self.taper = taper_kind
        self.pos = pos

    def _r(self):
        f = taper(self.pos, self.taper)
        return max(self.r * f, 0.5), max(self.r * (1.0 - f), 0.5)

    def stamp_step(self, A, b, t, h, mode):
        r1, r2 = self._r()
        a, w, c = self.nodes
        stamp_g(A, a, w, 1.0 / r1)
        stamp_g(A, w, c, 1.0 / r2)

    def currents(self, x):
        r1, r2 = self._r()
        a, w, c = self.nodes
        i1 = (x[a] - x[w]) / r1
        i2 = (x[w] - x[c]) / r2
        return [i1, i2 - i1, -i2]

    def power(self, x):
        r1, r2 = self._r()
        a, w, c = self.nodes
        return (x[a] - x[w]) ** 2 / r1 + (x[w] - x[c]) ** 2 / r2

    def observe(self, x):
        return {"p": self.power(x), "pos": self.pos}


# --------------------------------------------------------------------------- diodes (vectorised)

class Diode(Device):
    """Junction diode: Shockley + reverse breakdown (Zener). Terminals (anode, cathode); a series resistance gets
    an internal node from the netlist builder (use ``make_diode``)."""
    nonlinear = True
    kind = "diode"

    def __init__(self, a, k, is_=1e-14, n=1.0, bv=0.0, ibv=1e-3, nbv=1.0, part=None, name="", imax=1.0,
                 color: str | None = None, rs_node: int | None = None, rs: float = 0.0):
        super().__init__((a, k), part, name)
        self.is_, self.n, self.bv, self.ibv, self.nbv = is_, n, bv, ibv, nbv
        self.imax = imax
        self.color = color  # LEDs: emission colour (hex)
        self.rs = rs
        self.outer = rs_node  # external anode node when rs > 0
        self.group = DiodeGroup

    def current(self, v: float) -> float:
        nvt = self.n * VT
        i = self.is_ * (math.exp(min(v / nvt, 80.0)) - 1.0)
        if self.bv > 0:
            i -= self.ibv * math.exp(min(-(v + self.bv) / (self.nbv * VT), 80.0))
        return i + GMIN * v

    def currents(self, x):
        i = self.current(float(x[self.nodes[0]] - x[self.nodes[1]]))
        return [i, -i]

    def power(self, x):
        v = float(x[self.nodes[0]] - x[self.nodes[1]])
        p = v * self.current(v)
        if self.rs and self.outer is not None:
            vr = float(x[self.outer] - x[self.nodes[0]])
            p += vr * vr / self.rs
        return p

    def observe(self, x):
        v = float(x[self.nodes[0]] - x[self.nodes[1]])
        i = self.current(v)
        vt = v + (float(x[self.outer] - x[self.nodes[0]]) if self.outer is not None else 0.0)
        return {"v": vt, "i": i, "p": self.power(x)}


class DiodeGroup:
    nonlinear = True
    reactive = False
    event = False

    def __init__(self, diodes: list[Diode], size: int):
        self.d = diodes
        self.a = np.array([d.nodes[0] for d in diodes], dtype=np.int64)
        self.k = np.array([d.nodes[1] for d in diodes], dtype=np.int64)
        self.is_ = np.array([d.is_ for d in diodes])
        self.nvt = np.array([d.n * VT for d in diodes])
        self.bv = np.array([d.bv for d in diodes])
        self.has_bv = self.bv > 0
        self.ibv = np.array([d.ibv for d in diodes])
        self.nbvt = np.array([d.nbv * VT for d in diodes])
        self.vcrit = self.nvt * np.log(self.nvt / (math.sqrt(2.0) * self.is_))
        self.vcrit_r = self.nbvt * np.log(self.nbvt / (math.sqrt(2.0) * np.maximum(self.ibv, 1e-30)))
        self.vold = np.zeros(len(diodes))
        self.rows = np.concatenate([self.a, self.k, self.a, self.k])
        self.cols = np.concatenate([self.a, self.k, self.k, self.a])
        self.small = len(diodes) <= 6
        self.vcrit_f, self.bv_f, self.nbvt_f = self.vcrit.tolist(), self.bv.tolist(), self.nbvt.tolist()
        self.vcrit_r_f, self.is_f, self.ibv_f = self.vcrit_r.tolist(), self.is_.tolist(), self.ibv.tolist()

    def begin(self, x):
        self.vold = x[self.a] - x[self.k]
        if self.small:
            self.vold = self.vold.tolist()

    def _stamp_scalar(self, A, b, x):
        """Plain-Python path for a handful of diodes (numpy overhead dominates on tiny arrays)."""
        limited = False
        vold = self.vold
        exp = math.exp
        log = math.log
        for j in range(len(self.d)):
            a, k = int(self.a[j]), int(self.k[j])
            v = float(x[a] - x[k])
            nvt = float(self.nvt[j])
            vo = float(vold[j])
            if v > self.vcrit_f[j] and abs(v - vo) > 2 * nvt:
                if vo > 0:
                    arg = 1 + (v - vo) / nvt
                    vl = vo + nvt * log(arg) if arg > 0 else self.vcrit_f[j]
                else:
                    vl = nvt * log(max(v / nvt, 1e-300))
                limited = True
            else:
                vl = v
            bv = self.bv_f[j]
            if bv > 0:
                vr = -(v + bv)
                if vr > 0:
                    nb = self.nbvt_f[j]
                    vro = -(vo + bv)
                    if vr > self.vcrit_r_f[j] and abs(vr - vro) > 2 * nb:
                        if vro > 0:
                            arg = 1 + (vr - vro) / nb
                            vrl = vro + nb * log(arg) if arg > 0 else self.vcrit_r_f[j]
                        else:
                            vrl = nb * log(max(vr / nb, 1e-300))
                        vl = -vrl - bv
                        limited = True
            vold[j] = vl
            z = vl / nvt
            if z > 80.0:
                e80 = exp(80.0)
                e, de = e80 * (1.0 + z - 80.0), e80
            else:
                e = de = exp(z)
            is_ = self.is_f[j]
            i = is_ * (e - 1.0)
            g = is_ * de / nvt
            if bv > 0:
                nb = self.nbvt_f[j]
                zb = -(vl + bv) / nb
                if zb > 80.0:
                    e80 = exp(80.0)
                    eb, deb = e80 * (1.0 + zb - 80.0), e80
                else:
                    eb = deb = exp(zb)
                ibv = self.ibv_f[j]
                i -= ibv * eb
                g += ibv * deb / nb
            i += GMIN * vl
            g += GMIN
            ieq = i - g * vl
            A[a, a] += g
            A[k, k] += g
            A[a, k] -= g
            A[k, a] -= g
            b[a] -= ieq
            b[k] += ieq
        return limited

    def stamp_nl(self, A, b, x):
        if self.small:
            return self._stamp_scalar(A, b, x)
        v = x[self.a] - x[self.k]
        vl = pnjlim(v, self.vold, self.nvt, self.vcrit)
        if self.has_bv.any():  # limit the breakdown junction too (mirror of the forward one)
            vr = -(v + self.bv)
            vro = -(self.vold + self.bv)
            vrl = pnjlim(vr, vro, self.nbvt, self.vcrit_r)
            vl = np.where(self.has_bv & (vr > 0), -vrl - self.bv, vl)
        limited = bool(np.any(np.abs(vl - v) > 1e-9))
        self.vold = vl
        e, de = limexp(vl / self.nvt)
        i = self.is_ * (e - 1.0)
        g = self.is_ * de / self.nvt
        if self.has_bv.any():
            eb, deb = limexp(-(vl + self.bv) / self.nbvt)
            eb = np.where(self.has_bv, eb, 0.0)
            deb = np.where(self.has_bv, deb, 0.0)
            i = i - self.ibv * eb
            g = g + self.ibv * deb / self.nbvt
        i = i + GMIN * vl
        g = g + GMIN
        ieq = i - g * vl
        np.add.at(A, (self.rows, self.cols), np.concatenate([g, g, -g, -g]))
        np.add.at(b, self.a, -ieq)
        np.add.at(b, self.k, ieq)
        return limited


# --------------------------------------------------------------------------- bipolar transistors (vectorised)

class BJT(Device):
    """Ebers-Moll transport model with forward Early effect. Terminals (C, B, E); pol +1 NPN, -1 PNP."""
    nonlinear = True
    kind = "bjt"

    def __init__(self, c, b, e, pol=1, is_=1e-14, bf=100.0, br=1.0, vaf=100.0, nf=1.0, nr=1.0, part=None, name="",
                 imax=0.2, pmax=0.5):
        super().__init__((c, b, e), part, name)
        self.pol, self.is_, self.bf, self.brev, self.vaf, self.nf, self.nr = pol, is_, bf, br, vaf, nf, nr
        self.imax, self.pmax = imax, pmax
        self.group = BJTGroup

    def _model(self, vbe, vbc):
        p = self.pol
        vbe, vbc = p * vbe, p * vbc
        If = self.is_ * (math.exp(min(vbe / (self.nf * VT), 80)) - 1)
        Ir = self.is_ * (math.exp(min(vbc / (self.nr * VT), 80)) - 1)
        k = max(1.0 - vbc / self.vaf, 0.25) if self.vaf > 0 else 1.0
        ic = (If - Ir) * k - Ir / self.brev
        ib = If / self.bf + Ir / self.brev
        return p * ic, p * ib

    def currents(self, x):
        c, b, e = (float(x[n]) for n in self.nodes)
        ic, ib = self._model(b - e, b - c)
        return [ic, ib, -(ic + ib)]

    def observe(self, x):
        c, b, e = (float(x[n]) for n in self.nodes)
        ic, ib = self._model(b - e, b - c)
        return {"i": ic, "ib": ib, "vce": c - e, "p": self.power(x)}


class BJTGroup:
    nonlinear = True
    reactive = False
    event = False

    def __init__(self, devs: list[BJT], size: int):
        self.d = devs
        self.T = np.array([d.nodes for d in devs], dtype=np.int64)  # (m, 3) C, B, E
        self.p = np.array([d.pol for d in devs], dtype=float)
        self.is_ = np.array([d.is_ for d in devs])
        self.bf = np.array([d.bf for d in devs])
        self.brev = np.array([d.brev for d in devs])
        self.vaf = np.array([d.vaf if d.vaf > 0 else 1e12 for d in devs])
        self.nfvt = np.array([d.nf * VT for d in devs])
        self.nrvt = np.array([d.nr * VT for d in devs])
        self.vcf = self.nfvt * np.log(self.nfvt / (math.sqrt(2.0) * self.is_))
        self.vcr = self.nrvt * np.log(self.nrvt / (math.sqrt(2.0) * self.is_))
        self.vbe_old = np.zeros(len(devs))
        self.vbc_old = np.zeros(len(devs))
        m = len(devs)
        self.ri = np.repeat(self.T, 3, axis=1).reshape(m, 3, 3)
        self.ci = np.tile(self.T, 3).reshape(m, 3, 3)

    def _v(self, x):
        vc, vb, ve = x[self.T[:, 0]], x[self.T[:, 1]], x[self.T[:, 2]]
        return self.p * (vb - ve), self.p * (vb - vc)

    def begin(self, x):
        self.vbe_old, self.vbc_old = self._v(x)

    def stamp_nl(self, A, b, x):
        vbe, vbc = self._v(x)
        lbe = pnjlim(vbe, self.vbe_old, self.nfvt, self.vcf)
        lbc = pnjlim(vbc, self.vbc_old, self.nrvt, self.vcr)
        limited = bool(np.any(np.abs(lbe - vbe) > 1e-9) or np.any(np.abs(lbc - vbc) > 1e-9))
        self.vbe_old, self.vbc_old = lbe, lbc
        ef, def_ = limexp(lbe / self.nfvt)
        er, der = limexp(lbc / self.nrvt)
        If = self.is_ * (ef - 1.0) + GMIN * lbe
        gf = self.is_ * def_ / self.nfvt + GMIN
        Ir = self.is_ * (er - 1.0) + GMIN * lbc
        gr = self.is_ * der / self.nrvt + GMIN
        kraw = 1.0 - lbc / self.vaf
        k = np.maximum(kraw, 0.25)
        dk = np.where(kraw > 0.25, -1.0 / self.vaf, 0.0)
        ict = (If - Ir) * k
        dict_be = gf * k
        dict_bc = -gr * k + (If - Ir) * dk
        ic = ict - Ir / self.brev
        ib = If / self.bf + Ir / self.brev
        dic_be, dic_bc = dict_be, dict_bc - gr / self.brev
        dib_be, dib_bc = gf / self.bf, gr / self.brev
        die_be, die_bc = -(dic_be + dib_be), -(dic_bc + dib_bc)
        # terminal order C, B, E; dVbe/dV = p*[0, 1, -1], dVbc/dV = p*[-1, 1, 0]; real currents = p * I
        m = len(self.d)
        J = np.empty((m, 3, 3))
        for r, (dbe, dbc) in enumerate(((dic_be, dic_bc), (dib_be, dib_bc), (die_be, die_bc))):
            J[:, r, 0] = -dbc
            J[:, r, 1] = dbe + dbc
            J[:, r, 2] = -dbe
        I = np.stack([ic, ib, -(ic + ib)], axis=1) * self.p[:, None]
        # linearisation point consistent with the limited junction voltages: Vb = 0
        V = np.stack([-lbc * self.p, np.zeros(m), -lbe * self.p], axis=1)
        np.add.at(A, (self.ri, self.ci), J)
        rhs = I - np.einsum("mij,mj->mi", J, V)
        np.add.at(b, self.T, -rhs)
        return limited


# --------------------------------------------------------------------------- field-effect transistors (vectorised)

class FET(Device):
    """Square-law FET with a smooth sub-threshold corner. Terminals (D, G, S); pol +1 n-channel, -1 p-channel.
    MOSFET: vth > 0 (enhancement). JFET: vth = pinch-off (< 0 for n-channel), k = 2 * Idss / Vp^2."""
    nonlinear = True
    kind = "fet"

    def __init__(self, d, g, s, pol=1, vth=2.0, k=0.1, lam=0.01, part=None, name="", imax=0.5, pmax=0.5,
                 nsub=1.5):
        super().__init__((d, g, s), part, name)
        self.pol, self.vth, self.k, self.lam, self.nsub = pol, vth, k, lam, nsub
        self.imax, self.pmax = imax, pmax
        self.group = FETGroup

    def drain_current(self, vd, vg, vs):
        p = self.pol
        vgs, vds = p * (vg - vs), p * (vd - vs)
        rev = vds < 0
        if rev:
            vgs, vds = p * (vg - vd), -vds
        w = self.nsub * VT
        vov = w * sp((vgs - self.vth) / w)
        if vds < vov:
            i = self.k * (vov * vds - 0.5 * vds * vds) * (1 + self.lam * vds)
        else:
            i = 0.5 * self.k * vov * vov * (1 + self.lam * vds)
        return p * (-i if rev else i)

    def currents(self, x):
        vd, vg, vs = (float(x[n]) for n in self.nodes)
        i = self.drain_current(vd, vg, vs)
        return [i, 0.0, -i]

    def observe(self, x):
        vd, vg, vs = (float(x[n]) for n in self.nodes)
        i = self.drain_current(vd, vg, vs)
        return {"i": i, "vgs": vg - vs, "vds": vd - vs, "p": i * (vd - vs)}


class FETGroup:
    nonlinear = True
    reactive = False
    event = False

    def __init__(self, devs: list[FET], size: int):
        self.d = devs
        self.T = np.array([d.nodes for d in devs], dtype=np.int64)  # D, G, S
        self.p = np.array([d.pol for d in devs], dtype=float)
        self.vth = np.array([d.vth for d in devs])
        self.k = np.array([d.k for d in devs])
        self.lam = np.array([d.lam for d in devs])
        self.w = np.array([d.nsub * VT for d in devs])
        m = len(devs)
        self.ri = np.repeat(self.T, 3, axis=1).reshape(m, 3, 3)
        self.ci = np.tile(self.T, 3).reshape(m, 3, 3)
        self.vgs_old = np.zeros(m)

    def begin(self, x):
        self.vgs_old = self.p * (x[self.T[:, 1]] - x[self.T[:, 2]])

    def stamp_nl(self, A, b, x):
        vd, vg, vs = x[self.T[:, 0]], x[self.T[:, 1]], x[self.T[:, 2]]
        p = self.p
        vds_n = p * (vd - vs)
        rev = vds_n < 0
        vgs = np.where(rev, p * (vg - vd), p * (vg - vs))
        vds = np.abs(vds_n)
        # limit large gate swings per iteration (keeps the exponential corner well-behaved)
        vgs_n = p * (vg - vs)
        dv = vgs_n - self.vgs_old
        lim = 3.0 + 0.5 * np.abs(self.vgs_old - self.vth)
        limited_mask = np.abs(dv) > lim
        limited = bool(limited_mask.any())
        if limited:
            vgs_n = np.where(limited_mask, self.vgs_old + np.sign(dv) * lim, vgs_n)
            vgs = np.where(rev, vgs_n - vds_n, vgs_n)  # Vgd = Vgs - Vds (polarity space)
        self.vgs_old = vgs_n
        z = (vgs - self.vth) / self.w
        vov = self.w * np.where(z > 35, z, np.log1p(np.exp(np.minimum(z, 35))))
        s = 1.0 / (1.0 + np.exp(-np.clip(z, -700, 700)))
        lin = vds < vov
        cl = 1.0 + self.lam * vds
        i_lin = self.k * (vov * vds - 0.5 * vds * vds) * cl
        i_sat = 0.5 * self.k * vov * vov * cl
        i = np.where(lin, i_lin, i_sat)
        gm = np.where(lin, self.k * vds * cl, self.k * vov * cl) * s
        gds = np.where(lin, self.k * (vov - vds) * cl + self.k * (vov * vds - 0.5 * vds * vds) * self.lam,
                       0.5 * self.k * vov * vov * self.lam)
        gm = gm + GMIN
        gds = gds + GMIN
        m = len(self.d)
        J = np.zeros((m, 3, 3))
        # normal: current into D = Id; columns D, G, S
        Jd = np.stack([gds, gm, -(gm + gds)], axis=1)
        Js_rev = np.stack([-(gm + gds), gm, gds], axis=1)  # reversed: current into S = Id'
        J[:, 0, :] = np.where(rev[:, None], -Js_rev, Jd)
        J[:, 2, :] = -J[:, 0, :]
        idr = p * i  # real current into drain (normal) or source (reversed)
        I = np.zeros((m, 3))
        I[:, 0] = np.where(rev, -idr, idr)
        I[:, 2] = -I[:, 0]
        # linearisation point in real voltages consistent with the (possibly limited) gate voltage
        V = np.stack([vd, vs + p * vgs_n, vs], axis=1)
        np.add.at(A, (self.ri, self.ci), J)
        rhs = I - np.einsum("mij,mj->mi", J, V)
        np.add.at(b, self.T, -rhs)
        return limited


# --------------------------------------------------------------------------- behavioural blocks

class Behavioral(Device):
    """Nonlinear block given by ``func(V) -> currents into each terminal``; Jacobian by finite differences unless
    ``jac`` is overridden."""
    nonlinear = True
    kind = "behavioral"
    fd_h = 1e-6

    def func(self, V: list[float]) -> list[float]:
        raise NotImplementedError

    def jac(self, V: list[float]):
        I0 = self.func(V)
        k = len(V)
        J = [[0.0] * k for _ in range(k)]
        for c in range(k):
            Vp = list(V)
            h = self.fd_h * max(1.0, abs(V[c]))
            Vp[c] += h
            I1 = self.func(Vp)
            for r in range(k):
                J[r][c] = (I1[r] - I0[r]) / h
        return I0, J

    def stamp_nl(self, A, b, x):
        V = [float(x[n]) for n in self.nodes]
        I, J = self.jac(V)
        stamp_terms(A, b, self.nodes, I, J, V)
        return False

    def currents(self, x):
        return self.func([float(x[n]) for n in self.nodes])


def smin(a: float, b: float, w: float) -> float:
    """Smooth minimum."""
    m = min(a, b)
    return m - w * math.log1p(math.exp(-abs(a - b) / w))
