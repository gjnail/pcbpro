"""Launch the app, load the example and save screenshots of each page (used for visual checks)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QSurfaceFormat  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
out.mkdir(parents=True, exist_ok=True)
fmt = QSurfaceFormat()
fmt.setVersion(3, 3)
fmt.setProfile(QSurfaceFormat.CoreProfile)
fmt.setDepthBufferSize(24)
fmt.setSamples(8)
QSurfaceFormat.setDefaultFormat(fmt)
app = QApplication(sys.argv)

from pcbpro.ui.main_window import MainWindow  # noqa: E402
from pcbpro.ui.theme import apply_theme  # noqa: E402

apply_theme(app)
win = MainWindow()
win.resize(1600, 950)
win.show()
win.open_example()
steps = []


def shot(name, widget=None):
    def f():
        (widget or win).grab().save(str(out / f"{name}.png"))
        print("saved", name)
    return f


def view3d(name, view):
    def f():
        win.tabs.setCurrentWidget(win.page3d)
        win.page3d.view.set_view(view)
    return f


def grab3d(name):
    def f():
        img = win.page3d.view.grabFramebuffer()
        img.save(str(out / f"{name}.png"))
        win.grab().save(str(out / f"{name}_window.png"))
        print("saved", name)
    return f


seq = [
    (400, lambda: win.canvas.fit_board()),
    (300, shot("layout")),
    (100, lambda: win.run_drc()),
    (300, shot("layout_drc")),
    (100, view3d("3d_iso", "iso")),
    (1500, grab3d("3d_iso")),
    (100, view3d("3d_top", "top")),
    (800, grab3d("3d_top")),
    (100, view3d("3d_bottom", "bottom")),
    (800, grab3d("3d_bottom")),
    (100, lambda: win.tabs.setCurrentWidget(win.order_page)),
    (1200, shot("order")),
    (100, app.quit),
]
t = 0
for delay, fn in seq:
    t += delay
    QTimer.singleShot(t, fn)
app.exec()
