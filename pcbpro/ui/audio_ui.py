"""Audio play-through and frequency-response dialogs for pedal and amplifier boards."""
from __future__ import annotations

import math
import multiprocessing as mp

import numpy as np
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QSlider, QSplitter,
                               QVBoxLayout, QWidget)

from ..sim.audio import CLIPS, audio_worker, frequency_response, guitar_clip, load_wav, save_wav
from ..sim.cabinet import apply_ir, ir_response, load_ir
from .cab_ui import CabinetPicker
from .scope import BodePlot

ACCENT = "#4c9aff"
CAB_COLOR = "#f5a142"


def _knob_label(project, comp) -> str:
    """The silkscreen text printed next to a pot (LEVEL, TONE, ...), else its reference and value. The nearest label
    under the pot (+y, where the pedal generator prints it, about 20 mm down) wins over a nearer one above it - on a
    two-row pedal that is the label of the pot above; a label above is used when none is under the pot (an amp's
    front-panel controls are labelled above)."""
    best = None
    for t in project.texts:
        if not t.layer.endswith("SilkS"):
            continue
        d = math.hypot(t.x - comp.x, t.y - comp.y)
        key = (t.y < comp.y, d)
        if d < 26 and (best is None or key < best[0]) and t.text.replace(" ", "").isalpha() and len(t.text) <= 12:
            best = (key, t.text)
    return f"{best[1]} ({comp.ref})" if best else f"{comp.ref} {comp.value}"


class Waveforms(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dry = None
        self.wet = None
        self.suffix = ""
        self.setMinimumHeight(130)

    def set_data(self, dry, wet, suffix: str = ""):
        self.dry, self.wet, self.suffix = dry, wet, suffix
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(14, 16, 20))
        lane = self.height() / 2
        for k, (data, col, lab) in enumerate(((self.dry, QColor(150, 156, 168), "dry guitar" + self.suffix),
                                              (self.wet, QColor(ACCENT), "through the circuit" + self.suffix))):
            mid = lane * k + lane / 2
            p.setPen(QPen(QColor(52, 58, 70), 1))
            p.drawLine(QPointF(0, mid), QPointF(self.width(), mid))
            p.setPen(col)
            p.drawText(QRectF(8, lane * k + 2, 300, 16), Qt.AlignLeft, lab)
            if data is None or not len(data):
                continue
            d = np.asarray(data) - np.mean(data)
            d = d / (np.max(np.abs(d)) or 1.0)
            w = max(1, self.width())
            path = QPainterPath()
            amp = lane / 2 - 4
            for x, c in enumerate(np.array_split(d, w)):
                if not len(c):
                    continue
                y0, y1 = mid - float(c.max()) * amp, mid - float(c.min()) * amp
                if x == 0:
                    path.moveTo(x, y0)
                path.lineTo(x, y0)
                path.lineTo(x, y1)
            p.setPen(QPen(col, 1))
            p.drawPath(path)


class _Knobs(QGroupBox):
    """Sliders for the pots and selectors for the switches of the board."""

    def __init__(self, project, on_change, parent=None):
        super().__init__("Knobs and switches", parent)
        from ..sim.netlist import build_circuit
        self.ck = build_circuit(project)
        self.values: dict = {}
        form = QFormLayout(self)
        comps = {c.uid: c for c in project.components}
        for ctl in self.ck.controls:
            comp = comps.get(ctl.uid)
            if ctl.kind == "pot":
                s = QSlider(Qt.Horizontal)
                s.setRange(0, 100)
                s.setValue(50)
                self.values[ctl.key] = 0.5
                s.valueChanged.connect(lambda v, k=ctl.key: (self.values.__setitem__(k, v / 100), on_change()))
                form.addRow(_knob_label(project, comp) if comp else ctl.label, s)
            elif ctl.kind in ("toggle", "plug") and comp is not None and ctl.options:
                cb = QComboBox()
                cb.addItems(ctl.options)
                cb.setCurrentIndex(int(ctl.value))
                self.values[ctl.key] = int(ctl.value)
                cb.currentIndexChanged.connect(lambda i, k=ctl.key: (self.values.__setitem__(k, i), on_change()))
                form.addRow(ctl.label, cb)
        if not self.values:
            form.addRow(QLabel("No knobs or switches on this board."))


