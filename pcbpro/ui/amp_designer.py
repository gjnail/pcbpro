"""Amp Designer window: pick what you want, watch the amp take shape (spec sheet, tone, parts), then build the board."""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict

import numpy as np
from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSlider, QTableWidget,
                               QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from ..amp import gainstage as gs
from ..amp.designer import (POWER, VOICINGS, AmpSpec, design_amp, options_for, power_label,
                            report_html)
from ..amp.tonestack import response_db
from .amp_ui import ResponsePlot
from .icons import icon

PRE_TUBES = [("12AX7", "12AX7 - full gain"), ("5751", "5751 - 30 % less gain"), ("12AT7", "12AT7 - more headroom"),
             ("12AY7", "12AY7 - tweed, low gain"), ("12AU7", "12AU7 - lowest gain")]


class AmpDesignerDialog(QDialog):
    """Choices on the left, the live result on the right."""

    def __init__(self, spec: AmpSpec | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Amp Designer")
        self.setMinimumSize(1180, 760)
        self._busy = False
        self.design = None
        self.report = None
        spec = spec or AmpSpec()
        root = QVBoxLayout(self)
        head = QLabel("<h2 style='margin:0'>Design your amp</h2><span style='color:#8b93a1'>Choose what you want - "
                      "the circuit, the values, the transformers to buy and a ready-to-route board follow from "
                      "it. Everything updates as you go.</span>")
        root.addWidget(head)
        body = QHBoxLayout()
        root.addLayout(body, 1)

        # ------------------------------------------------------------------ left: choices
        left = QWidget()
        lay = QVBoxLayout(left)
        lay.setContentsMargins(0, 0, 6, 0)
        g1 = QGroupBox("1  What are you building?")
        g1.setStyleSheet("QPushButton { min-height: 30px; } QPushButton:checked { background-color: #2d6cdf; "
                         "border-color: #2d6cdf; color: white; font-weight: 600; }")
        row = QGridLayout(g1)
        self.inst = QButtonGroup(self)
        self.tech = QButtonGroup(self)
        for i, (text, key) in enumerate((("Guitar amp", "guitar"), ("Bass amp", "bass"))):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("key", key)
            self.inst.addButton(b, i)
            row.addWidget(b, 0, i)
        for i, (text, key) in enumerate((("Tube", "tube"), ("Solid state", "ss"))):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("key", key)
            self.tech.addButton(b, i)
            row.addWidget(b, 1, i)
        lay.addWidget(g1)

        g2 = QGroupBox("2  The sound")
        v2 = QVBoxLayout(g2)
        self.voicings = QListWidget()
        self.voicings.setMaximumHeight(150)
        v2.addWidget(self.voicings)
        self.blurb = QLabel()
        self.blurb.setWordWrap(True)
        self.blurb.setProperty("muted", True)
        v2.addWidget(self.blurb)
        f2 = QFormLayout()
        self.v1 = QComboBox()
        for key, text in PRE_TUBES:
            self.v1.addItem(text, key)
        f2.addRow("First preamp tube (V1)", self.v1)
        self.tight = QComboBox()
        for key in gs.TIGHT_LEVELS:
            self.tight.addItem(gs.TIGHT_LABELS[key], key)
        self.tight.setToolTip("How much bass reaches the distortion stages: tighter keeps fast palm mutes and "
                              "down-tuned riffs clear; the DEPTH control puts the weight back in the power amp.")
        f2.addRow("Tightness", self.tight)
        v2.addLayout(f2)
        lay.addWidget(g2)

        g3 = QGroupBox("3  Power")
        f3 = QFormLayout(g3)
        self.power = QComboBox()
        self.speaker = QComboBox()
        for z in (4, 8, 16):
            self.speaker.addItem(f"{z} ohm", z)
        self.rect = QComboBox()
        for key, text in (("auto", "Automatic (what the design calls for)"), ("tube", "Tube rectifier (sag)"),
                          ("ss", "Solid state (tight)")):
            self.rect.addItem(text, key)
        f3.addRow("Power stage", self.power)
        f3.addRow("Speaker", self.speaker)
        f3.addRow("Rectifier", self.rect)
        lay.addWidget(g3)

        g4 = QGroupBox("4  Features")
        f4 = QGridLayout(g4)
        self.master = QCheckBox("Master volume")
        self.bright = QCheckBox("Bright cap (volume / gain)")
        self.presence = QCheckBox("Presence control")
        self.choke = QCheckBox("Filter choke (less hum)")
        self.standby = QCheckBox("Standby switch")
        self.fx = QCheckBox("Effects loop")
        self.di = QCheckBox("XLR DI output")
        self.depth = QCheckBox("Depth control")
        self.depth.setToolTip("A resonance control on the feedback loop: more low-end thump from the power amp, "
                              "after the distortion.")
        self.dch = QCheckBox("DC heaters (quiet)")
        self.dch.setToolTip("Run the preamp tubes' heaters on filtered DC: no heater hum in the high-gain "
                            "stages.")
        self.nfb = QComboBox()
        for key, text in (("auto", "Feedback: as designed"), ("off", "No feedback (rawer)"),
                          ("light", "Light feedback"), ("normal", "Normal feedback (tighter)")):
            self.nfb.addItem(text, key)
        feats = (self.master, self.bright, self.presence, self.depth, self.fx, self.dch, self.choke, self.standby,
                 self.di)
        for i, w in enumerate(feats):
            f4.addWidget(w, i // 2, i % 2)
        f4.addWidget(self.nfb, 5, 0, 1, 2)
        lay.addWidget(g4)

        g5 = QGroupBox("5  Details")
        f5 = QFormLayout(g5)
        self.mains = QComboBox()
        self.mains.addItem("230 V (Europe, UK, Australia)", 230)
        self.mains.addItem("120 V (North America)", 120)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name your amp (optional)")
        f5.addRow("Mains", self.mains)
        f5.addRow("Name", self.name)
        lay.addWidget(g5)
        lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(left)
        scroll.setMinimumWidth(430)
        scroll.setMaximumWidth(470)
        body.addWidget(scroll)

        # ------------------------------------------------------------------ right: result
        self.tabs = QTabWidget()
        self.sheet = QTextBrowser()
        self.sheet.setOpenExternalLinks(False)
        self.sheet.setOpenLinks(False)
        self.sheet.anchorClicked.connect(self._link)
        self.pedal = ""  # a pedal picked from the spec sheet's "Pedals for this amp"
        self.tabs.addTab(self.sheet, icon("amp"), "Your amp")
        tone = QWidget()
        tl = QVBoxLayout(tone)
        self.plot = ResponsePlot()
        tl.addWidget(self.plot, 1)
        sl = QGridLayout()
        self.knobs = {}
        for i, n in enumerate(("Treble", "Bass", "Middle")):
            s = QSlider(Qt.Horizontal)
            s.setRange(0, 100)
            s.setValue(50)
            lab = QLabel("5.0")
            s.valueChanged.connect(lambda val, l=lab: (l.setText(f"{val / 10:.1f}"), self._tone()))
            sl.addWidget(QLabel(n), i, 0)
            sl.addWidget(s, i, 1)
            sl.addWidget(lab, i, 2)
            self.knobs[n] = s
        tl.addLayout(sl)
        self.tone_note = QLabel()
        self.tone_note.setWordWrap(True)
        self.tone_note.setProperty("muted", True)
        tl.addWidget(self.tone_note)
        self.tabs.addTab(tone, "Tone")
        gt = QWidget()
        gl = QVBoxLayout(gt)
        gl.addWidget(QLabel("<b>Low end into the distortion</b> <span style='color:#8b93a1'>- the preamp's response "
                            "up to its last clipping stage, gain on 10, relative to 1 kHz</span>"))
        self.tplot = ResponsePlot()
        self.tplot.setMinimumSize(520, 190)
        gl.addWidget(self.tplot, 1)
        self.tnote = QLabel()
        self.tnote.setWordWrap(True)
        self.tnote.setProperty("muted", True)
        gl.addWidget(self.tnote)
        gl.addWidget(QLabel("<b>Power amp: presence and depth</b> <span style='color:#8b93a1'>- what the feedback "
                            "controls do after the distortion</span>"))
        self.pplot = ResponsePlot()
        self.pplot.setMinimumSize(520, 170)
        gl.addWidget(self.pplot, 1)
        pg = QGridLayout()
        self.pknobs = {}
        for i, n in enumerate(("Presence", "Depth")):
            s = QSlider(Qt.Horizontal)
            s.setRange(0, 100)
            s.setValue(50)
            lab = QLabel("5.0")
            s.valueChanged.connect(lambda val, l=lab: (l.setText(f"{val / 10:.1f}"), self._power_plot()))
            pg.addWidget(QLabel(n), i, 0)
            pg.addWidget(s, i, 1)
            pg.addWidget(lab, i, 2)
            self.pknobs[n] = s
        gl.addLayout(pg)
        self.gain_tab = gt
        self.tabs.addTab(gt, "Gain && tightness")
        self._tight_cache: dict = {}
        from .amp_listen import ListenPanel
        self.listen = ListenPanel(self)
        self.tabs.addTab(self.listen, "Listen")
        self.bom = QTableWidget(0, 4)
        self.bom.setHorizontalHeaderLabels(["Qty", "Part", "Value", "Footprint"])
        self.bom.verticalHeader().setVisible(False)
        self.bom.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.tabs.addTab(self.bom, "Parts on the board")
        body.addWidget(self.tabs, 1)

        # ------------------------------------------------------------------ bottom bar
        bar = QHBoxLayout()
        save = QPushButton("Save spec sheet…")
        save.clicked.connect(self._save_sheet)
        bar.addWidget(save)
        bar.addStretch(1)
        self.route = QCheckBox("Autoroute the board")
        self.route.setChecked(True)
        bar.addWidget(self.route)
        cancel = QPushButton("Close")
        cancel.clicked.connect(self.reject)
        self.build = QPushButton("Build my amp")
        self.build.setIcon(icon("amp"))
        self.build.setProperty("primary", True)
        self.build.setMinimumHeight(34)
        self.build.clicked.connect(self.accept)
        bar.addWidget(cancel)
        bar.addWidget(self.build)
        root.addLayout(bar)

        # ------------------------------------------------------------------ wiring
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._refresh)
        self._load(spec)
        self.inst.idClicked.connect(lambda *_: self._choices_changed())
        self.tech.idClicked.connect(lambda *_: self._choices_changed())
        self.voicings.currentRowChanged.connect(lambda *_: self._voicing_changed())
        for w in (self.v1, self.power, self.speaker, self.rect, self.nfb, self.mains, self.tight):
            w.currentIndexChanged.connect(lambda *_: self._timer.start())
        for w in (self.master, self.bright, self.presence, self.choke, self.standby, self.fx, self.di, self.depth,
                  self.dch):
            w.toggled.connect(lambda *_: self._timer.start())
        self.name.textChanged.connect(lambda *_: self._timer.start())
        self._refresh()

    # ------------------------------------------------------------------ state
    def _load(self, spec: AmpSpec) -> None:
        self._busy = True
        s = spec.resolved()
        for b in self.inst.buttons():
            b.setChecked(b.property("key") == s.instrument)
        for b in self.tech.buttons():
            b.setChecked(b.property("key") == s.tech)
        self._fill_lists(s.voicing, s.power)
        self.v1.setCurrentIndex(max(0, self.v1.findData(s.v1)))
        self.speaker.setCurrentIndex(max(0, self.speaker.findData(s.speaker)))
        self.rect.setCurrentIndex(max(0, self.rect.findData(spec.rectifier)))
        self.nfb.setCurrentIndex(max(0, self.nfb.findData(spec.nfb)))
        self.mains.setCurrentIndex(max(0, self.mains.findData(s.mains)))
        self.master.setChecked(bool(s.master))
        self.bright.setChecked(bool(s.bright))
        self.presence.setChecked(s.presence)
        self.choke.setChecked(s.choke)
        self.standby.setChecked(s.standby)
        self.fx.setChecked(bool(s.fx_loop))
        self.di.setChecked(bool(s.di_out))
        self.depth.setChecked(bool(s.depth))
        self.dch.setChecked(s.dc_heaters)
        self.tight.setCurrentIndex(max(0, self.tight.findData(s.tight)))
        self.name.setText(spec.name)
        self._busy = False
        self._enable()

    def _key(self, group: QButtonGroup, default: str) -> str:
        b = group.checkedButton()
        return b.property("key") if b is not None else default

    def _fill_lists(self, voicing: str = "", power: str = "") -> None:
        inst, tech = self._key(self.inst, "guitar"), self._key(self.tech, "tube")
        vs, ps = options_for(inst, tech)
        self.voicings.blockSignals(True)
        self.voicings.clear()
        for k in vs:
            it = QListWidgetItem(VOICINGS[k].label)
            it.setData(Qt.UserRole, k)
            it.setToolTip(VOICINGS[k].blurb)
            self.voicings.addItem(it)
        keys = [self.voicings.item(i).data(Qt.UserRole) for i in range(self.voicings.count())]
        self.voicings.setCurrentRow(keys.index(voicing) if voicing in keys else 0)
        self.voicings.blockSignals(False)
        self.power.blockSignals(True)
        self.power.clear()
        for k in ps:
            self.power.addItem(power_label(k), k)
        v = VOICINGS[self._voicing()]
        want = power if power in ps else v.power if v.power in ps else ps[0]
        self.power.setCurrentIndex(self.power.findData(want))
        self.power.blockSignals(False)
        self.blurb.setText(v.blurb)

    def _voicing(self) -> str:
        it = self.voicings.currentItem()
        return it.data(Qt.UserRole) if it is not None else next(iter(VOICINGS))

    def _choices_changed(self) -> None:
        if self._busy:
            return
        self._fill_lists(self._voicing(), self.power.currentData())
        self._voicing_changed()

    def _voicing_changed(self) -> None:
        if self._busy:
            return
        v = VOICINGS[self._voicing()]
        self.blurb.setText(v.blurb)
        self._busy = True
        self.power.setCurrentIndex(max(0, self.power.findData(v.power)))
        self.master.setChecked(v.master)
        self.di.setChecked(v.instrument == "bass")
        self.v1.setCurrentIndex(max(0, self.v1.findData(v.v1)))
        self.nfb.setCurrentIndex(0)
        self.fx.setChecked(v.loop)
        self.depth.setChecked(v.depth)
        self.bright.setChecked(v.bright)
        self.tight.setCurrentIndex(max(0, self.tight.findData(v.tight or "normal")))
        self._busy = False
        self._enable()
        self._timer.start()

    def _enable(self) -> None:
        tube = self._key(self.tech, "tube") == "tube"
        bass = self._key(self.inst, "guitar") == "bass"
        pp = tube and self.power.currentData() in POWER and POWER[self.power.currentData()].pp
        v = VOICINGS[self._voicing()]
        for w in (self.v1, self.rect, self.bright, self.choke, self.standby, self.dch):
            w.setEnabled(tube)
        ltp = pp and v.pi == "ltp" and self.nfb.currentData() != "off"
        self.presence.setEnabled(ltp)
        self.depth.setEnabled(ltp)
        self.nfb.setEnabled(pp and v.pi == "ltp")
        self.tight.setEnabled(bool(v.tight))
        self.di.setEnabled(not tube and bass)

    def spec(self) -> AmpSpec:
        return AmpSpec(instrument=self._key(self.inst, "guitar"), tech=self._key(self.tech, "tube"),
                       voicing=self._voicing(), power=self.power.currentData() or "", rectifier=self.rect.currentData(),
                       speaker=self.speaker.currentData(), v1=self.v1.currentData(), master=self.master.isChecked(),
                       bright=self.bright.isChecked(), presence=self.presence.isChecked(), nfb=self.nfb.currentData(),
                       choke=self.choke.isChecked(), standby=self.standby.isChecked(), fx_loop=self.fx.isChecked(),
                       di_out=self.di.isChecked(), mains=self.mains.currentData(), name=self.name.text().strip(),
                       tight=self.tight.currentData() or "auto", depth=self.depth.isChecked(),
                       dc_heaters=self.dch.isChecked())

    # ------------------------------------------------------------------ results
    def _refresh(self) -> None:
        if self._busy:
            return
        self._enable()
        try:
            self.design, self.report = design_amp(self.spec())
        except Exception as e:  # never let a bad combination kill the window
            self.design = self.report = None
            self.sheet.setHtml(f"<p style='color:#ff8a6b'>This combination does not work yet: {e}</p>")
            self.build.setEnabled(False)
            return
        self.build.setEnabled(True)
        bar = self.sheet.verticalScrollBar().value()
        self.sheet.setHtml(report_html(self.report))
        self.sheet.verticalScrollBar().setValue(bar)
        self._tone()
        self._parts()
        self._gain_plots()
        if hasattr(self, "listen"):
            self.listen.update_knobs()
            self.listen._buttons()

    def _tone(self) -> None:
        rep = self.report
        if rep is None:
            return
        if rep.tone is None:
            self.plot.set_curves([])
            self.tone_note.setText("This voicing uses a single treble-cut tone control instead of a three-knob tone "
                                   "stack: turning it down rolls off the highs.")
            return
        f = np.logspace(math.log10(20), math.log10(20000), 240)
        t, b, m = (self.knobs[n].value() / 10 for n in ("Treble", "Bass", "Middle"))
        curves = [(f, response_db(rep.tone, k, k, k, f), QColor("#5a6577"), 1.2) for k in (5, 10)]
        curves.append((f, response_db(rep.tone, t, b, m, f), QColor("#f0a030"), 2.4))
        self.plot.set_curves(curves)
        self.tone_note.setText(f"{rep.tone_name} tone stack as wired in this design (driven from "
                               f"{rep.tone.rs / 1000:.1f}k). Orange: your knob settings; grey: all at 5 and at 10.")

    def _gain_plots(self) -> None:
        """The tightness curves (this design's level in colour, the other levels grey) and the power-amp plot."""
        rep = self.report
        an = rep.analysis if rep is not None else None
        if an is None or an.pre_db is None:
            self.tplot.set_curves([])
            self.tnote.setText("No tube preamp to analyse: the solid-state designs clip in one op-amp stage.")
        else:
            curves = []
            s = self.spec()
            if rep.tight:
                key = (s.voicing, s.power, s.v1, s.speaker)
                if self._tight_cache.get("key") != key:
                    others = {}
                    for lvl in gs.TIGHT_LEVELS:
                        try:
                            others[lvl] = design_amp(AmpSpec(**{**asdict(s), "tight": lvl}))[1].analysis
                        except Exception:  # an odd combination: just skip that curve
                            continue
                    self._tight_cache = {"key": key, "curves": others}
                for lvl, other in self._tight_cache["curves"].items():
                    if lvl != rep.tight and other is not None and other.pre_db is not None:
                        curves.append((other.freqs, other.pre_db, QColor("#4a5464"), 1.2))
            curves.append((an.freqs, an.pre_db, QColor("#f0a030"), 2.4))
            if rep.pedals:  # the classic metal trick on top: the Tight Boost in front (TIGHT at noon, drive down)
                from ..amp.metal_pedals import tight_boost_response
                tb = tight_boost_response(an.freqs, tight=0.5)
                tdb = 20 * np.log10(np.abs(tb))
                tdb -= float(np.interp(3.0, np.log10(an.freqs), tdb))
                curves.append((an.freqs, an.pre_db + tdb, QColor("#5fb36a"), 1.6))
            self.tplot.set_curves(curves)
            lows = ", ".join(f"{name.split(' (')[0]} {db:.0f} dB" for name, _hz, db in an.lows)
            self.tnote.setText((f"Orange: {gs.TIGHT_LABELS.get(rep.tight, rep.tight)}; grey: the other tightness "
                                f"levels" if rep.tight else "") +
                               ("; green: with the Tight Boost in front (TIGHT at noon). " if rep.pedals else ". ") +
                               f"Into the distortion: {lows}. {an.summary}")
        self._power_plot()

    def _power_plot(self) -> None:
        rep = self.report
        fb = rep.feedback if rep is not None else None
        for s in self.pknobs.values():
            s.setEnabled(fb is not None)
        if fb is None:
            self.pplot.set_curves([])
            return
        self.pknobs["Presence"].setEnabled(bool(fb.pres_c))
        self.pknobs["Depth"].setEnabled(bool(fb.depth_c))
        f = gs.FREQS
        pres, dep = (self.pknobs[n].value() / 10 for n in ("Presence", "Depth"))
        curves = [(f, gs.power_response(fb, f), QColor("#4a5464"), 1.2),
                  (f, gs.power_response(fb, f, presence=10 if fb.pres_c else 0, depth=10 if fb.depth_c else 0),
                   QColor("#4a5464"), 1.2),
                  (f, gs.power_response(fb, f, presence=pres if fb.pres_c else 0, depth=dep if fb.depth_c else 0),
                   QColor("#5fb3e0"), 2.4)]
        self.pplot.set_curves(curves)

    def done(self, r) -> None:  # closing for any reason stops a running render and the audio
        if hasattr(self, "listen"):
            self.listen.shutdown()
        super().done(r)

    def _link(self, url) -> None:
        """A pedal link on the spec sheet: close the designer and design that pedal instead."""
        target = url.toString()
        if target.startswith("pedal:"):
            self.pedal = target[6:]
            self.done(2)

    def _parts(self) -> None:
        if self.design is None:
            return
        rows = Counter()
        for p in self.design.parts:
            what = {"R": "Resistor", "C": "Capacitor", "V": "Tube + socket", "RV": "Pot", "D": "Diode", "J": "Jack",
                    "U": "IC", "W": "Pads"}.get(p.prefix, p.prefix)
            if p.prefix == "RV" and p.label:
                what = f"Pot ({p.label.lower()})"
            rows[(what, p.value, p.part if not p.fp else "wire pads")] += 1
        self.bom.setRowCount(len(rows))
        for r, ((what, value, part), n) in enumerate(sorted(rows.items(), key=lambda kv: (kv[0][0], kv[0][1]))):
            for c, text in enumerate((str(n), what, value, part)):
                self.bom.setItem(r, c, QTableWidgetItem(text))
        self.bom.resizeColumnsToContents()

    def _save_sheet(self) -> None:
        if self.report is None:
            return
        name = (self.report.title or "amp").replace(" ", "_") + "_spec.html"
        path, _ = QFileDialog.getSaveFileName(self, "Save spec sheet", name, "HTML (*.html)")
        if not path:
            return
        page = ("<!doctype html><html><head><meta charset='utf-8'><title>" + self.report.title + "</title>"
                "<style>body{background:#15181e;color:#e6e8ec;font-family:Segoe UI,Arial,sans-serif;max-width:980px;"
                "margin:24px auto;line-height:1.4}td{vertical-align:top}h3{margin-top:22px}</style></head><body>"
                + report_html(self.report) + "</body></html>")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(page)


class _BuildWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object, object)  # project (or None), notes

    def __init__(self, design, route: bool):
        super().__init__()
        self.design, self.route, self.stop = design, route, False

    @Slot()
    def run(self):
        from ..amp.builder import build_amp
        try:
            p, notes = build_amp(self.design, route=self.route, progress=lambda a, b, m: self.progress.emit(a, b, m),
                                 cancelled=lambda: self.stop)
            self.finished.emit(p, notes)
        except Exception as e:  # report instead of dying in the thread
            self.finished.emit(None, [f"{type(e).__name__}: {e}"])


