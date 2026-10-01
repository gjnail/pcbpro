"""Dockable side panels: library, properties, layers, nets and DRC results."""
from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..model.board import (FINISHES, MASK_COLORS, SILK_COLORS, Component, Footprint, Text, Track, Via, Zone,
                           natural_key)
from ..model.connectivity import get_connectivity
from ..model.footprints import LIBRARY, LibPart
from . import theme
from .canvas import LAYER_COLORS, THT_COLOR, pad_qpath
from .icons import icon


# --------------------------------------------------------------------------- footprint preview

class FootprintPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.fp: Footprint | None = None
        self.setMinimumHeight(150)

    def set_footprint(self, fp: Footprint | None):
        self.fp = fp
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(13, 15, 19))
        if self.fp is None:
            return
        x0, y0, x1, y1 = self.fp.courtyard
        w, h = max(x1 - x0, 0.5), max(y1 - y0, 0.5)
        s = min((self.width() - 30) / w, (self.height() - 30) / h)
        p.translate(self.width() / 2, self.height() / 2)
        p.scale(s, s)
        p.translate(-(x0 + x1) / 2, -(y0 + y1) / 2)
        p.setPen(Qt.NoPen)
        for pad in self.fp.pads:
            p.save()
            p.translate(pad.x, pad.y)
            p.rotate(-pad.rotation)
            p.setBrush(THT_COLOR if pad.kind == "tht" else (QColor(40, 40, 40) if pad.kind == "npth" else LAYER_COLORS["F.Cu"]))
            p.drawPath(pad_qpath(pad))
            if pad.drill:
                p.setBrush(QColor(13, 15, 19))
                if pad.is_slot:
                    dw, dh = pad.drill, pad.drill_h
                    r = min(dw, dh) / 2
                    p.drawRoundedRect(QRectF(-dw / 2, -dh / 2, dw, dh), r, r)
                else:
                    p.drawEllipse(QPointF(0, 0), pad.drill / 2, pad.drill / 2)
            p.restore()
        pen = QPen(LAYER_COLORS["F.SilkS"], 0.12)
        for g in self.fp.graphics:
            if g.layer != "silk":
                continue
            pen.setWidthF(g.width)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            if g.kind == "line":
                (a, b), (c, d) = g.pts
                p.drawLine(QPointF(a, b), QPointF(c, d))
            elif g.kind == "circle":
                (cx, cy), = g.pts
                if g.fill:
                    p.setBrush(LAYER_COLORS["F.SilkS"])
                p.drawEllipse(QPointF(cx, cy), g.r, g.r)
            elif g.kind == "arc":
                (cx, cy), = g.pts
                p.drawArc(QRectF(cx - g.r, cy - g.r, 2 * g.r, 2 * g.r), int(g.start * 16), int(g.sweep * 16))
            elif g.kind == "poly":
                if g.fill:
                    p.setBrush(LAYER_COLORS["F.SilkS"])
                p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in g.pts]))
        cp = QPen(QColor(255, 70, 200, 150), 1.0, Qt.DashLine)
        cp.setCosmetic(True)
        p.setPen(cp)
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))
        p.end()


_PLACEHOLDER = "__lazy__"
SOURCE_BADGE = {"catalog": "MPN", "user": "mine", "lcsc": "LCSC", "kicad": "KiCad", "builtin": ""}


