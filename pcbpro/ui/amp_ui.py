"""Amp menu: new amp boards from templates, net voltages / currents for the HV checks, the tone-stack designer,
track-width and HV-spacing calculators, tube pinouts and a heater / high-voltage report."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QMenu, QMessageBox, QPushButton, QSlider, QTableWidget, QTableWidgetItem,
                               QTextBrowser, QVBoxLayout, QWidget)

from ..amp import hv
from ..amp.tonestack import PRESETS, ToneStack, response_db, stack_parts, summary
from ..amp.tubes import TUBES, heater_load
from ..sim.units import fmt_eng, parse_value
from .icons import icon


# --------------------------------------------------------------------------- new amp

class NewAmpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        from ..amp.builder import DESIGNS
        self.setWindowTitle("New amp")
        self.setMinimumSize(760, 440)
        self.designs = DESIGNS
        lay = QVBoxLayout(self)
        intro = QLabel("Start from a complete, placed amp circuit: tube sockets along the rear edge, controls and "
                       "jacks on the front edge, every net annotated with its voltage and current, and HV net "
                       "classes so the router, the ground pour and DRC keep IPC-2221B spacing.")
        intro.setWordWrap(True)
        intro.setProperty("muted", True)
        lay.addWidget(intro)
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.addItems(list(DESIGNS))
        self.info = QTextBrowser()
        row.addWidget(self.list, 1)
        row.addWidget(self.info, 1)
        lay.addLayout(row, 1)
        self.route = QCheckBox("Autoroute the board when it is placed (10-30 s)")
        self.route.setChecked(True)
        lay.addWidget(self.route)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Create board")
        bb.button(QDialogButtonBox.Ok).setProperty("primary", True)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.list.currentRowChanged.connect(self._show)
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())
        self.list.setCurrentRow(0)

    def _show(self, row: int) -> None:
        if row < 0:
            return
        d = self.designs[self.list.item(row).text()]()
        tubes = [p.value for p in d.parts if p.role == "tube"]
        html = f"<h3>{d.name}</h3><p>{d.notes.replace(chr(10), '<br>')}</p>"
        html += f"<p><b>{len(d.parts)} parts</b>" + (f", tubes: {', '.join(tubes)}" if tubes else "") + "</p>"
        hot = sorted(((n, v) for n, v in d.volts.items() if abs(v) >= 100), key=lambda kv: -abs(kv[1]))[:6]
        if hot:
            html += "<p>High-voltage nodes: " + ", ".join(f"{n} {v:g} V" for n, v in hot) + "</p>"
        self.info.setHtml(html)

    @property
    def key(self) -> str:
        it = self.list.currentItem()
        return it.text() if it else next(iter(self.designs))


def new_amp(win) -> None:
    if not win._confirm_discard():
        return
    dlg = NewAmpDialog(win)
    if not dlg.exec():
        return
    from ..amp.builder import build_amp
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        project, notes = build_amp(dlg.designs[dlg.key]())
    finally:
        QApplication.restoreOverrideCursor()
    win.doc.set_project(project)
    win.canvas.drc_markers = []
    from .pedal_ui import _set_grid
    _set_grid(win, 1.27)
    win.tabs.setCurrentWidget(win.canvas)
    win.canvas.fit_board()
    if dlg.route.isChecked():
        win.autoroute()
    win.statusBar().showMessage("Amp board ready. Amp > Net voltages edits the HV data; Run DRC checks spacing, track "
                                "current, part ratings, bleeders and tube wiring.", 15000)


# --------------------------------------------------------------------------- net voltages

class NetVoltageDialog(QDialog):
    COLS = ["Net", "DC volts", "AC volts (rms)", "Current (A)", "Mains", "Class"]

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Net voltages and currents")
        self.setMinimumSize(760, 560)
        self.project = project
        lay = QVBoxLayout(self)
        intro = QLabel("Give every high-voltage, mains and high-current net its working values. DC volts are to "
                       "ground (B+ 450, bias -50); AC volts are rms (an HV winding 300, a heater 6.3; a push-pull plate "
                       "swings about B+ peak, i.e. 0.7 x B+ rms). Unlisted nets count as low-voltage signals near 0 V.")
        intro.setWordWrap(True)
        intro.setProperty("muted", True)
        lay.addWidget(intro)
        nets = sorted(set(project.nets()) | set(hv.net_table(project)), key=lambda n: (not hv.net_info(project, n).known, n))
        self.table = QTableWidget(len(nets), len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for r, net in enumerate(nets):
            d = hv.net_table(project).get(net, {})
            it = QTableWidgetItem(net)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(r, 0, it)
            for c, key in ((1, "v"), (2, "ac"), (3, "i")):
                val = d.get(key)
                self.table.setItem(r, c, QTableWidgetItem(f"{val:g}" if val else ""))
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            chk.setCheckState(Qt.Checked if d.get("mains") else Qt.Unchecked)
            self.table.setItem(r, 4, chk)
            cls = QTableWidgetItem(project.net_class_map.get(net, "Default"))
            cls.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(r, 5, cls)
        lay.addWidget(self.table, 1)
        s = hv.amp_settings(project)
        box = QGroupBox("Spacing and current rules")
        form = QFormLayout(box)
        self.cat = QComboBox()
        for k, text in hv.CATEGORIES.items():
            self.cat.addItem(f"{k}: {text}", k)
        self.cat.setCurrentIndex(max(0, self.cat.findData(s["category"])))
        self.rise = QDoubleSpinBox()
        self.rise.setRange(2, 100)
        self.rise.setSuffix(" °C")
        self.rise.setValue(float(s["rise"]))
        self.oz = QDoubleSpinBox()
        self.oz.setRange(0.5, 6)
        self.oz.setSingleStep(0.5)
        self.oz.setSuffix(" oz")
        self.oz.setValue(float(s["copper_oz"]))
        self.mains = QDoubleSpinBox()
        self.mains.setRange(1, 20)
        self.mains.setSuffix(" mm")
        self.mains.setValue(float(s["mains_clearance"]))
        form.addRow("IPC-2221B conductor category", self.cat)
        form.addRow("Allowed track temperature rise", self.rise)
        form.addRow("Copper weight", self.oz)
        form.addRow("Mains to everything else", self.mains)
        self.classes = QCheckBox("Create / update the HV, mains and power net classes from these values")
        self.classes.setChecked(True)
        form.addRow("", self.classes)
        lay.addWidget(box)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self) -> tuple[dict, dict]:
        nets = {}
        for r in range(self.table.rowCount()):
            net = self.table.item(r, 0).text()
            d = {}
            for c, key in ((1, "v"), (2, "ac"), (3, "i")):
                txt = (self.table.item(r, c).text() if self.table.item(r, c) else "").strip()
                if txt:
                    v = parse_value(txt.replace("V", "").replace("A", "").replace("v", ""))
                    if v is None:
                        try:
                            v = float(txt)
                        except ValueError:
                            v = None
                    if txt.lstrip().startswith("-") and v is not None and v > 0:
                        v = -v
                    if v:
                        d[key] = v
            if self.table.item(r, 4).checkState() == Qt.Checked:
                d["mains"] = True
            if d:
                nets[net] = d
        settings = {"category": self.cat.currentData(), "rise": self.rise.value(), "copper_oz": self.oz.value(),
                    "mains_clearance": self.mains.value()}
        return nets, settings


def edit_net_voltages(win) -> None:
    p = win.doc.project
    dlg = NetVoltageDialog(p, win)
    if not dlg.exec():
        return
    nets, settings = dlg.values()
    with win.doc.edit("Net voltages"):
        if not isinstance(getattr(p, "amp", None), dict):
            p.amp = {}
        p.amp["nets"] = nets
        p.amp.update(settings)
        notes = hv.apply_hv_netclasses(p) if dlg.classes.isChecked() else []
    win.doc.refill_zones()
    win.statusBar().showMessage(f"{len(nets)} nets annotated. " + "; ".join(notes), 12000)


def apply_classes(win) -> None:
    p = win.doc.project
    if not hv.net_table(p):
        QMessageBox.information(win, "HV net classes", "No net voltages yet: use Amp > Net voltages and currents first.")
        return
    with win.doc.edit("HV net classes"):
        notes = hv.apply_hv_netclasses(p)
    win.doc.refill_zones()
    QMessageBox.information(win, "HV net classes", "\n".join(notes) or "No HV nets.")


# --------------------------------------------------------------------------- tone stack designer

class ResponsePlot(QWidget):
    """Frequency response plot: 20 Hz - 20 kHz on a log axis, dB on the vertical axis."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(520, 300)
        self.curves: list = []  # (freqs, db, QColor, width)
        self.lo, self.hi = -40.0, 0.0

    def set_curves(self, curves) -> None:
        self.curves = curves
        allv = np.concatenate([c[1] for c in curves]) if curves else np.array([-40.0, 0.0])
        self.hi = 5 * math.ceil(float(allv.max()) / 5 + 0.2)
        self.lo = max(self.hi - 60, min(self.hi - 20, 5 * math.floor(float(allv.min()) / 5 - 0.2)))
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(46, 12, -14, -28)
        p.fillRect(self.rect(), QColor("#15181e"))
        p.fillRect(r, QColor("#1b1f27"))
        f0, f1 = math.log10(20), math.log10(20000)

        def X(f):
            return r.left() + (math.log10(f) - f0) / (f1 - f0) * r.width()

        def Y(db):
            return r.top() + (self.hi - db) / (self.hi - self.lo) * r.height()

        p.setFont(QFont(p.font().family(), 8))
        for f in (20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000):
            p.setPen(QPen(QColor("#2c323d"), 1))
            p.drawLine(QPointF(X(f), r.top()), QPointF(X(f), r.bottom()))
            p.setPen(QColor("#8b93a1"))
            lab = f"{f // 1000}k" if f >= 1000 else str(f)
            p.drawText(QRectF(X(f) - 20, r.bottom() + 4, 40, 14), Qt.AlignCenter, lab)
        db = self.lo
        while db <= self.hi + 1e-6:
            p.setPen(QPen(QColor("#2c323d"), 1))
            p.drawLine(QPointF(r.left(), Y(db)), QPointF(r.right(), Y(db)))
            p.setPen(QColor("#8b93a1"))
            p.drawText(QRectF(2, Y(db) - 7, 40, 14), Qt.AlignRight | Qt.AlignVCenter, f"{db:.0f} dB")
            db += 5
        for freqs, vals, col, width in self.curves:
            path = QPainterPath()
            for i, (f, v) in enumerate(zip(freqs, vals)):
                pt = QPointF(X(f), Y(max(self.lo, min(self.hi, v))))
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            p.setPen(QPen(col, width))
            p.drawPath(path)
        p.end()