class BuildDialog(QDialog):
    """Places (and routes) the designed amp in a background thread with progress."""

    def __init__(self, design, route: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Building your amp")
        self.setMinimumWidth(480)
        self.project = None
        self.notes: list = []
        lay = QVBoxLayout(self)
        self.label = QLabel(f"Placing {len(design.parts)} parts" + (" and routing the board…" if route else "…"))
        lay.addWidget(self.label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel = QPushButton("Stop routing")
        self.cancel.setEnabled(route)
        self.cancel.clicked.connect(self._stop)
        row.addWidget(self.cancel)
        lay.addLayout(row)
        self.worker = _BuildWorker(design, route)
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._progress)
        self.worker.finished.connect(self._done)
        QTimer.singleShot(0, self.thread.start)

    def _progress(self, a: int, b: int, msg: str) -> None:
        self.bar.setRange(0, max(1, b))
        self.bar.setValue(a)
        self.label.setText(f"{msg}  ({a}/{b})")

    def _stop(self) -> None:
        self.worker.stop = True
        self.cancel.setEnabled(False)
        self.label.setText("Stopping - keeping what is routed so far…")

    def _done(self, project, notes) -> None:
        self.project, self.notes = project, notes
        self.thread.quit()
        self.thread.wait()
        self.accept()

    def reject(self) -> None:  # closing the window stops the router; the dialog closes when the worker returns
        self._stop()


def open_designer(win) -> None:
    """Open the Amp Designer; on "Build my amp" replace the current design with the new amp board."""
    p = win.doc.project
    spec = None
    saved = (getattr(p, "amp", None) or {}).get("spec")
    if isinstance(saved, dict):
        try:
            spec = AmpSpec(**{k: v for k, v in saved.items() if k in AmpSpec.__dataclass_fields__})
        except TypeError:
            spec = None
    dlg = AmpDesignerDialog(spec, win)
    result = dlg.exec()
    if result == 2 and dlg.pedal:  # a pedal picked on the spec sheet
        from .amp_ui import open_metal_pedal
        open_metal_pedal(win, dlg.pedal)
        return
    if not result or dlg.design is None:
        return
    if not win._confirm_discard():
        return
    s = dlg.spec()
    design, rep = design_amp(s)
    build = BuildDialog(design, dlg.route.isChecked(), win)
    build.exec()
    project, notes = build.project, build.notes
    if project is None:
        QMessageBox.warning(win, "Amp Designer", "The board could not be built:\n" + "\n".join(notes))
        return
    project.amp["spec"] = asdict(s)
    win.doc.set_project(project)
    win.canvas.drc_markers = []
    from .pedal_ui import _set_grid
    _set_grid(win, 1.27)
    win.tabs.setCurrentWidget(win.canvas)
    win.canvas.fit_board()
    msg = (f"{rep.title}: {len(project.components)} parts, {len(project.tracks)} tracks. The spec sheet is in the "
           "project notes; reopen Amp > Amp Designer to change the design.")
    open_ = next((n for n in notes if "left unrouted" in n), "")
    if open_:
        msg += f" {open_[0].upper()}{open_[1:]} - route them by hand or move parts and run the autorouter."
    if any("did not fit" in n for n in notes):
        msg += " Some parts did not fit and sit at the board origin."
    win.statusBar().showMessage(msg, 20000)