class LibraryPanel(QWidget):
    """Browse / search every part source: built-in footprints, the MPN catalogue, My library and KiCad."""

    place_requested = Signal(object)  # LibPart
    action_requested = Signal(str)  # lcsc | kicad | kicad_file | wizard | folder | reload
    delete_requested = Signal(object)  # LibPart (user library)

    def __init__(self, index, parent=None):
        super().__init__(parent)
        from ..library.index import SOURCES
        self.index = index
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search: 0805, NE555, soic 8, usb-c, jst ph 4…")
        self.search.setClearButtonEnabled(True)
        row.addWidget(self.search, 1)
        from PySide6.QtWidgets import QMenu, QToolButton
        self.add_btn = QToolButton()
        self.add_btn.setText("Add parts")
        self.add_btn.setIcon(icon("new"))
        self.add_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.add_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.add_btn)
        for key, text in (("lcsc", "Import any LCSC / JLCPCB part (C-number)…"),
                          ("kicad", "KiCad libraries (add folder / download official)…"),
                          ("kicad_file", "Import KiCad footprint file (.kicad_mod)…"),
                          ("wizard", "Create footprint with the wizard…"), (None, None),
                          ("folder", "Open My library folder"), ("reload", "Reload libraries")):
            if key is None:
                menu.addSeparator()
            else:
                menu.addAction(text, lambda k=key: self.action_requested.emit(k))
        self.add_btn.setMenu(menu)
        row.addWidget(self.add_btn)
        lay.addLayout(row)
        self.source = QComboBox()
        for key, text in SOURCES.items():
            self.source.addItem(text, key)
        lay.addWidget(self.source)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        lay.addWidget(self.tree, 1)
        self.count = QLabel()
        self.count.setProperty("muted", True)
        self.count.setWordWrap(True)
        lay.addWidget(self.count)
        self.preview = FootprintPreview()
        lay.addWidget(self.preview)
        self.desc = QLabel()
        self.desc.setWordWrap(True)
        self.desc.setProperty("muted", True)
        self.desc.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.desc)
        self.place_btn = QPushButton("Place component")
        self.place_btn.setProperty("primary", True)
        self.place_btn.setIcon(icon("place"))
        lay.addWidget(self.place_btn)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(160)
        self._timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda _t: self._timer.start())
        self.source.currentIndexChanged.connect(lambda _i: self.refresh())
        self.tree.currentItemChanged.connect(self._on_current)
        self.tree.itemExpanded.connect(self._expand)
        self.tree.itemDoubleClicked.connect(lambda it, col: self._place())
        self.tree.customContextMenuRequested.connect(self._context)
        self.place_btn.clicked.connect(self._place)
        self.refresh()

    # ------------------------------------------------------------------ population
    def refresh(self):
        q = self.search.text().strip()
        src = self.source.currentData()
        self.tree.clear()
        if q:
            results = self.index.search(q, src, limit=600)
            for part in results:
                self.tree.addTopLevelItem(self._part_item(part, show_category=True))
            more = " (showing first 600 — refine the search)" if len(results) >= 600 else ""
            self.count.setText(f"{len(results):,} matches{more}")
            if results:
                self.tree.setCurrentItem(self.tree.topLevelItem(0))
        else:
            tree = self.index.tree(src)
            for top, subs in tree.items():
                n = sum(len(v) for v in subs.values())
                it = QTreeWidgetItem([top, f"{n:,}"])
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
                it.setData(0, Qt.UserRole + 1, ("top", src, top))
                it.addChild(QTreeWidgetItem([_PLACEHOLDER]))
                self.tree.addTopLevelItem(it)
            c = self.index.counts()
            self.count.setText(f"{c['builtin']:,} footprints · {c['catalog']:,} catalog parts · {c['user']:,} mine · "
                               f"{c['kicad']:,} KiCad  —  plus any LCSC part via Add parts")

    def _part_item(self, part, show_category=False) -> QTreeWidgetItem:
        badge = SOURCE_BADGE.get(part.source, "")
        info = part.category.split("/")[-1] if show_category else ""
        it = QTreeWidgetItem([part.name, " · ".join(x for x in (badge, info) if x)])
        it.setData(0, Qt.UserRole, part)
        tip = part.description or part.keywords
        if part.manufacturer:
            tip = f"{part.manufacturer} — {tip}"
        it.setToolTip(0, tip)
        return it

    def _expand(self, item):
        if item.childCount() != 1 or item.child(0).text(0) != _PLACEHOLDER:
            return
        item.takeChild(0)
        kind, src, top, *rest = item.data(0, Qt.UserRole + 1)
        subs = self.index.tree(src).get(top, {})
        if kind == "top":
            for sub, parts in subs.items():
                if sub == "":
                    for p in parts:
                        item.addChild(self._part_item(p))
                    continue
                child = QTreeWidgetItem([sub, f"{len(parts):,}"])
                child.setData(0, Qt.UserRole + 1, ("sub", src, top, sub))
                child.addChild(QTreeWidgetItem([_PLACEHOLDER]))
                item.addChild(child)
        else:
            for p in subs.get(rest[0], []):
                item.addChild(self._part_item(p))

    # ------------------------------------------------------------------ selection
    def current_part(self):
        cur = self.tree.currentItem()
        return cur.data(0, Qt.UserRole) if cur else None

    def _on_current(self, cur, prev):
        part: LibPart | None = cur.data(0, Qt.UserRole) if cur else None
        if part is None:
            self.preview.set_footprint(None)
            self.desc.setText("")
            return
        try:
            fp = part.make()
        except Exception as e:
            self.preview.set_footprint(None)
            self.desc.setText(f"<span style='color:{theme.BAD}'>Could not load footprint: {e}</span>")
            return
        self.preview.set_footprint(fp)
        lines = [f"<b>{part.name}</b>"]
        if part.manufacturer or part.mpn:
            lines.append(f"{part.mpn} · {part.manufacturer}".strip(" ·"))
        lines.append(part.description or fp.description)
        extra = f"Footprint {fp.name} · {len(fp.pads)} pads · default value {part.value}"
        if part.lcsc:
            extra += f" · LCSC {part.lcsc}"
        lines.append(extra)
        from ..library.verify import REFERENCES
        if part.name in REFERENCES or part.source == "kicad":
            ref = REFERENCES.get(part.name, part.name)
            lines.append(f"<span style='color:{theme.GOOD}'>✔ Land pattern verified against the datasheet-derived "
                         f"KiCad footprint {ref}</span>")
        elif "Verify against" in fp.description or part.source in ("lcsc", "user"):
            lines.append(f"<span style='color:{theme.WARN}'>Right-click › Check against KiCad footprint to compare "
                         f"this land pattern with a reference</span>")
        self.desc.setText("<br>".join(lines))

    def _place(self):
        part = self.current_part()
        if part is not None:
            self.place_requested.emit(part)

    def select_part(self, name: str):
        self.search.setText(name)
        self.refresh()

    def _context(self, pos):
        it = self.tree.itemAt(pos)
        part = it.data(0, Qt.UserRole) if it else None
        if part is None:
            return
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.addAction("Place", lambda: self.place_requested.emit(part))
        menu.addAction("Check against KiCad footprint (datasheet)…", lambda: self.action_requested.emit("compare"))
        if part.source in ("user", "lcsc") and getattr(part, "path", None):
            menu.addAction("Delete from My library", lambda: self.delete_requested.emit(part))
        menu.exec(QCursor.pos())


