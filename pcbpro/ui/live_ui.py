"""Play live: your guitar through the board's circuit in real time (audio interface in -> circuit -> speakers)."""
from __future__ import annotations

import multiprocessing as mp

from PySide6.QtCore import QRectF, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QSlider, QVBoxLayout, QWidget)

from .. import APP_NAME
from .audio_ui import _Knobs, _nets, full_scale
from .cab_ui import CabinetPicker

RATES = [44100, 48000, 88200, 96000]
BLOCKS = [32, 64, 128, 256, 512]


class Meter(QWidget):
    """Horizontal peak meter (0..1 full scale) with a red zone."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = 0.0
        self.hold = 0.0
        self.setFixedHeight(12)
        self.setMinimumWidth(120)

    def set_level(self, v: float):
        self.level = max(0.0, min(1.0, v))
        self.hold = max(self.level, self.hold * 0.97)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, QColor(24, 27, 33))
        w = r.width()
        db = lambda x: 0.0 if x <= 1e-5 else max(0.0, 1.0 + 20 * __import__("math").log10(x) / 60.0)  # noqa: E731
        lv = db(self.level)
        col = QColor("#3fcf8e") if lv < 0.85 else (QColor("#f5b83d") if lv < 0.97 else QColor("#f0605d"))
        p.fillRect(QRectF(0, 0, w * lv, r.height()), col)
        hx = w * db(self.hold)
        p.fillRect(QRectF(hx - 1, 0, 2, r.height()), QColor(230, 233, 240))


class LiveDialog(QDialog):
    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self.project = win.doc.project
        self.settings = QSettings(APP_NAME, APP_NAME)
        self.setWindowTitle("Play live")
        self.resize(800, 600)
        self._proc = None
        self._conn = None
        self.devs = None
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        # ---- audio devices
        box = QGroupBox("Audio interface")
        form = QFormLayout(box)
        self.host = QComboBox()
        self.in_dev = QComboBox()
        self.channel = QComboBox()
        self.out_dev = QComboBox()
        self.rate = QComboBox()
        for r in RATES:
            self.rate.addItem(f"{r / 1000:g} kHz", r)
        self.block = QComboBox()
        for b in BLOCKS:
            self.block.addItem(f"{b} samples", b)
        self.exclusive = QCheckBox("Exclusive mode (lowest latency)")
        self.oversample = QComboBox()
        self.oversample.addItem("Off", 1)
        self.oversample.addItem("2× (less aliasing)", 2)
        self.oversample.addItem("4×", 4)
        form.addRow("Driver", self.host)
        form.addRow("Input", self.in_dev)
        form.addRow("Guitar on", self.channel)
        form.addRow("Output", self.out_dev)
        form.addRow("Sample rate", self.rate)
        form.addRow("Buffer", self.block)
        form.addRow("", self.exclusive)
        form.addRow("Oversampling", self.oversample)
        left.addWidget(box)
        # ---- signal
        sbox = QGroupBox("Signal")
        sf = QFormLayout(sbox)
        nets, nin, nout = _nets(self.project)
        self.in_net = QComboBox()
        self.in_net.addItems(nets)
        self.in_net.setCurrentText(nin)
        self.out_net = QComboBox()
        self.out_net.addItems(nets)
        self.out_net.setCurrentText(nout)
        sf.addRow("Circuit input", self.in_net)
        sf.addRow("Circuit output", self.out_net)
        self.in_volts = QDoubleSpinBox()
        self.in_volts.setRange(0.05, 10.0)
        self.in_volts.setSingleStep(0.1)
        self.in_volts.setSuffix(" V")
        self.in_volts.setToolTip("The guitar voltage that drives the interface input to full scale. Lower it if the "
                                 "circuit sounds too clean, raise it for hotter pickups.")
        self.in_volts.valueChanged.connect(lambda v: self._send(("in_volts", v)))
        sf.addRow("Full scale =", self.in_volts)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(-48, 12)
        self.volume.valueChanged.connect(lambda v: (self.vol_label.setText(f"{v:+d} dB"), self._send(("out_db", v))))
        self.vol_label = QLabel()
        vrow = QHBoxLayout()
        vrow.addWidget(self.volume, 1)
        vrow.addWidget(self.vol_label)
        sf.addRow("Volume", vrow)
        self.bypass = QCheckBox("Bypass (dry guitar)")
        self.bypass.toggled.connect(lambda on: self._send(("bypass", on)))
        sf.addRow("", self.bypass)
        self.cab = CabinetPicker()
        self.cab.changed.connect(lambda path: self._send(("cab", path)))
        sf.addRow("Cabinet", self.cab)
        left.addWidget(sbox)
        left.addStretch(1)
        lay.addLayout(left, 1)
        right = QVBoxLayout()
        self.knobs = _Knobs(self.project, self._knobs_changed)
        right.addWidget(self.knobs)
        mbox = QGroupBox("Monitor")
        mf = QFormLayout(mbox)
        self.m_in = Meter()
        self.m_out = Meter()
        mf.addRow("Input", self.m_in)
        mf.addRow("Output", self.m_out)
        self.info = QLabel("Stopped")
        self.info.setWordWrap(True)
        self.info.setProperty("muted", True)
        mf.addRow(self.info)
        right.addWidget(mbox)
        right.addStretch(1)
        bar = QHBoxLayout()
        self.start_btn = QPushButton("▶  Start")
        self.start_btn.setProperty("primary", True)
        self.start_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        bar.addWidget(self.start_btn)
        bar.addWidget(self.stop_btn)
        right.addLayout(bar)
        warn = QLabel("Start with the volume low and headphones off your ears: a high-gain circuit can be loud.")
        warn.setWordWrap(True)
        warn.setProperty("muted", True)
        right.addWidget(warn)
        lay.addLayout(right, 1)
        self._sent_knobs: dict = {}
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._poll)
        self._load_devices()
        self._restore()

    # ------------------------------------------------------------------ devices
    def _load_devices(self):
        try:
            from ..sim.livefx import list_devices, preferred_hostapi
            self.devs = list_devices()
        except Exception as e:
            self.info.setText(f"Audio devices unavailable: {e}")
            self.start_btn.setEnabled(False)
            return
        self.host.blockSignals(True)
        for h in self.devs["hostapis"]:
            if any(d["hostapi"] == h["index"] for d in self.devs["inputs"]):
                self.host.addItem(h["name"], h["index"])
        i = self.host.findData(preferred_hostapi(self.devs))
        self.host.setCurrentIndex(max(i, 0))
        self.host.blockSignals(False)
        self.host.currentIndexChanged.connect(self._fill_devices)
        self.in_dev.currentIndexChanged.connect(self._fill_channels)
        self._fill_devices()

    def _fill_devices(self):
        h = self.host.currentData()
        for combo, key in ((self.in_dev, "inputs"), (self.out_dev, "outputs")):
            combo.blockSignals(True)
            combo.clear()
            for d in self.devs[key]:
                if d["hostapi"] == h:
                    combo.addItem(d["name"], d["index"])
            combo.blockSignals(False)
        hinfo = next((x for x in self.devs["hostapis"] if x["index"] == h), {})
        for combo, key in ((self.in_dev, "default_in"), (self.out_dev, "default_out")):
            # prefer an audio interface (Focusrite, Scarlett, ...) over the system default
            pick = next((i for i in range(combo.count()) if any(k in combo.itemText(i) for k in
                                                                ("Focusrite", "Scarlett", "Audient", "MOTU", "UMC",
                                                                 "Behringer", "Universal Audio", "Steinberg"))), -1)
            if pick < 0:
                pick = combo.findData(hinfo.get(key, -1))
            combo.setCurrentIndex(max(pick, 0))
        self.exclusive.setEnabled("WASAPI" in self.host.currentText())
        self._fill_channels()

    def _fill_channels(self):
        idx = self.in_dev.currentData()
        dev = next((d for d in self.devs["inputs"] if d["index"] == idx), None) if self.devs else None
        self.channel.clear()
        for c in range(dev["in"] if dev else 1):
            self.channel.addItem(f"Input {c + 1}", c)
        if dev:
            self.rate.setCurrentIndex(max(0, self.rate.findData(int(dev["rate"]))))

    def _restore(self):
        s = self.settings
        def pick(combo, key):
            v = s.value(key)
            if v is not None:
                i = combo.findText(str(v))
                if i >= 0:
                    combo.setCurrentIndex(i)
        pick(self.host, "live/host")
        pick(self.in_dev, "live/in")
        pick(self.channel, "live/channel")
        pick(self.out_dev, "live/out")
        pick(self.block, "live/block")
        pick(self.oversample, "live/oversample")
        if s.value("live/block") is None:
            self.block.setCurrentIndex(BLOCKS.index(128))
        if s.value("live/oversample") is None:
            self.oversample.setCurrentIndex(1)
        self.exclusive.setChecked(str(s.value("live/exclusive", "true")).lower() == "true")
        self.in_volts.setValue(float(s.value("live/in_volts", 1.0)))
        self.volume.setValue(int(s.value("live/volume", -12)))
        self.vol_label.setText(f"{self.volume.value():+d} dB")

    def _save(self):
        s = self.settings
        for key, combo in (("host", self.host), ("in", self.in_dev), ("channel", self.channel),
                           ("out", self.out_dev), ("block", self.block), ("oversample", self.oversample)):
            s.setValue(f"live/{key}", combo.currentText())
        s.setValue("live/exclusive", self.exclusive.isChecked())
        s.setValue("live/in_volts", self.in_volts.value())
        s.setValue("live/volume", self.volume.value())

    # ------------------------------------------------------------------ run
    def start(self):
        if self._proc is not None:
            return
        if self.in_dev.currentData() is None or self.out_dev.currentData() is None:
            QMessageBox.information(self, "Play live", "Choose an input and an output device.")
            return
        self._save()
        opts = {"in_device": self.in_dev.currentData(), "out_device": self.out_dev.currentData(),
                "channel": self.channel.currentData() or 0, "rate": self.rate.currentData(),
                "block": self.block.currentData(), "exclusive": self.exclusive.isChecked() and
                self.exclusive.isEnabled(), "oversample": self.oversample.currentData(),
                "in": self.in_net.currentText(), "out": self.out_net.currentText(),
                "controls": dict(self.knobs.values), "in_volts": self.in_volts.value(),
                "out_db": self.volume.value(), "bypass": self.bypass.isChecked(), "cab": self.cab.path(),
                "out_ref": full_scale(self.project, self.out_net.currentText())}
        from ..sim.livefx import live_worker
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        self._proc = ctx.Process(target=live_worker, args=(child, self.project.to_dict(), opts), daemon=True)
        self._proc.start()
        child.close()
        self._conn = parent
        self._sent_knobs = dict(self.knobs.values)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        for w in (self.host, self.in_dev, self.out_dev, self.rate, self.block, self.exclusive, self.oversample,
                  self.in_net, self.out_net, self.channel):
            w.setEnabled(False)
        self.info.setText("Starting… (compiling the circuit solver takes a few seconds)")
        self._timer.start()

    def stop(self, message: str = "Stopped"):
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
            self._proc.join(1.0)
            if self._proc.is_alive():
                self._proc.terminate()
        self._proc = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        for w in (self.host, self.in_dev, self.out_dev, self.rate, self.block, self.oversample, self.in_net,
                  self.out_net, self.channel):
            w.setEnabled(True)
        self.exclusive.setEnabled("WASAPI" in self.host.currentText())
        self.m_in.set_level(0)
        self.m_out.set_level(0)
        self.info.setText(message)

    def _send(self, msg):
        if self._conn is not None:
            try:
                self._conn.send(msg)
            except (OSError, BrokenPipeError):
                pass

    def _knobs_changed(self):
        for k, v in self.knobs.values.items():
            if self._sent_knobs.get(k) != v:
                self._sent_knobs[k] = v
                self._send(("control", k, v))

    def _poll(self):
        if self._conn is None:
            return
        try:
            while self._conn.poll():
                msg = self._conn.recv()
                if "stage" in msg:
                    self.info.setText(msg["stage"])
                elif "started" in msg:
                    self.mode = msg["mode"]
                    notes = msg.get("notes") or []
                    self.info.setText(f"Live ({msg['mode']} mode)" + ("\n" + "\n".join(notes) if notes else ""))
                elif "status" in msg:
                    st = msg["status"]
                    self.m_in.set_level(st["in"])
                    self.m_out.set_level(st["out"])
                    text = (f"Live ({getattr(self, 'mode', '')}) · latency ≈ {st['latency']:.1f} ms · CPU "
                            f"{st['load'] * 100:.0f} % (peak {st['load_max'] * 100:.0f} %)")
                    if st.get("cab"):
                        text += f" · cabinet: {st['cab']}"
                    if st["xruns"]:
                        text += f" · {st['xruns']} dropouts: raise the buffer or turn oversampling down"
                    if st["in"] > 0.98:
                        text += " · input clipping: lower the interface gain"
                    self.info.setText(text)
                elif "notice" in msg:
                    QMessageBox.warning(self, "Play live", msg["notice"])
                elif "error" in msg:
                    self.stop(f"Could not start: {msg['error']}")
                    return
        except (EOFError, OSError):
            self.stop("The audio engine stopped.")
            return
        if self._proc is not None and not self._proc.is_alive():
            self.stop("The audio engine stopped.")

    def closeEvent(self, ev):
        self.stop()
        super().closeEvent(ev)

    def reject(self):
        self.stop()
        super().reject()
