"""Run mode in the main window: blinking LED, buttons on the canvas, scope probes, 3D glow, stop on edit."""
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest


def _window(qapp):
    from pcbpro.ui.main_window import MainWindow
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    w.open_example()
    w.simctl.backend = "inprocess"
    return w


def _close(w):
    w.simctl.stop("")
    w.doc.dirty = False
    w.close()


def _pt(canvas, x, y):
    p = canvas.to_screen(x, y)
    return QPoint(int(round(p.x())), int(round(p.y())))


def _led_level(ctl):
    return max((lv for _, lv, _, _ in ctl.led_states()), default=0.0)


def test_run_blinks_and_button_holds_reset(qapp):
    w = _window(qapp)
    ctl = w.simctl
    ctl.set_probes(["THR"])
    assert ctl.start()
    assert w.canvas.tool.name == "sim"
    levels = []
    for _ in range(70):
        QTest.qWait(30)
        levels.append(_led_level(ctl))
    assert max(levels) > 0.3 and min(levels) < 0.05, levels
    assert len(ctl.scope.data()[0]) > 50
    w.canvas.repaint()  # overlay paints without errors
    # hold the RESET button on the canvas: the 555 stops and the LED goes dark
    sw = w.doc.project.component("SW1")
    w.canvas.zoom_to(sw.x, sw.y, 20.0)
    QTest.mousePress(w.canvas, Qt.LeftButton, Qt.NoModifier, _pt(w.canvas, sw.x, sw.y))
    QTest.qWait(400)
    held = [_led_level(ctl) for _ in range(12) if not QTest.qWait(30)]
    QTest.mouseRelease(w.canvas, Qt.LeftButton, Qt.NoModifier, _pt(w.canvas, sw.x, sw.y))
    assert max(held) < 0.05
    # editing the board stops the simulation
    with w.doc.edit("move"):
        w.doc.project.component("R1").x += 1
    assert not ctl.running and w.canvas.tool.name == "select"
    _close(w)


def test_3d_view_has_glowing_leds(qapp):
    w = _window(qapp)
    w.tabs.setCurrentWidget(w.page3d)
    QTest.qWait(400)
    view = w.page3d.view
    view.repaint()
    QTest.qWait(100)
    assert view.glow_meshes, "LED lenses should be separate glow meshes"
    w.simctl.start()
    QTest.qWait(600)
    view.repaint()
    assert view.grabFramebuffer().width() > 100
    _close(w)


def test_part_list_and_override(qapp):
    from pcbpro.sim.netlist import build_circuit
    w = _window(qapp)
    p = w.doc.project
    r1 = p.component("R1")
    with w.doc.edit("override"):
        p.sim.setdefault("parts", {})[r1.uid] = {"exclude": True}
    ck = build_circuit(p)
    assert ck.parts[r1.uid].status == "excluded"
    w.doc.undo()
    assert build_circuit(w.doc.project).parts[r1.uid].status == "simulated"
    w.sim_panel.refresh_preview()
    assert w.sim_panel.parts.topLevelItemCount() == len(p.components)
    _close(w)


def test_audio_and_bode_dialogs(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings

    from pcbpro.ui import cab_ui, pedal_ui
    monkeypatch.setattr(cab_ui, "settings", lambda: QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))
    monkeypatch.setattr(cab_ui, "find_irs", lambda *a, **k: [])  # no search of this PC from the tests
    from pcbpro.ui.audio_ui import AudioDialog, BodeDialog
    from pcbpro.ui.main_window import MainWindow
    w = MainWindow()
    w.show()
    pedal_ui.open_pedal_example(w)
    bode = BodeDialog(w, w)
    bode._update()
    assert len(bode.plot.freqs) > 50 and bode.plot.curves
    audio = AudioDialog(w, w)
    from PySide6.QtWidgets import QFormLayout
    form = audio.knobs.layout()
    labels = [form.itemAt(i, QFormLayout.ItemRole.LabelRole).widget().text() for i in range(form.rowCount())
              if form.itemAt(i, QFormLayout.ItemRole.LabelRole) is not None]
    assert any(t.startswith("DRIVE") for t in labels)
    clip, rate = audio._clip_data()
    assert len(clip) == int(audio.seconds.value() * rate)
    audio.close()
    bode.close()
    w.doc.dirty = False
    w.close()


def test_knob_labels_of_the_bundled_examples():
    """Each pot is named after its own silkscreen label: a pedal prints it under the knob (on a two-row pedal the
    label of the pot above is nearer), an amp above its front-panel controls. Pedal pots are made in knob order."""
    from pcbpro.amp.metal_pedals import METAL_EXAMPLES, PEDALS
    from pcbpro.examples import list_examples, load_example
    from pcbpro.sim.netlist import build_circuit
    from pcbpro.ui.audio_ui import _knob_label
    pedals = {name: PEDALS[key].knobs for key, name in METAL_EXAMPLES.items()}
    pedals["Three_Knob_Overdrive_125B.pcbpro"] = ("LEVEL", "TONE", "DRIVE")
    checked = set()
    for path in list_examples():
        p = load_example(path)
        comps = {c.uid: c for c in p.components}
        pots = [comps[ctl.uid] for ctl in build_circuit(p).controls if ctl.kind == "pot" and ctl.uid in comps]
        for c in pots:
            name = _knob_label(p, c)
            if name.endswith(f" ({c.ref})"):  # labelled: the generators print a pot's label in line with it
                text = name[:-len(c.ref) - 3]
                assert any(t.text == text and abs(t.x - c.x) < 0.05 for t in p.texts), (path.name, c.ref, name)
        if path.name in pedals:
            got = [_knob_label(p, c) for c in sorted(pots, key=lambda c: int(c.ref[2:]))]
            assert got == [f"{k} (RV{i})" for i, k in enumerate(pedals[path.name], 1)], path.name
            checked.add(path.name)
    assert checked == set(pedals)
