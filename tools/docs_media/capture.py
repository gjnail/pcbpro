"""Screenshots and screen recordings of PCBPro for the README, the guides and the website.

    python tools/docs_media/capture.py                 # everything
    python tools/docs_media/capture.py layout pedal-3d # the named shots and clips
    python tools/docs_media/capture.py --list

The app opens on screen for a minute or two while this runs: OpenGL needs a real window. It uses throwaway settings
(out/docs_media/settings.ini), so your recent files, window layout and cabinet list are left alone, and it never plays
sound. PNG screenshots go to out/docs_media/shots/ and the frames of each clip to out/docs_media/clips/NAME/; run
encode_media.py next to turn them into the WebP, MP4 and GIF files in docs/media. Use the app's environment (.venv).
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"  # 1:1 pixels, whatever the screen's scaling
os.environ["QT_SCALE_FACTOR"] = "1"

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "out" / "docs_media"
SHOTS = OUT / "shots"
CLIPS = OUT / "clips"
EXAMPLES = ROOT / "pcbpro" / "resources" / "examples"

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtGui import QSurfaceFormat  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

WIN_W, WIN_H = 1600, 1000

# ------------------------------------------------------------------------------------------------- the harness

_SETTINGS = OUT / "settings.ini"


class _Settings(QSettings):
    """Every QSettings the app opens goes to a throwaway INI file instead of the registry."""

    def __init__(self, *_a, **_k):
        super().__init__(str(_SETTINGS), QSettings.IniFormat)


def _patch() -> None:
    import numpy as np  # noqa: F401
    from pcbpro.sim import livefx
    from pcbpro.sim.cabinet import builtin_irs
    from pcbpro.ui import amp_listen, audio_ui, cab_ui, live_ui, main_window, shop
    for mod in (main_window, cab_ui, live_ui, shop):
        mod.QSettings = _Settings
    cab_ui.settings = lambda: _Settings()
    cab_ui.find_irs = lambda *a, **k: list(builtin_irs())  # never search this PC for IR files
    amp_listen.ListenPanel._play = lambda self, data: None  # never play sound
    audio_ui.AudioDialog._play = lambda self, data, ref=1.0: None
    def dev(index, name, hostapi, n_in, n_out):
        return {"index": index, "name": name, "hostapi": hostapi, "rate": 48000.0, "in": n_in, "out": n_out}
    devices = [dev(1, "Audio interface (Inputs 1+2)", 0, 2, 0), dev(2, "Audio interface (Outputs 1+2)", 0, 0, 2),
               dev(3, "Audio interface ASIO", 1, 2, 2)]
    fake = {"hostapis": [{"index": 0, "name": "Windows WASAPI", "default_in": 1, "default_out": 2},
                         {"index": 1, "name": "ASIO", "default_in": 3, "default_out": 3}],
            "inputs": [d for d in devices if d["in"]], "outputs": [d for d in devices if d["out"]]}
    livefx.list_devices = lambda: fake
    livefx.preferred_hostapi = lambda devs: 0


def start_app() -> QApplication:
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(8)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("PCBPro")
    _patch()
    from pcbpro.ui.icons import app_icon
    from pcbpro.ui.theme import apply_theme
    apply_theme(app)
    app.setWindowIcon(app_icon())
    return app


def wait(ms: int) -> None:
    QTest.qWait(ms)


def new_window():
    """A main window at the size of the screenshots. The central pages' own minimum widths are relaxed so the
    window can be WIN_W wide with the default docks."""
    from pcbpro.ui.main_window import MainWindow
    win = MainWindow()
    for i in range(win.tabs.count()):
        win.tabs.widget(i).setMinimumSize(1, 1)
    win.simctl.backend = "inprocess"
    win.move(20, 20)
    win.show()
    wait(300)
    win.resize(WIN_W, WIN_H)  # after show: the docks settle first
    wait(200)
    return win


def close_window(win) -> None:
    win.simctl.stop("")
    win.doc.dirty = False
    win.close()
    wait(100)


def load(win, file_name: str, grid: float | None = None):
    from pcbpro.examples import load_example
    win.doc.set_project(load_example(EXAMPLES / file_name))
    win.canvas.drc_markers = []
    if grid:
        from pcbpro.ui.pedal_ui import _set_grid
        _set_grid(win, grid)
    win.tabs.setCurrentWidget(win.canvas)
    wait(150)
    win.canvas.fit_board()
    wait(250)
    return win.doc.project


def save(img, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    img.save(str(SHOTS / f"{name}.png"))
    print("  shot", name, f"{img.width()}x{img.height()}", flush=True)


def grab(widget: QWidget, name: str) -> None:
    widget.repaint()
    wait(50)
    save(widget.grab(), name)


def show_dialog(dlg, w: int | None = None, h: int | None = None):
    if w and h:
        dlg.resize(w, h)
    dlg.move(60, 60)
    dlg.show()
    wait(400)
    return dlg


def view3d(win, w: int = 1280, h: int = 720):
    """A stand-alone 3D view of the window's document at an exact size, for 16:9 renders."""
    from pcbpro.ui.view3d import View3D
    v = View3D(win.doc)
    if hasattr(v, "set_simulation"):
        v.set_simulation(win.simctl)
    v.setWindowTitle("3D")
    v.resize(w, h)
    v.move(40, 40)
    v.show()
    wait(600)
    return v


