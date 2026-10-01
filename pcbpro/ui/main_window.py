"""Main application window."""
from __future__ import annotations

import json
import traceback
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDockWidget, QFileDialog, QLabel, QMainWindow,
                               QMessageBox, QPushButton, QTabWidget, QToolBar, QVBoxLayout, QWidget)

from .. import APP_NAME, FILE_EXT, __version__
from ..examples import flasher_555, list_examples, load_example
from ..model import footprints as fplib
from ..model.board import FINISHES, MASK_COLORS, SILK_COLORS, Component, Track, Zone
from ..model.drc import run_drc
from ..model.geometry import rounded_rect_points
from .canvas import Canvas
from .dialogs import AboutDialog, AutorouteDialog, NewBoardDialog, ShortcutsDialog, WelcomeDialog
from .document import Document, blank_project
from .flow import FlowLayout
from .icons import app_icon, icon
from .order_page import OrderPage
from .panels import DrcPanel, LayersPanel, LibraryPanel, NetsPanel, PropertiesPanel
from .tools import delete_items, duplicate_items, flip_items, make_tools, rotate_items
from .view3d import View3D

GRIDS = [("0.05 mm", 0.05), ("0.1 mm", 0.1), ("0.25 mm", 0.25), ("0.5 mm", 0.5), ("1 mm", 1.0),
         ("25 mil", 0.635), ("50 mil", 1.27), ("100 mil", 2.54)]
FILE_FILTER = f"PCBPro project (*{FILE_EXT})"