class ToneStackDialog(QDialog):
    FIELDS = [("c1", "Treble cap C1", "F"), ("r1", "Slope resistor R1", "Ω"), ("c2", "Bass cap C2", "F"),
              ("c3", "Mid cap C3", "F"), ("rt", "Treble pot", "Ω"), ("rb", "Bass pot", "Ω"), ("rm", "Mid pot", "Ω"),
              ("rs", "Source impedance", "Ω"), ("rl", "Load (volume pot)", "Ω")]

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Tone stack designer")
        self.setMinimumSize(980, 560)
        self.freqs = np.logspace(math.log10(20), math.log10(20000), 240)
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        self.preset = QComboBox()
        self.preset.addItems(list(PRESETS))
        left.addWidget(QLabel("Preset"))
        left.addWidget(self.preset)
        form = QFormLayout()
        self.edits = {}
        for key, label, unit in self.FIELDS:
            e = QLineEdit()
            e.editingFinished.connect(self._update)
            self.edits[key] = (e, unit)
            form.addRow(label, e)
        self.fixed = QCheckBox("Fixed mid resistor (no mid pot)")
        self.fixed.toggled.connect(self._update)
        form.addRow("", self.fixed)
        left.addLayout(form)
        grid = QGridLayout()
        self.sliders = {}
        for i, name in enumerate(("Treble", "Bass", "Middle")):
            s = QSlider(Qt.Horizontal)
            s.setRange(0, 100)
            s.setValue(50)
            lab = QLabel("5.0")
            s.valueChanged.connect(lambda v, l=lab: (l.setText(f"{v / 10:.1f}"), self._update()))
            grid.addWidget(QLabel(name), i, 0)
            grid.addWidget(s, i, 1)
            grid.addWidget(lab, i, 2)
            self.sliders[name] = s
        left.addLayout(grid)
        ins = QGroupBox("Insert into the board")
        f2 = QFormLayout(ins)
        self.in_net = QLineEdit("TS_IN")
        self.out_net = QLineEdit("TS_OUT")
        f2.addRow("Input net (driving stage)", self.in_net)
        f2.addRow("Output net (to volume / next grid)", self.out_net)
        b = QPushButton("Insert tone stack parts")
        b.clicked.connect(self._insert)
        f2.addRow("", b)
        left.addWidget(ins)
        left.addStretch(1)
        lay.addLayout(left, 0)
        right = QVBoxLayout()
        self.plot = ResponsePlot()
        right.addWidget(self.plot, 1)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        right.addWidget(self.summary)
        legend = QLabel("<span style='color:#f0a030'>■</span> current settings &nbsp; "
                        "<span style='color:#5a6577'>■</span> all controls at 5 and at 10")
        legend.setProperty("muted", True)
        right.addWidget(legend)
        lay.addLayout(right, 1)
        self.preset.currentTextChanged.connect(self._load)
        self._load(self.preset.currentText())

    def _load(self, name: str) -> None:
        ts = PRESETS[name]
        for key, (e, unit) in self.edits.items():
            e.setText(fmt_eng(getattr(ts, key), unit))
        self.fixed.blockSignals(True)
        self.fixed.setChecked(ts.mid_fixed)
        self.fixed.blockSignals(False)
        self._update()

    def stack(self) -> ToneStack:
        kw = {}
        for key, (e, _unit) in self.edits.items():
            v = parse_value(e.text())
            kw[key] = v if v else getattr(PRESETS[self.preset.currentText()], key)
        return ToneStack(**kw, mid_fixed=self.fixed.isChecked())

    def _update(self) -> None:
        ts = self.stack()
        t, b, m = (self.sliders[n].value() / 10 for n in ("Treble", "Bass", "Middle"))
        curves = [(self.freqs, response_db(ts, k, k, k, self.freqs), QColor("#5a6577"), 1.2) for k in (5, 10)]
        curves.append((self.freqs, response_db(ts, t, b, m, self.freqs), QColor("#f0a030"), 2.4))
        self.plot.set_curves(curves)
        self.summary.setText(summary(ts, t, b, m))

    def _insert(self) -> None:
        from ..amp.builder import _make
        from ..pedal.templates import pack_components
        p = self.win.doc.project
        parts = stack_parts(self.stack(), self.in_net.text().strip() or "TS_IN", self.out_net.text().strip() or "TS_OUT")
        with self.win.doc.edit("Insert tone stack"):
            comps = []
            for spec in parts:
                c = _make(p, spec)
                p.components.append(c)
                comps.append(c)
            for c in comps:
                p.components.remove(c)
            placed = pack_components(p, comps, None, "top")
            for c in comps:
                if c not in placed:
                    p.components.append(c)
        self.win.statusBar().showMessage(f"Inserted {len(comps)} tone stack parts ({len(placed)} placed in free space).",
                                         8000)