def gl(v, name: str) -> None:
    v.update()
    wait(120)
    save(v.grabFramebuffer(), name)


class Clip:
    """Frames of a recording with the time each is shown for; encode_media.py turns them into MP4 and GIF."""

    def __init__(self, name: str, fps: float = 30.0):
        self.name, self.fps = name, fps
        self.dir = CLIPS / name
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True)
        self.frames: list[tuple[str, float]] = []
        self.t_last = None

    def add(self, img, duration: float | None = None) -> None:
        f = f"{len(self.frames):04d}.png"
        img.save(str(self.dir / f))
        self.frames.append((f, duration if duration is not None else 1.0 / self.fps))

    def add_timed(self, img) -> None:
        """A frame grabbed in real time: it lasts until the next one is grabbed."""
        now = time.perf_counter()
        if self.frames and self.t_last is not None:
            f, _ = self.frames[-1]
            self.frames[-1] = (f, now - self.t_last)
        self.t_last = now
        self.add(img, 1.0 / self.fps)

    def hold(self, seconds: float) -> None:
        if self.frames:
            f, d = self.frames[-1]
            self.frames[-1] = (f, d + seconds)

    def done(self, poster: int = 0) -> None:
        (self.dir / "frames.json").write_text(json.dumps({"frames": self.frames, "poster": poster}), encoding="utf-8")
        print("  clip", self.name, len(self.frames), "frames", f"{sum(d for _, d in self.frames):.1f} s", flush=True)


# ------------------------------------------------------------------------------------------------- shots

JOBS: dict[str, callable] = {}


def job(name: str):
    def deco(fn):
        JOBS[name] = fn
        return fn
    return deco


@job("welcome")
def _welcome(app):
    from pcbpro.ui.dialogs import WelcomeDialog
    recent = ["Three_Knob_Overdrive_125B.pcbpro", "Amp_Plexi_Crunch_50W.pcbpro", "555_LED_Flasher.pcbpro"]
    dlg = show_dialog(WelcomeDialog(recent), 760, 440)
    grab(dlg, "welcome")
    dlg.close()


@job("layout")
def _layout(app):
    """The editor with the 555 example: library, board, properties; plus the DRC panel and the library search."""
    win = new_window()
    load(win, "555_LED_Flasher.pcbpro")
    grab(win, "layout")
    win.library.search.setText("ne555")
    wait(500)
    win.library.select_part("NE555")
    wait(300)
    grab(win, "library-search")
    win.library.search.setText("")
    win.run_drc()
    wait(400)
    grab(win, "drc")
    close_window(win)


@job("ratsnest")
def _ratsnest(app):
    """An unrouted board: parts placed, the ratsnest showing what to connect."""
    win = new_window()
    p = load(win, "555_LED_Flasher.pcbpro")
    with win.doc.edit("clear"):
        p.tracks.clear()
        p.vias.clear()
    win.doc.refill_zones()
    wait(300)
    win.canvas.fit_board()
    wait(200)
    grab(win.canvas, "ratsnest")
    close_window(win)