def _nets(project):
    """All nets, the default input and the default output (an amplifier's speaker when it has one)."""
    from ..sim.ampboard import output_net
    nets = list(project.nets())
    amp_out = output_net(project)
    if amp_out and amp_out not in nets:
        nets.append(amp_out)  # the speaker on the output transformer secondary (off the board)
    nin = "IN" if "IN" in nets else (nets[0] if nets else "")
    nout = amp_out or ("OUT" if "OUT" in nets else (nets[-1] if nets else ""))
    return nets, nin, nout


def full_scale(project, out_net: str) -> float:
    """Volts that map to full scale: 1 V for pedals, the speaker voltage at rated power for an amplifier output."""
    from ..sim.ampboard import SPEAKER_NET, full_scale_volts, output_net
    if out_net and out_net in (output_net(project), SPEAKER_NET):
        return full_scale_volts(project)
    return 1.0


class AudioDialog(QDialog):
    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self.project = win.doc.project
        self.setWindowTitle("Audio play-through")
        self.resize(900, 640)
        self.dry = None
        self.wet = None
        self.rate = 48000
        self.out_ref = 1.0
        self._proc = None
        self._conn = None
        self._sink = None
        self._buf = None
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        left = QVBoxLayout()
        box = QGroupBox("Signal")
        form = QFormLayout(box)
        nets, nin, nout = _nets(self.project)
        self.in_net = QComboBox()
        self.in_net.addItems(nets)
        self.in_net.setCurrentText(nin)
        self.out_net = QComboBox()
        self.out_net.addItems(nets)
        self.out_net.setCurrentText(nout)
        form.addRow("Input net", self.in_net)
        form.addRow("Output net", self.out_net)
        self.clip = QComboBox()
        self.clip.addItems(CLIPS + ["Load WAV file…"])
        self.clip.activated.connect(self._clip_chosen)
        self.wav_path = None
        form.addRow("Guitar clip", self.clip)
        self.level = QDoubleSpinBox()
        self.level.setRange(10, 2000)
        self.level.setValue(150)
        self.level.setSuffix(" mV peak")
        self.level.setToolTip("Pickup output: single coils ~100 mV, hot humbuckers up to ~1 V")
        form.addRow("Level", self.level)
        self.seconds = QDoubleSpinBox()
        self.seconds.setRange(0.5, 10)
        self.seconds.setValue(3.0)
        self.seconds.setSuffix(" s")
        form.addRow("Length", self.seconds)
        self.quality = QComboBox()
        self.quality.addItem("24 kHz (twice as fast)", 24000)
        self.quality.addItem("48 kHz", 48000)
        form.addRow("Sample rate", self.quality)
        self.cab = CabinetPicker()
        self.cab.changed.connect(self._cab_changed)
        form.addRow("Cabinet", self.cab)
        left.addWidget(box)
        self.knobs = _Knobs(self.project, self._knobs_changed)
        left.addWidget(self.knobs)
        left.addStretch(1)
        top.addLayout(left, 1)
        right = QVBoxLayout()
        self.bode = BodePlot()
        right.addWidget(QLabel("Frequency response (updates as you turn the knobs):"))
        right.addWidget(self.bode, 1)
        top.addLayout(right, 2)
        lay.addLayout(top, 1)
        self.wave = Waveforms()
        lay.addWidget(self.wave)
        bar = QHBoxLayout()
        self.render_btn = QPushButton("Render")
        self.render_btn.setProperty("primary", True)
        self.render_btn.clicked.connect(self.render)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.play_dry = QPushButton("▶ Dry")
        self.play_wet = QPushButton("▶ Processed")
        self.stop_btn = QPushButton("■")
        self.save_btn = QPushButton("Save WAV…")
        self.match = QCheckBox("Match loudness")
        self.match.setChecked(True)
        for b in (self.play_dry, self.play_wet, self.save_btn):
            b.setEnabled(False)
        self.play_dry.clicked.connect(lambda: self._play(self._out(self.dry)))
        self.play_wet.clicked.connect(lambda: self._play(self._out(self.wet), self.out_ref))
        self.stop_btn.clicked.connect(self._stop_audio)
        self.save_btn.clicked.connect(self._save)
        for w in (self.render_btn, self.cancel_btn, self.progress, self.play_dry, self.play_wet, self.stop_btn,
                  self.match, self.save_btn):
            bar.addWidget(w)
        lay.addLayout(bar)
        self.status = QLabel("Render the clip through the circuit, then compare dry and processed.")
        self.status.setProperty("muted", True)
        lay.addWidget(self.status)
        self._poll = QTimer(self)
        self._poll.setInterval(100)
        self._poll.timeout.connect(self._poll_worker)
        self._bode_timer = QTimer(self)
        self._bode_timer.setSingleShot(True)
        self._bode_timer.setInterval(120)
        self._bode_timer.timeout.connect(self._update_bode)
        self.in_net.currentTextChanged.connect(lambda _t: self._bode_timer.start())
        self.out_net.currentTextChanged.connect(lambda _t: self._bode_timer.start())
        self._bode_timer.start()

    # ------------------------------------------------------------------ inputs
    def _clip_chosen(self, i):
        if self.clip.itemText(i).startswith("Load"):
            path, _ = QFileDialog.getOpenFileName(self, "Guitar recording", "", "WAV audio (*.wav)")
            if path:
                self.wav_path = path
                self.clip.setItemText(i, f"WAV: {path.replace(chr(92), '/').split('/')[-1]}")
            else:
                self.clip.setCurrentIndex(0)

    def _clip_data(self):
        rate = self.quality.currentData()
        level = self.level.value() / 1000.0
        if self.clip.currentText().startswith("WAV") and self.wav_path:
            return load_wav(self.wav_path, rate, self.seconds.value(), level), rate
        return guitar_clip(self.clip.currentText(), self.seconds.value(), rate, level), rate

    def _knobs_changed(self):
        self._bode_timer.start()

    # ------------------------------------------------------------------ cabinet
    def _cab_ir(self, rate=None):
        path = self.cab.path()
        if not path:
            return None
        try:
            return load_ir(path, rate or self.rate)
        except Exception as e:
            self.status.setText(f"Cabinet IR: {e}")
            return None

    def _out(self, data):
        """What you hear: the signal through the selected cabinet."""
        if data is None:
            return None
        h = self._cab_ir()
        return apply_ir(data, h) if h is not None else data

    def _cab_changed(self, _path):
        self._bode_timer.start()
        if self.wet is not None and len(self.wet):
            self._stop_audio()
            self._show_waves()

    def _show_waves(self):
        ok = self.wet is not None and len(self.wet) > 0
        self.wave.set_data(self._out(self.dry), self._out(self.wet) if ok else None,
                           " + cabinet" if self.cab.path() else "")

    def _update_bode(self):
        try:
            f, h = frequency_response(self.project, self.in_net.currentText(), self.out_net.currentText(),
                                      dict(self.knobs.values))
        except Exception as e:
            self.status.setText(f"Frequency response: {e}")
            return
        curves = [("output / guitar", h, ACCENT)]
        ir = self._cab_ir(48000)
        if ir is not None:
            curves.append(("with the cabinet", h * ir_response(ir, 48000, f), CAB_COLOR))
        self.bode.set_data(f, curves)

    # ------------------------------------------------------------------ render (worker process)
    def render(self):
        self._stop_audio()
        try:
            clip, rate = self._clip_data()
        except Exception as e:
            QMessageBox.warning(self, "Audio", f"Could not read the clip:\n{e}")
            return
        self.dry, self.rate = clip, rate
        self.out_ref = full_scale(self.project, self.out_net.currentText())
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        opts = {"clip": clip, "rate": rate, "in": self.in_net.currentText(), "out": self.out_net.currentText(),
                "controls": dict(self.knobs.values)}
        self._proc = ctx.Process(target=audio_worker, args=(child, self.project.to_dict(), opts), daemon=True)
        self._proc.start()
        child.close()
        self._conn = parent
        self.render_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setValue(0)
        self.status.setText("Rendering… (the circuit is solved at every audio sample)")
        self._poll.start()

    def _poll_worker(self):
        if self._conn is None:
            return
        try:
            while self._conn.poll():
                msg = self._conn.recv()
                if "progress" in msg:
                    self.progress.setValue(int(msg["progress"] * 100))
                elif "done" in msg:
                    self.wet = np.asarray(msg["done"])
                    self._finish("Done: play the dry and processed versions to compare.")
                    return
                elif "error" in msg:
                    self._finish(f"Render failed: {msg['error']}")
                    return
        except (EOFError, OSError):
            self._finish("The render process stopped.")
            return
        if self._proc is not None and not self._proc.is_alive():
            self._finish("The render process stopped.")

    def _finish(self, text):
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
        self.render_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        ok = self.wet is not None and len(self.wet) > 0
        self.progress.setValue(100 if ok else 0)
        for b in (self.play_dry, self.play_wet, self.save_btn):
            b.setEnabled(ok)
        self._show_waves()
        self.status.setText(text)

    def _cancel(self):
        if self._conn is not None:
            try:
                self._conn.send("cancel")
            except OSError:
                pass
        self.wet = None
        self._finish("Cancelled.")

    # ------------------------------------------------------------------ playback
    def _pcm(self, data, ref: float = 1.0) -> bytes:
        d = np.asarray(data, dtype=float)
        d = d - np.mean(d)
        peak = np.max(np.abs(d)) or 1.0
        if self.match.isChecked():
            d = d / peak * 0.8
        else:  # keep the circuit's gain relative to its full scale (1 V, or an amp's speaker at rated power)
            d = d / max(ref, peak)
        return (np.clip(d, -1, 1) * 32767).astype("<i2").tobytes()

    def _play(self, data, ref: float = 1.0):
        if data is None:
            return
        try:
            from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
        except ImportError:
            QMessageBox.information(self, "Audio", "Audio output is not available; use Save WAV instead.")
            return
        self._stop_audio()
        fmt = QAudioFormat()
        fmt.setSampleRate(int(self.rate))
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.Int16)
        self._buf = QBuffer(self)
        self._buf.setData(QByteArray(self._pcm(data, ref)))
        self._buf.open(QIODevice.ReadOnly)
        self._sink = QAudioSink(QMediaDevices.defaultAudioOutput(), fmt, self)
        self._sink.start(self._buf)

    def _stop_audio(self):
        if self._sink is not None:
            self._sink.stop()
            self._sink = None
        if self._buf is not None:
            self._buf.close()
            self._buf = None

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save processed audio", f"{self.project.name}_audio.wav",
                                              "WAV audio (*.wav)")
        if path:
            save_wav(path, self._out(self.wet), int(self.rate))

    def closeEvent(self, ev):
        self._stop_audio()
        if self._conn is not None:
            self._cancel()
        super().closeEvent(ev)

    def reject(self):
        self._stop_audio()
        if self._conn is not None:
            self._cancel()
        super().reject()