def tone_stack(win) -> None:
    ToneStackDialog(win).exec()


# --------------------------------------------------------------------------- calculators

class CalculatorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Track width and HV spacing")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        g1 = QGroupBox("Track width for a current (IPC-2221)")
        f1 = QFormLayout(g1)
        self.amps = QDoubleSpinBox()
        self.amps.setRange(0.01, 100)
        self.amps.setValue(3.0)
        self.amps.setSuffix(" A")
        self.rise = QDoubleSpinBox()
        self.rise.setRange(1, 100)
        self.rise.setValue(10)
        self.rise.setSuffix(" °C rise")
        self.oz = QDoubleSpinBox()
        self.oz.setRange(0.5, 6)
        self.oz.setSingleStep(0.5)
        self.oz.setValue(1.0)
        self.oz.setSuffix(" oz")
        self.inner = QCheckBox("Inner layer")
        self.w_out = QLabel()
        for w in (self.amps, self.rise, self.oz):
            w.valueChanged.connect(self._calc)
        self.inner.toggled.connect(self._calc)
        f1.addRow("Current", self.amps)
        f1.addRow("Temperature rise", self.rise)
        f1.addRow("Copper", self.oz)
        f1.addRow("", self.inner)
        f1.addRow("Minimum width", self.w_out)
        lay.addWidget(g1)
        g2 = QGroupBox("Conductor spacing for a voltage (IPC-2221B table 6-1)")
        f2 = QFormLayout(g2)
        self.volts = QDoubleSpinBox()
        self.volts.setRange(0, 10000)
        self.volts.setValue(450)
        self.volts.setSuffix(" V peak")
        self.cat = QComboBox()
        for k, text in hv.CATEGORIES.items():
            self.cat.addItem(f"{k}: {text}", k)
        self.s_out = QLabel()
        self.volts.valueChanged.connect(self._calc)
        self.cat.currentIndexChanged.connect(self._calc)
        f2.addRow("Voltage between conductors", self.volts)
        f2.addRow("Category", self.cat)
        f2.addRow("Minimum spacing", self.s_out)
        hint = QLabel("AC: use the peak (rms x 1.41). Between an HV winding's two ends use twice the peak. "
                      "Mains to low voltage: keep 6.4 mm or more (reinforced insulation).")
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        f2.addRow(hint)
        lay.addWidget(g2)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._calc()

    def _calc(self) -> None:
        w = hv.track_width_for(self.amps.value(), self.rise.value(), self.oz.value(), not self.inner.isChecked())
        self.w_out.setText(f"<b>{w:.2f} mm</b> ({w / 0.0254:.0f} mil); a 1 mm track carries "
                           f"{hv.current_for(1.0, self.rise.value(), self.oz.value(), not self.inner.isChecked()):.1f} A")
        s = hv.ipc_clearance(self.volts.value(), self.cat.currentData())
        self.s_out.setText(f"<b>{s:.2f} mm</b> ({s / 0.0254:.0f} mil)")


