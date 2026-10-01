"""Order & Manufacture page: board spec, pre-flight checks, fab quote comparison and package export."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
                               QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..export.package import export_package, safe_name
from ..fab.fabs import PRICING_NOTE, QUANTITIES, THICKNESSES, OrderOptions, Quote, board_spec, quote_all
from ..fab.suppliers import MORE_FABS
from ..model.board import FINISHES, MASK_COLORS, SILK_COLORS
from ..model.drc import run_drc
from . import theme
from .flow import FlowLayout
from .icons import icon
from .shop import PartsCard


def _card() -> QFrame:
    f = QFrame()
    f.setProperty("card", True)
    return f


def _money(v: float) -> str:
    return f"${v:,.2f}"


class _Column(QWidget):
    """Left column: 320 px wide when there's room, narrower (down to its contents) on a small window."""

    def sizeHint(self):
        return super().sizeHint().expandedTo(QSize(320, 0))


class OrderPage(QWidget):
    drc_requested = Signal()

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.quotes: list[Quote] = []
        self.spec = None
        self.last_export = None
        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(14)

        # ---------------- left column: specs and options
        left = QVBoxLayout()
        spec_card = _card()
        sl = QVBoxLayout(spec_card)
        t = QLabel("Board specification")
        t.setProperty("heading", True)
        sl.addWidget(t)
        sub = QLabel("Detected automatically from your design")
        sub.setProperty("muted", True)
        sl.addWidget(sub)
        self.spec_grid = QGridLayout()
        self.spec_grid.setHorizontalSpacing(18)
        sl.addLayout(self.spec_grid)
        left.addWidget(spec_card)

        opt_card = _card()
        ol = QVBoxLayout(opt_card)
        t = QLabel("Order options")
        t.setProperty("heading", True)
        ol.addWidget(t)
        form = QFormLayout()
        self.qty = QComboBox()
        self.qty.addItems([str(q) for q in QUANTITIES])
        self.thick = QComboBox()
        self.thick.addItems([f"{t:g} mm" for t in THICKNESSES])
        self.mask = QComboBox()
        self.mask.addItems(MASK_COLORS)
        self.silk = QComboBox()
        self.silk.addItems(SILK_COLORS)
        self.finish = QComboBox()
        self.finish.addItems(FINISHES)
        self.copper = QComboBox()
        self.copper.addItems(["1 oz", "2 oz"])
        self.assembly = QCheckBox("SMT assembly (PCBA)")
        self.stencil = QCheckBox("Solder paste stencil")
        self.express = QCheckBox("Express build + shipping")
        form.addRow("Quantity", self.qty)
        form.addRow("Thickness", self.thick)
        form.addRow("Solder mask", self.mask)
        form.addRow("Silkscreen", self.silk)
        form.addRow("Surface finish", self.finish)
        form.addRow("Copper weight", self.copper)
        ol.addLayout(form)
        for w in (self.assembly, self.stencil, self.express):
            ol.addWidget(w)
        sync = QLabel("Mask, silkscreen, finish and thickness are shared with the 3D preview.")
        sync.setProperty("muted", True)
        sync.setWordWrap(True)
        ol.addWidget(sync)
        left.addWidget(opt_card)
        left.addStretch(1)
        lw = _Column()
        lw.setLayout(left)
        lw.setMaximumWidth(400)

        # ---------------- right column: checks, quotes, actions
        right = QVBoxLayout()
        check_card = _card()
        cl = QVBoxLayout(check_card)
        row = QHBoxLayout()
        t = QLabel("Pre-flight checks")
        t.setProperty("heading", True)
        row.addWidget(t)
        row.addStretch(1)
        self.recheck_btn = QPushButton("Re-check")
        self.recheck_btn.setIcon(icon("drc"))
        self.recheck_btn.clicked.connect(self.refresh_checks)
        row.addWidget(self.recheck_btn)
        cl.addLayout(row)
        self.checks = QLabel()
        self.checks.setWordWrap(True)
        self.checks.setTextFormat(Qt.RichText)
        cl.addWidget(self.checks)
        right.addWidget(check_card)

        q_card = _card()
        ql = QVBoxLayout(q_card)
        t = QLabel("Compare manufacturers")
        t.setProperty("heading", True)
        ql.addWidget(t)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Manufacturer", "Boards", "PCB", "Assembly", "Shipping", "Total",
                                              "Per board", "Delivery"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 8):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.table.setMinimumHeight(190)
        ql.addWidget(self.table)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.RichText)
        self.detail.setOpenExternalLinks(True)
        ql.addWidget(self.detail)
        note = QLabel(PRICING_NOTE)
        note.setProperty("muted", True)
        note.setWordWrap(True)
        ql.addWidget(note)
        more = QLabel("More fabs (no estimate): " + " · ".join(
            f"<a href='{f.url}' style='color:{theme.ACCENT}'>{f.name}</a>" for f in MORE_FABS))
        more.setProperty("muted", True)
        more.setWordWrap(True)
        more.setOpenExternalLinks(True)
        ql.addWidget(more)
        right.addWidget(q_card, 1)
        self.parts_card = PartsCard(doc)
        right.addWidget(self.parts_card)

        act_card = _card()
        al = FlowLayout(act_card)
        self.export_btn = QPushButton("Export manufacturing files…")
        self.export_btn.setIcon(icon("gerber"))
        self.order_btn = QPushButton("Export && open fab upload page")
        self.order_btn.setIcon(icon("order"))
        self.order_btn.setProperty("primary", True)
        self.folder_btn = QPushButton("Show files")
        self.folder_btn.setEnabled(False)
        al.addWidget(self.export_btn)
        al.addWidget(self.folder_btn)
        al.addStretch(1)
        al.addWidget(self.order_btn)
        right.addWidget(act_card)
        rw = QWidget()
        rw.setLayout(right)

        outer.addWidget(lw)
        outer.addWidget(rw, 1)

        for w in (self.qty, self.thick, self.mask, self.silk, self.finish, self.copper):
            w.currentTextChanged.connect(self._options_changed)
        for w in (self.assembly, self.stencil, self.express):
            w.toggled.connect(self._options_changed)
        self.table.itemSelectionChanged.connect(self._show_detail)
        self.export_btn.clicked.connect(self.export_files)
        self.order_btn.clicked.connect(self.order)
        self.folder_btn.clicked.connect(self._open_folder)
        self._loading = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self.refresh)
        doc.changed.connect(self._on_doc_changed)
        doc.replaced.connect(self.load_options)
        self.load_options()

    # ------------------------------------------------------------------ options <-> project
    def options(self) -> OrderOptions:
        return OrderOptions(
            quantity=int(self.qty.currentText()),
            thickness=float(self.thick.currentText().split()[0]),
            mask_color=self.mask.currentText(),
            silk_color=self.silk.currentText(),
            finish=self.finish.currentText(),
            copper_oz=float(self.copper.currentText().split()[0]),
            assembly=self.assembly.isChecked(),
            stencil=self.stencil.isChecked(),
            express=self.express.isChecked(),
        )

    def load_options(self):
        p = self.doc.project
        o = OrderOptions.from_dict(p.order)
        b = p.board
        o.thickness, o.mask_color, o.silk_color, o.finish, o.copper_oz = (b.thickness, b.mask_color, b.silk_color,
                                                                          b.finish, b.copper_oz)
        self._loading = True
        self.qty.setCurrentText(str(o.quantity))
        self.thick.setCurrentText(f"{o.thickness:g} mm")
        self.mask.setCurrentText(o.mask_color)
        self.silk.setCurrentText(o.silk_color)
        self.finish.setCurrentText(o.finish)
        self.copper.setCurrentText(f"{o.copper_oz:g} oz")
        self.assembly.setChecked(o.assembly)
        self.stencil.setChecked(o.stencil)
        self.express.setChecked(o.express)
        self._loading = False
        self._timer.start()

    def _options_changed(self, *_):
        if self._loading:
            return
        o = self.options()
        p = self.doc.project
        b = p.board
        board_change = (b.thickness, b.mask_color, b.silk_color, b.finish, b.copper_oz) != (
            o.thickness, o.mask_color, o.silk_color, o.finish, o.copper_oz)
        with self.doc.edit("Order options"):
            p.order = o.to_dict()
            if board_change:
                b.thickness, b.mask_color, b.silk_color, b.finish, b.copper_oz = (
                    o.thickness, o.mask_color, o.silk_color, o.finish, o.copper_oz)

    def _on_doc_changed(self):
        if self.isVisible():
            self._timer.start()
        b = self.doc.project.board
        if (self.mask.currentText(), self.finish.currentText(), self.silk.currentText()) != (b.mask_color, b.finish, b.silk_color):
            self.load_options()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.refresh()

    # ------------------------------------------------------------------ refresh
    def refresh(self):
        self.spec = board_spec(self.doc.project)
        self._fill_spec()
        self.quotes = quote_all(self.spec, self.options())
        self._fill_quotes()
        self.refresh_checks(run=False)

    def _fill_spec(self):
        s = self.spec
        while self.spec_grid.count():
            it = self.spec_grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        rows = [
            ("Size", f"{s.width:g} × {s.height:g} mm"),
            ("Layers", f"{s.layers}"),
            ("Min track", f"{s.min_track:.3f} mm" if s.min_track else "—"),
            ("Min clearance", f"{s.min_space:.3f} mm" if s.min_space else "—"),
            ("Min drill", f"{s.min_drill:.2f} mm" if s.min_drill else "—"),
            ("Min annular ring", f"{s.min_annular:.3f} mm" if s.min_annular else "—"),
            ("Holes", str(s.holes)),
            ("Parts (unique)", f"{s.parts} ({s.unique_parts})"),
            ("SMD / THT joints", f"{s.smd_joints} / {s.tht_joints}"),
        ]
        for r, (k, v) in enumerate(rows):
            kl = QLabel(k)
            kl.setProperty("muted", True)
            vl = QLabel(v)
            f = vl.font()
            f.setBold(True)
            vl.setFont(f)
            self.spec_grid.addWidget(kl, r, 0)
            self.spec_grid.addWidget(vl, r, 1)

    def _fill_quotes(self):
        self.table.setRowCount(len(self.quotes))
        best = next((q for q in self.quotes if q.ok), None)
        for r, q in enumerate(self.quotes):
            name = ("★ " if q is best else "") + q.fab.name
            cells = [name, str(q.boards), _money(q.board_cost), _money(q.assembly_cost + q.stencil_cost) if (
                q.assembly_cost or q.stencil_cost) else "—", _money(q.shipping) if q.shipping else "free",
                     _money(q.total), _money(q.unit), q.lead_text]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c:
                    it.setTextAlignment(Qt.AlignCenter)
                if not q.ok:
                    it.setForeground(QColor(theme.TEXT_DIM))
                    if c == 0:
                        it.setText("⚠ " + q.fab.name)
                        it.setForeground(QColor(theme.WARN))
                        it.setToolTip("Not compatible with these options:\n" + "\n".join(q.issues))
                elif q is best:
                    it.setForeground(QColor(theme.GOOD))
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                it.setData(Qt.UserRole, r)
                self.table.setItem(r, c, it)
        if self.quotes:
            self.table.selectRow(0)
        self._show_detail()

    def selected_quote(self) -> Quote | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows or not self.quotes:
            return None
        return self.quotes[rows[0].row()]

    def _show_detail(self):
        q = self.selected_quote()
        if q is None:
            self.detail.setText("")
            return
        parts = [f"<b>{q.fab.name}</b> — {q.fab.location}. {q.fab.blurb} "
                 f"<a href='{q.fab.url}' style='color:{theme.ACCENT}'>Open {q.fab.name} ↗</a>"]
        if q.issues:
            parts.append("<span style='color:%s'>⚠ %s</span>" % (theme.WARN, "<br>⚠ ".join(q.issues)))
        else:
            parts.append(f"<span style='color:{theme.GOOD}'>✔ Design meets {q.fab.name}'s standard capabilities.</span>")
        if q.notes:
            parts.append("<span style='color:%s'>%s</span>" % (theme.TEXT_DIM, " · ".join(q.notes)))
        self.detail.setText("<br>".join(parts))
        self.order_btn.setText(f"Export && open {q.fab.name} upload page")

    def refresh_checks(self, run: bool = True):
        p = self.doc.project
        items = []

        def row(ok, text, warn=False):
            col = theme.GOOD if ok else (theme.WARN if warn else theme.BAD)
            mark = "✔" if ok else ("⚠" if warn else "✖")
            items.append(f"<span style='color:{col}'>{mark}</span>&nbsp; {text}")

        row(len(p.board.outline) >= 3 and not p.board.polygon().is_empty, "Board outline is closed")
        row(bool(p.components), f"{len(p.components)} components placed", warn=True)
        unr = self.spec.unrouted if self.spec else 0
        row(unr == 0, "All connections routed" if unr == 0 else f"{unr} unrouted connection(s) — use Autoroute or route manually")
        row(not p.fills_stale, "Copper pours are up to date", warn=True)
        if run:
            viol = [v for v in run_drc(p) if v.kind != "unrouted"]
            self._last_drc = viol
        viol = getattr(self, "_last_drc", None)
        if viol is None:
            row(False, "Design rule check not run yet — click Re-check", warn=True)
        else:
            errs = sum(1 for v in viol if v.severity == "error")
            warns = len(viol) - errs
            row(errs == 0, "DRC: no errors" + (f" ({warns} warnings)" if warns else "") if errs == 0 else
                f"DRC: {errs} error(s), {warns} warning(s) — see the DRC panel")
        missing = [c.ref for c in p.components if c.footprint.model.get("type") != "none" and not (c.lcsc or c.mpn)]
        if self.assembly.isChecked():
            row(not missing, "All parts have MPN / LCSC numbers" if not missing else
                f"{len(missing)} part(s) without MPN/LCSC # (needed for assembly): {', '.join(missing[:8])}"
                + ("…" if len(missing) > 8 else ""), warn=True)
        self.checks.setText("<br>".join(items))

    # ------------------------------------------------------------------ actions
    def _default_folder(self) -> Path:
        base = self.doc.path.parent if self.doc.path else Path.home() / "Documents" / "PCBPro"
        return base / f"{safe_name(self.doc.project.name)}_fab"

    def export_files(self, folder: str | None = None) -> Path | None:
        if folder is None:
            start = str(self._default_folder())
            folder = QFileDialog.getExistingDirectory(self, "Export manufacturing files to…", str(Path(start).parent))
            if not folder:
                return None
            folder = str(Path(folder) / Path(start).name)
        res = export_package(self.doc.project, folder, include_assembly=True)
        self.last_export = res
        self.folder_btn.setEnabled(True)
        self.doc.changed.emit()
        return res.zip_path

    def order(self):
        q = self.selected_quote()
        if q is None:
            return
        if self.spec and self.spec.unrouted:
            r = QMessageBox.warning(self, "Unrouted connections",
                                    f"The design still has {self.spec.unrouted} unrouted connection(s). "
                                    "Boards made from it will not work. Continue anyway?",
                                    QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        if q.issues:
            r = QMessageBox.warning(self, "Manufacturability", f"{q.fab.name} reports:\n\n• " + "\n• ".join(q.issues)
                                    + "\n\nContinue anyway?", QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        zip_path = self.export_files(str(self._default_folder()))
        if zip_path is None:
            return
        self._open_folder()
        QDesktopServices.openUrl(QUrl(q.fab.url))
        QMessageBox.information(
            self, "Ready to order",
            f"Your Gerber package was saved to:\n{zip_path}\n\n"
            f"{q.fab.name}'s quote page has been opened in your browser. Upload the zip file there, "
            "check their Gerber preview, choose the same options and place the order."
            + ("\n\nFor assembly, also upload the BOM and CPL (pick-and-place) CSV files from the same folder."
               if self.assembly.isChecked() else ""))

    def _open_folder(self):
        if self.last_export is not None:
            path = self.last_export.folder
            if os.name == "nt":
                os.startfile(str(path))  # noqa: S606 - opening the user's own export folder
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
