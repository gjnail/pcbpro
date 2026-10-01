"""Simulation features for the main window: Simulate menu, Run button, Simulation and Oscilloscope docks."""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox, QToolBar

from .icons import icon
from .scope import ScopePanel
from .sim_dialogs import PartModelDialog, SerialMonitor, SourcesDialog
from .sim_panel import SimulationPanel
from .sim_tool import SimTool
from .simulation import SimController


def install(win) -> None:
    ctl = SimController(win.doc, win)
    win.simctl = ctl
    tool = SimTool(win.canvas, ctl)
    win.canvas.tools["sim"] = tool
    panel = SimulationPanel(ctl)
    panel.sim_tool = tool
    win.sim_panel = panel
    win.sim_dock = win._dock("Simulation", panel, Qt.RightDockWidgetArea, "sim")
    win.tabifyDockWidget(win.props_dock, win.sim_dock)
    win.props_dock.raise_()
    scope = ScopePanel(ctl)
    win.scope_panel = scope
    win.scope_dock = win._dock("Oscilloscope", scope, Qt.BottomDockWidgetArea, "scope")
    win.scope_dock.hide()
    win._serial_windows = {}
    win._hex_watch = QFileSystemWatcher(win)
    win._hex_watch.fileChanged.connect(lambda path: _hex_changed(win, path))

    A = win._act
    win.act_run = A("&Run / pause simulation", lambda: _run_pause(win), "F5", "simulate",
                    tip="Run the circuit (F5): LEDs light, press buttons, turn knobs, probe nets")
    win.act_stop = A("&Stop simulation", lambda: ctl.stop(""), "Shift+F5", "stop", tip="Stop the simulation")
    win.act_scope = A("&Oscilloscope", lambda: (win.scope_dock.show(), win.scope_dock.raise_()), None, "scope",
                      tip="Show the oscilloscope")
    m = QMenu("&Simulate", win)
    m.addAction(win.act_run)
    m.addAction(win.act_stop)
    m.addAction("&Restart from power-up", ctl.start)
    m.addSeparator()
    m.addAction(win.act_scope)
    m.addAction("Simulation &panel", lambda: (win.sim_dock.show(), win.sim_dock.raise_()))
    m.addAction("Power and signal &sources…", lambda: edit_sources(win))
    m.addAction("Simulation &model of the selected part…", lambda: _edit_selected(win))
    m.addSeparator()
    m.addAction("Load &firmware (.hex) for a microcontroller…", lambda: _load_hex_selected(win))
    m.addAction("Serial &monitor…", lambda: _serial_selected(win))
    m.addSeparator()
    m.addAction("Play &live (guitar in)…", lambda: open_live(win)).setShortcut(QKeySequence("Ctrl+Shift+L"))
    m.addAction("&Audio play-through…", lambda: open_audio(win))
    m.addAction("&Frequency response…", lambda: open_bode(win))
    m.addSeparator()
    m.addAction("Clear &smoke markers", ctl.clear_smoke)
    mb = win.menuBar()
    before = next((a for a in mb.actions() if a.text().replace("&", "") == "Tools"), None)
    if before is not None:
        mb.insertMenu(before, m)
    else:
        mb.addMenu(m)
    win.sim_menu = m
    view = next((a.menu() for a in mb.actions() if a.text().replace("&", "") == "View"), None)
    if view is not None:
        view.addAction(win.sim_dock.toggleViewAction())
        view.addAction(win.scope_dock.toggleViewAction())
    tb = win.findChild(QToolBar, "main_tb")
    if tb is not None:
        tb.insertAction(win.act_3d, win.act_run)
        w = tb.widgetForAction(win.act_run)
        if w is not None:
            w.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        win.act_run.setIconText("Run")

    def started():
        win.canvas.set_tool("sim")
        win.sim_dock.show()
        win.sim_dock.raise_()
        if ctl.probes:
            win.scope_dock.show()
        win.act_run.setIconText("Pause")
        win.statusBar().showMessage("Simulation running: click buttons and switches, scroll pots, double-click a "
                                    "net to probe it.", 6000)

    def stopped(reason):
        if win.canvas.tool is tool:
            win.canvas.set_tool("select")
        win.act_run.setIconText("Run")
        if reason:
            win.statusBar().showMessage(reason, 8000)
            if ctl.error and reason == ctl.error:
                QMessageBox.warning(win, "Simulation", reason)
        win.canvas.update()

    def state():
        win.act_run.setIconText("Run" if not ctl.running or ctl.paused else "Pause")

    def tool_changed(name):
        if ctl.running and name != "sim":
            ctl.stop("Simulation stopped to edit the board.")

    ctl.started.connect(started)
    ctl.stopped.connect(stopped)
    ctl.state_changed.connect(state)
    ctl.updated.connect(lambda: _sync_panel(win))
    win.canvas.tool_changed.connect(tool_changed)
    panel.part_activated.connect(lambda uid: _goto_part(win, uid))
    panel.edit_part.connect(lambda uid: edit_part(win, uid))
    panel.edit_sources.connect(lambda: edit_sources(win))
    panel.serial_requested.connect(lambda uid: open_serial(win, uid))
    panel.load_hex.connect(lambda uid: load_hex(win, uid))
    panel.clock_changed.connect(lambda uid, hz: set_clock(win, uid, hz))
    panel.audio_requested.connect(lambda: open_audio(win))
    panel.bode_requested.connect(lambda: open_bode(win))
    panel.live_requested.connect(lambda: open_live(win))
    win.props.sim_model_hook = lambda uid: edit_part(win, uid)
    view3d = getattr(getattr(win, "page3d", None), "view", None)
    if view3d is not None and hasattr(view3d, "set_simulation"):
        view3d.set_simulation(ctl)
    app = QApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(lambda: ctl.stop(""))
    win.destroyed.connect(lambda *_: ctl.stop(""))
    _watch_hex_files(win)
    win.doc.replaced.connect(lambda: _watch_hex_files(win))


