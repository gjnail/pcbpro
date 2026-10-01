"""Dialogs: new board, zone properties, autorouter progress, shortcuts, about, welcome."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..model.board import Project, Zone
from ..route.autorouter import Autorouter, RouteResult
from .icons import app_icon, icon


def _mm(value, lo=0.0, hi=1000.0, step=0.5, dec=2) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setSuffix(" mm")
    s.setValue(value)
    return s


class NewBoardDialog(QDialog):
    PRESETS = [("Custom", None), ("50 × 50 mm (cheapest fab tier)", (50, 50)), ("100 × 100 mm (fab sweet spot)", (100, 100)),
               ("100 × 80 mm (Eurocard half)", (100, 80)), ("68.6 × 53.3 mm (Arduino Uno size)", (68.58, 53.34)),
               ("65 × 30 mm (Raspberry Pi HAT-mini)", (65, 30)), ("30 × 20 mm (tiny breakout)", (30, 20))]

    def __init__(self, parent=None, title="New board", project: Project | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.preset = QComboBox()
        self.preset.addItems([n for n, _ in self.PRESETS])
        self.name = QComboBox()
        self.name.setEditable(True)
        self.name.setCurrentText(project.name if project else "My Board")
        b = project.board if project else None
        self.w = _mm(b.width if b else 60, 5, 600)
        self.h = _mm(b.height if b else 40, 5, 600)
        self.r = _mm(1.5, 0, 50, 0.5)
        self.layers = QComboBox()
        self.layers.addItems(["2", "4"])
        self.layers.setCurrentText(str(b.layers if b else 2))
        self.thick = QComboBox()
        self.thick.addItems(["0.8", "1.0", "1.2", "1.6", "2.0"])
        self.thick.setCurrentText(f"{b.thickness:g}" if b else "1.6")
        self.holes = QCheckBox("Add M3 mounting holes in the corners")
        self.pour = QCheckBox("Add GND copper pour on the bottom layer")
        if project is None:
            form.addRow("Name", self.name)
        form.addRow("Preset", self.preset)
        form.addRow("Width", self.w)
        form.addRow("Height", self.h)
        form.addRow("Corner radius", self.r)
        form.addRow("Copper layers", self.layers)
        form.addRow("Thickness (mm)", self.thick)
        lay.addLayout(form)
        if project is None:
            lay.addWidget(self.holes)
            lay.addWidget(self.pour)
            self.pour.setChecked(True)
        self.preset.currentIndexChanged.connect(self._preset)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _preset(self, i):
        size = self.PRESETS[i][1]
        if size:
            self.w.setValue(size[0])
            self.h.setValue(size[1])

    def values(self) -> dict:
        return {"name": self.name.currentText().strip() or "My Board", "width": self.w.value(), "height": self.h.value(),
                "radius": self.r.value(), "layers": int(self.layers.currentText()), "thickness": float(self.thick.currentText()),
                "holes": self.holes.isChecked(), "pour": self.pour.isChecked()}


class ZoneDialog(QDialog):
    def __init__(self, project: Project, zone: Zone | None, layer: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Copper zone")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.net = QComboBox()
        self.net.setEditable(True)
        nets = project.nets()
        self.net.addItems(["<no net>"] + nets)
        default = zone.net if zone else ("GND" if "GND" in nets else "")
        if default:
            self.net.setCurrentText(default)
        self.layer = QComboBox()
        self.layer.addItems(project.copper_layers)
        self.layer.setCurrentText(zone.layer if zone else layer)
        self.clear = _mm(zone.clearance if zone else 0.3, 0.05, 5, 0.05)
        self.minw = _mm(zone.min_width if zone else 0.25, 0.05, 5, 0.05)
        self.prio = QSpinBox()
        self.prio.setRange(0, 100)
        self.prio.setValue(zone.priority if zone else 0)
        self.thermal = QCheckBox("Thermal relief on through-hole pads")
        self.thermal.setChecked(zone.thermal if zone else True)
        form.addRow("Net", self.net)
        form.addRow("Layer", self.layer)
        form.addRow("Clearance", self.clear)
        form.addRow("Minimum width", self.minw)
        form.addRow("Priority", self.prio)
        lay.addLayout(form)
        lay.addWidget(self.thermal)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def make_zone(self, pts) -> Zone:
        net = self.net.currentText().strip()
        return Zone(self.layer.currentText(), None if net in ("", "<no net>") else net, [tuple(p) for p in pts],
                    clearance=self.clear.value(), min_width=self.minw.value(), priority=self.prio.value(),
                    thermal=self.thermal.isChecked())


# --------------------------------------------------------------------------- autorouter

class _RouteWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)

    def __init__(self, project: Project, opts: dict):
        super().__init__()
        self.project = project
        self.opts = opts
        self.cancel = False

    def run(self):
        try:
            r = Autorouter(self.project, progress=lambda a, b, m: self.progress.emit(a, b, m),
                           cancelled=lambda: self.cancel, **self.opts).run()
        except Exception as e:  # report instead of crashing the worker thread
            r = RouteResult()
            r.failed_nets = [f"error: {e}"]
        self.finished.emit(r)


class AutorouteDialog(QDialog):
    """Runs the autorouter on a copy of the design in a background thread."""

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Autorouter")
        self.setMinimumWidth(460)
        self.source = project
        self.result: RouteResult | None = None
        self.work: Project | None = None
        lay = QVBoxLayout(self)
        info = QLabel("Routes all unrouted connections with 45° tracks and vias on a grid, respecting the net "
                      "class widths and clearances. Nets with a copper pour (e.g. GND) are connected last with "
                      "short stubs and vias into the pour.")
        info.setWordWrap(True)
        info.setProperty("muted", True)
        lay.addWidget(info)
        form = QFormLayout()
        self.grid = QComboBox()
        self.grid.addItems(["Auto", "0.1 mm (fine, slow)", "0.15 mm", "0.2 mm", "0.25 mm", "0.5 mm (coarse, fast)"])
        self.via_cost = QComboBox()
        self.via_cost.addItems(["Normal", "Avoid vias", "Prefer vias"])
        self.pour = QCheckBox("Connect pour nets with stubs")
        self.pour.setChecked(True)
        form.addRow("Routing grid", self.grid)
        form.addRow("Via usage", self.via_cost)
        form.addRow("", self.pour)
        lay.addLayout(form)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        lay.addWidget(self.bar)
        self.status = QLabel("Ready")
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch(1)
        self.start_btn = QPushButton("Start routing")
        self.start_btn.setProperty("primary", True)
        self.start_btn.setIcon(icon("autoroute"))
        self.cancel_btn = QPushButton("Cancel")
        row.addWidget(self.start_btn)
        row.addWidget(self.cancel_btn)
        lay.addLayout(row)
        self.start_btn.clicked.connect(self.start)
        self.cancel_btn.clicked.connect(self._cancel)
        self.thread = None
        self.worker = None

    def start(self):
        grid = {0: None, 1: 0.1, 2: 0.15, 3: 0.2, 4: 0.25, 5: 0.5}[self.grid.currentIndex()]
        via = {0: 10.0, 1: 30.0, 2: 4.0}[self.via_cost.currentIndex()]
        self.work = self.source.clone()
        self.worker = _RouteWorker(self.work, {"grid": grid, "via_cost": via, "route_pour_nets": self.pour.isChecked()})
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._progress)
        self.worker.finished.connect(self._done)
        self.start_btn.setEnabled(False)
        self.grid.setEnabled(False)
        self.status.setText("Routing…")
        self.thread.start()

    def _progress(self, a, b, msg):
        self.bar.setRange(0, max(b, 1))
        self.bar.setValue(a)
        self.status.setText(f"{msg}  ({a}/{b})")

    def _done(self, result: RouteResult):
        self.result = result
        self.thread.quit()
        self.thread.wait()
        self.thread = None
        if result.failed_nets and str(result.failed_nets[0]).startswith("error:"):
            self.status.setText(f"Autorouter error: {result.failed_nets[0][6:]}")
            self.result = None
            self.start_btn.setEnabled(True)
            return
        if result.cancelled:
            self.status.setText("Cancelled")
            self.result = None
            self.reject()
            return
        self.accept()

    def _cancel(self):
        if self.worker is not None and self.thread is not None:
            self.worker.cancel = True
            self.status.setText("Cancelling…")
        else:
            self.reject()

    def closeEvent(self, ev):
        if self.thread is not None:
            self.worker.cancel = True
            self.thread.quit()
            self.thread.wait()
        super().closeEvent(ev)


# --------------------------------------------------------------------------- info dialogs

SHORTCUTS = [
    ("Tools", ""), ("S / Esc", "Select & move"), ("X", "Route tracks"), ("V", "Place via (while routing: via + layer change)"),
    ("Z", "Copper zone"), ("B", "Board outline"), ("T", "Text"), ("M", "Measure"), ("N", "Connect pads (edit netlist)"),
    ("P", "Place selected library part"),
    ("Editing", ""), ("R / Shift+R", "Rotate selection ±90°"), ("F", "Flip to other side"), ("Del", "Delete"),
    ("Ctrl+D", "Duplicate"), ("Arrows", "Nudge by grid (Shift ×10)"), ("U", "Select whole trace"),
    ("E / double-click", "Properties"), ("Ctrl+Z / Ctrl+Y", "Undo / redo"),
    ("Routing", ""), ("W / Shift+W", "Wider / narrower track"), ("/", "Toggle 45° posture"),
    ("Backspace", "Remove last corner"), ("Enter / double-click", "Finish route"),
    ("View", ""), ("Wheel", "Zoom at cursor"), ("Middle / right drag, Space+drag", "Pan"), ("Home", "Fit board"),
    ("L, PgUp, PgDn", "Switch active copper layer"), ("F3", "Toggle 3D view"), ("F8", "Run DRC"),
    ("3D view", ""), ("Left drag", "Orbit"), ("Right drag", "Pan"), ("1 / 2 / 3 / 0", "Top / bottom / front / iso"),
    ("Simulation", ""), ("F5", "Run / pause the circuit"), ("Shift+F5 / Esc", "Stop the simulation"),
    ("Click / hold", "Operate a switch / press a button"), ("Drag or wheel on a pot", "Turn the knob"),
    ("Double-click a net", "Probe it on the oscilloscope"),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard shortcuts")
        self.setMinimumSize(520, 640)
        lay = QVBoxLayout(self)
        grid = QGridLayout()
        for r, (k, d) in enumerate(SHORTCUTS):
            if not d:
                lab = QLabel(f"<b>{k}</b>")
                lab.setStyleSheet("margin-top:8px; color:#4c9aff;")
                grid.addWidget(lab, r, 0, 1, 2)
            else:
                kl = QLabel(f"<code>{k}</code>")
                grid.addWidget(kl, r, 0)
                grid.addWidget(QLabel(d), r, 1)
        lay.addLayout(grid)
        lay.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(app_icon().pixmap(72, 72))
        top.addWidget(ic)
        txt = QLabel(f"<h2>{APP_NAME} {__version__}</h2>"
                     "<p>PCB layout, 3D visualisation and fabrication ordering in one desktop application.</p>"
                     "<p>Built with Qt (PySide6), OpenGL and Shapely.</p>"
                     "<p style='color:#8b93a1'>Always verify footprints against datasheets and check the fab's "
                     "Gerber viewer before paying for an order.</p>")
        txt.setWordWrap(True)
        top.addWidget(txt, 1)
        lay.addLayout(top)
        bb = QDialogButtonBox(QDialogButtonBox.Ok)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)


class WelcomeDialog(QDialog):
    """Start screen: new board, open, example or recent file."""

    def __init__(self, recent: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Welcome to {APP_NAME}")
        self.setMinimumSize(620, 380)
        self.choice = None
        self.path = None
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(64, 64))
        left.addWidget(logo)
        title = QLabel(f"<h1 style='margin:0'>{APP_NAME}</h1><p style='color:#8b93a1'>Design · Visualise · Order</p>")
        left.addWidget(title)
        for text, key, ic in (("New pedal…", "pedal", "pedal"), ("New amp (guitar / bass)…", "amp", "amp"),
                              ("New board…", "new", "new"),
                              ("Open project…", "open", "open"),
                              ("Open the overdrive pedal example", "pedal_example", "pedal"),
                              ("Open the 555 flasher example", "example", "board")):
            b = QPushButton(text)
            b.setIcon(icon(ic))
            b.setMinimumHeight(36)
            if key == "pedal":
                b.setProperty("primary", True)
            b.clicked.connect(lambda _c=False, k=key: self._pick(k))
            left.addWidget(b)
        left.addStretch(1)
        lay.addLayout(left, 1)
        right = QVBoxLayout()
        lab = QLabel("Recent projects")
        lab.setProperty("muted", True)
        right.addWidget(lab)
        self.list = QListWidget()
        for r in recent:
            it = QListWidgetItem(r)
            self.list.addItem(it)
        if not recent:
            it = QListWidgetItem("No recent projects yet")
            it.setFlags(Qt.NoItemFlags)
            self.list.addItem(it)
        self.list.itemDoubleClicked.connect(lambda it: self._recent(it))
        right.addWidget(self.list, 1)
        lay.addLayout(right, 1)

    def _pick(self, key):
        self.choice = key
        self.accept()

    def _recent(self, it):
        if it.flags() & Qt.ItemIsEnabled:
            self.choice = "recent"
            self.path = it.text()
            self.accept()
