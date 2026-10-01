"""Buy components: the shopping list with one-click searches at the big distributors and the pedal-parts shops,
a parts-list upload for the suppliers' BOM tools, and Order-menu links to every PCB fab and supplier."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
                               QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QToolBar, QVBoxLayout, QWidget)

from .. import APP_NAME
from ..export.package import safe_name
from ..fab.suppliers import (SUPPLIERS, TAYDA_DRILL_URL, Line, Supplier, fab_links, order_csv, order_text, scaled,
                             shopping_list, supplier_by_key)
from . import theme
from .flow import FlowLayout
from .icons import icon

MAX_TABS = 8  # ask before opening more browser tabs than this at once


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


def _is_pedal(project) -> bool:
    from ..pedal.enclosure import get_enclosure
    return get_enclosure(project) is not None


def _fab_folder(doc) -> Path:
    base = doc.path.parent if doc.path else Path.home() / "Documents" / "PCBPro"
    return base / f"{safe_name(doc.project.name)}_fab"


def _open_folder(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))  # noqa: S606 - the user's own export folder
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _line_key(ln: Line) -> tuple:
    return ln.section, ln.value, ln.package, ln.mpn, ln.lcsc


class BuyPartsDialog(QDialog):
    """Parts to buy, with a search link per line at the chosen supplier."""

    COLS = ["Qty", "Value", "Package", "Designators", "Part #", "Search for", ""]

    def __init__(self, doc, parent=None, supplier: str | None = None):
        super().__init__(parent)
        self.doc = doc
        self.settings = QSettings(APP_NAME, APP_NAME)
        self.lines: list[Line] = []
        self.rows: list[Line | str] = []  # table row -> line, or the section name on a heading row
        self.edited: dict[tuple, str] = {}  # search words the user typed, kept across refreshes
        self._filling = False
        self.setWindowTitle("Buy components")
        self.setWindowIcon(icon("parts"))
        self.resize(1180, 680)
        outer = QHBoxLayout(self)
        split = QSplitter(Qt.Horizontal)
        outer.addWidget(split)

        # ---------------- left: suppliers
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 6, 0)
        t = QLabel("Where to buy")
        t.setProperty("heading", True)
        ll.addWidget(t)
        self.supplier_list = QListWidget()
        self.supplier_list.setSpacing(1)
        for title, kind in (("General distributors", "distributor"), ("Pedal parts shops", "pedal")):
            head = QListWidgetItem(title.upper())
            head.setFlags(Qt.NoItemFlags)
            head.setForeground(QColor(theme.TEXT_DIM))
            f = head.font()
            f.setBold(True)
            f.setPointSizeF(f.pointSizeF() * 0.85)
            head.setFont(f)
            self.supplier_list.addItem(head)
            for s in SUPPLIERS:
                if s.kind == kind:
                    it = QListWidgetItem(f"{s.name}\n{s.region}")
                    it.setData(Qt.UserRole, s.key)
                    it.setToolTip(s.blurb)
                    self.supplier_list.addItem(it)
        ll.addWidget(self.supplier_list, 1)
        self.blurb = QLabel()
        self.blurb.setWordWrap(True)
        self.blurb.setProperty("muted", True)
        ll.addWidget(self.blurb)
        row = QHBoxLayout()
        self.site_btn = QPushButton("Open website")
        self.upload_btn = QPushButton("Upload parts list…")
        self.upload_btn.setToolTip("Save the list as a CSV and open this supplier's BOM tool, which fills a cart from it")
        row.addWidget(self.site_btn)
        row.addWidget(self.upload_btn)
        ll.addLayout(row)
        self.pedal_card = QFrame()
        self.pedal_card.setProperty("card", True)
        pl = QVBoxLayout(self.pedal_card)
        pt = QLabel("<b>Have Tayda drill the enclosure</b>")
        pl.addWidget(pt)
        pm = QLabel("Tayda drills and UV-prints Hammond-style boxes. PCBPro exports the hole coordinates in Tayda's "
                    "format (side, mm from centre); add them in Tayda's drill designer.")
        pm.setWordWrap(True)
        pm.setProperty("muted", True)
        pl.addWidget(pm)
        self.drill_btn = QPushButton("Export holes && open drill service")
        self.drill_btn.setIcon(icon("drill"))
        pl.addWidget(self.drill_btn)
        ll.addWidget(self.pedal_card)
        left.setMinimumWidth(300)
        split.addWidget(left)

        # ---------------- right: the list
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)
        top = QHBoxLayout()
        t = QLabel("Parts to buy")
        t.setProperty("heading", True)
        top.addWidget(t)
        self.summary = QLabel()
        self.summary.setProperty("muted", True)
        top.addWidget(self.summary)
        top.addStretch(1)
        lab = QLabel("Build")
        lab.setProperty("muted", True)
        top.addWidget(lab)
        self.sets = QSpinBox()
        self.sets.setRange(1, 1000)
        self.sets.setSuffix(" ×")
        self.sets.setToolTip("Number of boards you are building; quantities are multiplied by it")
        top.addWidget(self.sets)
        rl.addLayout(top)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                   | QAbstractItemView.AnyKeyPressed)
        hh = self.table.horizontalHeader()
        for c in range(len(self.COLS)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        rl.addWidget(self.table, 1)
        hint = QLabel("Click <b>Find</b> to search for a line at the selected supplier. Edit <i>Search for</i> to "
                      "refine the words; a part number (MPN, or an LCSC # at LCSC) opens the exact product.")
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        rl.addWidget(hint)
        bl = QHBoxLayout()
        self.search_sel_btn = QPushButton("Find selected lines")
        self.copy_btn = QPushButton("Copy list")
        self.save_btn = QPushButton("Save list…")
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        for b in (self.search_sel_btn, self.copy_btn, self.save_btn):
            bl.addWidget(b)
        bl.addStretch(1)
        bl.addWidget(close)
        rl.addLayout(bl)
        split.addWidget(right)
        split.setSizes([310, 870])

        self.supplier_list.currentItemChanged.connect(self._supplier_changed)
        self.site_btn.clicked.connect(lambda: open_url(self.supplier().url))
        self.upload_btn.clicked.connect(self.upload_list)
        self.drill_btn.clicked.connect(self.tayda_drill)
        self.sets.valueChanged.connect(self._fill_table)
        self.table.itemChanged.connect(self._item_changed)
        self.table.cellDoubleClicked.connect(self._double_clicked)
        self.search_sel_btn.clicked.connect(self.search_selected)
        self.copy_btn.clicked.connect(self.copy_list)
        self.save_btn.clicked.connect(self.save_list)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self.refresh)
        doc.changed.connect(self._schedule)
        doc.replaced.connect(self._project_replaced)
        self.refresh()
        self.set_supplier(supplier or self.settings.value("buy_supplier", "")
                          or ("tayda" if _is_pedal(doc.project) else "digikey"))

    # ------------------------------------------------------------------ supplier
    def supplier(self) -> Supplier:
        it = self.supplier_list.currentItem()
        return supplier_by_key(it.data(Qt.UserRole) if it else "") or SUPPLIERS[0]

    def set_supplier(self, key: str) -> None:
        for i in range(self.supplier_list.count()):
            it = self.supplier_list.item(i)
            if it.data(Qt.UserRole) == key:
                self.supplier_list.setCurrentItem(it)
                return
        self.supplier_list.setCurrentRow(1)  # first supplier below the heading

    def _supplier_changed(self, *_):
        s = self.supplier()
        self.settings.setValue("buy_supplier", s.key)
        self.blurb.setText(f"{s.blurb}")
        self.upload_btn.setEnabled(bool(s.bom_url))
        self.upload_btn.setToolTip(f"Save the list as a CSV and open {s.name}'s BOM tool" if s.bom_url else
                                   f"{s.name} has no BOM upload; use Find on each line instead")
        self.table.setHorizontalHeaderItem(6, QTableWidgetItem(f"At {s.name}"))
        self._fill_buttons()

    # ------------------------------------------------------------------ list
    def _schedule(self):
        if self.isVisible():
            self._timer.start()

    def _project_replaced(self):
        self.edited.clear()
        self.refresh()

    def refresh(self):
        self.lines = shopping_list(self.doc.project)
        for ln in self.lines:
            ln.query = self.edited.get(_line_key(ln), ln.query)
        self.pedal_card.setVisible(_is_pedal(self.doc.project))
        self.setWindowTitle(f"Buy components - {self.doc.project.name}")
        self._fill_table()

    def current_lines(self) -> list[Line]:
        """The list scaled by the number of boards being built."""
        return scaled(self.lines, self.sets.value())

    def _fill_table(self, *_):
        self._filling = True
        n = self.sets.value()
        self.table.clearSpans()
        self.rows = []
        section = None
        for ln in self.lines:
            if ln.section != section:
                section = ln.section
                self.rows.append(section)
            self.rows.append(ln)
        self.table.setRowCount(len(self.rows))
        bold = QFont(self.table.font())
        bold.setBold(True)
        for r, ln in enumerate(self.rows):
            if isinstance(ln, str):
                it = QTableWidgetItem(ln.upper())
                it.setFlags(Qt.ItemIsEnabled)
                it.setForeground(QColor(theme.TEXT_DIM))
                it.setFont(bold)
                self.table.removeCellWidget(r, 6)
                self.table.setItem(r, 0, it)
                self.table.setSpan(r, 0, 1, len(self.COLS))
                continue
            code = "  ".join(x for x in (ln.mpn, ln.lcsc) if x)
            cells = [str(ln.qty * n), ln.value, ln.package, ln.refs, code, ln.query]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
                if c == 5:
                    flags |= Qt.ItemIsEditable
                    it.setToolTip("Search words - double-click to edit")
                elif c == 2 and ln.notes:
                    it.setToolTip(ln.notes)
                it.setFlags(flags)
                if c == 0:
                    it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, it)
        self._filling = False
        total = sum(ln.qty for ln in self.lines) * n
        coded = sum(1 for ln in self.lines if ln.mpn or ln.lcsc)
        self.summary.setText(f"  {len(self.lines)} lines · {total} parts"
                             + (f" · {coded} with part numbers" if coded else ""))
        self._fill_buttons()

    def line_at(self, row: int) -> Line | None:
        ln = self.rows[row] if 0 <= row < len(self.rows) else None
        return ln if isinstance(ln, Line) else None

    def _fill_buttons(self):
        s = self.supplier()
        for r in range(len(self.rows)):
            ln = self.line_at(r)
            if ln is None:
                continue
            b = self.table.cellWidget(r, 6)
            if not isinstance(b, QPushButton):
                b = QPushButton()
                b.setFlat(True)
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _c=False, row=r: self.open_row(row))
                self.table.setCellWidget(r, 6, b)
            exact = bool(s.part_url and ln.lcsc)
            b.setText("Open ↗" if exact else "Find ↗")
            b.setToolTip(s.line_url(ln))

    def _item_changed(self, item: QTableWidgetItem):
        if self._filling or item.column() != 5:
            return
        ln = self.line_at(item.row())
        if ln is not None:
            ln.query = item.text().strip()
            self.edited[_line_key(ln)] = ln.query
            self._fill_buttons()

    def _double_clicked(self, row: int, col: int):
        if col != 5:
            self.open_row(row)

    def open_row(self, row: int) -> None:
        ln = self.line_at(row)
        if ln is not None:
            open_url(self.supplier().line_url(ln))

    def search_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        lines = [ln for ln in map(self.line_at, rows) if ln is not None]
        if not lines:
            QMessageBox.information(self, "Find selected lines", "Select one or more lines in the list first.")
            return
        s = self.supplier()
        if len(lines) > MAX_TABS and QMessageBox.question(
                self, "Find selected lines", f"This opens {len(lines)} browser tabs at {s.name}. Continue?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        for ln in lines:
            open_url(s.line_url(ln))

    # ------------------------------------------------------------------ export
    def copy_list(self):
        QGuiApplication.clipboard().setText(order_text(self.current_lines(), self.doc.project.name))
        self.copy_btn.setText("Copied ✓")
        QTimer.singleShot(1500, lambda: self.copy_btn.setText("Copy list"))

    def save_list(self):
        folder = _fab_folder(self.doc)
        start = str((folder if folder.exists() else folder.parent) / f"{safe_name(self.doc.project.name)}_parts.csv")
        path, _ = QFileDialog.getSaveFileName(self, "Save parts list", start, "CSV (*.csv);;Text (*.txt)")
        if not path:
            return None
        lines = self.current_lines()
        text = order_text(lines, self.doc.project.name) if path.lower().endswith(".txt") else order_csv(lines)
        Path(path).write_text(text, encoding="utf-8")
        return Path(path)

    def write_order_csv(self) -> Path:
        folder = _fab_folder(self.doc)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{safe_name(self.doc.project.name)}_parts_order.csv"
        path.write_text(order_csv(self.current_lines()), encoding="utf-8")
        return path

    def upload_list(self):
        s = self.supplier()
        if not s.bom_url:
            return
        path = self.write_order_csv()
        _open_folder(path.parent)
        open_url(s.bom_url)
        missing = sum(1 for ln in self.lines if not ln.mpn)
        note = (f"\n\n{missing} of {len(self.lines)} lines have no manufacturer part number. The BOM tool searches "
                "those by their Description column, so check its suggestions (or add MPNs to the parts in "
                "Properties).") if missing else ""
        QMessageBox.information(
            self, f"Upload to {s.name}",
            f"The parts list was saved to:\n{path}\n\n{s.name}'s BOM tool is open in your browser. Upload the file, "
            "match the Quantity and Manufacturer Part Number columns if asked, then add the parts to your cart."
            + note)

    def tayda_drill(self):
        from ..pedal.drill import tayda_text
        folder = _fab_folder(self.doc)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{safe_name(self.doc.project.name)}_Tayda_drill.txt"
        path.write_text(tayda_text(self.doc.project), encoding="utf-8")
        _open_folder(folder)
        open_url(TAYDA_DRILL_URL)
        QMessageBox.information(
            self, "Tayda drilling service",
            f"The drill coordinates were saved to:\n{path}\n\nTayda's drill service is open in your browser (it "
            "needs a free account with the same email as your Tayda shop account). Create a box design for your "
            "enclosure and add each hole from the file: side, diameter and X/Y in mm from the side's centre.")

    def closeEvent(self, ev):
        self._timer.stop()
        super().closeEvent(ev)


def show_buy_parts(win, supplier: str | None = None) -> BuyPartsDialog:
    """Open (or raise) the window's Buy components dialog."""
    dlg = getattr(win, "buy_parts_dialog", None)
    if dlg is None:
        dlg = BuyPartsDialog(win.doc, win, supplier)
        win.buy_parts_dialog = dlg
    else:
        dlg.refresh()
        if supplier:
            dlg.set_supplier(supplier)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg


