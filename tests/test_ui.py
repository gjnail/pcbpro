from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from pcbpro.model.board import Component
from pcbpro.model.connectivity import get_connectivity
from pcbpro.model.footprints import chip, find_part


def _pt(canvas, x, y):
    p = canvas.to_screen(x, y)
    return QPoint(int(round(p.x())), int(round(p.y())))


def _window(qapp):
    from pcbpro.ui.document import blank_project
    from pcbpro.ui.main_window import MainWindow
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    w.doc.set_project(blank_project(40, 30))
    QTest.qWait(50)
    w.canvas.zoom_to(20, 15, 20.0)
    return w


def _close(w):
    w.doc.dirty = False
    w.close()


def test_place_connect_route_undo(qapp):
    w = _window(qapp)
    c, doc = w.canvas, w.doc
    w.place_part(find_part("Resistor 0805"))
    for x in (10, 25):
        QTest.mouseMove(c, _pt(c, x, 15))
        QTest.mouseClick(c, Qt.LeftButton, Qt.NoModifier, _pt(c, x, 15))
    c.set_tool("select")
    assert [comp.ref for comp in doc.project.components] == ["R1", "R2"]
    r1, r2 = doc.project.components
    # netlist editing with the connect tool
    c.set_tool("connect")
    p1 = r1.pad_pos(r1.footprint.pads[1])
    p2 = r2.pad_pos(r2.footprint.pads[0])
    QTest.mouseClick(c, Qt.LeftButton, Qt.NoModifier, _pt(c, *p1))
    QTest.mouseClick(c, Qt.LeftButton, Qt.NoModifier, _pt(c, *p2))
    net = r1.pad_nets["2"]
    assert net and r2.pad_nets["1"] == net
    assert get_connectivity(doc.project).unrouted_count() == 1
    # interactive routing, pad to pad
    c.set_tool("route")
    QTest.mouseClick(c, Qt.LeftButton, Qt.NoModifier, _pt(c, *p1))
    QTest.mouseMove(c, _pt(c, *p2))
    QTest.mouseClick(c, Qt.LeftButton, Qt.NoModifier, _pt(c, *p2))
    assert doc.project.tracks and all(t.net == net for t in doc.project.tracks)
    assert get_connectivity(doc.project).unrouted_count() == 0
    n = len(doc.project.tracks)
    doc.undo()
    assert len(doc.project.tracks) == 0
    doc.redo()
    assert len(doc.project.tracks) == n
    _close(w)


def test_move_rotate_flip_delete(qapp):
    w = _window(qapp)
    doc, c = w.doc, w.canvas
    with doc.edit("add"):
        doc.project.components.append(Component("R1", "1k", chip("R", "0805"), 10, 10))
    comp = doc.project.components[0]
    c.set_tool("select")
    QTest.mouseClick(c, Qt.LeftButton, Qt.NoModifier, _pt(c, 10, 10))
    assert doc.selection == [comp]
    QTest.mousePress(c, Qt.LeftButton, Qt.NoModifier, _pt(c, 10, 10))
    QTest.mouseMove(c, _pt(c, 12, 10))
    QTest.mouseMove(c, _pt(c, 15, 12))
    QTest.mouseRelease(c, Qt.LeftButton, Qt.NoModifier, _pt(c, 15, 12))
    comp = doc.project.components[0]
    assert (comp.x, comp.y) == (15, 12)
    c.setFocus()
    QTest.keyClick(c, Qt.Key_R)
    assert doc.project.components[0].rotation == 90
    QTest.keyClick(c, Qt.Key_F)
    assert doc.project.components[0].side == "bottom"
    QTest.keyClick(c, Qt.Key_Delete)
    assert doc.project.components == []
    doc.undo()
    assert len(doc.project.components) == 1
    _close(w)


def test_example_3d_and_order_pages(qapp, tmp_path):
    from pcbpro.ui.main_window import MainWindow
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    w.open_example()
    w.tabs.setCurrentWidget(w.page3d)
    QTest.qWait(600)
    view = w.page3d.view
    view.repaint()
    QTest.qWait(200)
    assert len(view.meshes) > 10
    assert view.grabFramebuffer().width() > 100
    w.tabs.setCurrentWidget(w.order_page)
    QTest.qWait(200)
    assert w.order_page.quotes and w.order_page.quotes[0].ok
    zp = w.order_page.export_files(str(tmp_path / "fab"))
    assert zp.exists()
    _close(w)
