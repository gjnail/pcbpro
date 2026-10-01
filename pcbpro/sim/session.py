"""Running simulation: pacing against the wall clock, live controls, LED averaging, probes and snapshots.

``SimRunner`` does the work and is used directly by tests and the audio renderer. The UI runs it in a worker
process (``WorkerSession``) so a busy solver or an emulated microcontroller never stalls the interface; snapshots
come back about 30 times a second over a pipe.
"""
from __future__ import annotations

import time
import traceback

import numpy as np

from ..model.board import Project
from . import stress
from .engine import SimError, Simulator
from .netlist import BoardCircuit, build_circuit


class SimRunner:
    def __init__(self, project: Project, mode: str = "design", start: str = "power", speed: float = 1.0,
                 probes: list[str] | None = None, controls: dict | None = None):
        if mode == "built" and project.zones and project.fills_stale:
            from ..model.copper import fill_all_zones
            fill_all_zones(project)
        self.ck: BoardCircuit = build_circuit(project, mode)
        self.sim = Simulator(self.ck, h_max=1e-3)
        self.speed = speed
        self.quantum = float((project.sim or {}).get("mcu_quantum", 100e-6))
        self.quantum_max = max(self.quantum, float((project.sim or {}).get("mcu_quantum_max", 2e-3)))
        self._q = self.quantum
        self.leds = [(d, col, label, uid) for uid, info in self.ck.parts.items() for d, col, label in info.leds]
        self._led_q = np.zeros(len(self.leds))
        self._frame_t0 = 0.0
        self._last_t = 0.0
        self.probe_nets: list[str] = []
        self._probe_nodes: list[int] = []
        self._probe_t: list[float] = []
        self._probe_v: list[np.ndarray] = []
        self.set_probes(probes or [])
        self.smoke: dict[str, stress.Stress] = {}
        self.serial: dict[str, str] = {}
        self.error = ""
        self._wall_hist: list[tuple[float, float]] = []
        for key, value in (controls or {}).items():
            ctl = self.ck.control(key)
            if ctl is not None:
                ctl.apply(value)
        self.sim.on_accept = self._on_accept
        if start == "op":
            self.sim.start_op()
        else:
            self.sim.start_uic()
        self._last_t = self.sim.t
        for m in self.ck.mcus:
            m.attach(self)

    # ------------------------------------------------------------------ hooks
    def _on_accept(self, t: float, x) -> None:
        dt = t - self._last_t
        self._last_t = t
        if self.leds and dt > 0:
            for j, (d, _, _, _) in enumerate(self.leds):
                self._led_q[j] += d.current(float(x[d.nodes[0]] - x[d.nodes[1]])) * dt
        if self._probe_nodes:
            self._probe_t.append(t)
            self._probe_v.append(x[self._probe_nodes].copy())

    def set_probes(self, nets: list[str]) -> None:
        self.probe_nets = [n for n in nets if n in self.ck.net_node]
        self._probe_nodes = [self.ck.net_node[n] for n in self.probe_nets]
        self._probe_t, self._probe_v = [], []

    # ------------------------------------------------------------------ control
    def command(self, cmd: str, *args) -> None:
        if cmd == "control":
            key, value = args
            ctl = self.ck.control(key)
            if ctl is not None and ctl.apply(value):
                self.sim.touch()
        if cmd in ("control", "serial"):
            self._q = self.quantum  # an input changed: back to short quanta
        if cmd == "speed":
            self.speed = float(args[0])
        elif cmd == "probes":
            self.set_probes(list(args[0]))
        elif cmd == "serial":
            uid, text = args
            for m in self.ck.mcus:
                if m.uid == uid:
                    m.serial_in(text)
        elif cmd == "clear_smoke":
            self.smoke.clear()

    def advance(self, wall_dt: float, budget: float = 0.025) -> None:
        """Advance the simulation by ``wall_dt * speed`` seconds of circuit time, or until ``budget`` seconds of
        wall-clock time are used up (then the simulation is running slower than requested)."""
        if self.error:
            return
        target = self.sim.t + max(wall_dt, 0.0) * self.speed
        deadline = time.perf_counter() + budget
        mcus = self.ck.mcus
        try:
            while self.sim.t < target - 1e-15:
                if mcus:  # co-simulation: the CPUs run a quantum ahead, then the circuit catches up
                    q_end = min(target, self.sim.t + self._q)
                    before = sum(m._seq for m in mcus)
                    for m in mcus:
                        m.run_to(q_end)
                    self.sim.run_until(q_end)
                    # quiet pins: let the quantum grow (fewer forced circuit steps); any pin activity resets it
                    if sum(m._seq for m in mcus) != before:
                        self._q = self.quantum
                    else:
                        self._q = min(self._q * 2.0, self.quantum_max)
                else:
                    self.sim.step(min(target - self.sim.t, 1e-3))
                if time.perf_counter() > deadline:
                    break
        except SimError as e:
            self.error = str(e)
        except Exception as e:  # pragma: no cover - reported to the UI
            self.error = f"{type(e).__name__}: {e}"
            traceback.print_exc()

    # ------------------------------------------------------------------ output
    def snapshot(self, wall_now: float | None = None) -> dict:
        sim, ck = self.sim, self.ck
        x = sim.x
        frame = max(sim.t - self._frame_t0, 1e-12)
        led_i = (self._led_q / frame).tolist() if self.leds else []
        if not self.leds or sim.t == self._frame_t0:
            led_i = [d.current(float(x[d.nodes[0]] - x[d.nodes[1]])) for d, *_ in self.leds]
        led_map = {d: i for (d, *_), i in zip(self.leds, led_i)}
        self._led_q[:] = 0.0
        self._frame_t0 = sim.t
        for s in stress.check(ck, x, led_map):
            old = self.smoke.get(s.uid)
            if old is None or (old.severity == "warning" and s.severity == "error"):
                self.smoke[s.uid] = s
        parts = {}
        for uid, info in ck.parts.items():
            if not info.devices:
                continue
            p = 0.0
            for d in info.devices:
                try:
                    p += d.power(x)
                except Exception:
                    pass
            parts[uid] = p
        now = time.perf_counter() if wall_now is None else wall_now
        self._wall_hist.append((now, sim.t))
        self._wall_hist = [h for h in self._wall_hist if now - h[0] < 1.5]
        ratio = 0.0
        if len(self._wall_hist) > 1:
            (w0, t0), (w1, t1) = self._wall_hist[0], self._wall_hist[-1]
            if w1 > w0:
                ratio = (t1 - t0) / (w1 - w0)
        probes = None
        if self._probe_nodes and self._probe_t:
            probes = {"nets": list(self.probe_nets), "t": np.array(self._probe_t),
                      "v": np.array(self._probe_v).reshape(len(self._probe_t), len(self._probe_nodes))}
            self._probe_t, self._probe_v = [], []
        serial = {}
        for m in ck.mcus:
            text = m.serial_out()
            if text:
                serial[m.uid] = text
        states = {d.part + ":" + d.name: d.state for d in sim.events if d.part}
        ctl = {c.key: c.value for c in ck.controls}
        led_col = [getattr(d, "dyn_color", None) for d, *_ in self.leds]
        return {"t": sim.t, "v": x[:ck.n_nodes].copy(), "led": led_i, "led_col": led_col, "power": parts, "ratio": ratio,
                "steps": sim.steps, "smoke": {u: (s.severity, s.message) for u, s in self.smoke.items()},
                "probes": probes, "serial": serial, "error": self.error, "states": states, "controls": ctl,
                "mcu": {m.uid: m.status() for m in ck.mcus}}