# --------------------------------------------------------------------------- properties

def _spin(value, lo=-10000.0, hi=10000.0, step=0.1, decimals=3, suffix=" mm") -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setSuffix(suffix)
    s.setValue(value)
    s.setKeyboardTracking(False)
    s.setButtonSymbols(QDoubleSpinBox.NoButtons)
    return s


class PropertiesPanel(QScrollArea):
    def __init__(self, doc, canvas, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.canvas = canvas
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self._refreshers = []
        self._building = False
        doc.selection_changed.connect(self.rebuild)
        doc.replaced.connect(self.rebuild)
        doc.changed.connect(self.refresh)
        self.rebuild()

    # helpers -----------------------------------------------------------------
    def _edit(self, label, fn):
        if self._building:
            return
        with self.doc.edit(label):
            fn()

    def _row_float(self, form, label, getter, setter, **kw):
        w = _spin(getter(), **kw)
        w.valueChanged.connect(lambda v: self._edit(f"Change {label}", lambda: setter(v)))
        self._refreshers.append(lambda: (not w.hasFocus()) and _set_quiet(w, getter()))
        form.addRow(label, w)
        return w

    def _row_text(self, form, label, getter, setter):
        w = QLineEdit(getter())
        w.editingFinished.connect(lambda: getter() != w.text() and self._edit(f"Change {label}", lambda: setter(w.text())))
        self._refreshers.append(lambda: (not w.hasFocus()) and w.text() != getter() and w.setText(getter()))
        form.addRow(label, w)
        return w

    def _row_combo(self, form, label, options, getter, setter, editable=False):
        w = QComboBox()
        w.setEditable(editable)
        w.addItems(options)
        cur = getter()
        if cur not in options and cur is not None:
            w.addItem(str(cur))
        w.setCurrentText("" if cur is None else str(cur))
        sig = w.currentTextChanged if not editable else w.lineEdit().editingFinished
        if editable:
            w.activated.connect(lambda i: self._combo_commit(label, w, getter, setter))
            sig.connect(lambda: self._combo_commit(label, w, getter, setter))
        else:
            sig.connect(lambda t: self._edit(f"Change {label}", lambda: setter(t)))
        form.addRow(label, w)
        return w

    def _combo_commit(self, label, w, getter, setter):
        t = w.currentText().strip()
        if (getter() or "") != t:
            self._edit(f"Change {label}", lambda: setter(t or None))

    def _row_check(self, form, label, getter, setter):
        w = QCheckBox()
        w.setChecked(bool(getter()))
        w.toggled.connect(lambda v: self._edit(f"Change {label}", lambda: setter(v)))
        form.addRow(label, w)
        return w

    def _header(self, lay, title, subtitle=""):
        t = QLabel(title)
        t.setProperty("heading", True)
        lay.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setProperty("muted", True)
            s.setWordWrap(True)
            lay.addWidget(s)

    def refresh(self):
        if self.doc.in_transaction:
            pass
        self._building = True
        try:
            for r in self._refreshers:
                try:
                    r()
                except RuntimeError:
                    pass
        finally:
            self._building = False

    def rebuild(self):
        self._building = True
        self._refreshers = []
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        sel = self.doc.selection
        try:
            if not sel:
                self._build_board(lay)
            elif len(sel) > 1:
                self._header(lay, f"{len(sel)} items selected")
                kinds = OrderedDict()
                for it in sel:
                    kinds[type(it).__name__] = kinds.get(type(it).__name__, 0) + 1
                lab = QLabel("<br>".join(f"{n} × {k}" for k, n in kinds.items()))
                lay.addWidget(lab)
                tracks = [s for s in sel if isinstance(s, Track)]
                if tracks:
                    form = QFormLayout()
                    self._row_float(form, "Track width", lambda: tracks[0].width,
                                    lambda v: [setattr(t, "width", v) for t in tracks], lo=0.05, hi=20, step=0.05)
                    lay.addLayout(form)
            else:
                it = sel[0]
                if isinstance(it, Component):
                    self._build_component(lay, it)
                elif isinstance(it, Track):
                    self._build_track(lay, it)
                elif isinstance(it, Via):
                    self._build_via(lay, it)
                elif isinstance(it, Zone):
                    self._build_zone(lay, it)
                elif isinstance(it, Text):
                    self._build_text(lay, it)
        finally:
            self._building = False
        lay.addStretch(1)
        self.setWidget(root)

    def _nets(self):
        return [""] + self.doc.project.nets()

    def _build_component(self, lay, c: Component):
        self._header(lay, f"{c.ref}  ·  {c.value}", f"{c.footprint.name} — {c.footprint.description}")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self._row_text(form, "Reference", lambda: c.ref, lambda v: setattr(c, "ref", v.strip() or c.ref))
        std = standard_values(c.ref)
        if std:
            self._row_combo(form, "Value", std, lambda: c.value, lambda v: setattr(c, "value", v or c.value), editable=True)
        else:
            self._row_text(form, "Value", lambda: c.value, lambda v: setattr(c, "value", v))
        self._row_float(form, "X", lambda: c.x, lambda v: setattr(c, "x", v))
        self._row_float(form, "Y", lambda: c.y, lambda v: setattr(c, "y", v))
        self._row_float(form, "Rotation", lambda: c.rotation, lambda v: setattr(c, "rotation", v % 360),
                        lo=-360, hi=360, step=90, decimals=1, suffix=" °")
        self._row_combo(form, "Side", ["top", "bottom"], lambda: c.side, lambda v: setattr(c, "side", v))
        self._row_check(form, "Locked", lambda: c.locked, lambda v: setattr(c, "locked", v))
        self._row_check(form, "Show reference", lambda: c.show_ref, lambda v: setattr(c, "show_ref", v))
        self._row_check(form, "Show value", lambda: c.show_value, lambda v: setattr(c, "show_value", v))
        self._row_text(form, "MPN", lambda: c.mpn, lambda v: setattr(c, "mpn", v))
        self._row_text(form, "LCSC part #", lambda: c.lcsc, lambda v: setattr(c, "lcsc", v))
        hook = getattr(self, "sim_model_hook", None)  # set by the simulation feature (ui/sim_ui.py)
        if hook is not None:
            from ..sim.models import resolve
            try:
                r = resolve(c, (self.doc.project.sim or {}).get("parts", {}).get(c.uid))
                text = r.model if r.simulated else {"none": "connection only", "excluded": "excluded"}.get(
                    r.kind, "not simulated")
            except Exception:
                text = "?"
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            lab = QLabel(text)
            lab.setWordWrap(True)
            h.addWidget(lab, 1)
            b = QPushButton("Change…")
            b.clicked.connect(lambda _c=False, uid=c.uid: hook(uid))
            h.addWidget(b)
            form.addRow("Simulation", row)
        lay.addLayout(form)
        numbers = c.footprint.pad_numbers()
        if numbers:
            lab = QLabel("Pad nets")
            lab.setProperty("muted", True)
            lay.addWidget(lab)
            table = QTableWidget(len(numbers), 2)
            table.setHorizontalHeaderLabels(["Pad", "Net"])
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            nets = self._nets()
            for r, num in enumerate(sorted(numbers, key=natural_key)):
                item = QTableWidgetItem(num)
                item.setFlags(Qt.ItemIsEnabled)
                table.setItem(r, 0, item)
                combo = QComboBox()
                combo.setEditable(True)
                combo.addItems(nets)
                combo.setCurrentText(c.pad_nets.get(num, ""))

                def commit(num=num, combo=combo):
                    t = combo.currentText().strip()
                    if c.pad_nets.get(num, "") == t:
                        return

                    def apply():
                        if t:
                            c.pad_nets[num] = t
                        else:
                            c.pad_nets.pop(num, None)
                    self._edit(f"Set net of {c.ref}.{num}", apply)
                combo.lineEdit().editingFinished.connect(commit)
                combo.activated.connect(lambda i, commit=commit: commit())
                table.setCellWidget(r, 1, combo)
            table.setMinimumHeight(min(28 * len(numbers) + 30, 360))
            lay.addWidget(table)

    def _build_track(self, lay, t: Track):
        self._header(lay, "Track", f"Length {t.length():.3f} mm")
        form = QFormLayout()
        self._row_float(form, "Width", lambda: t.width, lambda v: setattr(t, "width", v), lo=0.05, hi=20, step=0.05)
        self._row_combo(form, "Layer", self.doc.project.copper_layers, lambda: t.layer, lambda v: setattr(t, "layer", v))
        self._row_combo(form, "Net", self._nets(), lambda: t.net, lambda v: setattr(t, "net", v or None), editable=True)
        self._row_float(form, "Start X", lambda: t.x1, lambda v: setattr(t, "x1", v))
        self._row_float(form, "Start Y", lambda: t.y1, lambda v: setattr(t, "y1", v))
        self._row_float(form, "End X", lambda: t.x2, lambda v: setattr(t, "x2", v))
        self._row_float(form, "End Y", lambda: t.y2, lambda v: setattr(t, "y2", v))
        lay.addLayout(form)

    def _build_via(self, lay, v: Via):
        self._header(lay, "Via", "Through-hole via (all copper layers)")
        form = QFormLayout()
        self._row_float(form, "X", lambda: v.x, lambda x: setattr(v, "x", x))
        self._row_float(form, "Y", lambda: v.y, lambda y: setattr(v, "y", y))
        self._row_float(form, "Diameter", lambda: v.diameter, lambda x: setattr(v, "diameter", x), lo=0.2, hi=10, step=0.05)
        self._row_float(form, "Drill", lambda: v.drill, lambda x: setattr(v, "drill", x), lo=0.1, hi=8, step=0.05)
        self._row_combo(form, "Net", self._nets(), lambda: v.net, lambda x: setattr(v, "net", x or None), editable=True)
        lay.addLayout(form)

    def _build_zone(self, lay, z: Zone):
        self._header(lay, "Copper zone", "Filled automatically after every edit")
        form = QFormLayout()
        self._row_combo(form, "Net", self._nets(), lambda: z.net, lambda x: setattr(z, "net", x or None), editable=True)
        self._row_combo(form, "Layer", self.doc.project.copper_layers, lambda: z.layer, lambda x: setattr(z, "layer", x))
        self._row_float(form, "Clearance", lambda: z.clearance, lambda x: setattr(z, "clearance", x), lo=0.05, hi=5, step=0.05)
        self._row_float(form, "Min width", lambda: z.min_width, lambda x: setattr(z, "min_width", x), lo=0.05, hi=5, step=0.05)
        w = QSpinBox()
        w.setRange(0, 100)
        w.setValue(z.priority)
        w.valueChanged.connect(lambda x: self._edit("Zone priority", lambda: setattr(z, "priority", x)))
        form.addRow("Priority", w)
        self._row_check(form, "Thermal reliefs", lambda: z.thermal, lambda x: setattr(z, "thermal", x))
        self._row_float(form, "Relief gap", lambda: z.thermal_gap, lambda x: setattr(z, "thermal_gap", x), lo=0.1, hi=3, step=0.05)
        self._row_float(form, "Spoke width", lambda: z.spoke_width, lambda x: setattr(z, "spoke_width", x), lo=0.1, hi=3, step=0.05)
        self._row_check(form, "Keep islands", lambda: z.keep_islands, lambda x: setattr(z, "keep_islands", x))
        lay.addLayout(form)

    def _build_text(self, lay, t: Text):
        self._header(lay, "Text")
        form = QFormLayout()
        self._row_text(form, "Text", lambda: t.text, lambda v: setattr(t, "text", v))
        self._row_float(form, "Height", lambda: t.size, lambda v: setattr(t, "size", v), lo=0.3, hi=50, step=0.1)
        self._row_float(form, "X", lambda: t.x, lambda v: setattr(t, "x", v))
        self._row_float(form, "Y", lambda: t.y, lambda v: setattr(t, "y", v))
        self._row_float(form, "Rotation", lambda: t.rotation, lambda v: setattr(t, "rotation", v % 360),
                        lo=-360, hi=360, step=90, decimals=1, suffix=" °")
        layers = ["F.SilkS", "B.SilkS"] + self.doc.project.copper_layers
        self._row_combo(form, "Layer", layers, lambda: t.layer, lambda v: setattr(t, "layer", v))
        lay.addLayout(form)

    def _build_board(self, lay):
        p = self.doc.project
        b = p.board
        self._header(lay, "Board", f"{b.width:.2f} × {b.height:.2f} mm · {len(p.components)} parts · "
                                   f"{len(p.tracks)} tracks · {len(p.vias)} vias")
        form = QFormLayout()
        self._row_text(form, "Project name", lambda: p.name, lambda v: setattr(p, "name", v))
        self._row_text(form, "Revision", lambda: p.revision, lambda v: setattr(p, "revision", v))
        self._row_text(form, "Author", lambda: p.author, lambda v: setattr(p, "author", v))
        lay.addLayout(form)
        box = QLabel("Stack-up & finish")
        box.setProperty("muted", True)
        lay.addWidget(box)
        form = QFormLayout()
        self._row_combo(form, "Copper layers", ["2", "4"], lambda: str(b.layers), lambda v: self._set_layers(int(v)))
        self._row_float(form, "Thickness", lambda: b.thickness, lambda v: setattr(b, "thickness", v), lo=0.4, hi=3.2,
                        step=0.2, decimals=2)
        self._row_combo(form, "Solder mask", MASK_COLORS, lambda: b.mask_color, lambda v: setattr(b, "mask_color", v))
        self._row_combo(form, "Silkscreen", SILK_COLORS, lambda: b.silk_color, lambda v: setattr(b, "silk_color", v))
        self._row_combo(form, "Surface finish", FINISHES, lambda: b.finish, lambda v: setattr(b, "finish", v))
        self._row_combo(form, "Copper weight", ["1 oz", "2 oz"], lambda: f"{b.copper_oz:g} oz",
                        lambda v: setattr(b, "copper_oz", float(v.split()[0])))
        lay.addLayout(form)
        box = QLabel("Design rules")
        box.setProperty("muted", True)
        lay.addWidget(box)
        r = p.rules
        nc = p.netclasses.get("Default")
        form = QFormLayout()
        if nc:
            self._row_float(form, "Track width", lambda: nc.track_width, lambda v: setattr(nc, "track_width", v), lo=0.05, hi=10, step=0.05)
            self._row_float(form, "Clearance", lambda: nc.clearance, lambda v: setattr(nc, "clearance", v), lo=0.05, hi=5, step=0.05)
            self._row_float(form, "Via diameter", lambda: nc.via_diameter, lambda v: setattr(nc, "via_diameter", v), lo=0.2, hi=5, step=0.05)
            self._row_float(form, "Via drill", lambda: nc.via_drill, lambda v: setattr(nc, "via_drill", v), lo=0.1, hi=3, step=0.05)
        self._row_float(form, "Min track", lambda: r.min_track, lambda v: setattr(r, "min_track", v), lo=0.05, hi=5, step=0.01)
        self._row_float(form, "Min drill", lambda: r.min_drill, lambda v: setattr(r, "min_drill", v), lo=0.1, hi=5, step=0.05)
        self._row_float(form, "Edge clearance", lambda: r.edge_clearance, lambda v: setattr(r, "edge_clearance", v), lo=0, hi=5, step=0.05)
        self._row_float(form, "Mask expansion", lambda: r.mask_expansion, lambda v: setattr(r, "mask_expansion", v), lo=0, hi=1, step=0.01)
        self._row_check(form, "Tent vias", lambda: r.tent_vias, lambda v: setattr(r, "tent_vias", v))
        lay.addLayout(form)
        hint = QLabel("Tip: select an item to edit it. Double-click a component to jump here.")
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        lay.addWidget(hint)

    def _set_layers(self, n: int):
        p = self.doc.project
        p.board.layers = n
        if n == 2:
            valid = set(p.copper_layers)
            for t in p.tracks:
                if t.layer not in valid:
                    t.layer = "F.Cu"
            for z in p.zones:
                if z.layer not in valid:
                    z.layer = "F.Cu"


E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1]
E6 = [1.0, 1.5, 2.2, 3.3, 4.7, 6.8]


