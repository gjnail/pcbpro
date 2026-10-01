"""Application entry point."""
from __future__ import annotations

import os
import sys
import traceback


def _excepthook(exc_type, exc, tb):
    """Show unexpected errors instead of silently killing the app."""
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    sys.stderr.write(text)
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is not None:
            QMessageBox.critical(None, "PCBPro - unexpected error",
                                 f"{exc_type.__name__}: {exc}\n\nYour work has not been lost; save it under a new name "
                                 f"to be safe.\n\n{text[-1500:]}")
    except Exception:
        pass


def _schedule_selftest(app, win, out_dir: str) -> None:
    """Smoke test for installed builds: example -> 3D render -> Gerber export -> report, then quit."""
    from pathlib import Path

    from PySide6.QtCore import QTimer

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = []

    def step1():
        win.open_example()
        win.tabs.setCurrentWidget(win.page3d)

    def step2():
        try:
            view = win.page3d.view
            img = view.grabFramebuffer()
            img.save(str(out / "selftest_3d.png"))
            # build machines without a GPU (CI) have no usable OpenGL: the 3D step still runs but isn't required
            gpu = not os.environ.get("PCBPRO_SELFTEST_NO_GPU")
            report.append(f"3d meshes={len(view.meshes)} image={img.width()}x{img.height()}"
                          + ("" if gpu else " (not required: PCBPRO_SELFTEST_NO_GPU)"))
            zp = win.order_page.export_files(str(out / "selftest_fab"))
            report.append(f"export={zp.name}")
            counts = win.lib_index.counts()
            report.append("library=" + ", ".join(f"{k}:{v}" for k, v in counts.items()))
            ok = (len(view.meshes) > 5 or not gpu) and counts["builtin"] > 1000 and counts["catalog"] > 200
            state["ok"] = ok
            # simulation: the circuit in-process, then the worker process the UI uses (spawned exe in builds)
            from .sim.session import SimRunner
            r = SimRunner(win.doc.project.clone(), "design", "power")
            r.advance(0.5, budget=30.0)
            snap = r.snapshot()
            report.append(f"sim t={snap['t']:.2f}s steps={snap['steps']} error={r.error or 'none'}")
            state["ok"] = ok and not r.error and snap["t"] > 0.45
            # real-time audio engine: JIT-compiled circuit kernel and the audio device library
            import time as _time

            import numpy as _np

            from .pedal.examples import overdrive_example
            from .sim.livefx import list_devices
            from .sim.realtime import RealtimeModel
            t0 = _time.perf_counter()
            rt = RealtimeModel(overdrive_example(route=False), rate=48000, oversample=2)
            rt.warm_up()
            t1 = _time.perf_counter()
            y = rt.process_block(_np.sin(_np.arange(4800) * 0.0576) * 0.2)
            load = (_time.perf_counter() - t1) / 0.1
            devs = list_devices()
            report.append(f"realtime compile={t1 - t0:.1f}s load={load * 100:.0f}% "
                          f"audio devices in={len(devs['inputs'])} out={len(devs['outputs'])}")
            state["ok"] = state["ok"] and bool(_np.all(_np.isfinite(y))) and load < 1.0
            # speaker cabinet IRs bundled with the app, convolved like the live engine does
            from .sim.cabinet import Convolver, builtin_irs, load_ir
            cabs = builtin_irs()
            yc = Convolver(load_ir(cabs[0], 48000), 128).process(y[:1280]) if cabs else _np.zeros(0)
            report.append(f"cabinet IRs built-in={len(cabs)} out={float(_np.max(_np.abs(yc), initial=0)):.3f}")
            state["ok"] = state["ok"] and len(cabs) == 4 and bool(_np.all(_np.isfinite(yc)))
            # vacuum tubes: an example amp board (transformer, speaker, supplies modelled) played in real time
            from .model.fileio import load_project as _load
            from .sim.ampboard import output_net
            champ = _load(Path(__file__).resolve().parent / "resources" / "examples" / "Amp_Tweed_Champ_5W.pcbpro")
            t2 = _time.perf_counter()
            amp = RealtimeModel(champ, "IN", output_net(champ), rate=48000, oversample=1)
            amp.warm_up()
            ya = amp.process_block(_np.sin(_np.arange(4800) * 0.0576) * 0.2)
            report.append(f"tube amp compile={_time.perf_counter() - t2:.1f}s out={float(_np.max(_np.abs(ya))):.1f}V "
                          f"tubes={sum(1 for d in amp.nl if d.kind in ('triode', 'pentode'))}")
            state["ok"] = state["ok"] and bool(_np.all(_np.isfinite(ya))) and float(_np.max(_np.abs(ya))) > 0.1
            win.tabs.setCurrentWidget(win.canvas)
            win.simctl.backend = "worker"
            win.simctl.start()
            QTimer.singleShot(4000, step3)  # give the worker process time to start and run
        except Exception as e:  # pragma: no cover - reported in the file
            report.append(f"RESULT FAIL {type(e).__name__}: {e}")
            finish()

    def step3():
        try:
            snap = win.simctl.snap or {}
            report.append(f"sim worker t={snap.get('t', 0):.2f}s error={win.simctl.error or 'none'}")
            state["ok"] = state["ok"] and snap.get("t", 0) > 0.5 and not win.simctl.error
            win.simctl.stop("")
            report.append("RESULT OK" if state["ok"] else "RESULT FAIL")
        except Exception as e:  # pragma: no cover - reported in the file
            report.append(f"RESULT FAIL {type(e).__name__}: {e}")
        finish()

    def finish():
        (out / "selftest.txt").write_text("\n".join(report), encoding="utf-8")
        win.doc.dirty = False
        app.quit()

    state = {"ok": False}
    QTimer.singleShot(300, step1)
    QTimer.singleShot(2500, step2)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QSurfaceFormat
    from PySide6.QtWidgets import QApplication

    from . import APP_NAME, __version__

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(8)
    QSurfaceFormat.setDefaultFormat(fmt)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PCBPro.PCBPro.1")
        except Exception:
            pass
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_NAME)
    sys.excepthook = _excepthook

    from .ui.icons import app_icon
    from .ui.main_window import MainWindow
    from .ui.theme import apply_theme

    apply_theme(app)
    app.setWindowIcon(app_icon())
    win = MainWindow()
    win.show()
    if "--selftest" in argv:
        i = argv.index("--selftest")
        out = argv[i + 1] if i + 1 < len(argv) else "."
        _schedule_selftest(app, win, out)
        return app.exec()
    files = [a for a in argv[1:] if not a.startswith("-")]
    if files:
        win.load_path(files[0])
    elif "--example" in argv:
        win.open_example()
    elif "--no-welcome" not in argv:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(150, win.show_welcome)
    return app.exec()