class BodeDialog(QDialog):
    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.project = win.doc.project
        self.setWindowTitle("Frequency response")
        self.resize(820, 520)
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        box = QGroupBox("Nets")
        form = QFormLayout(box)
        nets, nin, nout = _nets(self.project)
        self.in_net = QComboBox()
        self.in_net.addItems(nets)
        self.in_net.setCurrentText(nin)
        self.out_net = QComboBox()
        self.out_net.addItems(nets)
        self.out_net.setCurrentText(nout)
        form.addRow("Input", self.in_net)
        form.addRow("Output", self.out_net)
        left.addWidget(box)
        self.knobs = _Knobs(self.project, lambda: self._timer.start())
        left.addWidget(self.knobs)
        note = QLabel("Small-signal gain from a guitar (10 k source) to a 1 M load, around the bias point.")
        note.setWordWrap(True)
        note.setProperty("muted", True)
        left.addWidget(note)
        left.addStretch(1)
        lay.addLayout(left, 1)
        self.plot = BodePlot()
        lay.addWidget(self.plot, 2)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._update)
        self.in_net.currentTextChanged.connect(lambda _t: self._timer.start())
        self.out_net.currentTextChanged.connect(lambda _t: self._timer.start())
        self._timer.start()

    def _update(self):
        try:
            f, h = frequency_response(self.project, self.in_net.currentText(), self.out_net.currentText(),
                                      dict(self.knobs.values))
            self.plot.set_data(f, [("output / input", h, ACCENT)])
        except Exception as e:
            self.plot.set_data([], [])
            self.setWindowTitle(f"Frequency response: {e}")
