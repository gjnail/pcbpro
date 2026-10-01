"""Simulation controller shared by the canvas, the 3D view, the Simulation panel and the scope.

It runs the circuit in a worker process (or in-process for tests), polls snapshots and keeps what the views need:
node voltages, LED brightness, per-part power, smoke markers, scope traces and serial text.
"""
from __future__ import annotations

import math
import multiprocessing as mp
import time
from collections import deque

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from ..sim.netlist import BoardCircuit, build_circuit
from ..sim.session import SimRunner, worker_main

SCOPE_SECONDS = 20.0


class ScopeBuffer:
    """Recent samples of the probed nets (time + one column per net)."""

    def __init__(self):
        self.nets: list[str] = []
        self.chunks: deque = deque()
        self.t_last = 0.0

    def reset(self, nets: list[str]) -> None:
        self.nets = list(nets)
        self.chunks.clear()
        self.t_last = 0.0

    def add(self, nets, t, v) -> None:
        if list(nets) != self.nets:
            self.reset(nets)
        if len(t) == 0:
            return
        self.chunks.append((np.asarray(t), np.asarray(v)))
        self.t_last = float(t[-1])
        while self.chunks and self.chunks[0][0][-1] < self.t_last - SCOPE_SECONDS:
            self.chunks.popleft()

    def data(self, t0: float | None = None):
        if not self.chunks:
            return np.zeros(0), np.zeros((0, len(self.nets)))
        t = np.concatenate([c[0] for c in self.chunks])
        v = np.concatenate([c[1] for c in self.chunks])
        if t0 is not None:
            k = np.searchsorted(t, t0)
            t, v = t[k:], v[k:]
        return t, v