@job("autoroute")
def _autoroute(app):
    """Recording: the autorouter's result on the 555 board, revealed net by net in the order it routed them."""
    from pcbpro.route.autorouter import Autorouter
    win = new_window()
    p = load(win, "555_LED_Flasher.pcbpro")
    with win.doc.edit("clear"):
        p.tracks.clear()
        p.vias.clear()
    win.doc.refill_zones()
    win.canvas.fit_board()
    wait(300)
    r = Autorouter(p.clone()).run()
    clip = Clip("autoroute", fps=24)
    clip.add(win.canvas.grab(), 1.2)
    order = []
    for t in r.tracks:
        if t.net not in order:
            order.append(t.net)
    for net in order:
        with win.doc.edit("route"):
            p.tracks.extend(t for t in r.tracks if t.net == net)
            p.vias.extend(v for v in r.vias if v.net == net)
        win.canvas.repaint()
        wait(30)
        clip.add(win.canvas.grab(), 0.35)
    with win.doc.edit("vias"):
        p.vias.extend(v for v in r.vias if v not in p.vias)
    win.doc.refill_zones()
    wait(300)
    win.canvas.repaint()
    clip.add(win.canvas.grab(), 2.5)
    clip.done(poster=len(clip.frames) - 1)
    close_window(win)


@job("board-3d")
def _board_3d(app):
    win = new_window()
    load(win, "555_LED_Flasher.pcbpro")
    win.tabs.setCurrentWidget(win.page3d)
    win.page3d.view.set_view("iso")
    wait(900)
    grab(win, "3d-window")
    v = view3d(win)
    v.set_view("iso")
    gl(v, "board-3d")
    v.set_view("top")
    gl(v, "board-3d-top")
    v.set_view("bottom")
    gl(v, "board-3d-bottom")
    v.close()
    close_window(win)


@job("library-showcase")
def _library_showcase(app):
    """A board full of library parts, in 3D: what the generated footprints and models look like."""
    from pcbpro.model.board import Component
    from pcbpro.model.footprints import find_part
    from pcbpro.ui.document import blank_project
    names = ["Resistor 0402", "Resistor 0805", "Capacitor 1206", "Tantalum case B (3528-21)",
             "Electrolytic SMD 6.3x5.4", "Power inductor 6x6x4.5", "LED 0805", "WS2812B 5050 addressable",
             "Diode SMA", "SOT-23", "SOT-223", "TO-252 (DPAK)", "SOIC-8", "TSSOP-20", "LQFP-48 7x7 P0.5",
             "QFN-32 5x5 P0.5", "BGA-256 17x17 P1.0", "Crystal / oscillator SMD 3.2x2.5 (4 pads)",
             "Tactile switch SMD 6x6", "USB-C receptacle 16P (USB 2.0)", "JST SH 4-pin SMD", "microSD socket",
             "DIP-16 (300 mil)", "Pin header 2x5 P2.54", "JST XH 3-pin", "Screw terminal 3-pin P5.08",
             "DC barrel jack 5.5x2.1", "Electrolytic D8 P3.5 H11.5", "Film box L13 W5 P10", "Resistor axial 1/4 W P10.16",
             "LED 5 mm THT", "TO-220-3 vertical", "TO-92 inline", "Relay SPDT Songle SRD (10 A)",
             "Rotary encoder EC11 with switch", "ESP32-WROOM-32 module"]
    p = blank_project(120, 80, 3.0, name="Library showcase")
    x, y, row_h = 5.0, 5.0, 0.0
    for name in names:
        part = find_part(name)
        if part is None:
            print("  missing part", name)
            continue
        fp = part.make()
        x0, y0, x1, y1 = fp.courtyard
        w, h = x1 - x0, y1 - y0
        if x + w > 116:
            x, y, row_h = 5.0, y + row_h + 2.5, 0.0
        p.components.append(Component(p.next_ref(part.prefix), part.value, fp, round(x - x0, 2), round(y - y0, 2)))
        x += w + 2.5
        row_h = max(row_h, h)
    win = new_window()
    win.doc.set_project(p)
    wait(300)
    v = view3d(win)
    v.yaw, v.pitch = -22.0, 40.0
    v.fit()
    v.dist *= 0.82
    gl(v, "library-3d")
    v.close()
    close_window(win)


