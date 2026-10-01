"""The Amp Designer's Listen tab: hear a design before you build it.

The board the designer would build is simulated tube by tube (in a background process) with a palm-muted metal riff
or your own DI recording, then a speaker cabinet impulse response is applied and the result plays. "Keep as A" holds
a render so you can switch to another voicing, tightness or knob setting and compare.
"""
from __future__ import annotations

import multiprocessing as mp
from dataclasses import asdict

import numpy as np
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                               QMessageBox, QProgressBar, QPushButton, QSlider, QVBoxLayout, QWidget)

KNOBS = ("GAIN", "VOLUME", "MASTER", "BASS", "MIDDLE", "TREBLE", "PRESENCE", "DEPTH")
DEFAULTS = {"GAIN": 5.0, "VOLUME": 5.0, "MASTER": 2.0, "BASS": 5.0, "MIDDLE": 5.0, "TREBLE": 6.0, "PRESENCE": 5.0,
            "DEPTH": 4.0}
RATE = 48000


class ListenPanel(QWidget):
    """Render the current design with a riff, through a cabinet, and play it (with an A/B hold)."""

    def __init__(self, dialog, parent=None):
        super().__init__(parent)
        self.dlg = dialog
        self.dry = None  # the clip (volts)
        self.wet = None  # the processed result, cabinet applied, normalised
        self.held = None  # (label, audio) for A/B
        self.label = ""
        self._proc = self._conn = self._sink = self._buf = None
        self._cab = None
        lay = QVBoxLayout(self)
        head = QLabel("<b>Hear this amp</b> <span style='color:#8b93a1'>- the board as designed, simulated tube by "
                      "tube, with a palm-muted metal riff or your own DI recording, through a speaker cabinet</span>")
        head.setWordWrap(True)
        lay.addWidget(head)
        top = QHBoxLayout()
        form = QFormLayout()
        self.clip = QComboBox()
        self.clip.addItem("Metal riff: palm mutes and power chords", "riff")
        self.clip.addItem("Your DI recording (WAV)…", "wav")
        self.clip.activated.connect(self._clip_chosen)
        self.wav_path = None
        form.addRow("Play", self.clip)
        self.level = QDoubleSpinBox()
        self.level.setRange(50, 1500)
        self.level.setValue(400)
        self.level.setSuffix(" mV peak")
        self.level.setToolTip("How hot the guitar is: single coils about 150 mV, humbuckers 300-500 mV, active pickups "
                              "up to 1 V or more")
        form.addRow("Pickup level", self.level)
        self.cab_row = QHBoxLayout()
        self.cab_note = QLabel("loading…")
        self.cab_row.addWidget(self.cab_note)
        form.addRow("Cabinet", self.cab_row)
        top.addLayout(form, 1)
        grid = QGridLayout()
        self.knobs = {}
        for i, name in enumerate(KNOBS):
            s = QSlider(Qt.Horizontal)
            s.setRange(0, 100)
            s.setValue(int(DEFAULTS[name] * 10))
            val = QLabel(f"{DEFAULTS[name]:.1f}")
            s.valueChanged.connect(lambda v, lab=val: lab.setText(f"{v / 10:.1f}"))
            grid.addWidget(QLabel(name.title()), i, 0)
            grid.addWidget(s, i, 1)
            grid.addWidget(val, i, 2)
            self.knobs[name] = (s, val, grid.itemAtPosition(i, 0).widget())
        top.addLayout(grid, 1)
        lay.addLayout(top)
        bar = QHBoxLayout()
        self.render_btn = QPushButton("Render && play")
        self.render_btn.setProperty("primary", True)
        self.render_btn.clicked.connect(self.render)
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.clicked.connect(lambda: self._play(self.wet))
        self.dry_btn = QPushButton("▶ DI")
        self.dry_btn.setToolTip("The clean guitar signal going in")
        self.dry_btn.clicked.connect(lambda: self._play(self._norm(self.dry)))
        self.stop_btn = QPushButton("■")
        self.stop_btn.clicked.connect(self._stop)
        self.hold_btn = QPushButton("Keep as A")
        self.hold_btn.setToolTip("Hold this render, change the design or the knobs, render again and compare")
        self.hold_btn.clicked.connect(self._hold)
        self.a_btn = QPushButton("▶ A")
        self.a_btn.clicked.connect(lambda: self._play(self.held[1] if self.held else None))
        self.save_btn = QPushButton("Save WAV…")
        self.save_btn.clicked.connect(self._save)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        for w in (self.render_btn, self.play_btn, self.dry_btn, self.stop_btn, self.hold_btn, self.a_btn,
                  self.save_btn, self.progress):
            bar.addWidget(w)
        lay.addLayout(bar)
        self.status = QLabel("Render to hear the current design. It takes a few seconds: every tube is simulated at "
                             "every sample.")
        self.status.setWordWrap(True)
        self.status.setProperty("muted", True)
        lay.addWidget(self.status)
        lay.addStretch(1)
        self._poll = QTimer(self)
        self._poll.setInterval(100)
        self._poll.timeout.connect(self._poll_worker)
        self._buttons()

    # ------------------------------------------------------------------ state
    def showEvent(self, ev):
        super().showEvent(ev)
        if self._cab is None:  # the cabinet list (and its first-run IR search) only when the tab is first used
            from .cab_ui import CabinetPicker
            self._cab = CabinetPicker(self, auto_search=False)
            if not self._cab.path():
                pick = next((self._cab.combo.itemData(i) for i in range(self._cab.combo.count())
                             if "4x12" in str(self._cab.combo.itemData(i))), None)
                self._cab.set_path(pick)
            self.cab_note.hide()
            self.cab_row.addWidget(self._cab, 1)
        self.update_knobs()

    def update_knobs(self) -> None:
        """Show only the knobs the current design has."""
        design = self.dlg.design
        have = {p.label for p in design.parts if p.prefix == "RV" and p.label} if design is not None else set()
        for name, (s, val, lab) in self.knobs.items():
            for w in (s, val, lab):
                w.setVisible(name in have)

    def _buttons(self) -> None:
        busy = self._proc is not None
        self.render_btn.setEnabled(not busy and self.dlg.design is not None)
        for b in (self.play_btn, self.dry_btn, self.save_btn, self.hold_btn):
            b.setEnabled(not busy and self.wet is not None)
        self.a_btn.setEnabled(self.held is not None)
        self.a_btn.setText(f"▶ A: {self.held[0]}" if self.held else "▶ A")

    def _clip_chosen(self, i):
        if self.clip.itemData(i) == "wav":
            path, _ = QFileDialog.getOpenFileName(self, "A DI guitar recording", "", "WAV audio (*.wav)")
            if path:
                self.wav_path = path
                self.clip.setItemText(i, f"DI: {path.replace(chr(92), '/').split('/')[-1]}")
            else:
                self.clip.setCurrentIndex(0)

    def knob_values(self) -> dict:
        return {name: s.value() / 100.0 for name, (s, _v, _l) in self.knobs.items()}

    def clip_data(self) -> np.ndarray:
        level = self.level.value() / 1000.0
        if self.clip.currentData() == "wav" and self.wav_path:
            from ..sim.audio import load_wav
            return load_wav(self.wav_path, RATE, 8.0, level)
        from ..amp.demo import metal_riff
        return metal_riff(RATE, 6.0, level)

    # ------------------------------------------------------------------ rendering
    def render(self) -> None:
        if self.dlg.design is None or self._proc is not None:
            return
        self._stop()
        try:
            self.dry = self.clip_data()
        except Exception as e:
            QMessageBox.warning(self, "Listen", f"Could not read the recording:\n{e}")
            return
        spec = asdict(self.dlg.spec())
        knobs = self.knob_values()
        self.label = (f"{self.dlg.report.title}, tightness {spec.get('tight', '-')}, gain "
                      f"{knobs.get('GAIN', knobs.get('VOLUME', 0)) * 10:.1f}")
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        from ..amp.demo import listen_worker
        self._proc = ctx.Process(target=listen_worker, args=(child, spec, knobs,
                                                             {"clip": self.dry, "rate": RATE, "oversample": 2}),
                                 daemon=True)
        self._proc.start()
        child.close()
        self._conn = parent
        self.progress.setValue(0)
        self.status.setText("Building the board and simulating it…")
        self._buttons()
        self._poll.start()

    def _poll_worker(self) -> None:
        if self._conn is None:
            return
        try:
            while self._conn.poll():
                msg = self._conn.recv()
                if "progress" in msg:
                    self.progress.setValue(int(msg["progress"] * 100))
                elif "done" in msg:
                    self._finish(np.asarray(msg["done"], dtype=float))
                    return
                elif "error" in msg:
                    self._finish(None, f"Could not simulate this design: {msg['error']}")
                    return
                elif "cancelled" in msg:
                    self._finish(None, "Cancelled.")
                    return
        except (EOFError, OSError):
            self._finish(None, "The simulation process stopped.")
            return
        if self._proc is not None and not self._proc.is_alive():
            self._finish(None, "The simulation process stopped.")

    def finish_render(self, speaker: np.ndarray) -> None:
        """Cabinet + level for a finished render (also used directly by tests)."""
        y = speaker - np.mean(speaker)
        path = self._cab.path() if self._cab is not None else None
        if path:
            from ..sim.cabinet import apply_ir, load_ir
            y = apply_ir(y, load_ir(path, RATE))[:len(speaker)]
        self.wet = self._norm(y)

    def _finish(self, speaker, message: str = "") -> None:
        self._poll.stop()
        if self._conn is not None:
            try:
                self._conn.close()
            except OSError:
                pass
        self._conn = None
        if self._proc is not None:
            self._proc.join(0.2)
            if self._proc.is_alive():
                self._proc.terminate()
        self._proc = None
        if speaker is not None and len(speaker):
            self.finish_render(speaker)
            self.progress.setValue(100)
            self.status.setText(f"Playing: {self.label}. 'Keep as A' holds it for comparing.")
            self._play(self.wet)
        else:
            self.progress.setValue(0)
            self.status.setText(message)
        self._buttons()

    # ------------------------------------------------------------------ playback
    @staticmethod
    def _norm(data):
        if data is None:
            return None
        d = np.asarray(data, dtype=float)
        d = d - np.mean(d)
        return d / (np.max(np.abs(d)) or 1.0) * 0.8

    def _play(self, data) -> None:
        if data is None:
            return
        try:
            from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
        except ImportError:
            QMessageBox.information(self, "Listen", "Audio output is not available here; use Save WAV instead.")
            return
        self._stop()
        fmt = QAudioFormat()
        fmt.setSampleRate(RATE)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.Int16)
        self._buf = QBuffer(self)
        self._buf.setData(QByteArray((np.clip(data, -1, 1) * 32767).astype("<i2").tobytes()))
        self._buf.open(QIODevice.ReadOnly)
        self._sink = QAudioSink(QMediaDevices.defaultAudioOutput(), fmt, self)
        self._sink.start(self._buf)

    def _stop(self) -> None:
        if self._sink is not None:
            self._sink.stop()
            self._sink = None
        if self._buf is not None:
            self._buf.close()
            self._buf = None

    def _hold(self) -> None:
        if self.wet is not None:
            self.held = (self.label, self.wet)
            self._buttons()

    def _save(self) -> None:
        if self.wet is None:
            return
        name = (self.label.split(",")[0] or "amp").replace(" ", "_") + ".wav"
        path, _ = QFileDialog.getSaveFileName(self, "Save the render", name, "WAV audio (*.wav)")
        if path:
            from ..sim.audio import save_wav
            save_wav(path, self.wet, RATE, normalize=True)

    def shutdown(self) -> None:
        self._stop()
        if self._conn is not None:
            try:
                self._conn.send("cancel")
            except OSError:
                pass
        if self._proc is not None:
            self._proc.terminate()
            self._proc = None
        self._poll.stop()