class PartsCard(QFrame):
    """Order-tab card: what the board needs and one-click jumps to the suppliers."""

    QUICK = ["digikey", "mouser", "lcsc", "tayda"]

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setProperty("card", True)
        lay = QHBoxLayout(self)
        text = QVBoxLayout()
        t = QLabel("Buy components")
        t.setProperty("heading", True)
        text.addWidget(t)
        self.summary = QLabel()
        self.summary.setProperty("muted", True)
        self.summary.setWordWrap(True)
        text.addWidget(self.summary)
        lay.addLayout(text, 1)
        btns = FlowLayout()  # one row, wrapping when the Order tab is narrow
        lay.addLayout(btns)
        for key in self.QUICK:
            s = supplier_by_key(key)
            b = QPushButton(s.name)
            b.setToolTip(f"{s.region}. {s.blurb}")
            b.clicked.connect(lambda _c=False, k=key: show_buy_parts(self.window(), k))
            btns.addWidget(b)
        self.list_btn = QPushButton("Shopping list && all suppliers…")
        self.list_btn.setIcon(icon("parts"))
        self.list_btn.clicked.connect(lambda: show_buy_parts(self.window()))
        btns.addWidget(self.list_btn)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.refresh)
        doc.changed.connect(lambda: self.isVisible() and self._timer.start())
        doc.replaced.connect(self.refresh)
        self.refresh()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.refresh()

    def refresh(self):
        lines = shopping_list(self.doc.project)
        if not lines:
            self.summary.setText("No parts placed yet.")
            return
        parts = sum(ln.qty for ln in lines)
        coded = sum(1 for ln in lines if ln.mpn or ln.lcsc)
        self.summary.setText(f"{parts} parts on {len(lines)} lines"
                             + (f", {coded} with part numbers" if coded else "")
                             + ". Find each line at a supplier, or upload the list to its BOM tool.")