class Viewer3DPage(QWidget):
    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QWidget()
        bl = FlowLayout(bar)  # one row, wrapping on narrow windows
        bl.setContentsMargins(10, 6, 10, 6)
        self.view = View3D(doc)
        for name, label in (("iso", "Iso"), ("top", "Top"), ("bottom", "Bottom"), ("front", "Front")):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, n=name: self.view.set_view(n))
            bl.addWidget(b)
        self.comps = QCheckBox("Components")
        self.comps.setChecked(True)
        self.comps.toggled.connect(self.view.set_show_components)
        bl.addSpacing(12)
        bl.addWidget(self.comps)
        # pedal view: the enclosure with knobs, footswitch and jacks around the board
        self.pedal_cb = QCheckBox("Pedal enclosure")
        self.pedal_cb.toggled.connect(self.view.set_show_enclosure)
        self.lid_cb = QCheckBox("Base plate")
        self.lid_cb.toggled.connect(self.view.set_show_lid)
        pedal_view = QPushButton("Pedal view")
        pedal_view.setIcon(icon("pedal"))
        pedal_view.clicked.connect(lambda: (self.pedal_cb.setChecked(True), self.view.set_view("pedal")))
        for w in (self.pedal_cb, self.lid_cb, pedal_view):
            bl.addWidget(w)
        bl.addStretch(1)
        self.mask = QComboBox()
        self.mask.addItems(MASK_COLORS)
        self.silk = QComboBox()
        self.silk.addItems(SILK_COLORS)
        self.finish = QComboBox()
        self.finish.addItems(FINISHES)
        for lab, w in (("Mask", self.mask), ("Silk", self.silk), ("Finish", self.finish)):
            l = QLabel(lab)
            l.setProperty("muted", True)
            bl.addGroup(l, w)
        shot = QPushButton("Screenshot…")
        shot.setIcon(icon("camera"))
        shot.clicked.connect(self.screenshot)
        bl.addSpacing(8)
        bl.addWidget(shot)
        lay.addWidget(bar)
        lay.addWidget(self.view, 1)
        hint = QLabel("  Left-drag orbit · right-drag pan · wheel zoom · double-click fit · keys 1/2/3/0 = top/bottom/front/iso")
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self._sync()
        doc.changed.connect(self._sync)
        doc.replaced.connect(self._sync)
        self.mask.currentTextChanged.connect(lambda v: self._set("mask_color", v))
        self.silk.currentTextChanged.connect(lambda v: self._set("silk_color", v))
        self.finish.currentTextChanged.connect(lambda v: self._set("finish", v))

    def _sync(self):
        b = self.doc.project.board
        for w, v in ((self.mask, b.mask_color), (self.silk, b.silk_color), (self.finish, b.finish)):
            if w.currentText() != v:
                w.blockSignals(True)
                w.setCurrentText(v)
                w.blockSignals(False)

    def _set(self, attr, value):
        b = self.doc.project.board
        if getattr(b, attr) != value:
            with self.doc.edit(f"Board {attr.replace('_', ' ')}"):
                setattr(b, attr, value)

    def screenshot(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save 3D screenshot", f"{self.doc.project.name}_3d.png", "PNG image (*.png)")
        if path:
            self.view.grabFramebuffer().save(path)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(APP_NAME, APP_NAME)
        self.doc = Document(blank_project())
        self.setWindowIcon(app_icon())
        self.resize(1500, 920)

        self.canvas = Canvas(self.doc)
        self.canvas.register_tools(make_tools(self.canvas))
        self.canvas.key_fallback = self._canvas_key
        self.page3d = Viewer3DPage(self.doc)
        self.order_page = OrderPage(self.doc)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.canvas, icon("layers"), "PCB Layout")
        self.tabs.addTab(self.page3d, icon("cube"), "3D View")
        self.tabs.addTab(self.order_page, icon("order"), "Order && Manufacture")
        self.setCentralWidget(self.tabs)

        self._build_docks()
        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        self._build_statusbar()

        self.doc.state_changed.connect(self._update_title)
        self.doc.message.connect(lambda m: self.statusBar().showMessage(m, 3000))
        self.doc.changed.connect(self._update_counts)
        self.canvas.status.connect(self.hint_label.setText)
        self.canvas.cursor_moved.connect(lambda x, y: self.pos_label.setText(f"X {x:8.3f}   Y {y:8.3f} mm"))
        self.canvas.layer_changed.connect(lambda L: self.layer_label.setText(f"Layer: {L}"))
        self.canvas.tool_changed.connect(self._tool_changed)
        self.canvas.open_properties.connect(lambda: (self.props_dock.show(), self.props_dock.raise_()))
        self.page3d.view.info.connect(lambda m: self.statusBar().showMessage(m, 8000))
        self.order_page.drc_requested.connect(self.run_drc)
        from . import pedal_ui
        pedal_ui.install(self)  # Pedal menu, Enclosure & Drilling tab, enclosure overlay
        from . import shop
        shop.install(self)  # Buy components, supplier and fab website links
        from . import sim_ui
        sim_ui.install(self)  # Simulate menu, Run button, Simulation and Oscilloscope docks
        from . import amp_ui
        amp_ui.install(self)  # Amp menu: amp templates, HV net data, tone stacks, calculators, tube data
        self.canvas.set_tool("select")
        self._update_title()
        self._update_counts()
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        QTimer.singleShot(0, self.canvas.fit_board)

    # ------------------------------------------------------------------ construction
    def _dock(self, title, widget, area, name) -> QDockWidget:
        d = QDockWidget(title, self)
        d.setObjectName(name)
        d.setWidget(widget)
        d.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable)
        self.addDockWidget(area, d)
        return d

    def _build_docks(self):
        from ..library.index import LibraryIndex
        try:
            kicad_dirs = json.loads(self.settings.value("kicad_dirs", "[]"))
        except (TypeError, ValueError):
            kicad_dirs = []
        self.lib_index = LibraryIndex(kicad_dirs)
        self.library = LibraryPanel(self.lib_index)
        self.library.place_requested.connect(self.place_part)
        self.library.action_requested.connect(self.library_action)
        self.library.delete_requested.connect(self._delete_library_part)
        self.nets = NetsPanel(self.doc)
        self.nets.net_selected.connect(self.highlight_net)
        self.props = PropertiesPanel(self.doc, self.canvas)
        self.layers = LayersPanel(self.canvas)
        self.drc = DrcPanel()
        self.drc.run_requested.connect(self.run_drc)
        self.drc.violation_activated.connect(self._goto_violation)
        self.lib_dock = self._dock("Library", self.library, Qt.LeftDockWidgetArea, "lib")
        self.nets_dock = self._dock("Nets", self.nets, Qt.LeftDockWidgetArea, "nets")
        self.tabifyDockWidget(self.lib_dock, self.nets_dock)
        self.lib_dock.raise_()
        self.props_dock = self._dock("Properties", self.props, Qt.RightDockWidgetArea, "props")
        self.layers_dock = self._dock("Layers", self.layers, Qt.RightDockWidgetArea, "layers")
        self.drc_dock = self._dock("Design Rule Check", self.drc, Qt.BottomDockWidgetArea, "drc")
        self.drc_dock.hide()
        self.resizeDocks([self.lib_dock, self.props_dock], [290, 310], Qt.Horizontal)
        self.resizeDocks([self.props_dock, self.layers_dock], [560, 330], Qt.Vertical)

    def _act(self, text, slot, shortcut=None, ic=None, checkable=False, tip=None) -> QAction:
        a = QAction(text, self)
        if ic:
            a.setIcon(icon(ic))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setCheckable(checkable)
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        if slot:
            a.triggered.connect(slot)
        return a

    def _build_actions(self):
        A = self._act
        self.act_new = A("&New board…", self.new_board, "Ctrl+N", "new")
        self.act_open = A("&Open…", self.open_file, "Ctrl+O", "open")
        self.act_save = A("&Save", self.save, "Ctrl+S", "save")
        self.act_save_as = A("Save &As…", self.save_as, "Ctrl+Shift+S")
        self.act_example = A("Open &example: 555 LED flasher", self.open_example, None, "board")
        self.act_export = A("Export &Gerbers, drills, BOM && CPL…", self.export_fab, "Ctrl+E", "gerber")
        self.act_quit = A("E&xit", self.close, "Ctrl+Q")
        self.act_undo = A("&Undo", self.doc.undo, "Ctrl+Z", "undo")
        self.act_redo = A("&Redo", self.doc.redo, "Ctrl+Y", "redo")
        self.act_rotate = A("&Rotate 90°\tR", lambda: rotate_items(self.doc, self.doc.selection, 90), None, "rotate",
                            tip="Rotate selection (R)")
        self.act_flip = A("&Flip side\tF", lambda: flip_items(self.doc, self.doc.selection), None, "flip",
                          tip="Flip selection to the other side (F)")
        self.act_delete = A("&Delete\tDel", lambda: delete_items(self.doc, self.doc.selection), None, "delete",
                            tip="Delete selection (Del)")
        self.act_duplicate = A("D&uplicate", lambda: duplicate_items(self.doc, self.doc.selection), "Ctrl+D")
        self.act_select_all = A("Select &all", self.select_all, "Ctrl+A")
        self.act_props = A("&Properties…\tE", lambda: (self.props_dock.show(), self.props_dock.raise_()))
        self.act_fit = A("&Fit board\tHome", self.canvas.fit_board, None, "fit", tip="Fit board in view (Home)")
        self.act_3d = A("&3D view", self.toggle_3d, "F3", "cube", tip="3D view (F3)")
        self.act_order = A("&Order PCBs…", lambda: self.tabs.setCurrentWidget(self.order_page), "Ctrl+Shift+O", "order",
                           tip="Compare fabs and order boards")
        self.act_autoroute = A("&Autoroute…", self.autoroute, "Ctrl+Shift+A", "autoroute", tip="Autoroute (Ctrl+Shift+A)")
        self.act_drc = A("Run &DRC", self.run_drc, "F8", "drc", tip="Design rule check (F8)")
        self.act_refill = A("Refill &zones", self.doc.refill_zones, "Ctrl+B", "refill", tip="Refill copper zones (Ctrl+B)")
        self.act_board = A("&Board size…", self.board_setup, None, "board")
        self.act_pour = A("Add &ground pour on active layer", self.add_ground_pour, None, "zone")
        self.act_clear_tracks = A("&Remove all tracks && vias", self.clear_tracks)
        self.act_shortcuts = A("&Keyboard shortcuts", lambda: ShortcutsDialog(self).exec(), "F1")
        self.act_about = A(f"&About {APP_NAME}", lambda: AboutDialog(self).exec())
        self.tool_actions: dict[str, QAction] = {}
        group = QActionGroup(self)
        for name, text, ic, key in (("select", "Select / move", "select", "S"), ("route", "Route tracks", "route", "X"),
                                    ("via", "Place via", "via", "V"), ("zone", "Copper zone", "zone", "Z"),
                                    ("outline", "Board outline", "outline", "B"), ("text", "Text", "text", "T"),
                                    ("measure", "Measure", "measure", "M"), ("connect", "Connect pads (netlist)", "connect", "N")):
            a = A(f"{text}\t{key}", lambda _c=False, n=name: self.canvas.set_tool(n), None, ic, True, f"{text} ({key})")
            group.addAction(a)
            self.tool_actions[name] = a
        self.doc.state_changed.connect(self._update_undo)
        self._update_undo()

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&File")
        for a in (self.act_new, self.act_open, self.act_example):
            m.addAction(a)
        self.recent_menu = m.addMenu("Open &recent")
        self._fill_recent()
        m.addSeparator()
        m.addAction(self.act_save)
        m.addAction(self.act_save_as)
        m.addSeparator()
        m.addAction(self.act_export)
        m.addSeparator()
        m.addAction(self.act_quit)
        m = mb.addMenu("&Edit")
        for a in (self.act_undo, self.act_redo, None, self.act_rotate, self.act_flip, self.act_duplicate, self.act_delete,
                  None, self.act_select_all, self.act_props):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("&Place")
        for name in ("route", "via", "zone", "outline", "text", "connect"):
            m.addAction(self.tool_actions[name])
        m.addSeparator()
        m.addAction(self.act_pour)
        m = mb.addMenu("&View")
        m.addAction(self.act_fit)
        m.addAction(self.act_3d)
        m.addSeparator()
        for d in (self.lib_dock, self.nets_dock, self.props_dock, self.layers_dock, self.drc_dock):
            m.addAction(d.toggleViewAction())
        m = mb.addMenu("&Library")
        m.addAction(icon("library"), "Find a part…", lambda: (self.lib_dock.show(), self.lib_dock.raise_(),
                                                              self.library.search.setFocus()))
        m.addSeparator()
        m.addAction(icon("order"), "Import any LCSC / JLCPCB part (C-number)…", lambda: self.library_action("lcsc"))
        m.addAction("Search LCSC website…", lambda: self.library_action("lcsc"))
        m.addAction(icon("layers"), "KiCad footprint libraries…", lambda: self.library_action("kicad"))
        m.addAction("Import KiCad footprint file (.kicad_mod)…", lambda: self.library_action("kicad_file"))
        m.addAction(icon("place"), "Footprint wizard…", lambda: self.library_action("wizard"))
        m.addSeparator()
        m.addAction("Open My library folder", lambda: self.library_action("folder"))
        m.addAction("Reload libraries", lambda: self.library_action("reload"))
        m = mb.addMenu("&Tools")
        for a in (self.act_board, None, self.act_autoroute, self.act_refill, self.act_drc, None, self.tool_actions["measure"],
                  None, self.act_clear_tracks):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("&Order")
        m.addAction(self.act_order)
        m.addAction(self.act_export)
        m = mb.addMenu("&Help")
        m.addAction(self.act_shortcuts)
        m.addAction(self.act_about)

    def _build_toolbars(self):
        tb = QToolBar("Main")
        tb.setObjectName("main_tb")
        tb.setIconSize(QSize(22, 22))
        tb.setMovable(False)
        self.addToolBar(tb)
        for a in (self.act_new, self.act_open, self.act_save, None, self.act_undo, self.act_redo, None):
            tb.addSeparator() if a is None else tb.addAction(a)
        for name in ("select", "route", "via", "zone", "outline", "text", "measure", "connect"):
            tb.addAction(self.tool_actions[name])
        tb.addSeparator()
        for a in (self.act_rotate, self.act_flip, self.act_delete, None, self.act_autoroute, self.act_refill, self.act_drc,
                  None, self.act_fit):
            tb.addSeparator() if a is None else tb.addAction(a)
        tb.addSeparator()
        lab = QLabel(" Grid ")
        lab.setProperty("muted", True)
        tb.addWidget(lab)
        self.grid_combo = QComboBox()
        for text, v in GRIDS:
            self.grid_combo.addItem(text, v)
        self.grid_combo.setCurrentIndex(3)
        self.grid_combo.currentIndexChanged.connect(self._grid_changed)
        tb.addWidget(self.grid_combo)
        lab = QLabel("  Layer ")
        lab.setProperty("muted", True)
        tb.addWidget(lab)
        self.layer_combo = QComboBox()
        self._fill_layer_combo()
        self.layer_combo.currentTextChanged.connect(lambda t: t and self.canvas.set_active_layer(t))
        self.canvas.layer_changed.connect(lambda L: self.layer_combo.setCurrentText(L))
        self.doc.replaced.connect(self._fill_layer_combo)
        self.doc.changed.connect(self._maybe_fill_layer_combo)
        tb.addWidget(self.layer_combo)
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy().Expanding, spacer.sizePolicy().verticalPolicy())
        tb.addWidget(spacer)
        tb.addAction(self.act_3d)
        tb.addAction(self.act_order)
        tb.setToolButtonStyle(Qt.ToolButtonIconOnly)
        for a in (self.act_3d, self.act_order, self.act_autoroute):
            w = tb.widgetForAction(a)
            if w is not None:
                w.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.act_3d.setIconText("3D")
        self.act_order.setIconText("Order")
        self.act_autoroute.setIconText("Autoroute")

    def _fill_layer_combo(self):
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        self.layer_combo.addItems(self.doc.project.copper_layers)
        self.layer_combo.setCurrentText(self.canvas.active_layer)
        self.layer_combo.blockSignals(False)

    def _maybe_fill_layer_combo(self):
        if self.layer_combo.count() != len(self.doc.project.copper_layers):
            self._fill_layer_combo()

    def _build_statusbar(self):
        sb = self.statusBar()
        self.hint_label = QLabel()
        self.pos_label = QLabel("X 0.000  Y 0.000 mm")
        self.layer_label = QLabel(f"Layer: {self.canvas.active_layer}")
        self.count_label = QLabel()
        self.pos_label.setMinimumWidth(210)
        sb.addWidget(self.hint_label, 1)
        sb.addPermanentWidget(self.count_label)
        sb.addPermanentWidget(self.layer_label)
        sb.addPermanentWidget(self.pos_label)

    # ------------------------------------------------------------------ state
    def _update_title(self):
        self.setWindowTitle(f"{self.doc.title} — {APP_NAME}")

    def _update_undo(self):
        self.act_undo.setEnabled(self.doc.can_undo())
        self.act_redo.setEnabled(self.doc.can_redo())

    def _update_counts(self):
        from ..model.connectivity import get_connectivity
        p = self.doc.project
        try:
            unr = get_connectivity(p).unrouted_count()
        except Exception:
            unr = "?"
        col = "#3fcf8e" if unr == 0 else "#f5b83d"
        self.count_label.setText(f"{len(p.components)} parts · {len(p.tracks)} tracks · {len(p.vias)} vias · "
                                 f"<span style='color:{col}'>{unr} unrouted</span>")

    def _tool_changed(self, name):
        a = self.tool_actions.get(name)
        if a:
            a.setChecked(True)
        elif name == "place":
            for a in self.tool_actions.values():
                a.setChecked(False)

    def _grid_changed(self, i):
        self.canvas.grid = self.grid_combo.itemData(i)
        self.canvas.update()

    def _canvas_key(self, ev) -> bool:
        if ev.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            return False
        k = ev.key()
        tools = {Qt.Key_S: "select", Qt.Key_X: "route", Qt.Key_V: "via", Qt.Key_Z: "zone", Qt.Key_B: "outline",
                 Qt.Key_T: "text", Qt.Key_M: "measure", Qt.Key_N: "connect"}
        if k in tools:
            self.canvas.set_tool(tools[k])
            return True
        if k == Qt.Key_Escape and self.canvas.tool is not self.canvas.tools["select"]:
            self.canvas.set_tool("select")
            return True
        sel = self.doc.selection
        if k == Qt.Key_R and sel:
            rotate_items(self.doc, sel, -90 if ev.modifiers() & Qt.ShiftModifier else 90)
            return True
        if k == Qt.Key_F and sel:
            flip_items(self.doc, sel)
            return True
        if k in (Qt.Key_Delete, Qt.Key_Backspace) and sel:
            delete_items(self.doc, sel)
            return True
        if k == Qt.Key_E and sel:
            self.props_dock.show()
            self.props_dock.raise_()
            return True
        if k == Qt.Key_P:
            self.library._place()
            return True
        return False

    # ------------------------------------------------------------------ commands
    def highlight_net(self, net):
        self.canvas.highlight_net = net
        self.canvas.update()

    def place_part(self, part):
        try:
            fp = part.make()
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Could not load footprint for {part.name}:\n{e}")
            return
        self.tabs.setCurrentWidget(self.canvas)
        self.canvas.set_tool("place", footprint=fp, prefix=part.prefix, value=part.value, mpn=part.mpn, lcsc=part.lcsc)
        self.canvas.setFocus()

    # ------------------------------------------------------------------ library management
    def library_action(self, key: str):
        from . import library_dialogs as ld
        if key == "lcsc":
            dlg = ld.LcscImportDialog(self)
            if dlg.exec() and dlg.saved_name:
                self._library_saved(dlg.saved_name, dlg.place_after)
        elif key == "kicad":
            dlg = ld.KicadLibraryDialog(self.lib_index, self)
            dlg.exec()
            if dlg.changed:
                self.settings.setValue("kicad_dirs", json.dumps(self.lib_index.kicad_dirs))
                self.library.refresh()
        elif key == "kicad_file":
            name = ld.import_kicad_file(self)
            if name:
                self._library_saved(name, False)
        elif key == "wizard":
            dlg = ld.FootprintWizardDialog(self)
            if dlg.exec() and dlg.saved_name:
                self._library_saved(dlg.saved_name, dlg.place_after)
        elif key == "folder":
            ld.open_library_folder()
        elif key == "compare":
            part = self.library.current_part()
            if part is not None:
                ld.CompareDialog(part, self.lib_index, self).exec()
        elif key == "reload":
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self.lib_index.reload_user()
                self.lib_index.reload_kicad()
            finally:
                QApplication.restoreOverrideCursor()
            self.library.refresh()

    def _library_saved(self, name: str, place: bool):
        self.lib_index.reload_user()
        self.lib_dock.show()
        self.lib_dock.raise_()
        self.library.select_part(name)
        self.statusBar().showMessage(f"Saved '{name}' to My library", 5000)
        if place:
            part = next((p for p in self.lib_index.user if p.name == name), None)
            if part is not None:
                self.place_part(part)

    def _delete_library_part(self, part):
        from ..library.userlib import delete_part
        if QMessageBox.question(self, APP_NAME, f"Delete '{part.name}' from My library?") == QMessageBox.Yes:
            delete_part(part)
            self.lib_index.reload_user()
            self.library.refresh()

    def select_all(self):
        p = self.doc.project
        self.doc.set_selection(list(p.components) + list(p.tracks) + list(p.vias) + list(p.texts))

    def toggle_3d(self):
        self.tabs.setCurrentWidget(self.page3d if self.tabs.currentWidget() is not self.page3d else self.canvas)

    def run_drc(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if self.doc.project.fills_stale:
                self.doc.refill_zones()
            viol = run_drc(self.doc.project)
        finally:
            QApplication.restoreOverrideCursor()
        self.canvas.drc_markers = viol
        self.drc.set_results(viol)
        self.drc_dock.show()
        self.drc_dock.raise_()
        self.canvas.update()
        errs = sum(1 for v in viol if v.severity == "error")
        self.statusBar().showMessage(f"DRC finished: {errs} errors, {len(viol) - errs} warnings", 5000)
        self.order_page._last_drc = [v for v in viol if v.kind != "unrouted"]

    def _goto_violation(self, v):
        self.tabs.setCurrentWidget(self.canvas)
        self.canvas.focus_marker = (v.x, v.y)
        self.canvas.zoom_to(v.x, v.y, max(self.canvas.scale, 30))
        items = [it for it in (self.doc.project.find(u) for u in v.uids) if it is not None]
        if items:
            self.doc.set_selection(items)

    def autoroute(self):
        dlg = AutorouteDialog(self.doc.project, self)
        if dlg.exec() and dlg.result is not None:
            r = dlg.result
            with self.doc.edit("Autoroute"):
                self.doc.project.tracks.extend(r.tracks)
                self.doc.project.vias.extend(r.vias)
            self.doc.refill_zones()
            msg = f"Autorouter: {r.routed} connections routed with {len(r.tracks)} tracks and {len(r.vias)} vias."
            if r.failed:
                msg += f" {r.failed} connection(s) could not be routed (nets: {', '.join(r.failed_nets[:6])})."
            self.statusBar().showMessage(msg, 12000)
            if r.failed:
                QMessageBox.information(self, "Autorouter", msg + "\n\nTry moving parts apart, a finer grid, or route "
                                                                  "the remaining connections manually.")

    def add_ground_pour(self):
        p = self.doc.project
        nets = p.nets()
        net = "GND" if "GND" in nets else (nets[0] if nets else None)
        with self.doc.edit("Add ground pour"):
            p.zones.append(Zone(self.canvas.active_layer, net, list(p.board.outline)))
        self.doc.refill_zones()

    def clear_tracks(self):
        if QMessageBox.question(self, "Remove routing", "Remove all tracks and vias?") == QMessageBox.Yes:
            with self.doc.edit("Remove all tracks"):
                self.doc.project.tracks.clear()
                self.doc.project.vias.clear()

    def board_setup(self):
        dlg = NewBoardDialog(self, "Board size", self.doc.project)
        if dlg.exec():
            v = dlg.values()
            b = self.doc.project.board
            x0, y0, _, _ = b.bounds()
            with self.doc.edit("Board size"):
                b.outline = rounded_rect_points(x0, y0, v["width"], v["height"], v["radius"])
                b.layers = v["layers"]
                b.thickness = v["thickness"]
            self.canvas.fit_board()

    # ------------------------------------------------------------------ files
    def _confirm_discard(self) -> bool:
        if not self.doc.dirty:
            return True
        r = QMessageBox.question(self, APP_NAME, "Save changes to the current design?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def new_board(self):
        if not self._confirm_discard():
            return
        dlg = NewBoardDialog(self)
        if not dlg.exec():
            return
        v = dlg.values()
        p = blank_project(v["width"], v["height"], v["radius"], v["layers"], v["thickness"], v["name"])
        if v["holes"]:
            m = 3.5
            for i, (x, y) in enumerate(((m, m), (v["width"] - m, m), (m, v["height"] - m), (v["width"] - m, v["height"] - m)), 1):
                c = Component(f"H{i}", "M3", fplib.mounting_hole("M3", False), x, y)
                c.show_ref = False
                p.components.append(c)
        if v["pour"]:
            p.extra_nets.append("GND")
            p.zones.append(Zone(p.copper_layers[-1], "GND", list(p.board.outline)))
        self.doc.set_project(p)
        self.canvas.fit_board()

    def open_file(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open project", str(self._last_dir()), FILE_FILTER + ";;All files (*)")
        if path:
            self.load_path(path)

    def load_path(self, path: str) -> bool:
        try:
            self.doc.open(path)
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Could not open {path}:\n{e}")
            return False
        self._add_recent(path)
        self.canvas.drc_markers = []
        self.canvas.fit_board()
        return True

    def open_example(self):
        if not self._confirm_discard():
            return
        examples = list_examples()
        p = load_example(examples[0]) if examples else flasher_555()
        self.doc.set_project(p)
        self.canvas.drc_markers = []
        self.canvas.fit_board()

    def save(self) -> bool:
        if self.doc.path is None:
            return self.save_as()
        try:
            self.doc.save()
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Could not save:\n{e}")
            return False
        self.statusBar().showMessage(f"Saved {self.doc.path}", 3000)
        return True

    def save_as(self) -> bool:
        start = self._last_dir() / (self.doc.project.name.replace(" ", "_") + FILE_EXT)
        path, _ = QFileDialog.getSaveFileName(self, "Save project", str(start), FILE_FILTER)
        if not path:
            return False
        if not path.lower().endswith(FILE_EXT):
            path += FILE_EXT
        try:
            self.doc.save(path)
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Could not save:\n{e}")
            return False
        self._add_recent(path)
        return True

    def export_fab(self):
        zp = self.order_page.export_files()
        if zp:
            self.order_page._open_folder()
            self.statusBar().showMessage(f"Manufacturing files written: {zp}", 8000)

    def _last_dir(self) -> Path:
        d = self.settings.value("last_dir")
        if d and Path(d).exists():
            return Path(d)
        p = Path.home() / "Documents" / "PCBPro"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def recent(self) -> list[str]:
        r = self.settings.value("recent", "[]")
        try:
            items = json.loads(r) if isinstance(r, str) else list(r)
        except ValueError:
            items = []
        return [x for x in items if Path(x).exists()]

    def _add_recent(self, path: str):
        path = str(Path(path).resolve())
        items = [path] + [x for x in self.recent() if x != path]
        self.settings.setValue("recent", json.dumps(items[:10]))
        self.settings.setValue("last_dir", str(Path(path).parent))
        self._fill_recent()

    def _fill_recent(self):
        self.recent_menu.clear()
        items = self.recent()
        for path in items:
            self.recent_menu.addAction(Path(path).name, lambda p=path: self._confirm_discard() and self.load_path(p))
        self.recent_menu.setEnabled(bool(items))

    def show_welcome(self):
        dlg = WelcomeDialog(self.recent(), self)
        if not dlg.exec():
            return
        if dlg.choice == "new":
            self.new_board()
        elif dlg.choice in ("pedal", "pedal_example"):
            from . import pedal_ui
            (pedal_ui.new_pedal if dlg.choice == "pedal" else pedal_ui.open_pedal_example)(self)
        elif dlg.choice == "amp":
            from .amp_designer import open_designer
            open_designer(self)
        elif dlg.choice == "open":
            self.open_file()
        elif dlg.choice == "example":
            self.open_example()
        elif dlg.choice == "recent" and dlg.path:
            self.load_path(dlg.path)

    def closeEvent(self, ev):
        if not self._confirm_discard():
            ev.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        ev.accept()