# --------------------------------------------------------------------------- worker process

def worker_main(conn, project_dict: dict, opts: dict) -> None:  # pragma: no cover - runs in a child process
    """Child process: build the circuit, then run / pause / step on commands and send snapshots."""
    try:
        project = Project.from_dict(project_dict)
        runner = SimRunner(project, opts.get("mode", "design"), opts.get("start", "power"), opts.get("speed", 1.0),
                           opts.get("probes"), opts.get("controls"))
    except Exception as e:
        conn.send({"fatal": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()})
        return
    conn.send({"ready": True})
    paused = bool(opts.get("paused", False))
    last = time.perf_counter()
    last_snap = 0.0
    while True:
        try:
            while conn.poll():
                msg = conn.recv()
                cmd = msg[0]
                if cmd == "stop":
                    return
                if cmd == "pause":
                    paused = bool(msg[1])
                elif cmd == "step":
                    runner.advance(float(msg[1]) / max(runner.speed, 1e-12), budget=5.0)
                else:
                    runner.command(*msg)
            now = time.perf_counter()
            dt = now - last
            if dt < 0.005:  # advance in chunks: tiny slices would force tiny time steps
                time.sleep(0.005 - dt)
                continue
            dt = min(dt, 0.1)
            last = now
            if not paused:
                runner.advance(dt)
            else:
                time.sleep(0.01)
            if now - last_snap >= 1 / 30:
                last_snap = now
                conn.send(runner.snapshot(now))
        except (EOFError, BrokenPipeError, OSError):
            return
