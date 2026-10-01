"""Guitar-pedal user interface: New Pedal wizard, Enclosure & Drilling tab, layout overlay and the Pedal menu."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMenu, QMessageBox, QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..model.geometry import iter_polygons
from ..pedal.enclosure import (CATALOG, FACE_NAMES, FACES, HARDWARE, KNOB_COLORS, PAINT_ALLOWANCE, POWDER_COATS,
                               Enclosure, PanelHole, all_holes, centre_on_board, fit_outline, get_enclosure,
                               hole_face_point, set_enclosure)
from ..pedal.drill import _z
from . import theme
from .flow import FlowLayout
from .icons import icon

EXAMPLE_NAME = "Three_Knob_Overdrive_125B.pcbpro"
ENCLOSURE_KEYS = ["1590LB", "1590A", "1590B", "1590BS", "125B", "1590BB", "1590BB2", "1590XX", "1590DD"]


def _muted(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setProperty("muted", True)
    return lab


def _spin(value: float, lo: float, hi: float, step: float = 0.5, suffix: str = " mm", dec: int = 1) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setSuffix(suffix)
    s.setValue(value)
    s.setKeyboardTracking(False)
    return s


# --------------------------------------------------------------------------- new pedal wizard

class PedalWizardDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        from ..pedal.templates import PedalOptions
        self.setWindowTitle("New pedal")
        self.setMinimumWidth(560)
        o = PedalOptions()
        lay = QVBoxLayout(self)
        intro = QLabel("Creates a board shaped for the enclosure, with board-mounted pots at the knob positions, "
                       "panel holes for the footswitch, jacks and DC socket, and (optionally) the usual power, "
                       "bias and LED sections. Everything stays editable.")
        intro.setWordWrap(True)
        intro.setProperty("muted", True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.name = QLineEdit(o.name)
        self.enc = QComboBox()
        for k in ENCLOSURE_KEYS:
            s = CATALOG[k]
            self.enc.addItem(f"{s.name}  ({s.ext[0]:g} × {s.ext[1]:g} × {s.depth:g} mm)", k)
        self.enc.setCurrentIndex(ENCLOSURE_KEYS.index("125B"))
        self.blurb = _muted("")
        self.blurb.setWordWrap(True)
        self.orient = QComboBox()
        self.orient.addItems(["Usual for this box", "Portrait", "Landscape"])
        self.knobs = QSpinBox()
        self.knobs.setRange(0, 8)
        self.knobs.setValue(3)
        self.labels = QLineEdit("LEVEL, TONE, DRIVE")
        self.pot = QComboBox()
        self.pot.addItem("Alpha 16 mm (right-angle PCB)", "pot")
        self.pot.addItem("Alpha 9 mm (vertical PCB)", "pot9")
        self.jacks = QComboBox()
        for text, key in (("Automatic", "auto"), ("Top-mounted (pedalboard friendly)", "top"),
                          ("Side-mounted (input right, output left)", "side")):
            self.jacks.addItem(text, key)
        self.led = QComboBox()
        for text, key in (("3 mm LED on the board", "board3"), ("5 mm LED on the board", "board5"),
                          ("LED in a panel bezel (wired)", "panel"), ("No LED", "none")):
            self.led.addItem(text, key)
        self.color = QComboBox()
        self.color.addItems(list(POWDER_COATS))
        self.power = QCheckBox("Power input: reverse-polarity diode + RC filter")
        self.vref = QCheckBox("4.5 V bias (VREF) for op-amp stages")
        self.pads = QCheckBox("Off-board wire pads (9V, GND, IN, OUT, LED)")
        self.pour = QCheckBox("Ground pour on both layers")
        self.values = QCheckBox("Print part values on the silkscreen (kit style)")
        for cb in (self.power, self.vref, self.pads, self.pour, self.values):
            cb.setChecked(True)
        form.addRow("Name", self.name)
        form.addRow("Enclosure", self.enc)
        form.addRow("", self.blurb)
        form.addRow("Orientation", self.orient)
        form.addRow("Knobs", self.knobs)
        form.addRow("Knob names", self.labels)
        form.addRow("Pots", self.pot)
        form.addRow("Jacks", self.jacks)
        form.addRow("Status LED", self.led)
        form.addRow("Finish", self.color)
        lay.addLayout(form)
        for cb in (self.power, self.vref, self.pads, self.pour, self.values):
            lay.addWidget(cb)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Create pedal")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.enc.currentIndexChanged.connect(self._enc_changed)
        self.knobs.valueChanged.connect(self._knobs_changed)
        self._enc_changed()

    def _enc_changed(self):
        s = CATALOG[self.enc.currentData()]
        self.blurb.setText(f"{s.blurb}  Usable flat area inside the screw bosses {s.usable[0]:g} × {s.usable[1]:g} mm, "
                           f"{s.depth:g} mm deep.")
        if s.key in ("1590LB", "1590A") and self.pot.currentData() == "pot":
            self.pot.setCurrentIndex(1)

    def _knobs_changed(self, n: int):
        names = ["LEVEL", "TONE", "DRIVE", "MID", "BASS", "TREBLE", "BLEND", "GATE"]
        cur = [t.strip() for t in self.labels.text().split(",") if t.strip()]
        cur = (cur + [n2 for n2 in names if n2 not in cur])[:n]
        self.labels.setText(", ".join(cur))

    def options(self):
        from ..pedal.templates import PedalOptions
        labels = [t.strip().upper() for t in self.labels.text().split(",") if t.strip()]
        n = self.knobs.value()
        labels = (labels + [f"KNOB{i + 1}" for i in range(len(labels), n)])[:n]
        orient = {0: "", 1: "portrait", 2: "landscape"}[self.orient.currentIndex()]
        return PedalOptions(name=self.name.text().strip() or "My Pedal", enclosure=self.enc.currentData(),
                            orientation=orient, knobs=labels, pot=self.pot.currentData(),
                            jacks=self.jacks.currentData(), led=self.led.currentData(), power=self.power.isChecked(),
                            vref=self.vref.isChecked(), wire_pads=self.pads.isChecked(), pour=self.pour.isChecked(),
                            silk_values=self.values.isChecked(), color=self.color.currentText())


# --------------------------------------------------------------------------- unfolded enclosure view

class UnfoldedView(QWidget):
    """Interactive drill template: click to select, drag panel holes, double-click to add one."""

    hole_selected = Signal(object)  # uid or None
    add_requested = Signal(str, float, float)  # face, x, y
    status = Signal(str)

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.selected: str | None = None
        self._drag = None
        self.setMouseTracking(True)
        self.setMinimumSize(380, 360)
        self.setFocusPolicy(Qt.StrongFocus)

    # geometry ---------------------------------------------------------------------------
    def enclosure(self) -> Enclosure | None:
        return get_enclosure(self.doc.project)

    def _xf(self, enc: Enclosure):
        from ..pedal.drill import drawing_bounds
        b = drawing_bounds(enc).adjusted(-6, -6, 6, 6)
        s = min(self.width() / b.width(), self.height() / b.height())
        ox = self.width() / 2 - b.center().x() * s
        oy = self.height() / 2 - b.center().y() * s
        return s, ox, oy

    def _to_mm(self, pos) -> QPointF | None:
        enc = self.enclosure()
        if enc is None:
            return None
        s, ox, oy = self._xf(enc)
        return QPointF((pos.x() - ox) / s, (pos.y() - oy) / s)

    def _hit(self, pos):
        enc = self.enclosure()
        pt = self._to_mm(pos)
        if enc is None or pt is None:
            return None
        from ..pedal.drill import to_drawing
        best = None
        for h in all_holes(self.doc.project, enc):
            c = to_drawing(enc, h.face, h.x, h.y)
            d = ((c.x() - pt.x()) ** 2 + (c.y() - pt.y()) ** 2) ** 0.5
            if d <= h.d / 2 + 1.5 and (best is None or d < best[0]):
                best = (d, h)
        return best[1] if best else None

    # painting ---------------------------------------------------------------------------
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.BASE))
        enc = self.enclosure()
        if enc is None:
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(self.rect(), Qt.AlignCenter, "No enclosure yet.\nPick one from the Enclosure list above.")
            return
        from ..pedal.drill import draw_unfolded
        s, ox, oy = self._xf(enc)
        p.translate(ox, oy)
        p.scale(s, s)
        draw_unfolded(p, self.doc.project, enc, selected=self.selected, paper="#f6f3ec", show_coords=s > 3.2)
        p.end()

    # interaction ------------------------------------------------------------------------
    def mousePressEvent(self, ev):
        self.setFocus()
        h = self._hit(ev.position())
        self.selected = h.uid if h else None
        self.hole_selected.emit(self.selected)
        if ev.button() == Qt.RightButton and h is not None and not h.derived:
            menu = QMenu(self)
            menu.addAction("Delete hole", lambda: self._delete(h.uid))
            menu.exec(ev.globalPosition().toPoint())
            return
        if ev.button() == Qt.LeftButton and h is not None:
            if h.derived:
                self.status.emit(f"{h.label}: this hole follows {h.ref} on the board - move the part in the PCB "
                                 "layout to move it.")
            else:
                self.doc.begin("Move panel hole")
                self._drag = h.uid
        self.update()

    def mouseMoveEvent(self, ev):
        enc = self.enclosure()
        pt = self._to_mm(ev.position())
        if enc is None or pt is None:
            return
        from ..pedal.drill import from_drawing
        where = from_drawing(enc, pt)
        if self._drag is not None and where is not None:
            face, x, y = where
            for h in enc.holes:
                if h.uid == self._drag:
                    h.face, h.x, h.y = face, round(x * 2) / 2, round(y * 2) / 2
            set_enclosure(self.doc.project, enc)
            self.doc.live_update()
            self.update()
        if where is not None:
            face, x, y = where
            self.status.emit(f"Side {face} ({FACE_NAMES[face]}):  X {x:+.1f}  Y {y:+.1f} mm from the centre")

    def mouseReleaseEvent(self, ev):
        if self._drag is not None:
            self._drag = None
            self.doc.commit()

    def mouseDoubleClickEvent(self, ev):
        pt = self._to_mm(ev.position())
        enc = self.enclosure()
        if enc is None or pt is None or self._hit(ev.position()) is not None:
            return
        from ..pedal.drill import from_drawing
        where = from_drawing(enc, pt)
        if where:
            self.add_requested.emit(where[0], round(where[1] * 2) / 2, round(where[2] * 2) / 2)

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected:
            self._delete(self.selected)
            return
        super().keyPressEvent(ev)

    def _delete(self, uid: str):
        enc = self.enclosure()
        if enc is None or not any(h.uid == uid for h in enc.holes):
            return
        with self.doc.edit("Delete panel hole"):
            enc.holes = [h for h in enc.holes if h.uid != uid]
            set_enclosure(self.doc.project, enc)
        self.selected = None
        self.hole_selected.emit(None)


# --------------------------------------------------------------------------- enclosure page

class EnclosurePage(QWidget):
    def __init__(self, doc, win, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.win = win
        self._building = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        # row 1: enclosure settings (rows wrap on narrow windows)
        r1 = FlowLayout()
        self.model = QComboBox()
        self.model.addItem("No enclosure", "")
        for k in ENCLOSURE_KEYS:
            self.model.addItem(CATALOG[k].name, k)
        self.orient = QComboBox()
        self.orient.addItems(["Portrait", "Landscape"])
        self.side = QComboBox()
        self.side.addItem("Pots on the bottom side (standard)", "bottom")
        self.side.addItem("Pots on the top side", "top")
        self.standoff = _spin(0.0, 0.0, 40.0, 0.5, " mm")
        self.standoff.setSpecialValueText("auto")
        self.standoff.setToolTip("Distance from the inside of the face to the PCB (auto: from the pots)")
        self.color = QComboBox()
        self.color.addItems(list(POWDER_COATS))
        self.knob_color = QComboBox()
        self.knob_color.addItems(list(KNOB_COLORS))
        self.knob_d = _spin(20.0, 8.0, 40.0, 1.0, " mm", 0)
        self.coat = QCheckBox(f"Powder coat (+{PAINT_ALLOWANCE:g} mm)")
        self.led_hole = QComboBox()
        self.led_hole.addItem("LED bezels", "bezel")
        self.led_hole.addItem("Bare LEDs", "bare")
        for lab, w in (("Enclosure", self.model), ("Orientation", self.orient), ("Board", self.side),
                       ("Standoff", self.standoff), ("Finish", self.color), ("Knobs", self.knob_color),
                       ("Ø", self.knob_d)):
            r1.addGroup(_muted(lab), w)
        r1.addWidget(self.led_hole)
        r1.addWidget(self.coat)
        r1.addStretch(1)
        lay.addLayout(r1)
        # row 2: actions
        r2 = FlowLayout()
        self.add_kind = QComboBox()
        for k, hw in HARDWARE.items():
            self.add_kind.addItem(hw.label, k)
        self.add_face = QComboBox()
        for f in FACES:
            self.add_face.addItem(f"{f} - {FACE_NAMES[f]}", f)
        add = QPushButton("Add hole")
        add.setIcon(icon("drill"))
        dele = QPushButton("Delete")
        r2.addGroup(_muted("Panel hole"), self.add_kind)
        r2.addWidget(self.add_face)
        r2.addWidget(add)
        r2.addWidget(dele)
        r2.addStretch(1)
        btns = {}
        for key, text in (("fit", "Fit board to enclosure"), ("centre", "Centre on board"),
                          ("pdf", "Drill template (PDF)…"), ("tayda", "Tayda coordinates…"),
                          ("bom", "Build sheet…"), ("3d", "Show in 3D")):
            b = QPushButton(text)
            btns[key] = b
            r2.addWidget(b)
        btns["pdf"].setProperty("primary", True)
        btns["pdf"].setIcon(icon("drill"))
        btns["3d"].setIcon(icon("cube"))
        lay.addLayout(r2)
        # body: drawing | table + checks
        split = QSplitter(Qt.Horizontal)
        self.view = UnfoldedView(doc)
        split.addWidget(self.view)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setProperty("muted", True)
        rl.addWidget(self.info)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Side", "Label", "Ø mm", "X mm", "Y mm", "Hardware", "From"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        hh = self.table.horizontalHeader()
        for i in range(7):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        rl.addWidget(self.table, 3)
        crow = QHBoxLayout()
        crow.addWidget(_muted("Enclosure checks"))
        crow.addStretch(1)
        self.check_btn = QPushButton("Re-check")
        crow.addWidget(self.check_btn)
        rl.addLayout(crow)
        self.checks = QTreeWidget()
        self.checks.setHeaderLabels(["", "Problem"])
        self.checks.setRootIsDecorated(False)
        self.checks.header().setSectionResizeMode(1, QHeaderView.Stretch)
        rl.addWidget(self.checks, 2)
        split.addWidget(right)
        split.setSizes([620, 520])
        lay.addWidget(split, 1)
        self.hint = _muted("Drag panel holes to move them · double-click a side to add the selected hole type there · "
                           "holes from board parts follow the parts · coordinates are Tayda's: mm from each side's "
                           "centre, seen from outside")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        # wiring
        self.model.currentIndexChanged.connect(self._model_changed)
        for w in (self.orient, self.side, self.color, self.knob_color, self.led_hole):
            w.currentIndexChanged.connect(self._settings_changed)
        for w in (self.standoff, self.knob_d):
            w.valueChanged.connect(self._settings_changed)
        self.coat.toggled.connect(self._settings_changed)
        add.clicked.connect(self._add_default)
        dele.clicked.connect(lambda: self.view.selected and self.view._delete(self.view.selected))
        btns["fit"].clicked.connect(lambda: fit_board(self.win))
        btns["centre"].clicked.connect(self._centre)
        btns["pdf"].clicked.connect(lambda: export_drill_pdf(self.win))
        btns["tayda"].clicked.connect(lambda: export_tayda(self.win))
        btns["bom"].clicked.connect(lambda: export_build_sheet(self.win))
        btns["3d"].clicked.connect(lambda: show_pedal_3d(self.win))
        self.check_btn.clicked.connect(self.refresh_checks)
        self.view.hole_selected.connect(self._select_row)
        self.view.add_requested.connect(self._add_at)
        self.view.status.connect(lambda m: self.win.statusBar().showMessage(m, 4000))
        self.table.itemChanged.connect(self._item_changed)
        self.table.itemSelectionChanged.connect(self._row_selected)
        self.checks.itemActivated.connect(self._goto_check)
        self.checks.itemClicked.connect(self._goto_check)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.refresh)
        doc.changed.connect(self._schedule)
        doc.replaced.connect(self._schedule)
        self.refresh()

    # ------------------------------------------------------------------ sync
    def _schedule(self):
        if self.isVisible():
            self._timer.start()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.refresh()

    def refresh(self):
        enc = get_enclosure(self.doc.project)
        self._building = True
        try:
            self.model.setCurrentIndex(max(0, self.model.findData(enc.model if enc else "")))
            for w in (self.orient, self.side, self.standoff, self.color, self.knob_color, self.knob_d, self.coat,
                      self.led_hole):
                w.setEnabled(enc is not None)
            if enc is not None:
                self.orient.setCurrentIndex(1 if enc.landscape else 0)
                self.side.setCurrentIndex(max(0, self.side.findData(enc.face_side)))
                if not self.standoff.hasFocus():
                    self.standoff.setValue(enc.standoff)
                self.color.setCurrentText(enc.color)
                self.knob_color.setCurrentText(enc.knob_color)
                if not self.knob_d.hasFocus():
                    self.knob_d.setValue(enc.knob_d)
                self.coat.setChecked(enc.paint_allowance > 0)
                self.led_hole.setCurrentIndex(max(0, self.led_hole.findData(enc.led_hole)))
            self._fill_table(enc)
            self._fill_info(enc)
        finally:
            self._building = False
        self.view.update()
        self.refresh_checks()

    def _fill_info(self, enc):
        if enc is None:
            self.info.setText("Choose an enclosure to see the board inside it, place panel holes and print a drill "
                              "template.")
            return
        p = self.doc.project
        near, far = enc.z_levels(p)
        s = enc.spec
        mirrored = ("The layout is seen from the component side, so left and right are swapped on the face."
                    if enc.face_side == "bottom" else "")
        self.info.setText(f"<b>{s.name}</b> · face {enc.face_size[0]:g} × {enc.face_size[1]:g} mm · {s.depth:g} mm deep"
                          f"<br>Board {enc.resolved_standoff(p):.1f} mm behind the face · {enc.free_depth(p):.1f} mm free "
                          f"for parts below it. {mirrored}")

    def _fill_table(self, enc):
        self.table.blockSignals(True)
        holes = all_holes(self.doc.project, enc) if enc else []
        self.table.setRowCount(len(holes))
        for r, h in enumerate(holes):
            vals = [h.face, h.label, f"{h.d:g}", f"{_z(h.x):.2f}", f"{_z(h.y):.2f}", h.hardware.label, h.ref or "panel"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setData(Qt.UserRole, h.uid)
                editable = not h.derived and c in (0, 1, 2, 3, 4)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | (Qt.ItemIsEditable if editable else Qt.NoItemFlags))
                if h.derived:
                    it.setForeground(QColor(theme.TEXT_DIM))
                self.table.setItem(r, c, it)
        self.table.blockSignals(False)

    def refresh_checks(self):
        self.checks.clear()
        if get_enclosure(self.doc.project) is None:
            return
        from ..pedal.checks import run_pedal_checks
        try:
            viol = run_pedal_checks(self.doc.project)
        except Exception as e:  # never let a check crash the page
            viol = []
            self.checks.addTopLevelItem(QTreeWidgetItem(["!", f"Check failed: {e}"]))
        if not viol:
            it = QTreeWidgetItem(["✔", "Everything fits: board, parts, knobs and jacks clear each other"])
            it.setForeground(0, QColor(theme.GOOD))
            self.checks.addTopLevelItem(it)
        for v in viol:
            it = QTreeWidgetItem(["●", v.message])
            it.setForeground(0, QColor(theme.BAD if v.severity == "error" else theme.WARN))
            it.setToolTip(1, v.message)
            it.setData(0, Qt.UserRole, v)
            self.checks.addTopLevelItem(it)
        self.checks.resizeColumnToContents(0)

    # ------------------------------------------------------------------ edits
    def _edit(self, label, fn):
        if self._building:
            return
        enc = get_enclosure(self.doc.project)
        if enc is None:
            return
        with self.doc.edit(label):
            fn(enc)
            set_enclosure(self.doc.project, enc)
        self.refresh()

    def _model_changed(self):
        if self._building:
            return
        key = self.model.currentData()
        p = self.doc.project
        enc = get_enclosure(p)
        with self.doc.edit("Enclosure"):
            if not key:
                set_enclosure(p, None)
            else:
                if enc is None:
                    enc = Enclosure(key)
                    centre_on_board(p, enc)
                else:
                    enc.model = key
                    enc.orientation = ""
                set_enclosure(p, enc)

    def _settings_changed(self, *_):
        def apply(enc: Enclosure):
            enc.orientation = "landscape" if self.orient.currentIndex() == 1 else "portrait"
            enc.face_side = self.side.currentData()
            enc.standoff = self.standoff.value()
            enc.color = self.color.currentText()
            enc.knob_color = self.knob_color.currentText()
            enc.knob_d = self.knob_d.value()
            enc.paint_allowance = PAINT_ALLOWANCE if self.coat.isChecked() else 0.0
            enc.led_hole = self.led_hole.currentData()
        self._edit("Enclosure settings", apply)

    def _centre(self):
        self._edit("Centre enclosure", lambda enc: centre_on_board(self.doc.project, enc))

    def _add_default(self):
        kind = self.add_kind.currentData()
        face = self.add_face.currentData()
        if face not in HARDWARE[kind].faces and HARDWARE[kind].faces != "ABCDE":
            face = HARDWARE[kind].faces[0]
        self._add_at(face, 0.0, 0.0)

    def _add_at(self, face: str, x: float, y: float):
        kind = self.add_kind.currentData()
        h = PanelHole.of(kind, face, x, y)
        self._edit("Add panel hole", lambda enc: enc.holes.append(h))
        self.view.selected = h.uid
        self.view.update()
        self._select_row(h.uid)

    def _item_changed(self, item: QTableWidgetItem):
        uid = item.data(Qt.UserRole)
        col = item.column()
        text = item.text().strip()

        def apply(enc: Enclosure):
            for h in enc.holes:
                if h.uid != uid:
                    continue
                try:
                    if col == 0 and text.upper() in FACES:
                        h.face = text.upper()
                    elif col == 1:
                        h.label = text
                    elif col == 2:
                        h.d = max(0.5, float(text))
                    elif col == 3:
                        h.x = float(text)
                    elif col == 4:
                        h.y = float(text)
                except ValueError:
                    pass
        self._edit("Edit panel hole", apply)

    def _select_row(self, uid):
        self.table.blockSignals(True)
        self.table.clearSelection()
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it is not None and it.data(Qt.UserRole) == uid:
                self.table.selectRow(r)
                break
        self.table.blockSignals(False)

    def _row_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if rows:
            it = self.table.item(rows[0].row(), 0)
            self.view.selected = it.data(Qt.UserRole) if it else None
            self.view.update()

    def _goto_check(self, item, _col=0):
        v = item.data(0, Qt.UserRole)
        if v is None:
            return
        self.win.tabs.setCurrentWidget(self.win.canvas)
        self.win._goto_violation(v)


# --------------------------------------------------------------------------- layout overlay

ENC_COLOR = QColor(86, 180, 233)
BOSS_COLOR = QColor(230, 159, 0)
KEEP_COLOR = QColor(240, 96, 93)


def _cos_pen(color, w=1.2, style=Qt.SolidLine) -> QPen:
    pen = QPen(color, w, style)
    pen.setCosmetic(True)
    return pen


def _geom_path(g) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.OddEvenFill)
    for poly in iter_polygons(g):
        path.addPolygon(QPolygonF([QPointF(x, y) for x, y in poly.exterior.coords]))
        for ring in poly.interiors:
            path.addPolygon(QPolygonF([QPointF(x, y) for x, y in ring.coords]))
    return path


def paint_enclosure_overlay(canvas, p: QPainter) -> None:
    """Draw the enclosure cavity, screw bosses and panel hardware keep-outs on the PCB layout (board coords)."""
    if not canvas.visible.get("Enclosure", True):
        return
    proj = canvas.doc.project
    enc = get_enclosure(proj)
    if enc is None:
        return
    from shapely.geometry import Point
    from ..pedal.checks import _overlap, _side_body
    p.save()
    p.setBrush(Qt.NoBrush)
    p.setPen(_cos_pen(QColor(140, 146, 160), 1.0, Qt.DotLine))
    p.drawPath(_geom_path(enc.geom_to_board(enc.face_polygon())))
    p.setPen(_cos_pen(ENC_COLOR, 1.4))
    p.drawPath(_geom_path(enc.geom_to_board(enc.cavity_polygon())))
    boss = QColor(BOSS_COLOR)
    boss.setAlpha(70)
    p.setPen(_cos_pen(BOSS_COLOR, 1.0))
    p.setBrush(boss)
    for b in enc.boss_polygons():
        p.drawPath(_geom_path(enc.geom_to_board(b)))
    near, far = enc.z_levels(proj)
    labels = []
    for h in all_holes(proj, enc):
        r_body, _, outer = h.effective_body()
        if h.face == "A":
            c = enc.geom_to_board(Point(h.x, h.y))
            cx, cy = c.x, c.y
            if not h.derived and r_body > 0:  # panel part hanging behind the face: keep the board clear
                keep = QColor(KEEP_COLOR)
                keep.setAlpha(36)
                p.setBrush(keep)
                p.setPen(_cos_pen(KEEP_COLOR, 1.0, Qt.DashLine))
                p.drawEllipse(QPointF(cx, cy), r_body, r_body)
            if outer > 0:
                p.setBrush(Qt.NoBrush)
                p.setPen(_cos_pen(QColor(170, 176, 190, 150), 1.0, Qt.DashLine))
                p.drawEllipse(QPointF(cx, cy), outer / 2, outer / 2)
            p.setPen(_cos_pen(ENC_COLOR, 1.3))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), h.d / 2, h.d / 2)
            p.drawLine(QPointF(cx - h.d / 2 - 1, cy), QPointF(cx + h.d / 2 + 1, cy))
            p.drawLine(QPointF(cx, cy - h.d / 2 - 1), QPointF(cx, cy + h.d / 2 + 1))
            if not h.derived:
                labels.append((cx, cy + max(r_body, h.d / 2) + 1.5, h.label))
        else:
            rect, zr = _side_body(enc, h)
            hits = _overlap(zr, (near, far)) or _overlap(zr, (far, far + 12.0))
            col = QColor(KEEP_COLOR if hits else QColor(140, 146, 160))
            col.setAlpha(40 if hits else 25)
            p.setBrush(col)
            p.setPen(_cos_pen(KEEP_COLOR if hits else QColor(140, 146, 160), 1.0, Qt.DashLine))
            p.drawPath(_geom_path(enc.geom_to_board(rect)))
            u, v, _z = hole_face_point(enc, h)
            bx, by = enc.face_to_board(u, v)
            labels.append((bx, by, f"{h.label} ({h.face}, {_z:.0f} mm deep)"))
    # wall names (mirrored with the layout when the face sees the bottom of the board)
    W, H = enc.face_size
    for face, (u, v) in (("B", (0, H / 2 + 2.5)), ("D", (0, -H / 2 - 2.5)), ("C", (-W / 2 - 2.5, 0)),
                         ("E", (W / 2 + 2.5, 0))):
        x, y = enc.face_to_board(u, v)
        labels.append((x, y, f"{face} · {FACE_NAMES[face].lower()}"))
    p.restore()
    # screen-space text
    p.save()
    p.resetTransform()
    f = QFont("Segoe UI")
    f.setPixelSize(11)
    p.setFont(f)
    for x, y, text in labels:
        sp = canvas.to_screen(x, y)
        p.setPen(QColor(150, 200, 240))
        p.drawText(QRectF(sp.x() - 150, sp.y() - 8, 300, 16), Qt.AlignCenter, text)
    note = f"{enc.spec.name}"
    if enc.face_side == "bottom":
        note += " · pots under the board: the face is the mirror image of this view"
    p.setPen(QColor(150, 200, 240))
    p.drawText(QRectF(14, 10, 900, 18), Qt.AlignLeft | Qt.AlignVCenter, note)
    p.restore()


# --------------------------------------------------------------------------- commands

def new_pedal(win) -> None:
    if not win._confirm_discard():
        return
    dlg = PedalWizardDialog(win)
    if not dlg.exec():
        return
    from ..pedal.templates import new_pedal_project
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        project, notes = new_pedal_project(dlg.options())
    finally:
        QApplication.restoreOverrideCursor()
    win.doc.set_project(project)
    win.canvas.drc_markers = []
    _set_grid(win, 1.27)
    win.tabs.setCurrentWidget(win.canvas)
    win.canvas.fit_board()
    msg = ("Your pedal board is ready. Add the effect circuit from the Library (Pedal parts) and use the Connect tool "
           "(N) to wire it up; the Enclosure tab shows the drill template.")
    if notes:
        QMessageBox.information(win, "New pedal", msg + "\n\nNotes:\n• " + "\n• ".join(notes))
    else:
        win.statusBar().showMessage(msg, 12000)


def _set_grid(win, value: float) -> None:
    combo = getattr(win, "grid_combo", None)
    if combo is None:
        return
    for i in range(combo.count()):
        if abs(combo.itemData(i) - value) < 1e-6:
            combo.setCurrentIndex(i)
            return


def example_path() -> Path:
    from ..examples import EXAMPLE_DIR
    return EXAMPLE_DIR / EXAMPLE_NAME


def open_pedal_example(win) -> None:
    if not win._confirm_discard():
        return
    path = example_path()
    if path.exists():
        from ..examples import load_example
        project = load_example(path)
    else:
        from ..pedal.examples import overdrive_example
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            project = overdrive_example()
        finally:
            QApplication.restoreOverrideCursor()
    win.doc.set_project(project)
    win.canvas.drc_markers = []
    _set_grid(win, 1.27)
    win.canvas.fit_board()


def show_enclosure_tab(win) -> None:
    win.tabs.setCurrentWidget(win.enclosure_page)


def add_enclosure(win) -> None:
    p = win.doc.project
    if get_enclosure(p) is None:
        enc = Enclosure("125B")
        centre_on_board(p, enc)
        with win.doc.edit("Add enclosure"):
            set_enclosure(p, enc)
    show_enclosure_tab(win)


def fit_board(win) -> None:
    p = win.doc.project
    enc = get_enclosure(p)
    if enc is None:
        QMessageBox.information(win, "Fit board", "Choose an enclosure first (Pedal ▸ Enclosure && drilling).")
        return
    v_bottom = None
    for h in enc.holes:
        if h.face == "A" and h.kind == "footswitch":
            r, _, _ = h.effective_body()
            v_bottom = max(v_bottom or -1e9, h.y + r + 2.0)
    outline = fit_outline(enc, v_bottom=v_bottom)
    if len(outline) < 3:
        QMessageBox.warning(win, "Fit board", "There is no room for a board above the footswitch.")
        return
    with win.doc.edit("Fit board to enclosure"):
        p.board.outline = outline
        for z in p.zones:
            if z.net == "GND" and len(z.outline) >= 3:
                z.outline = list(outline)
    win.canvas.fit_board()


def insert_block(win, name: str) -> None:
    from ..pedal.templates import BLOCKS, insert_block as _insert, parts_region
    p = win.doc.project
    fn = BLOCKS[name]
    parts = fn()
    with win.doc.edit(f"Insert {name}"):
        placed = _insert(p, parts, parts_region(p, "top"), "top")
    if len(placed) < len(parts):
        QMessageBox.information(win, "Insert circuit block", f"Placed {len(placed)} of {len(parts)} parts; there was no "
                                "free room for the rest. Make space and insert the block again.")
    win.doc.set_selection(placed)
    win.tabs.setCurrentWidget(win.canvas)


def set_values_on_silk(win, on: bool) -> None:
    p = win.doc.project
    with win.doc.edit("Silkscreen values"):
        for c in p.components:
            if c.footprint.model.get("type", "auto") != "none" and not c.ref.upper().startswith(("H", "FID", "TP")):
                c.show_value = on


def _ask_path(win, title, suffix, filt) -> str | None:
    start = str(win._last_dir() / (win.doc.project.name.replace(" ", "_") + suffix))
    path, _ = QFileDialog.getSaveFileName(win, title, start, filt)
    return path or None


def _need_enclosure(win) -> bool:
    if get_enclosure(win.doc.project) is None:
        QMessageBox.information(win, "Enclosure", "This design has no enclosure yet. Pick one in the Enclosure tab.")
        show_enclosure_tab(win)
        return False
    return True


def export_drill_pdf(win) -> None:
    if not _need_enclosure(win):
        return
    path = _ask_path(win, "Export drill template", "_drill_template.pdf", "PDF (*.pdf)")
    if not path:
        return
    from ..pedal.drill import export_pdf
    from PySide6.QtCore import QLocale
    page = "letter" if QLocale().measurementSystem() == QLocale.ImperialUSSystem else "a4"
    try:
        export_pdf(win.doc.project, path, page)
    except Exception as e:
        QMessageBox.critical(win, "Drill template", f"Could not write {path}:\n{e}")
        return
    win.statusBar().showMessage(f"Drill template written: {path} - print it at 100 % scale", 10000)
    _open(path)


def export_tayda(win) -> None:
    if not _need_enclosure(win):
        return
    path = _ask_path(win, "Export Tayda drill coordinates", "_tayda.txt", "Text (*.txt);;CSV (*.csv)")
    if not path:
        return
    from ..pedal.drill import tayda_csv, tayda_text
    text = tayda_csv(win.doc.project) if path.lower().endswith(".csv") else tayda_text(win.doc.project)
    Path(path).write_text(text, encoding="utf-8")
    win.statusBar().showMessage(f"Drill coordinates written: {path}", 8000)


def export_build_sheet(win) -> None:
    path = _ask_path(win, "Export build sheet", "_build_sheet.csv", "CSV (*.csv);;Text (*.txt)")
    if not path:
        return
    from ..pedal.bom import pedal_bom_csv, pedal_bom_text
    text = pedal_bom_text(win.doc.project) if path.lower().endswith(".txt") else pedal_bom_csv(win.doc.project)
    Path(path).write_text(text, encoding="utf-8")
    win.statusBar().showMessage(f"Build sheet written: {path}", 8000)


def show_pedal_3d(win) -> None:
    page = win.page3d
    if hasattr(page, "pedal_cb"):
        page.pedal_cb.setChecked(True)
    else:
        page.view.set_show_enclosure(True)
    win.tabs.setCurrentWidget(page)
    QTimer.singleShot(50, lambda: page.view.set_view("pedal"))


def _open(path: str) -> None:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


# --------------------------------------------------------------------------- installation

def install(win) -> None:
    """Add the pedal features to a MainWindow."""
    win.enclosure_page = EnclosurePage(win.doc, win)
    idx = win.tabs.indexOf(win.page3d) + 1
    win.tabs.insertTab(idx, win.enclosure_page, icon("drill"), "Enclosure && Drilling")
    win.canvas.world_overlays.append(lambda p: paint_enclosure_overlay(win.canvas, p))
    m = QMenu("&Pedal", win)
    m.addAction(icon("pedal"), "&New pedal…", lambda: new_pedal(win)).setShortcut(QKeySequence("Ctrl+Shift+N"))
    m.addAction(icon("pedal"), "Open example: three-knob overdrive", lambda: open_pedal_example(win))
    m.addSeparator()
    m.addAction(icon("drill"), "&Enclosure && drilling", lambda: add_enclosure(win))
    m.addAction("&Fit board outline to the enclosure", lambda: fit_board(win))
    blocks = m.addMenu("Insert circuit &block")
    from ..pedal.templates import BLOCKS
    for name in BLOCKS:
        blocks.addAction(name, lambda n=name: insert_block(win, n))
    silk = m.addMenu("&Silkscreen")
    silk.addAction("Print part values on all parts", lambda: set_values_on_silk(win, True))
    silk.addAction("Remove part values", lambda: set_values_on_silk(win, False))
    m.addSeparator()
    m.addAction(icon("drill"), "Export &drill template (PDF)…", lambda: export_drill_pdf(win))
    m.addAction("Export &Tayda drill coordinates…", lambda: export_tayda(win))
    m.addAction("Export &build sheet (BOM)…", lambda: export_build_sheet(win))
    m.addSeparator()
    m.addAction(icon("cube"), "Show the pedal in &3D", lambda: show_pedal_3d(win))
    m.addAction(icon("drc"), "Run DRC with enclosure &checks", win.run_drc)
    mb = win.menuBar()
    before = next((a for a in mb.actions() if a.text().replace("&", "") == "Tools"), None)
    if before is not None:
        mb.insertMenu(before, m)
    else:
        mb.addMenu(m)
    win.pedal_menu = m