@job("dialogs")
def _dialogs(app):
    """The footprint wizard, the KiCad comparison and the LCSC import."""
    from pcbpro.model.footprints import find_part
    from pcbpro.ui.library_dialogs import CompareDialog, FootprintWizardDialog, LcscImportDialog
    win = new_window()
    dlg = show_dialog(FootprintWizardDialog(win), 980, 620)
    i = dlg.family.findText("QFN", Qt.MatchContains)
    if i >= 0:
        dlg.family.setCurrentIndex(i)
        wait(300)
    grab(dlg, "footprint-wizard")
    dlg.close()
    if win.lib_index.kicad:
        part = find_part("SOIC-8")
        dlg = show_dialog(CompareDialog(part, win.lib_index, win), 980, 640)
        k = dlg.ref.findText("SOIC-8_3.9x4.9mm_P1.27mm", Qt.MatchContains)
        if k >= 0:
            dlg.ref.setCurrentIndex(k)
        wait(500)
        grab(dlg, "footprint-check")
        dlg.close()
    else:
        print("  no KiCad library installed: skipping footprint-check")
    dlg = show_dialog(LcscImportDialog(win, "C2040"), 760, 520)
    grab(dlg, "lcsc-import")
    dlg.close()
    close_window(win)


# ---- pedals

@job("pedal")
def _pedal(app):
    from pcbpro.ui import pedal_ui
    from pcbpro.ui.pedal_ui import PedalWizardDialog
    win = new_window()
    dlg = show_dialog(PedalWizardDialog(win))
    dlg.adjustSize()
    wait(200)
    grab(dlg, "pedal-wizard")
    dlg.close()
    load(win, "Three_Knob_Overdrive_125B.pcbpro", 1.27)
    grab(win, "pedal-layout")
    win.resize(2240, WIN_H)  # the drilling page wants the room
    wait(300)
    win.tabs.setCurrentWidget(win.enclosure_page)
    wait(800)
    grab(win.enclosure_page, "enclosure")
    win.resize(WIN_W, WIN_H)
    pedal_ui.show_pedal_3d(win)
    wait(1200)
    grab(win, "pedal-3d-window")
    win.tabs.setCurrentWidget(win.canvas)
    v = view3d(win)
    v.set_show_enclosure(True)
    wait(300)
    v.set_view("pedal")
    gl(v, "pedal-3d")
    v.yaw, v.pitch = 200.0, -38.0
    v.update()
    gl(v, "pedal-3d-inside")
    v.set_show_enclosure(False)
    v.set_view("iso")
    gl(v, "pedal-board-3d")
    v.close()
    close_window(win)


@job("pedal-orbit")
def _pedal_orbit(app):
    win = new_window()
    load(win, "Three_Knob_Overdrive_125B.pcbpro", 1.27)
    v = view3d(win, 960, 540)
    v.set_show_enclosure(True)
    wait(300)
    v.set_view("pedal")
    yaw0, pitch = v.yaw, 34.0
    clip = Clip("pedal-orbit", fps=30)
    for i in range(180):
        v.yaw = yaw0 + 360.0 * i / 180
        v.pitch = pitch + 8.0 * math.sin(i / 180 * 2 * math.pi)
        v.update()
        wait(8)
        clip.add(v.grabFramebuffer())
    clip.done()
    v.close()
    close_window(win)


@job("drill-template")
def _drill_template(app):
    """Page 1 of the printable drill template, rendered from the PDF the app writes."""
    from PySide6.QtCore import QSize
    from PySide6.QtPdf import QPdfDocument
    from pcbpro.examples import load_example
    from pcbpro.pedal.drill import export_pdf
    pdf = OUT / "drill_template.pdf"
    export_pdf(load_example(EXAMPLES / "Three_Knob_Overdrive_125B.pcbpro"), pdf, "a4")
    doc = QPdfDocument()
    doc.load(str(pdf))
    size = doc.pagePointSize(0)
    scale = 1600 / size.width()
    page = doc.render(0, QSize(int(size.width() * scale), int(size.height() * scale)))
    from PySide6.QtGui import QColor, QImage, QPainter
    img = QImage(page.size(), QImage.Format_RGB32)  # paper: the PDF page itself is transparent
    img.fill(QColor("white"))
    painter = QPainter(img)
    painter.drawImage(0, 0, page)
    painter.end()
    save(img, "drill-template")


@job("buy")
def _buy(app):
    from pcbpro.ui.shop import BuyPartsDialog
    win = new_window()
    load(win, "Three_Knob_Overdrive_125B.pcbpro", 1.27)
    dlg = show_dialog(BuyPartsDialog(win.doc, win, "tayda"), 1240, 780)
    wait(500)
    grab(dlg, "buy-parts")
    dlg.close()
    win.resize(2240, WIN_H)  # the order page wants the room
    win.tabs.setCurrentWidget(win.order_page)
    wait(900)
    grab(win.order_page, "order")
    close_window(win)