def _eng(v: float, unit_prefixes) -> str:
    for scale, suffix in unit_prefixes:
        if v >= scale * 0.999:
            n = v / scale
            text = f"{n:.3g}" if n < 1000 else f"{n:.0f}"
            if suffix in ("k", "M", "R") and "." in text:
                return text.replace(".", suffix)  # 4k7 / 2M2 / 4R7 style
            return f"{text}{suffix}"
    return f"{v:g}"


def standard_values(ref: str) -> list[str]:
    """Common orderable values for R / C / L parts (E24 resistors, E6 capacitors and inductors)."""
    import re as _re
    m = _re.match(r"[A-Za-z]+", ref or "")
    prefix = m.group(0).upper() if m else ""
    if prefix in ("R", "RN"):
        vals = [d * 10 ** e for e in range(0, 7) for d in E24] + [10e6]
        return [_eng(v, [(1e6, "M"), (1e3, "k"), (1, "R")]) for v in vals]
    if prefix == "C":
        vals = [d * 10 ** e for e in range(-12, -3) for d in E6] + [1e-3]
        return [_eng(v, [(1e-6, "uF"), (1e-9, "nF"), (1e-12, "pF")]) for v in vals]
    if prefix == "L":
        vals = [d * 10 ** e for e in range(-9, -2) for d in E6]
        return [_eng(v, [(1e-3, "mH"), (1e-6, "uH"), (1e-9, "nH")]) for v in vals]
    return []


