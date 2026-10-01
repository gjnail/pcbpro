"""Modified nodal analysis engine: DC operating point, adaptive-step transient and small-signal AC.

Unknown vector x = [ground (always 0), node voltages..., branch currents...]. Stamps go into a full matrix and the
ground row and column are dropped when solving.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from .devices import NEWTON, CapacitorGroup, Device, EventDevice, Inductor, VoltageSource


class SimError(RuntimeError):
    pass


class NoConvergence(SimError):
    pass


class Circuit:
    """Nodes and devices. Node 0 is ground."""

    def __init__(self):
        self.node_names: list[str] = ["GND"]
        self.node_index: dict = {}
        self.devices: list[Device] = []
        self.warnings: list[str] = []

    def node(self, key, name: str | None = None) -> int:
        if key in self.node_index:
            return self.node_index[key]
        i = len(self.node_names)
        self.node_index[key] = i
        self.node_names.append(name if name is not None else str(key))
        return i

    def ground(self, key) -> int:
        self.node_index[key] = 0
        return 0

    def internal(self, label: str) -> int:
        i = len(self.node_names)
        self.node_names.append(label)
        return i

    def add(self, dev: Device) -> Device:
        self.devices.append(dev)
        return dev

    @property
    def n_nodes(self) -> int:
        return len(self.node_names)


def _overrides(dev, name: str) -> bool:
    return getattr(type(dev), name) is not getattr(Device, name)


class Simulator:
    def __init__(self, circuit: Circuit, gmin: float = 1e-10, h_max: float = 1e-3, h_min: float = 1e-10):
        self.ckt = circuit
        self.gmin = gmin
        self.h_max_default = h_max
        self.h_min = h_min
        idx = circuit.n_nodes
        for d in circuit.devices:
            d.br = list(range(idx, idx + d.n_branches))
            idx += d.n_branches
        self.N = idx
        self.nn = circuit.n_nodes
        # groups (vectorised device families)
        buckets: dict[type, list] = defaultdict(list)
        singles: list[Device] = []
        for d in circuit.devices:
            if d.group is not None:
                buckets[d.group].append(d)
            else:
                singles.append(d)
        self.groups = [g(devs, self.N) for g, devs in buckets.items()]
        self.capgroup = next((g for g in self.groups if isinstance(g, CapacitorGroup)), None)
        self.singles = singles
        self.nl = [d for d in singles if d.nonlinear] + [g for g in self.groups if g.nonlinear]
        self.steppers = [d for d in singles if _overrides(d, "stamp_step")] + \
                        [g for g in self.groups if hasattr(g, "stamp_step")]
        self.acceptors = [d for d in singles if _overrides(d, "accept")] + \
                         [g for g in self.groups if hasattr(g, "accept")]
        self.reactive = [d for d in singles if d.reactive] + [g for g in self.groups if g.reactive]
        self.events: list[EventDevice] = [d for d in singles if d.event]
        self.breakers = [d for d in singles if _overrides(d, "next_break")]
        self.sources = [d for d in circuit.devices if isinstance(d, VoltageSource)]
        self.A0 = np.zeros((self.N, self.N))
        self.b0 = np.zeros(self.N)
        for d in circuit.devices:
            d.stamp_static(self.A0, self.b0)
        diag = np.arange(1, self.nn)
        self.A0[diag, diag] += gmin
        self.x = np.zeros(self.N)
        self.t = 0.0
        self.h = 1e-7
        self.after_break = True
        self.extra_breaks: list[float] = []
        self.steps = 0
        self.rejected = 0
        self.newton_iters = 0
        self.max_step_hint = min([s.wave.max_step() for s in self.sources if s.wave.max_step()] or [h_max])
        from .devices import Behavioral
        self.damp_nodes = any(isinstance(d, Behavioral) for d in singles)
        self.on_accept = None  # callback(t, x) after each accepted step
        self.vntol, self.reltol = 1e-6, 1e-4  # Newton convergence: absolute volts, relative

    # ------------------------------------------------------------------ solving
    def _assemble(self, t: float, h: float, mode: str, gshunt: float = 0.0):
        A = self.A0.copy()
        b = self.b0.copy()
        for d in self.steppers:
            d.stamp_step(A, b, t, h, mode)
        if gshunt:
            diag = np.arange(1, self.nn)
            A[diag, diag] += gshunt
        return A, b

    def _newton(self, A0, b0, x0, maxit: int = 60):
        x = x0.copy()
        for d in self.nl:
            d.begin(x)
        for it in range(maxit):
            NEWTON["it"] = it
            A = A0.copy()
            b = b0.copy()
            limited = False
            for d in self.nl:
                if d.stamp_nl(A, b, x):
                    limited = True
            try:
                sol = np.linalg.solve(A[1:, 1:], b[1:])
            except np.linalg.LinAlgError:
                raise SimError(self._singular_hint(A)) from None
            xn = np.empty_like(x)
            xn[0] = 0.0
            xn[1:] = sol
            if not np.all(np.isfinite(xn)):
                raise NoConvergence("solution diverged")
            if self.damp_nodes and it > 0:
                # behavioural blocks saturate: cap the per-iteration node voltage change so Newton cannot ping-pong
                dv = xn[1:self.nn] - x[1:self.nn]
                worst = float(np.max(np.abs(dv))) if len(dv) else 0.0
                lim = max(2.0, 0.3 * float(np.max(np.abs(x[1:self.nn]))) if len(dv) else 2.0)
                if worst > lim:
                    xn = x + (xn - x) * (lim / worst)
                    limited = True
            dx = np.abs(xn - x)
            tol = np.empty_like(x)
            tol[:self.nn] = self.vntol + self.reltol * np.abs(xn[:self.nn])
            tol[self.nn:] = 1e-9 + self.reltol * np.abs(xn[self.nn:])
            x = xn
            self.newton_iters += 1
            if not limited and np.all(dx <= tol):
                return x, it + 1
        worst = int(np.argmax(dx / tol))
        raise NoConvergence(f"no convergence near {self.unknown_name(worst)}")

    def unknown_name(self, i: int) -> str:
        if i < self.nn:
            return f"net {self.ckt.node_names[i]}"
        for d in self.ckt.devices:
            if i in d.br:
                return f"current of {d.name or d.kind}"
        return f"unknown {i}"

    def _singular_hint(self, A) -> str:
        empty = [self.ckt.node_names[i] for i in range(1, self.nn)
                 if np.count_nonzero(A[i, 1:]) <= 1 and abs(A[i, i]) <= self.gmin * 1.01]
        if empty:
            return "Floating net(s) with nothing to set their voltage: " + ", ".join(empty[:6])
        return "The circuit matrix is singular (a loop of voltage sources or a floating section)."

    # ------------------------------------------------------------------ DC operating point
    def operating_point(self) -> np.ndarray:
        """Solve the DC operating point (capacitors open, inductors shorted) and make it the current state."""
        x = None
        last_err = None
        try:
            x = self._dc_solve(self.x * 0, 0.0)
        except SimError as e:
            last_err = e
        if x is None:  # gmin stepping
            xg = np.zeros(self.N)
            try:
                for g in (1e-2, 1e-3, 1e-4, 1e-5, 1e-6, 1e-7, 1e-8, 1e-9, 1e-10, 0.0):
                    xg = self._dc_solve(xg, g)
                x = xg
            except SimError as e:
                last_err = e
        if x is None:  # source stepping
            xs = np.zeros(self.N)
            try:
                for s in np.linspace(0.05, 1.0, 20):
                    for src in self.sources:
                        src.scale = float(s)
                    xs = self._dc_solve(xs, 0.0)
                x = xs
            except SimError as e:
                last_err = e
            finally:
                for src in self.sources:
                    src.scale = 1.0
        if x is None:
            raise SimError(f"DC operating point failed: {last_err}")
        # settle discrete states (comparators, 555 latch, logic) against the solution
        for _ in range(30):
            changed = False
            for d in self.events:
                if d.update(x, 0.0):
                    changed = True
            if not changed:
                break
            x = self._dc_solve(x, 0.0)
        self.x = x
        for d in self.acceptors:
            d.accept(x, self.t, 1.0, "dc")
        self.after_break = True
        return x

    def _dc_solve(self, x0, gshunt):
        A, b = self._assemble(self.t, 1.0, "dc", gshunt)
        x, _ = self._newton(A, b, x0, 150)
        return x

    def start_uic(self) -> None:
        """Power-up start: every capacitor and inductor at its initial condition (normally 0) and all node voltages
        at 0; sources ramp up from t = 0."""
        self.x = np.zeros(self.N)
        self.t = 0.0
        for src in self.sources:
            src.ramping = True
        if self.capgroup is not None:
            self.capgroup.reset(uic=True)
        for d in self.singles:
            if isinstance(d, Inductor):
                d.reset(uic=True)
        self.after_break = True
        self.h = 1e-7

    def start_op(self) -> np.ndarray:
        self.t = 0.0
        for src in self.sources:
            src.ramping = False
        x = self.operating_point()
        return x

    # ------------------------------------------------------------------ transient
    def next_breakpoint(self, t: float) -> float | None:
        best = None
        for d in self.breakers:
            tb = d.next_break(t)
            if tb is not None and tb > t + 1e-15 and (best is None or tb < best):
                best = tb
        for tb in self.extra_breaks:
            if tb > t + 1e-15 and (best is None or tb < best):
                best = tb
        return best

    def add_break(self, t: float) -> None:
        self.extra_breaks.append(t)
        self.extra_breaks = [b for b in self.extra_breaks if b > self.t - 1e-12]

    def touch(self) -> None:
        """A switch, pot or source changed: restart integration cleanly at the current time."""
        self.after_break = True
        self.h = min(self.h, 1e-6)

    def _event_fraction(self, x0, x1) -> float | None:
        best = None
        for d in self.events:
            if d.next_state(x1) == d.state:
                continue
            f0 = d.thresholds(x0)
            f1 = d.thresholds(x1)
            for a, c in zip(f0, f1):
                if (a < 0) != (c < 0) and a != c:
                    fr = a / (a - c)
                    if 0.0 <= fr <= 1.0 and (best is None or fr < best):
                        best = fr
        return best

    def step(self, h_max: float | None = None) -> float:
        """Advance by one accepted time step (at most h_max). Returns the step taken."""
        h_cap = min(h_max or self.h_max_default, self.h_max_default, self.max_step_hint)
        t0, x0 = self.t, self.x
        h_want = self.h
        h = min(h_want, h_cap)
        capped = h < h_want
        bp = self.next_breakpoint(t0)
        hit_bp = False
        if bp is not None and bp - t0 <= h * (1 + 1e-9):
            h = max(bp - t0, self.h_min)
            hit_bp = True
        refine = 0
        ratio = 0.0
        rejected = False
        for attempt in range(80):
            mode = "be" if self.after_break else "trap"
            try:
                A, b = self._assemble(t0 + h, h, mode)
                x1, iters = self._newton(A, b, x0)
            except NoConvergence:
                self.rejected += 1
                rejected = True
                if h <= self.h_min * 1.01:
                    raise SimError(f"Simulation stopped at t = {t0 * 1e3:.4g} ms: the circuit did not converge.")
                h = max(h * 0.25, self.h_min)
                hit_bp = False
                self.after_break = True
                continue
            ratio = max((d.step_ratio(x0, x1) for d in self.reactive), default=0.0)
            if ratio > 1.0 and h > self.h_min * 4:
                self.rejected += 1
                rejected = True
                h = max(h * max(0.2, 0.8 / ratio), self.h_min)
                hit_bp = False
                continue
            fr = self._event_fraction(x0, x1)
            if fr is not None and refine < 12:
                hn = h * fr * 1.0001 + self.h_min
                if hn < h * 0.999 and hn > self.h_min * 2:
                    refine += 1
                    self.rejected += 1
                    rejected = True
                    h = hn
                    hit_bp = False
                    continue
            break
        else:
            raise SimError(f"Simulation stuck at t = {t0 * 1e3:.4g} ms.")
        t1 = t0 + h
        for d in self.acceptors:
            d.accept(x1, t1, h, mode)
        changed = False
        for d in self.events:
            if d.update(x1, t1):
                changed = True
        self.x = x1
        self.t = t1
        self.steps += 1
        if self.on_accept is not None:
            self.on_accept(t1, x1)
        h_top = min(self.h_max_default, self.max_step_hint)
        if changed:
            self.after_break = True
            self.h = max(self.h_min * 10, min(h, 1e-6))
        elif hit_bp:
            self.after_break = True
            self.h = max(self.h_min * 10, min(h_want, h_top) if not rejected else h)
        else:
            self.after_break = False
            if capped and not rejected:
                self.h = h_want if ratio < 0.5 else max(h, h_want * 0.5)
            elif iters <= 6 and ratio < 0.5:
                self.h = min(h * 1.8, h_top)
            elif iters > 15:
                self.h = h * 0.5
            else:
                self.h = h
        return h

    def run_until(self, t_end: float, h_max: float | None = None, max_steps: int | None = None) -> int:
        n = 0
        while self.t < t_end - 1e-15:
            self.step(min(h_max or self.h_max_default, t_end - self.t))
            n += 1
            if max_steps is not None and n >= max_steps:
                break
        return n

    def transient(self, t_end: float, nodes: list[int], h_max: float | None = None, uic: bool = True):
        """Convenience: run from t = 0 and return (times, voltages[len(nodes)])."""
        if uic:
            self.start_uic()
        else:
            self.start_op()
        ts, vs = [self.t], [self.x[nodes].copy()]

        def rec(t, x):
            ts.append(t)
            vs.append(x[nodes].copy())
        self.on_accept = rec
        try:
            self.run_until(t_end, h_max)
        finally:
            self.on_accept = None
        return np.array(ts), np.array(vs)

    def run_fixed(self, t_end: float, h: float, record=None, progress=None):
        """Fixed-step transient (audio rendering). The step matrix is assembled once per (step, method, discrete
        state) and only the right-hand side is rebuilt each step; the next solution is predicted by linear
        extrapolation. Steps that do not converge are split."""
        n = int(round((t_end - self.t) / h))
        tols = self.vntol, self.reltol
        self.vntol, self.reltol = 2e-5, 5e-4  # audio: well below the 16-bit LSB of a guitar-level signal
        try:
            return self._run_fixed(n, h, record, progress)
        finally:
            self.vntol, self.reltol = tols

    def _run_fixed(self, n, h, record, progress):
        split = [d for d in self.steppers if hasattr(d, "stamp_rhs")]
        others = [d for d in self.steppers if not hasattr(d, "stamp_rhs")]
        cache: dict = {}
        x_prev = None

        def assemble(t, hh, mode):
            key = (hh, mode, tuple(d.state for d in self.events))
            ent = cache.get(key)
            if ent is None:
                if len(cache) > 16:
                    cache.clear()
                A = self.A0.copy()
                b = self.b0.copy()
                for d in others:
                    d.stamp_step(A, b, t, hh, mode)
                for d in split:
                    d.stamp_matrix(A, hh, mode)
                ent = cache[key] = (A, b)
            A, bs = ent
            b = bs.copy()
            for d in split:
                d.stamp_rhs(b, t, hh, mode)
            return A, b

        for i in range(n):
            target = self.t + h
            while self.t < target - 1e-15:
                hh = target - self.t
                for attempt in range(8):
                    mode = "be" if self.after_break else "trap"
                    try:
                        A, b = assemble(self.t + hh, hh, mode)
                        guess = self.x if x_prev is None or hh != h else 2.0 * self.x - x_prev
                        x1, iters = self._newton(A, b, guess, 40)
                        break
                    except NoConvergence:
                        hh *= 0.25
                        self.after_break = True
                else:
                    raise SimError(f"Audio render did not converge at t = {self.t:.4f} s")
                for d in self.acceptors:
                    d.accept(x1, self.t + hh, hh, mode)
                changed = False
                for d in self.events:
                    if d.update(x1, self.t + hh):
                        changed = True
                self.after_break = changed
                x_prev = self.x if hh == h else None
                self.x = x1
                self.t += hh
            if record is not None:
                record(i, self.x)
            if progress is not None and i % 2000 == 0 and progress(i / max(n, 1)):
                return False
        return True

    # ------------------------------------------------------------------ AC
    def ac_sweep(self, freqs, source: VoltageSource, out_nodes: list[int]):
        """Small-signal response around the current operating point. Returns complex array (len(freqs), outs)."""
        x = self.x
        A, b = self._assemble(self.t, 1.0, "dc")
        for d in self.nl:
            d.begin(x)
            d.stamp_nl(A, b, x)
        C = np.zeros((self.N, self.N))
        for d in self.ckt.devices:
            d.stamp_ac(C)
        rhs = np.zeros(self.N, dtype=complex)
        rhs[source.br[0]] = 1.0
        out = np.zeros((len(freqs), len(out_nodes)), dtype=complex)
        Ar = A[1:, 1:]
        Cr = C[1:, 1:]
        for i, f in enumerate(freqs):
            M = Ar + 1j * 2 * math.pi * f * Cr
            sol = np.linalg.solve(M, rhs[1:])
            full = np.concatenate([[0.0], sol])
            out[i] = full[out_nodes]
        return out

    # ------------------------------------------------------------------ queries
    def v(self, node: int) -> float:
        return float(self.x[node])