# ---- amps

def _designer(voicing: str = "modern", **kw):
    from pcbpro.amp.designer import AmpSpec
    from pcbpro.ui.amp_designer import AmpDesignerDialog
    dlg = AmpDesignerDialog(AmpSpec(voicing=voicing, **kw))
    return show_dialog(dlg, 1500, 960)


@job("designer")
def _designer_shots(app):
    import numpy as np
    from dataclasses import asdict
    from pcbpro.amp.demo import metal_riff, render_design
    dlg = _designer("modern")
    wait(500)
    grab(dlg, "designer")
    dlg.tabs.setCurrentIndex(1)
    for name, val in (("Treble", 65), ("Bass", 40), ("Middle", 55)):
        dlg.knobs[name].setValue(val)
    wait(400)
    grab(dlg, "designer-tone")
    dlg.tabs.setCurrentWidget(dlg.gain_tab)
    wait(1500)
    grab(dlg, "designer-gain")
    dlg.tabs.setCurrentWidget(dlg.listen)
    wait(600)
    lp = dlg.listen
    lp.dry = metal_riff(48000, 6.0, 0.4)
    knobs = lp.knob_values()
    out = render_design(asdict(dlg.spec()), knobs, lp.dry, 48000, 2)
    lp.label = f"{dlg.report.title}, tightness {dlg.spec().tight}, gain {knobs.get('GAIN', 0.5) * 10:.1f}"
    lp.finish_render(np.asarray(out))
    lp.progress.setValue(100)
    lp.status.setText(f"Playing: {lp.label}. 'Keep as A' holds it for comparing.")
    lp._buttons()
    wait(300)
    grab(dlg, "designer-listen")
    dlg.tabs.setCurrentIndex(dlg.tabs.count() - 1)
    wait(300)
    grab(dlg, "designer-parts")
    dlg.listen.shutdown()
    dlg.close()


@job("designer-voicings")
def _designer_voicings(app):
    """Recording: the spec sheet as you click through the voicings."""
    dlg = _designer("blackface")
    wait(500)
    clip = Clip("designer-voicings", fps=24)
    clip.add(dlg.grab(), 1.6)
    for i in range(dlg.voicings.count()):
        item = dlg.voicings.item(i)
        if not item.flags():
            continue
        dlg.voicings.setCurrentRow(i)
        wait(500)
        dlg.sheet.verticalScrollBar().setValue(0)
        wait(60)
        clip.add(dlg.grab(), 1.6)
    clip.done(poster=5)
    dlg.listen.shutdown()
    dlg.close()


@job("amp")
def _amp(app):
    from pcbpro.ui.amp_ui import NetVoltageDialog, ToneStackDialog, TubeTableDialog
    win = new_window()
    load(win, "Amp_Modern_High_Gain_50W.pcbpro")
    grab(win, "amp-layout")
    win.run_drc()
    wait(500)
    grab(win, "amp-drc")
    v = view3d(win)
    v.set_view("iso")
    gl(v, "amp-3d")
    v.yaw, v.pitch = 160.0, 28.0
    v.fit()
    gl(v, "amp-3d-rear")
    v.close()
    dlg = show_dialog(NetVoltageDialog(win.doc.project, win), 980, 640)
    grab(dlg, "hv-nets")
    dlg.close()
    dlg = show_dialog(ToneStackDialog(win), 1100, 620)
    grab(dlg, "tone-stack")
    dlg.close()
    dlg = show_dialog(TubeTableDialog(win), 1100, 620)
    grab(dlg, "tubes")
    dlg.close()
    close_window(win)


@job("amp-orbit")
def _amp_orbit(app):
    win = new_window()
    load(win, "Amp_Plexi_Crunch_50W.pcbpro")
    v = view3d(win, 960, 540)
    v.set_view("iso")
    yaw0 = v.yaw
    clip = Clip("amp-orbit", fps=30)
    for i in range(200):
        v.yaw = yaw0 + 50.0 * math.sin(i / 200 * 2 * math.pi)
        v.pitch = 36.0 + 6.0 * math.sin(i / 200 * 4 * math.pi)
        v.update()
        wait(8)
        clip.add(v.grabFramebuffer())
    clip.done()
    v.close()
    close_window(win)