def _set_quiet(w, v):
    w.blockSignals(True)
    w.setValue(v)
    w.blockSignals(False)
    return True


# --------------------------------------------------------------------------- layers

class LayersPanel(QWidget):
    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(8, 8, 8, 8)
        self.lay.setSpacing(4)
        canvas.layer_changed.connect(lambda _l: self.rebuild())
        canvas.doc.replaced.connect(self.rebuild)
        canvas.doc.changed.connect(self._maybe_rebuild)
        self._nlayers = None
        self.rebuild()

    def _maybe_rebuild(self):
        if self._nlayers != len(self.canvas.doc.project.copper_layers):
            self.rebuild()

    def rebuild(self):
        while self.lay.count():
            item = self.lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        c = self.canvas
        layers = c.doc.project.copper_layers
        self._nlayers = len(layers)
        title = QLabel("Copper (click to make active)")
        title.setProperty("muted", True)
        self.lay.addWidget(title)
        for L in layers:
            self.lay.addWidget(self._row(L, active=(L == c.active_layer), copper=True))
        title = QLabel("Other layers")
        title.setProperty("muted", True)
        self.lay.addWidget(title)
        for L in ("F.SilkS", "B.SilkS", "Edge.Cuts"):
            self.lay.addWidget(self._row(L))
        title = QLabel("Display")
        title.setProperty("muted", True)
        self.lay.addWidget(title)
        for key, label in (("Zones", "Copper zones"), ("Ratsnest", "Ratsnest"), ("PadNumbers", "Pad numbers"),
                           ("NetNames", "Net names on pads"), ("Courtyard", "Courtyards"), ("Fab", "Fab outlines"),
                           ("DRC", "DRC markers"), ("Grid", "Grid"), ("Enclosure", "Pedal enclosure")):
            cb = QCheckBox(label)
            cb.setChecked(c.visible.get(key, True))
            cb.toggled.connect(lambda v, k=key: self._set_vis(k, v))
            self.lay.addWidget(cb)
        self.lay.addStretch(1)

    def _set_vis(self, key, v):
        self.canvas.visible[key] = v
        self.canvas.update()

    def _row(self, layer, active=False, copper=False):
        w = QFrame()
        h = QHBoxLayout(w)
        h.setContentsMargins(4, 2, 4, 2)
        cb = QCheckBox()
        cb.setChecked(self.canvas.visible.get(layer, True))
        cb.toggled.connect(lambda v: self._set_vis(layer, v))
        h.addWidget(cb)
        sw = QLabel()
        col = LAYER_COLORS.get(layer, QColor(200, 200, 200))
        sw.setFixedSize(14, 14)
        sw.setStyleSheet(f"background:{col.name()}; border-radius:3px;")
        h.addWidget(sw)
        if copper:
            btn = QRadioButton(layer)
            btn.setChecked(active)
            btn.toggled.connect(lambda on: on and self.canvas.set_active_layer(layer))
            h.addWidget(btn, 1)
        else:
            h.addWidget(QLabel(layer), 1)
        if active:
            w.setStyleSheet("QFrame { background:#1f3a63; border-radius:5px; }")
        return w


