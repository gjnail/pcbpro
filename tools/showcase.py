"""Place a wide variety of library parts on one board and screenshot it (visual check of footprints + 3D)."""
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

from pcbpro.model.board import Component  # noqa: E402
from pcbpro.model.footprints import find_part  # noqa: E402
from pcbpro.ui.document import blank_project  # noqa: E402
from pcbpro.ui.main_window import MainWindow  # noqa: E402
from pcbpro.ui.theme import apply_theme  # noqa: E402

NAMES = [
    "Resistor 0402", "Resistor 0805", "Capacitor 1206", "Tantalum case B (3528-21)", "Electrolytic SMD 6.3x5.4",
    "Power inductor 6x6x4.5", "LED 0805", "WS2812B 5050 addressable", "LED PLCC-2 2835", "Diode SMA",
    "SOT-23", "SOT-223", "SOT-89-3", "TO-252 (DPAK)", "TO-263-5 (D2PAK)", "PowerPAK SO-8 5x6 (DFN5x6)",
    "SOIC-8", "TSSOP-20", "SSOP-28", "LQFP-48 7x7 P0.5", "LQFP-100 14x14 P0.5", "QFN-32 5x5 P0.5",
    "BGA-256 17x17 P1.0", "PLCC-44", "Crystal / oscillator SMD 3.2x2.5 (4 pads)", "Tactile switch SMD 6x6",
    "USB-C receptacle 16P (USB 2.0)", "USB Micro-B receptacle", "JST SH 4-pin SMD", "FFC/FPC 20-pin P0.5",
    "microSD socket", "U.FL / IPEX receptacle", "SMA edge mount", "CR2032 holder SMD",
    "DIP-16 (300 mil)", "Pin header 2x5 P2.54", "Pin socket 1x6 P2.54", "IDC box header 2x5", "JST XH 3-pin",
    "Screw terminal 3-pin P5.08", "DC barrel jack 5.5x2.1", "RJ45 8P8C shielded", "Electrolytic D8 P3.5 H11.5",
    "Film box L13 W5 P10", "Ceramic disc D5 W2.5 P5", "Resistor axial 1/4 W P10.16", "Diode DO-41",
    "LED 5 mm THT", "TO-220-3 vertical", "TO-92 inline", "Relay SPDT Songle SRD (10 A)", "Trimmer 3296W multi-turn",
    "Rotary encoder EC11 with switch", "DIP switch 4-position THT", "Buzzer D12 P6.5", "Crystal HC-49/US (low profile)",
    "D-Sub 9 female", "ESP32-WROOM-32 module", "Slide switch SPDT THT", "Toroid vertical D14",
]

p = blank_project(160, 110, 3.0, name="Library showcase")
x, y, row_h = 8.0, 10.0, 0.0
for name in NAMES:
    part = find_part(name)
    if part is None:
        print("missing", name)
        continue
    fp = part.make()
    x0, y0, x1, y1 = fp.courtyard
    w, h = x1 - x0, y1 - y0
    if x + w > 154:
        x = 8.0
        y += row_h + 3.0
        row_h = 0.0
    c = Component(p.next_ref(part.prefix), part.value, fp, round(x - x0, 2), round(y - y0, 2))
    p.components.append(c)
    x += w + 3.0
    row_h = max(row_h, h)
print("placed", len(p.components), "parts; last row ends at y =", round(y + row_h, 1))

apply_theme(app)
win = MainWindow()
win.resize(1600, 950)
win.show()
win.doc.set_project(p)


def shot3d(view, name, dist=None):
    def f():
        win.tabs.setCurrentWidget(win.page3d)
        win.page3d.view.set_view(view)
        if dist:
            win.page3d.view.dist *= dist
    def g():
        win.page3d.view.grabFramebuffer().save(str(out / f"{name}.png"))
        print("saved", name)
    return f, g


seq = [(300, lambda: win.canvas.fit_board()), (300, lambda: win.grab().save(str(out / "showcase_layout.png")))]
for view, name, dist in (("iso", "showcase_iso", None), ("top", "showcase_top", None)):
    f, g = shot3d(view, name, dist)
    seq += [(100, f), (1500, g)]


def zoom():
    v = win.page3d.view
    v.yaw, v.pitch = -30, 38
    v.target[0], v.target[1] = 60.0, -25.0
    v.dist = 75
    v.update()


seq += [(100, zoom), (900, lambda: win.page3d.view.grabFramebuffer().save(str(out / "showcase_zoom.png")))]
seq += [(100, lambda: (win.tabs.setCurrentWidget(win.canvas), win.library.search.setText("usb"))),
        (600, lambda: win.grab().save(str(out / "showcase_library_search.png"))), (100, app.quit)]
t = 0
for d, fn in seq:
    t += d
    QTimer.singleShot(t, fn)
app.exec()