# ---- simulation

def _sim_window(file_name: str = "555_LED_Flasher.pcbpro", probes=("THR", "OUT")):
    win = new_window()
    load(win, file_name)
    ctl = win.simctl
    ctl.set_probes(list(probes))
    ctl.start()
    return win


@job("sim")
def _sim(app):
    win = _sim_window()
    win.scope_dock.show()
    win.resizeDocks([win.scope_dock], [300], Qt.Vertical)
    win.scope_panel.tb.setCurrentIndex(10)  # 2 s: a couple of the 555's cycles
    wait(4500)
    grab(win, "sim-run")
    clip = Clip("sim-555", fps=24)
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 6.0:
        wait(15)
        clip.add_timed(win.grab())
    clip.done()
    v = view3d(win)
    v.set_view("iso")
    for _ in range(40):  # catch the LED lit
        wait(40)
        if max((x for _, x, _, _ in win.simctl.led_states()), default=0.0) > 0.6:
            break
    gl(v, "sim-3d-glow")
    v.close()
    close_window(win)


@job("audio")
def _audio(app):
    import numpy as np
    from pcbpro.sim.audio import guitar_clip, render_fast
    from pcbpro.ui.audio_ui import AudioDialog, BodeDialog, full_scale
    from pcbpro.ui.live_ui import LiveDialog
    win = new_window()
    load(win, "Three_Knob_Overdrive_125B.pcbpro", 1.27)
    dlg = show_dialog(AudioDialog(win, win), 1240, 860)
    wait(800)
    clip, rate = dlg._clip_data()
    dlg.dry, dlg.rate = clip, rate
    dlg.out_ref = full_scale(dlg.project, dlg.out_net.currentText())
    dlg.wet = np.asarray(render_fast(dlg.project, clip, rate, dlg.in_net.currentText(), dlg.out_net.currentText(),
                                     dict(dlg.knobs.values)))
    dlg._finish("Done: play the dry and processed versions to compare.")
    wait(400)
    grab(dlg, "audio")
    dlg.close()
    dlg = show_dialog(BodeDialog(win, win), 980, 620)
    wait(800)
    grab(dlg, "frequency-response")
    dlg.close()
    dlg = show_dialog(LiveDialog(win, win), 900, 700)
    wait(800)
    grab(dlg, "play-live")
    dlg.close()
    close_window(win)


@job("sim-panel")
def _sim_panel(app):
    """Operating point table and the Simulation panel on an amp."""
    win = _sim_window("Amp_Tweed_Champ_5W.pcbpro", probes=())
    wait(3000)
    win.scope_dock.show()
    wait(300)
    grab(win, "sim-amp")
    close_window(win)


# ---- examples gallery

@job("examples")
def _examples(app):
    """A 3D picture of every bundled example, for the gallery on the website and docs/examples.md."""
    win = new_window()
    v = view3d(win, 1280, 720)
    for f in sorted(EXAMPLES.glob("*.pcbpro")):
        load(win, f.name)
        v.set_show_enclosure(False)
        v.set_view("iso")
        wait(500)
        gl(v, f"example-{f.stem}")
        if f.stem.startswith(("Three_Knob", "Metal_")):
            v.set_show_enclosure(True)
            wait(300)
            v.set_view("pedal")
            gl(v, f"example-{f.stem}-box")
            v.set_show_enclosure(False)
    v.close()
    close_window(win)


def main(argv: list[str]) -> None:
    if "--list" in argv:
        print("\n".join(JOBS))
        return
    names = [a for a in argv if not a.startswith("-")] or list(JOBS)
    unknown = set(names) - set(JOBS)
    if unknown:
        raise SystemExit(f"unknown: {', '.join(sorted(unknown))}; --list shows them")
    OUT.mkdir(parents=True, exist_ok=True)
    if _SETTINGS.exists():
        _SETTINGS.unlink()
    app = start_app()
    failed = []
    for name in names:
        print(name, flush=True)
        try:
            JOBS[name](app)
        except Exception as e:  # keep going: report at the end
            import traceback
            traceback.print_exc()
            failed.append(f"{name}: {type(e).__name__}: {e}")
        for w in app.topLevelWidgets():
            if w.isVisible():
                w.close()
        wait(100)
    if failed:
        print("FAILED:\n  " + "\n  ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