# --------------------------------------------------------------------------- nets

class NetsPanel(QWidget):
    net_selected = Signal(object)

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter nets")
        self.filter.setClearButtonEnabled(True)
        lay.addWidget(self.filter)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Net", "Pads", "Unrouted", "Class"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for i in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.table.setSortingEnabled(True)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        for text, fn in (("Add", self._add), ("Rename", self._rename), ("Delete", self._delete), ("Class…", self._class)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        self.summary = QLabel()
        self.summary.setProperty("muted", True)
        lay.addWidget(self.summary)
        self.filter.textChanged.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self._sel)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.refresh)
        doc.changed.connect(self._timer.start)
        doc.replaced.connect(self.refresh)
        self.refresh()

    def refresh(self):
        p = self.doc.project
        conn = get_connectivity(p)
        pads: dict[str, int] = {}
        for c in p.components:
            for pad in c.footprint.pads:
                n = c.pad_nets.get(pad.number)
                if n:
                    pads[n] = pads.get(n, 0) + 1
        status = conn.net_status()
        q = self.filter.text().strip().lower()
        nets = [n for n in p.nets() if q in n.lower()]
        cur = self.current()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(nets))
        total_unrouted = 0
        for r, n in enumerate(nets):
            unr = status.get(n, (0, 0))[1]
            total_unrouted += unr
            items = [QTableWidgetItem(n), _num_item(pads.get(n, 0)), _num_item(unr),
                     QTableWidgetItem(p.net_class_map.get(n, "Default"))]
            if unr:
                items[2].setForeground(QColor(theme.WARN))
            else:
                items[2].setForeground(QColor(theme.GOOD))
            for col, it in enumerate(items):
                self.table.setItem(r, col, it)
        self.table.setSortingEnabled(True)
        if cur:
            for r in range(self.table.rowCount()):
                if self.table.item(r, 0).text() == cur:
                    self.table.blockSignals(True)
                    self.table.selectRow(r)
                    self.table.blockSignals(False)
        self.summary.setText(f"{len(p.nets())} nets · {conn.unrouted_count()} unrouted connections")

    def current(self) -> str | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        it = self.table.item(rows[0].row(), 0)
        return it.text() if it else None

    def _sel(self):
        self.net_selected.emit(self.current())

    def _add(self):
        name, ok = QInputDialog.getText(self, "Add net", "Net name:")
        if ok and name.strip() and name.strip() not in self.doc.project.nets():
            with self.doc.edit("Add net"):
                self.doc.project.extra_nets.append(name.strip())

    def _rename(self):
        n = self.current()
        if not n:
            return
        name, ok = QInputDialog.getText(self, "Rename net", f"New name for {n}:", text=n)
        if ok and name.strip() and name.strip() != n:
            if name.strip() in self.doc.project.nets():
                if QMessageBox.question(self, "Merge nets", f"Net {name.strip()} exists. Merge {n} into it?") != QMessageBox.Yes:
                    return
            with self.doc.edit("Rename net"):
                self.doc.project.rename_net(n, name.strip())

    def _delete(self):
        n = self.current()
        if n and QMessageBox.question(self, "Delete net", f"Remove net {n} from all pads, tracks and zones?") == QMessageBox.Yes:
            with self.doc.edit("Delete net"):
                self.doc.project.rename_net(n, None)

    def _class(self):
        n = self.current()
        if not n:
            return
        p = self.doc.project
        names = list(p.netclasses)
        cur = p.net_class_map.get(n, "Default")
        name, ok = QInputDialog.getItem(self, "Net class", f"Net class for {n} (type a new name to create one):",
                                        names, names.index(cur) if cur in names else 0, True)
        if not ok or not name.strip():
            return
        name = name.strip()
        from ..model.board import NetClass
        with self.doc.edit("Set net class"):
            if name not in p.netclasses:
                base = p.netclasses.get("Default") or NetClass("Default")
                p.netclasses[name] = NetClass(name, base.clearance, base.track_width * 2, base.via_diameter, base.via_drill)
            if name == "Default":
                p.net_class_map.pop(n, None)
            else:
                p.net_class_map[n] = name