# --------------------------------------------------------------------------- main window

def _link_action(menu: QMenu, text: str, url: str, tip: str) -> QAction:
    a = menu.addAction(text, lambda: open_url(url))
    a.setToolTip(tip)
    a.setStatusTip(tip)
    return a


def install(win) -> None:
    """Add Buy components and the supplier / fab website links to a MainWindow."""
    act = QAction(icon("parts"), "&Buy components…", win)
    act.setShortcut(QKeySequence("Ctrl+Shift+B"))
    act.setToolTip("Shopping list with links to Digi-Key, Mouser, LCSC, Tayda and more (Ctrl+Shift+B)")
    act.setStatusTip(act.toolTip())
    act.setIconText("Buy parts")
    act.triggered.connect(lambda: show_buy_parts(win))
    win.act_buy_parts = act
    mb = win.menuBar()
    menu = next((a.menu() for a in mb.actions() if a.text().replace("&", "") == "Order" and a.menu()), None)
    if menu is None:
        menu = mb.addMenu("&Order")
    menu.addAction(act)
    menu.addSeparator()
    fabs = menu.addMenu(icon("board"), "PCB manufacturer websites")
    quoted = True
    for f in fab_links():
        if quoted and not f.quoted:
            fabs.addSeparator()
            quoted = False
        _link_action(fabs, f"{f.name}  ({f.region})", f.url, f.blurb)
    parts = menu.addMenu(icon("parts"), "Component supplier websites")
    kind = None
    for s in SUPPLIERS:
        if kind is not None and s.kind != kind:
            parts.addSeparator()
        kind = s.kind
        _link_action(parts, f"{s.name}  ({s.region})", s.url, s.blurb)
    parts.addSeparator()
    _link_action(parts, "Tayda enclosure drilling service", TAYDA_DRILL_URL,
                 "Tayda drills and UV-prints enclosures from the coordinates in Pedal > Export Tayda drill coordinates")
    tb = win.findChild(QToolBar, "main_tb")
    if tb is not None:
        tb.addAction(act)
        w = tb.widgetForAction(act)
        if w is not None:
            w.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
