"""Simulation dock: run controls, settings, live knobs and buttons, part models and warnings."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSlider,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..sim.units import fmt_eng
from .theme import BAD, GOOD, TEXT_DIM, WARN

SPEEDS = [("1/1000 ×", 1e-3), ("1/100 ×", 1e-2), ("1/10 ×", 0.1), ("1/4 ×", 0.25), ("1/2 ×", 0.5),
          ("Real time", 1.0), ("2 ×", 2.0), ("5 ×", 5.0)]
STATUS = {"simulated": ("●", GOOD, "simulated"), "connection": ("○", TEXT_DIM, "connection only"),
          "unsupported": ("✕", BAD, "not simulated"), "excluded": ("–", TEXT_DIM, "excluded"),
          "error": ("!", BAD, "error")}


class SimulationPanel(QWidget):
    part_activated = Signal(str)  # component uid
    edit_part = Signal(str)
    edit_sources = Signal()
    serial_requested = Signal(str)
    load_hex = Signal(str)
    clock_changed = Signal(str, float)
    audio_requested = Signal()
    bode_requested = Signal()
    live_requested = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.sim = controller
        self.doc = controller.doc
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        # run bar
        bar = QHBoxLayout()
        self.run_btn = QPushButton("▶  Run")
        self.run_btn.setProperty("primary", True)
        self.run_btn.setToolTip("Run / pause the simulation (F5)")
        self.run_btn.clicked.connect(self.toggle_run)
        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setToolTip("Stop the simulation (Shift+F5)")
        self.stop_btn.clicked.connect(lambda: self.sim.stop(""))
        self.restart_btn = QPushButton("↻")
        self.restart_btn.setToolTip("Restart from power-up")
        self.restart_btn.clicked.connect(self.sim.start)
        bar.addWidget(self.run_btn, 1)
        bar.addWidget(self.stop_btn)
        bar.addWidget(self.restart_btn)
        lay.addLayout(bar)
        self.status = QLabel("Stopped")
        self.status.setProperty("muted", True)
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        # settings
        box = QGroupBox("Settings")
        form = QFormLayout(box)
        self.speed = QComboBox()
        for text, v in SPEEDS:
            self.speed.addItem(text, v)
        self.speed.setCurrentIndex(5)
        self.speed.currentIndexChanged.connect(lambda i: self.sim.set_speed(self.speed.itemData(i)))
        form.addRow("Speed", self.speed)
        self.mode = QComboBox()
        self.mode.addItem("As designed (netlist)", "design")
        self.mode.addItem("As built (copper)", "built")
        self.mode.setToolTip("As built follows the routed copper: missing tracks and shorts change the circuit")
        self.mode.currentIndexChanged.connect(self._mode_changed)
        form.addRow("Circuit", self.mode)
        self.start = QComboBox()
        self.start.addItem("Power-up from 0 V", "power")
        self.start.addItem("From DC operating point", "op")
        self.start.currentIndexChanged.connect(lambda i: setattr(self.sim, "start_kind", self.start.itemData(i)))
        form.addRow("Start", self.start)
        self.backend = QCheckBox("Run in a separate process")
        self.backend.setChecked(True)
        self.backend.setToolTip("Keeps the interface responsive; turn off to debug")
        self.backend.toggled.connect(lambda on: setattr(self.sim, "backend", "worker" if on else "inprocess"))
        form.addRow("", self.backend)
        lay.addWidget(box)

        # sources
        self.src_box = QGroupBox("Power and signal sources")
        sl = QVBoxLayout(self.src_box)
        self.src_list = QLabel()
        self.src_list.setWordWrap(True)
        self.src_list.setTextFormat(Qt.RichText)
        sl.addWidget(self.src_list)
        b = QPushButton("Edit sources…")
        b.clicked.connect(self.edit_sources.emit)
        sl.addWidget(b)
        lay.addWidget(self.src_box)

        # live controls
        self.ctl_box = QGroupBox("Controls")
        self.ctl_lay = QVBoxLayout(self.ctl_box)
        self.ctl_lay.setSpacing(4)
        lay.addWidget(self.ctl_box)

        # microcontrollers
        self.mcu_box = QGroupBox("Microcontrollers")
        self.mcu_lay = QVBoxLayout(self.mcu_box)
        lay.addWidget(self.mcu_box)

        # audio
        self.audio_box = QGroupBox("Audio")
        al = QHBoxLayout(self.audio_box)
        lb = QPushButton("Play live…")
        lb.setProperty("primary", True)
        lb.setToolTip("Play your guitar through the circuit in real time (audio interface in, speakers out)")
        lb.clicked.connect(self.live_requested.emit)
        al.addWidget(lb)
        ab = QPushButton("Play through…")
        ab.setToolTip("Render a guitar clip through the circuit and listen to it")
        ab.clicked.connect(self.audio_requested.emit)
        fb = QPushButton("Frequency response…")
        fb.clicked.connect(self.bode_requested.emit)
        al.addWidget(ab)
        al.addWidget(fb)
        lay.addWidget(self.audio_box)

        # parts
        pbox = QGroupBox("Part models")
        pl = QVBoxLayout(pbox)
        self.parts = QTreeWidget()
        self.parts.setHeaderLabels(["", "Part", "Model"])
        self.parts.setRootIsDecorated(False)
        self.parts.setUniformRowHeights(True)
        self.parts.setSelectionMode(QAbstractItemView.SingleSelection)
        self.parts.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.parts.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.parts.header().setStretchLastSection(True)
        self.parts.setMinimumHeight(160)
        self.parts.itemClicked.connect(lambda it, _c: self.part_activated.emit(it.data(0, Qt.UserRole)))
        self.parts.itemDoubleClicked.connect(lambda it, _c: self.edit_part.emit(it.data(0, Qt.UserRole)))
        pl.addWidget(self.parts)
        hint = QLabel("Double-click a part to choose its model or pin mapping.")
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        pl.addWidget(hint)
        lay.addWidget(pbox)

        # warnings
        wbox = QGroupBox("Warnings")
        wl = QVBoxLayout(wbox)
        self.warnings = QListWidget()
        self.warnings.setWordWrap(True)
        self.warnings.setMinimumHeight(70)
        self.warnings.itemClicked.connect(self._warning_clicked)
        wl.addWidget(self.warnings)
        lay.addWidget(wbox)
        lay.addStretch(1)

        self._preview = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(400)
        self._preview_timer.timeout.connect(self.refresh_preview)
        self._ctl_widgets: dict[str, QWidget] = {}
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(200)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start()
        controller.started.connect(self._on_started)
        controller.stopped.connect(self._on_stopped)
        controller.state_changed.connect(self._update_buttons)
        self.doc.changed.connect(lambda: self._preview_timer.start())
        self.doc.replaced.connect(lambda: self._preview_timer.start())
        self._update_buttons()
        self._preview_timer.start()

    # ------------------------------------------------------------------ run state
    def toggle_run(self):
        if not self.sim.running:
            self.sim.start()
        else:
            self.sim.set_paused(not self.sim.paused)

    def _mode_changed(self, i):
        self.sim.mode = self.mode.itemData(i)
        if self.sim.running:
            self.sim.start()
        self._preview_timer.start()

    def _update_buttons(self):
        running, paused = self.sim.running, self.sim.paused
        self.run_btn.setText("⏸  Pause" if running and not paused else ("▶  Resume" if paused else "▶  Run"))
        self.stop_btn.setEnabled(running)
        self.restart_btn.setEnabled(running)

    def _on_started(self):
        self._fill_from(self.sim.ck)
        self._update_buttons()

    def _on_stopped(self, reason):
        self._update_buttons()
        if reason:
            self.status.setText(reason)
        self._preview_timer.start()

    def _update_status(self):
        if not self.sim.running or not self.isVisible():
            return
        snap = self.sim.snap
        if snap is None:
            self.status.setText("Starting…")
            return
        ratio = snap.get("ratio", 0.0)
        lag = ""
        if self.sim.speed > 0 and ratio and ratio < self.sim.speed * 0.8:
            lag = f" (asked for ×{self.sim.speed:g}; the circuit is too busy to keep up)"
        state = "Paused" if self.sim.paused else "Running"
        self.status.setText(f"{state} · t = {fmt_eng(snap.get('t', 0.0), 's')} · ×{ratio:.3g} real time{lag}")
        self._fill_warnings(self.sim.ck, snap.get("smoke") or {})
        for m_uid, st in (snap.get("mcu") or {}).items():
            lab = self._ctl_widgets.get("mcu:" + m_uid)
            if lab is not None:
                lab.setText(st)

    # ------------------------------------------------------------------ preview (not running)
    def refresh_preview(self):
        if self.sim.running or not self.isVisible():
            return
        from ..sim.netlist import build_circuit
        try:
            ck = build_circuit(self.doc.project, self.sim.mode)
        except Exception as e:
            self.status.setText(f"Circuit error: {e}")
            return
        self._preview = ck
        self._fill_from(ck)
        if not self.sim.running:
            n_sim = sum(1 for i in ck.parts.values() if i.status == "simulated")
            n_bad = sum(1 for i in ck.parts.values() if i.status in ("unsupported", "error"))
            self.status.setText(f"Stopped · {n_sim} parts simulated" + (f", {n_bad} not simulated" if n_bad else ""))

    def showEvent(self, ev):
        super().showEvent(ev)
        self._preview_timer.start()

    def _fill_from(self, ck):
        if ck is None:
            return
        self._fill_sources(ck)
        self._fill_parts(ck)
        self._fill_controls(ck)
        self._fill_mcus(ck)
        self._fill_warnings(ck, {})
        self.audio_box.setVisible(bool(self.doc.project.pedal) or "IN" in ck.net_node)

    def _fill_sources(self, ck):
        rows = []
        for s in ck.sources:
            p = s.params
            if s.kind == "dc":
                val = fmt_eng(p.get("v", 0), "V")
            elif s.kind == "sine":
                val = f"{fmt_eng(p.get('amp', 0), 'V')} sine {fmt_eng(p.get('freq', 0), 'Hz')}"
            elif s.kind == "square":
                val = f"square {fmt_eng(p.get('freq', 0), 'Hz')}"
            else:
                val = s.kind
            rows.append(f"<b>{s.net}</b>: {val} <span style='color:{TEXT_DIM}'>({s.label}"
                        f"{', auto' if s.auto else ''})</span>")
        for info in ck.parts.values():
            if info.res.kind in ("battery", "dcjack", "usb") and info.status == "simulated":
                rows.append(f"<b>{info.ref}</b>: {info.res.model} <span style='color:{TEXT_DIM}'>"
                            f"{info.note}</span>")
        self.src_list.setText("<br>".join(rows) if rows else f"<span style='color:{WARN}'>No power source found."
                                                              "</span>")

    def _fill_parts(self, ck):
        self.parts.clear()
        for uid, info in sorted(ck.parts.items(), key=lambda kv: _ref_key(kv[1].ref)):
            sym, col, label = STATUS.get(info.status, ("?", TEXT_DIM, info.status))
            model = info.res.model
            tip = label
            if info.res.verify:
                sym, col = "⚠", WARN
                tip = "simulated - pinout not verified against a datasheet: check it"
            if info.note:
                tip += f"\n{info.note}"
            it = QTreeWidgetItem(["", f"{info.ref}  {info.value}", model])
            it.setText(0, sym)
            it.setForeground(0, QColor(col))
            for c in range(3):
                it.setToolTip(c, tip)
            it.setData(0, Qt.UserRole, uid)
            self.parts.addTopLevelItem(it)

    def _fill_controls(self, ck):
        while self.ctl_lay.count():
            w = self.ctl_lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self._ctl_widgets = {}
        ctls = [c for c in ck.controls if c.kind != "source"]
        live = self.sim.running and ck is self.sim.ck
        if not ctls:
            lab = QLabel("No buttons, switches or knobs on this board.")
            lab.setProperty("muted", True)
            self.ctl_lay.addWidget(lab)
        for ctl in ctls:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            name = QLabel(ctl.label)
            name.setMinimumWidth(90)
            h.addWidget(name, 1)
            value = self.sim.controls.get(ctl.key, ctl.value) if live else ctl.value
            if ctl.kind == "momentary":
                b = QPushButton("Hold to press")
                b.pressed.connect(lambda k=ctl.key: self.sim.set_control(k, 1))
                b.released.connect(lambda k=ctl.key: self.sim.set_control(k, 0))
                b.setEnabled(live)
                h.addWidget(b)
            elif ctl.kind in ("toggle", "plug"):
                cb = QComboBox()
                cb.addItems(ctl.options or ["off", "on"])
                cb.setCurrentIndex(int(value))
                cb.currentIndexChanged.connect(lambda i, k=ctl.key: self.sim.set_control(k, i))
                cb.setEnabled(live)
                h.addWidget(cb)
                self._ctl_widgets[ctl.key] = cb
            elif ctl.kind in ("pot", "temp"):
                s = QSlider(Qt.Horizontal)
                s.setMinimumWidth(110)
                if ctl.kind == "pot":
                    s.setRange(0, 1000)
                    s.setValue(int(float(value) * 1000))
                    s.valueChanged.connect(lambda v, k=ctl.key: self.sim.set_control(k, v / 1000))
                else:
                    s.setRange(int(ctl.lo), int(ctl.hi))
                    s.setValue(int(float(value)))
                    s.valueChanged.connect(lambda v, k=ctl.key: self.sim.set_control(k, float(v)))
                s.setEnabled(live)
                h.addWidget(s)
                self._ctl_widgets[ctl.key] = s
            elif ctl.kind == "encoder":
                for text, step in (("◀", -1), ("▶", 1)):
                    b = QPushButton(text)
                    b.setFixedWidth(34)
                    b.clicked.connect(lambda _c=False, k=ctl.key, st=step: self._encoder(k, st))
                    b.setEnabled(live)
                    h.addWidget(b)
            self.ctl_lay.addWidget(row)
        for s in ck.sources:
            ctl = next((c for c in ck.controls if c.kind == "source" and c.devices and c.devices[0] is s.device),
                       None)
            if ctl is None:
                continue
            cb = QCheckBox(f"{s.net} source on")
            cb.setChecked(bool(self.sim.controls.get(ctl.key, ctl.value)) if live else bool(ctl.value))
            cb.toggled.connect(lambda on, k=ctl.key: self.sim.set_control(k, 1 if on else 0))
            cb.setEnabled(live)
            self.ctl_lay.addWidget(cb)

    def _encoder(self, key, step):
        tool = getattr(self, "sim_tool", None)
        if tool is not None:
            tool._rotate(key, step)

    def _fill_mcus(self, ck):
        while self.mcu_lay.count():
            w = self.mcu_lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        infos = [i for i in ck.parts.values() if i.res.kind == "mcu"]
        self.mcu_box.setVisible(bool(infos))
        for info in infos:
            row = QWidget()
            v = QVBoxLayout(row)
            v.setContentsMargins(0, 0, 0, 0)
            cfg = (self.doc.project.sim or {}).get("mcu", {}).get(info.uid, {})
            fw = cfg.get("name") or "no firmware loaded"
            clock = cfg.get("clock") or info.res.params.get("clock", 16e6)
            title = QLabel(f"<b>{info.ref}</b> {info.res.model} · {fmt_eng(clock, 'Hz')} · {fw}")
            title.setWordWrap(True)
            v.addWidget(title)
            st = QLabel("")
            st.setProperty("muted", True)
            v.addWidget(st)
            self._ctl_widgets["mcu:" + info.uid] = st
            h = QHBoxLayout()
            ck_combo = QComboBox()
            ck_combo.setEditable(True)
            ck_combo.setToolTip("CPU clock (set by the fuses / crystal on the real board)")
            for hz in (1e6, 8e6, 9.6e6, 12e6, 16e6, 20e6):
                ck_combo.addItem(fmt_eng(hz, "Hz"), hz)
            ck_combo.setCurrentText(fmt_eng(clock, "Hz"))
            ck_combo.activated.connect(lambda i, u=info.uid, c=ck_combo: self.clock_changed.emit(u, c.itemData(i)))
            h.addWidget(ck_combo)
            lb = QPushButton("Load .hex…")
            lb.clicked.connect(lambda _c=False, u=info.uid: self.load_hex.emit(u))
            sb = QPushButton("Serial monitor")
            sb.clicked.connect(lambda _c=False, u=info.uid: self.serial_requested.emit(u))
            h.addWidget(lb)
            h.addWidget(sb)
            v.addLayout(h)
            self.mcu_lay.addWidget(row)

    def _fill_warnings(self, ck, smoke: dict):
        if ck is None:
            return
        items = [(w, None, WARN) for w in ck.warnings]
        for info in ck.parts.values():
            if info.status in ("unsupported", "error"):
                items.append((f"{info.ref} ({info.value}) is not simulated: {info.note or 'no model'}", info.uid,
                              TEXT_DIM))
            elif info.res.verify and info.status == "simulated":
                items.append((f"{info.ref}: pinout not verified, check it against the datasheet", info.uid, WARN))
        for uid, (sev, msg) in smoke.items():
            ref = ck.parts[uid].ref if uid in ck.parts else "?"
            items.insert(0, (f"{'🔥' if sev == 'error' else '⚠'} {ref}: {msg}", uid, BAD if sev == "error" else WARN))
        key = [(t, u) for t, u, _ in items]
        if getattr(self, "_warn_key", None) == key:
            return
        self._warn_key = key
        self.warnings.clear()
        for text, uid, col in items:
            it = QListWidgetItem(text)
            it.setForeground(QColor(col))
            it.setData(Qt.UserRole, uid)
            self.warnings.addItem(it)
        if not items:
            it = QListWidgetItem("No problems found.")
            it.setForeground(QColor(GOOD))
            self.warnings.addItem(it)

    def _warning_clicked(self, it):
        uid = it.data(Qt.UserRole)
        if uid:
            self.part_activated.emit(uid)

    def sync_control(self, key: str, value) -> None:
        w = self._ctl_widgets.get(key)
        if w is None:
            return
        w.blockSignals(True)
        if isinstance(w, QSlider):
            w.setValue(int(value * 1000) if w.maximum() == 1000 else int(value))
        elif isinstance(w, QComboBox):
            w.setCurrentIndex(int(value))
        w.blockSignals(False)


def _ref_key(ref: str):
    import re
    m = re.match(r"([A-Za-z]+)(\d*)", ref or "")
    return (m.group(1), int(m.group(2) or 0)) if m else (ref, 0)