def _run_pause(win):
    ctl = win.simctl
    if not ctl.running:
        ctl.start()
    else:
        ctl.set_paused(not ctl.paused)


def _sync_panel(win):
    pass


def _goto_part(win, uid):
    comp = next((c for c in win.doc.project.components if c.uid == uid), None)
    if comp is None:
        return
    win.tabs.setCurrentWidget(win.canvas)
    win.canvas.zoom_to(comp.x, comp.y, max(win.canvas.scale, 18))
    if not win.simctl.running:
        win.doc.set_selection([comp])


def _selected_component(win):
    from ..model.board import Component
    return next((it for it in win.doc.selection if isinstance(it, Component)), None)


def _edit_selected(win):
    comp = _selected_component(win)
    if comp is None:
        QMessageBox.information(win, "Simulation model", "Select a component first (or double-click it in the "
                                                         "Simulation panel's part list).")
        return
    edit_part(win, comp.uid)


def edit_part(win, uid):
    comp = next((c for c in win.doc.project.components if c.uid == uid), None)
    if comp is None:
        return
    dlg = PartModelDialog(win.doc.project, comp, win)
    if dlg.exec() and dlg.result_override is not None:
        with win.doc.edit(f"Simulation model of {comp.ref}"):
            sim = win.doc.project.sim
            parts = sim.setdefault("parts", {})
            if dlg.result_override:
                parts[uid] = dlg.result_override
            else:
                parts.pop(uid, None)
        win.sim_panel.refresh_preview()


def edit_sources(win):
    from ..sim.netlist import BoardCircuit, auto_sources, build_circuit
    proj = win.doc.project
    try:
        ck = build_circuit(proj, win.simctl.mode, sources=[])
        auto = auto_sources(proj, ck)
    except Exception:
        auto = []
    dlg = SourcesDialog(proj, auto, win)
    if dlg.exec():
        new = dlg.sources()
        with win.doc.edit("Simulation sources"):
            if new is None:
                proj.sim.pop("sources", None)
            else:
                proj.sim["sources"] = new
        win.sim_panel.refresh_preview()


def _mcu_infos(win):
    from ..sim.netlist import build_circuit
    try:
        ck = win.simctl.ck if win.simctl.running and win.simctl.ck is not None else build_circuit(win.doc.project)
    except Exception:
        return []
    return [i for i in ck.parts.values() if i.res.kind == "mcu"]


def _pick_mcu(win):
    infos = _mcu_infos(win)
    sel = _selected_component(win)
    if sel is not None:
        for i in infos:
            if i.uid == sel.uid:
                return i
    if len(infos) == 1:
        return infos[0]
    if not infos:
        QMessageBox.information(win, "Microcontroller", "No supported microcontroller on this board (ATmega328P, "
                                                        "ATtiny85/13A, Arduino Nano or Pro Mini).")
    else:
        QMessageBox.information(win, "Microcontroller", "Select the microcontroller first.")
    return None