def _num_item(v: int) -> QTableWidgetItem:
    it = QTableWidgetItem()
    it.setData(Qt.DisplayRole, v)
    it.setTextAlignment(Qt.AlignCenter)
    return it


# --------------------------------------------------------------------------- DRC

class DrcPanel(QWidget):
    violation_activated = Signal(object)
    run_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        top = QHBoxLayout()
        self.run_btn = QPushButton("Run DRC")
        self.run_btn.setIcon(icon("drc"))
        self.run_btn.setProperty("primary", True)
        self.run_btn.clicked.connect(self.run_requested.emit)
        top.addWidget(self.run_btn)
        self.summary = QLabel("Not run yet")
        top.addWidget(self.summary, 1)
        self.show_unrouted = QCheckBox("Show unrouted")
        self.show_unrouted.setChecked(True)
        self.show_unrouted.toggled.connect(lambda _v: self._fill())
        top.addWidget(self.show_unrouted)
        lay.addLayout(top)
        self.list = QTreeWidget()
        self.list.setHeaderLabels(["Severity", "Type", "Message"])
        self.list.setRootIsDecorated(False)
        self.list.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.list.itemActivated.connect(self._activate)
        self.list.itemClicked.connect(self._activate)
        lay.addWidget(self.list, 1)
        self.violations = []

    def set_results(self, violations):
        self.violations = violations
        self._fill()

    def _fill(self):
        self.list.clear()
        errs = sum(1 for v in self.violations if v.severity == "error")
        warns = sum(1 for v in self.violations if v.severity != "error")
        unr = sum(1 for v in self.violations if v.kind == "unrouted")
        if not self.violations:
            self.summary.setText(f"<span style='color:{theme.GOOD}'>✔ No DRC violations</span>")
        else:
            self.summary.setText(f"<span style='color:{theme.BAD}'>{errs} errors</span> · "
                                 f"<span style='color:{theme.WARN}'>{warns} warnings</span> · {unr} unrouted")
        for v in self.violations:
            if v.kind == "unrouted" and not self.show_unrouted.isChecked():
                continue
            it = QTreeWidgetItem([v.severity.upper(), v.kind, v.message])
            it.setForeground(0, QColor(theme.BAD if v.severity == "error" else theme.WARN))
            it.setData(0, Qt.UserRole, v)
            self.list.addTopLevelItem(it)
        self.list.resizeColumnToContents(0)
        self.list.resizeColumnToContents(1)

    def _activate(self, item, col=0):
        v = item.data(0, Qt.UserRole)
        if v is not None:
            self.violation_activated.emit(v)