class SimController(QObject):
    started = Signal()
    stopped = Signal(str)
    updated = Signal()  # new snapshot
    state_changed = Signal()
    serial_received = Signal(str, str)  # uid, text

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.ck: BoardCircuit | None = None
        self.running = False
        self.paused = False
        self.mode = "design"
        self.start_kind = "power"
        self.speed = 1.0
        self.backend = "worker"
        self.probes: list[str] = list((doc.project.sim or {}).get("probes", []))
        self.snap: dict | None = None
        self.scope = ScopeBuffer()
        self.serial: dict[str, str] = {}
        self.controls: dict[str, float] = {}
        self.node_v = np.zeros(1)
        self.led_level: dict[int, float] = {}  # id(Diode) -> 0..1 brightness
        self.led_dyn: dict[int, str] = {}  # id(LED) -> colour decoded from data (WS2812)
        self.led_items: list = []  # (component uid, Diode, colour, label)
        self.item_nodes: dict[str, int] = {}  # track / via / zone uid -> node
        self.error = ""
        self._proc = None
        self._conn = None
        self._runner: SimRunner | None = None
        self._last_wall = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._ignore_changes = 0
        doc.changed.connect(self._doc_changed)
        doc.replaced.connect(lambda: self.stop("A different design was opened."))

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> bool:
        self.stop("")
        project = self.doc.project
        if project.zones and project.fills_stale:
            self.doc.refill_zones()
        self.error = ""
        try:
            self.ck = build_circuit(project, self.mode)
        except Exception as e:
            self.error = f"Could not build the circuit: {e}"
            self.stopped.emit(self.error)
            return False
        self._map_items()
        self.led_items = [(uid, d, col, label) for uid, info in self.ck.parts.items() for d, col, label in info.leds]
        self.led_level = {}
        self.node_v = np.zeros(self.ck.n_nodes)
        self.snap = None
        self.serial = {}
        self.controls = {c.key: c.value for c in self.ck.controls}
        self.scope.reset([p for p in self.probes if p in self.ck.net_node])
        opts = {"mode": self.mode, "start": self.start_kind, "speed": self.speed, "probes": self.scope.nets,
                "paused": False}
        if self.backend == "worker":
            ctx = mp.get_context("spawn")
            parent, child = ctx.Pipe()
            self._proc = ctx.Process(target=worker_main, args=(child, project.to_dict(), opts), daemon=True)
            self._proc.start()
            child.close()
            self._conn = parent
        else:
            try:
                self._runner = SimRunner(project.clone(), self.mode, self.start_kind, self.speed, self.scope.nets)
            except Exception as e:
                self.error = f"Could not start: {e}"
                self.stopped.emit(self.error)
                return False
        self.running = True
        self.paused = False
        self._last_wall = time.perf_counter()
        self._timer.start()
        self.started.emit()
        self.state_changed.emit()
        return True

    def stop(self, reason: str = "") -> None:
        was = self.running
        self.running = False
        self.paused = False
        self._timer.stop()
        if self._conn is not None:
            try:
                self._conn.send(("stop",))
            except (OSError, BrokenPipeError):
                pass
            try:
                self._conn.close()
            except OSError:
                pass
            self._conn = None
        if self._proc is not None:
            self._proc.join(0.5)
            if self._proc.is_alive():
                self._proc.terminate()
            self._proc = None
        self._runner = None
        self.led_level = {}
        if was:
            self.stopped.emit(reason)
            self.state_changed.emit()

    def set_paused(self, on: bool) -> None:
        if not self.running:
            return
        self.paused = on
        self._send(("pause", on))
        self._last_wall = time.perf_counter()
        self.state_changed.emit()

    def _send(self, msg) -> None:
        if self._conn is not None:
            try:
                self._conn.send(msg)
            except (OSError, BrokenPipeError):
                self.stop("The simulation process ended.")
        elif self._runner is not None and msg[0] not in ("pause", "stop"):
            if msg[0] == "step":
                self._runner.advance(float(msg[1]) / max(self._runner.speed, 1e-12), budget=5.0)
            else:
                self._runner.command(*msg)

    # ------------------------------------------------------------------ live controls
    def set_control(self, key: str, value) -> None:
        self.controls[key] = value
        if self.ck is not None:
            ctl = self.ck.control(key)
            if ctl is not None:
                ctl.value = value
        self._send(("control", key, value))

    def set_speed(self, speed: float) -> None:
        self.speed = speed
        self._send(("speed", speed))

    def set_probes(self, nets: list[str]) -> None:
        self.probes = list(dict.fromkeys(nets))
        if self.running and self.ck is not None:
            live = [p for p in self.probes if p in self.ck.net_node]
            self.scope.reset(live)
            self._send(("probes", live))
        self.updated.emit()

    def toggle_probe(self, net: str) -> None:
        self.set_probes([p for p in self.probes if p != net] if net in self.probes else self.probes + [net])

    def send_serial(self, uid: str, text: str) -> None:
        self._send(("serial", uid, text))

    def clear_smoke(self) -> None:
        self._send(("clear_smoke",))

    # ------------------------------------------------------------------ queries for the views
    def net_voltage(self, net: str | None) -> float | None:
        if self.ck is None or not net or not self.running:
            return None
        n = self.ck.net_node.get(net)
        if n is None:
            return None
        return float(self.node_v[n]) if n < len(self.node_v) else None

    def node_voltage(self, n: int | None) -> float | None:
        if n is None or not self.running or n >= len(self.node_v):
            return None
        return float(self.node_v[n])

    def pad_voltage(self, comp, number: str) -> float | None:
        if self.ck is None:
            return None
        return self.node_voltage(self.ck.pad_nodes.get((comp.uid, number)))

    def item_voltage(self, item) -> float | None:
        if self.ck is None:
            return None
        n = self.item_nodes.get(item.uid)
        if n is None and getattr(item, "net", None):
            n = self.ck.net_node.get(item.net) if self.mode == "design" else None
        return self.node_voltage(n)

    def vmax(self) -> float:
        if self.ck is None:
            return 5.0
        vals = [abs(s.params.get("v", 0.0)) for s in self.ck.sources if s.kind == "dc"]
        for info in self.ck.parts.values():
            if info.res.kind in ("battery", "dcjack", "usb"):
                for d in info.devices:
                    if hasattr(d, "wave"):
                        vals.append(abs(d.wave.value(1.0)))
        return max(vals + [1.0])

    def _map_items(self) -> None:
        self.item_nodes = {}
        if self.ck is None:
            return
        proj = self.doc.project
        if self.mode == "built":
            from ..model.connectivity import get_connectivity
            from ..model.copper import collect_copper
            conn = get_connectivity(proj)
            for s in collect_copper(proj, include_zones=True):
                if s.kind == "pad":
                    continue
                root = conn.uf.find(s.node)
                n = self.ck.node_index.get(("cl", root))
                if n is not None:
                    key = s.obj.uid
                    self.item_nodes.setdefault(key, n)
        else:
            for it in (*proj.tracks, *proj.vias, *proj.zones):
                if it.net and it.net in self.ck.net_node:
                    self.item_nodes[it.uid] = self.ck.net_node[it.net]

    # ------------------------------------------------------------------ polling
    def _tick(self) -> None:
        snaps = []
        if self._conn is not None:
            try:
                while self._conn.poll():
                    msg = self._conn.recv()
                    if "fatal" in msg:
                        self.error = msg["fatal"]
                        self.stop(self.error)
                        return
                    if "ready" in msg:
                        continue
                    snaps.append(msg)
            except (EOFError, OSError, BrokenPipeError):
                self.stop(self.error or "The simulation process ended unexpectedly.")
                return
            if self._proc is not None and not self._proc.is_alive() and not snaps:
                self.stop(self.error or "The simulation process ended unexpectedly.")
                return
        elif self._runner is not None:
            now = time.perf_counter()
            dt = min(now - self._last_wall, 0.1)
            self._last_wall = now
            if not self.paused:
                self._runner.advance(dt)
            snaps.append(self._runner.snapshot(now))
        if not snaps:
            return
        for s in snaps:
            pr = s.get("probes")
            if pr is not None:
                self.scope.add(pr["nets"], pr["t"], pr["v"])
            for uid, text in (s.get("serial") or {}).items():
                self.serial[uid] = (self.serial.get(uid, "") + text)[-20000:]
                self.serial_received.emit(uid, text)
        snap = snaps[-1]
        self.snap = snap
        self.node_v = np.asarray(snap["v"])
        cols = snap.get("led_col") or [None] * len(self.led_items)
        for (uid, d, col, label), i, dc in zip(self.led_items, snap.get("led", []), cols):
            self.led_level[id(d)] = led_brightness(i)
            if dc:
                self.led_dyn[id(d)] = dc
        if snap.get("error"):
            self.error = snap["error"]
            self.updated.emit()
            self.stop(self.error)
            return
        self.updated.emit()

    def led_states(self):
        """(component uid, brightness 0..1, colour hex, label) for every LED die."""
        return [(uid, self.led_level.get(id(d), 0.0), self.led_dyn.get(id(d), col), label)
                for uid, d, col, label in self.led_items]

    # ------------------------------------------------------------------ editing stops the run
    def _doc_changed(self) -> None:
        if self.running and not self._ignore_changes:
            self.stop("Simulation stopped: the design changed.")


def led_brightness(i: float) -> float:
    """Perceived brightness for an average LED current (20 mA = full)."""
    if i <= 1e-6:
        return 0.0
    return min(1.0, math.sqrt(i / 0.02))