def _load_hex_selected(win):
    info = _pick_mcu(win)
    if info is not None:
        load_hex(win, info.uid)


def _serial_selected(win):
    info = _pick_mcu(win)
    if info is not None:
        open_serial(win, info.uid)


def load_hex(win, uid):
    comp = next((c for c in win.doc.project.components if c.uid == uid), None)
    if comp is None:
        return
    cfg = (win.doc.project.sim or {}).get("mcu", {}).get(uid, {})
    start = cfg.get("path") or str(win._last_dir())
    path, _ = QFileDialog.getOpenFileName(win, f"Firmware for {comp.ref}", start,
                                          "Intel HEX firmware (*.hex *.ihex);;All files (*)")
    if not path:
        return
    _store_hex(win, uid, path, restart=False)


def _store_hex(win, uid, path, restart: bool):
    from ..sim.avr.hexfile import HexError, parse_hex
    try:
        text = Path(path).read_text(encoding="ascii", errors="replace")
        parse_hex(text)
    except (OSError, HexError) as e:
        QMessageBox.warning(win, "Firmware", f"Could not read {path}:\n{e}")
        return
    ctl = win.simctl
    was_running = ctl.running
    ctl._ignore_changes += 1
    try:
        with win.doc.edit("Load firmware"):
            mcu = win.doc.project.sim.setdefault("mcu", {})
            cfg = copy.deepcopy(mcu.get(uid, {}))
            cfg.update({"hex": text, "path": str(Path(path).resolve()), "name": Path(path).name})
            mcu[uid] = cfg
    finally:
        ctl._ignore_changes -= 1
    _watch_hex_files(win)
    win.sim_panel.refresh_preview()
    if was_running or restart:
        ctl.start()
    win.statusBar().showMessage(f"Firmware {Path(path).name} loaded", 5000)


def set_clock(win, uid, hz):
    ctl = win.simctl
    was = ctl.running
    with win.doc.edit("Microcontroller clock"):
        win.doc.project.sim.setdefault("mcu", {}).setdefault(uid, {})["clock"] = float(hz)
    if was:
        ctl.start()


def _watch_hex_files(win):
    w = win._hex_watch
    if w.files():
        w.removePaths(w.files())
    for cfg in ((win.doc.project.sim or {}).get("mcu") or {}).values():
        p = cfg.get("path")
        if p and Path(p).exists():
            w.addPath(p)


def _hex_changed(win, path):
    """The firmware file was rebuilt (Arduino IDE 'Export compiled binary'): reload it into every MCU using it."""
    for uid, cfg in list(((win.doc.project.sim or {}).get("mcu") or {}).items()):
        if cfg.get("path") and Path(cfg["path"]) == Path(path) and Path(path).exists():
            _store_hex(win, uid, path, restart=win.simctl.running)
    if Path(path).exists() and path not in win._hex_watch.files():
        win._hex_watch.addPath(path)


def open_serial(win, uid):
    dlg = win._serial_windows.get(uid)
    if dlg is not None:
        try:
            dlg.show()
            dlg.raise_()
            return
        except RuntimeError:
            pass
    comp = next((c for c in win.doc.project.components if c.uid == uid), None)
    dlg = SerialMonitor(win.simctl, uid, comp.ref if comp else uid, win)
    win._serial_windows[uid] = dlg
    dlg.destroyed.connect(lambda *_: win._serial_windows.pop(uid, None))
    dlg.show()


def open_audio(win):
    from .audio_ui import AudioDialog
    dlg = AudioDialog(win, win)
    dlg.exec()


def open_bode(win):
    from .audio_ui import BodeDialog
    dlg = BodeDialog(win, win)
    dlg.exec()


def open_live(win):
    from .live_ui import LiveDialog
    dlg = getattr(win, "_live_dialog", None)
    if dlg is not None:
        try:
            dlg.show()
            dlg.raise_()
            return
        except RuntimeError:
            pass
    win.simctl.stop("")
    dlg = LiveDialog(win, win)
    dlg.setAttribute(Qt.WA_DeleteOnClose)
    win._live_dialog = dlg
    dlg.destroyed.connect(lambda *_: setattr(win, "_live_dialog", None))
    dlg.show()