def calculators(win) -> None:
    CalculatorDialog(win).exec()


# --------------------------------------------------------------------------- tube data and report

class TubeTableDialog(QDialog):
    COLS = ["Tube", "Also", "Base", "Type", "Pinout (seen from below: pin 1 next to the gap / key)", "Heater",
            "Va max", "Pa max", "mu"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tube pinouts and ratings")
        self.setMinimumSize(1100, 560)
        lay = QVBoxLayout(self)
        t = QTableWidget(len(TUBES), len(self.COLS))
        t.setHorizontalHeaderLabels(self.COLS)
        t.verticalHeader().setVisible(False)
        kinds = {"triode2": "dual triode", "pentode": "pentode / triode", "power": "power", "rectifier": "rectifier"}
        for r, tube in enumerate(TUBES.values()):
            cells = [tube.name, ", ".join(tube.aliases), {"noval": "Noval", "b7g": "B7G", "octal": "Octal"}[tube.base],
                     kinds[tube.kind], tube.pinout_text(), f"{tube.heater_v:g} V {tube.heater_a:g} A",
                     f"{tube.va_max:g} V", f"{tube.pa_max:g} W" if tube.pa_max else f"{tube.i_max_ma:g} mA",
                     f"{tube.mu:g}" if tube.mu else ""]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if tube.note:
                    it.setToolTip(tube.note)
                t.setItem(r, c, it)
        t.resizeColumnsToContents()
        lay.addWidget(t, 1)
        note = QLabel("Codes: PA/GA/KA and PB/GB/KB = plate, grid, cathode of the two triode sections; A anode, G1 "
                      "grid, G2 screen, G3 suppressor, K cathode, H heater, HCT heater centre tap, HK filament-cathode, "
                      "IS internal shield, NC not connected (never a tie point). Hover a row for notes.")
        note.setWordWrap(True)
        note.setProperty("muted", True)
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


def tube_table(win) -> None:
    TubeTableDialog(win).exec()


def amp_report(win) -> None:
    from ..amp.checks import run_amp_checks
    p = win.doc.project
    lines = []
    load = heater_load(p)
    if load.tubes:
        lines.append("<h3>Heaters</h3><ul>")
        for v, a in sorted(load.by_voltage.items()):
            names = [f"{ref} {name}" for ref, name, hv_, _ in load.tubes if hv_ == v]
            lines.append(f"<li><b>{v:g} V: {a:.2f} A</b> ({', '.join(names)}) - choose a winding rated "
                         f"{a * 1.2:.1f} A or more</li>")
        lines.append("</ul>")
    hot = [(n, hv.net_info(p, n)) for n in hv.net_table(p)]
    hot = sorted([(n, v) for n, v in hot if v.peak >= 50 or v.mains], key=lambda kv: -kv[1].peak)
    if hot:
        lines.append("<h3>High-voltage nets</h3><ul>")
        for n, v in hot[:20]:
            lines.append(f"<li>{n}: {v.describe()} (peak {v.peak:.0f} V, class {p.net_class_map.get(n, 'Default')})</li>")
        lines.append("</ul>")
    viol = run_amp_checks(p)
    if viol:
        kinds: dict = {}
        for v in viol:
            kinds.setdefault(v.kind, []).append(v)
        lines.append("<h3>Amp checks</h3><ul>")
        for k, vs in kinds.items():
            errs = sum(1 for v in vs if v.severity == "error")
            lines.append(f"<li>{k}: {errs} errors, {len(vs) - errs} warnings - e.g. {vs[0].message}</li>")
        lines.append("</ul><p>Run DRC to see each one on the board.</p>")
    elif hot:
        lines.append("<p>All amp checks pass (spacing, track current, part ratings, bleeders, tube wiring).</p>")
    if not lines:
        lines.append("<p>No tubes and no annotated nets yet. Start from Amp > New amp, or annotate nets with "
                     "Amp > Net voltages and currents.</p>")
    box = QMessageBox(win)
    box.setWindowTitle("Amp report")
    box.setTextFormat(Qt.RichText)
    box.setText("".join(lines))
    box.exec()


# --------------------------------------------------------------------------- installation

def open_amp_example(win, file_name: str, design: str) -> None:
    """Open a bundled amp example (placed and routed); builds it if the file is missing."""
    if not win._confirm_discard():
        return
    from ..examples import EXAMPLE_DIR, load_example
    path = EXAMPLE_DIR / file_name
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        if path.exists():
            project = load_example(path)
        else:
            from ..amp.builder import DESIGNS, build_amp
            project, _ = build_amp(DESIGNS[design](), route=True)
    finally:
        QApplication.restoreOverrideCursor()
    win.doc.set_project(project)
    win.canvas.drc_markers = []
    win.tabs.setCurrentWidget(win.canvas)
    win.canvas.fit_board()


def open_metal_pedal(win, key: str) -> None:
    """Open one of the metal pedals (placed and routed): the bundled copy, or built on the spot."""
    if not win._confirm_discard():
        return
    from ..amp.metal_pedals import METAL_EXAMPLES, PEDALS, build_pedal
    from ..examples import EXAMPLE_DIR, load_example
    path = EXAMPLE_DIR / METAL_EXAMPLES.get(key, "")
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        project = load_example(path) if key in METAL_EXAMPLES and path.exists() else build_pedal(key, route=True)
    finally:
        QApplication.restoreOverrideCursor()
    win.doc.set_project(project)
    win.canvas.drc_markers = []
    from .pedal_ui import _set_grid
    _set_grid(win, 1.27)
    win.tabs.setCurrentWidget(win.canvas)
    win.canvas.fit_board()
    win.statusBar().showMessage(f"{PEDALS[key].title}: the circuit, how to wire it and how to use it are in the project "
                                "notes. Pedal > Enclosure && drilling for the box; Simulate > Play to hear it.", 20000)


def install(win) -> None:
    """Add the Amp menu to a MainWindow."""
    from ..amp.builder import AMP_EXAMPLES
    from ..amp.metal_pedals import PEDALS
    from .amp_designer import open_designer
    m = QMenu("&Amp", win)
    m.addAction(icon("amp"), "Amp &Designer…", lambda: open_designer(win)).setShortcut("Ctrl+Alt+A")
    m.addAction("&New amp from a template…", lambda: new_amp(win))
    ex = m.addMenu(icon("amp"), "Open &example amp")
    for design, file_name in AMP_EXAMPLES.items():
        ex.addAction(design, lambda d=design, f=file_name: open_amp_example(win, f, d))
    mp = m.addMenu(icon("pedal"), "&Metal pedals")
    for key, kind in PEDALS.items():
        a = mp.addAction(kind.title, lambda k=key: open_metal_pedal(win, k))
        a.setToolTip(kind.blurb)
        a.setStatusTip(kind.blurb)
    m.addSeparator()
    m.addAction("Net &voltages and currents…", lambda: edit_net_voltages(win))
    m.addAction("Apply &HV net classes", lambda: apply_classes(win))
    m.addAction(icon("drc"), "Run DRC with H&V checks", win.run_drc)
    m.addAction("Heater && HV &report", lambda: amp_report(win))
    m.addSeparator()
    m.addAction("&Tone stack designer…", lambda: tone_stack(win))
    m.addAction("Track width && HV &spacing calculator…", lambda: calculators(win))
    m.addAction(icon("amp"), "Tube &pinouts and ratings…", lambda: tube_table(win))
    mb = win.menuBar()
    before = next((a for a in mb.actions() if a.text().replace("&", "") == "Tools"), None)
    if before is not None:
        mb.insertMenu(before, m)
    else:
        mb.addMenu(m)
    win.amp_menu = m
