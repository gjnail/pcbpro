import json
import math

import pytest
from shapely.geometry import Polygon

from pcbpro.model.board import Component, Project
from pcbpro.model.footprints import find_part
from pcbpro.pedal.enclosure import (CATALOG, Enclosure, PanelHole, all_holes, derived_holes, fit_outline,
                                    get_enclosure, knob_layout, set_enclosure, side_position, side_to_face)


def _part(name):
    lp = find_part(name)
    assert lp is not None, name
    return lp.make()


# --------------------------------------------------------------------------- catalogue & geometry

@pytest.mark.parametrize("key", list(CATALOG))
def test_catalogue_dimensions_are_consistent(key):
    s = CATALOG[key]
    for i in (0, 1):
        assert s.cavity[i] < s.face[i] <= s.ext[i] + 1e-6
        assert s.usable[i] > 20
    assert s.depth > 20 and s.face_t > s.wall


def test_board_face_mapping_mirrors_when_pots_are_under_the_board():
    enc = Enclosure("125B", cx=30, cy=60, face_side="bottom")
    u, v = enc.board_to_face(40, 50)  # right of and above the centre in the layout
    assert (u, v) == (-10, 10)  # seen from outside the face: left of centre, still above
    assert enc.face_to_board(u, v) == (40, 50)
    enc.face_side = "top"
    assert enc.board_to_face(40, 50) == (10, 10)


def test_side_coordinates_round_trip():
    enc = Enclosure("1590B")
    for wall, (u, v) in (("B", (12.0, enc.cavity_size[1] / 2)), ("D", (-8.0, -enc.cavity_size[1] / 2)),
                         ("C", (-enc.cavity_size[0] / 2, 20.0)), ("E", (enc.cavity_size[0] / 2, -15.0))):
        x, y = side_position(enc, wall, u, v, 9.0)
        u2, v2, z = side_to_face(enc, wall, x, y)
        assert abs(u2 - u) < 1e-9 and abs(v2 - v) < 1e-9 and abs(z - 9.0) < 1e-9
    # Tayda: +Y on the top side points to the rim (away from face A)
    assert side_position(enc, "B", 0, 0, enc.spec.depth)[1] == pytest.approx(enc.spec.depth / 2)


@pytest.mark.parametrize("n", range(1, 7))
def test_knob_layout_fits_the_cavity(n):
    enc = Enclosure("1590BB")
    pts = knob_layout(n, enc)
    assert len(pts) == n
    W, H = enc.cavity_size
    for u, v in pts:
        assert abs(u) + 8.5 <= W / 2 and abs(v) + 8.5 <= H / 2
    for i, a in enumerate(pts):
        for b in pts[i + 1:]:
            assert math.dist(a, b) >= 19.0


def test_fit_outline_avoids_the_screw_bosses():
    enc = Enclosure("1590B", cx=30, cy=56)
    outline = fit_outline(enc)
    board = enc.geom_to_face(Polygon(outline))
    for boss in enc.boss_polygons():
        assert board.intersection(boss).area < 1e-6
    assert board.area > 0.9 * enc.usable_polygon().area


# --------------------------------------------------------------------------- holes from board parts

def test_pot_shaft_becomes_a_face_hole(qapp):
    p = Project("t")
    enc = Enclosure("125B", cx=30, cy=60)
    set_enclosure(p, enc)
    pot = Component("RV1", "B100K", _part("Alpha 16 mm pot (PCB right-angle)"), 20, 30, 0, "bottom")
    p.components.append(pot)
    (h,) = derived_holes(p, get_enclosure(p))
    assert h.face == "A" and h.kind == "pot" and h.d == 7.5
    assert (h.x, h.y) == pytest.approx((10, 30))  # mirrored: left in the layout is right on the face
    assert not h.wrong_side
    pot.side = "top"
    assert derived_holes(p, get_enclosure(p))[0].wrong_side


def test_board_mounted_jack_drills_the_wall_it_faces(qapp):
    p = Project("t")
    set_enclosure(p, Enclosure("125B", cx=32, cy=60))
    jack = Component("J1", "IN", _part('1/4" jack stereo, Neutrik NMJ6HCD2'), 50, 40, 0, "top")
    p.components.append(jack)
    (h,) = derived_holes(p, get_enclosure(p))
    # opening points +x in the layout; panel A sees the bottom of the board, so that is the left wall (C)
    assert h.face == "C" and h.kind == "jack"
    enc = get_enclosure(p)
    near, far = enc.z_levels(p)
    _, v, z = side_to_face(enc, "C", h.x, h.y)
    assert v == pytest.approx(20) and z == pytest.approx(far + 9.1)


def test_enclosure_survives_save_and_load(qapp):
    from pcbpro.pedal.templates import PedalOptions, new_pedal_project
    p, _ = new_pedal_project(PedalOptions(enclosure="1590BB", knobs=["A", "B", "C", "D"]))
    data = json.loads(json.dumps(p.to_dict()))
    q = Project.from_dict(data)
    a, b = get_enclosure(p), get_enclosure(q)
    assert b.model == "1590BB" and len(b.holes) == len(a.holes)
    assert [h.to_dict() for h in b.holes] == [h.to_dict() for h in a.holes]


# --------------------------------------------------------------------------- generator & checks

@pytest.mark.parametrize("key,knobs", [("125B", 3), ("1590B", 2), ("1590BB", 4), ("1590XX", 6), ("1590DD", 4)])
def test_new_pedal_passes_the_enclosure_checks(qapp, key, knobs):
    from pcbpro.pedal.checks import run_pedal_checks
    from pcbpro.pedal.templates import PedalOptions, new_pedal_project
    p, notes = new_pedal_project(PedalOptions(enclosure=key, knobs=[f"K{i}" for i in range(knobs)]))
    errors = [v.message for v in run_pedal_checks(p) if v.severity == "error"]
    assert errors == []
    assert sum(1 for c in p.components if c.ref.startswith("RV")) == knobs
    kinds = {h.kind for h in all_holes(p, get_enclosure(p))}
    assert {"pot", "footswitch", "jack", "dc"} <= kinds


def test_checks_catch_real_problems(qapp):
    from pcbpro.pedal.checks import run_pedal_checks
    from pcbpro.pedal.templates import PedalOptions, new_pedal_project, part
    p, _ = new_pedal_project(PedalOptions(enclosure="1590B", knobs=["VOL", "GAIN"]))
    enc = get_enclosure(p)
    # a board as big as the face hits the walls and bosses
    W, H = enc.face_size
    p.board.outline = [(0, 0), (W, 0), (W, H), (0, H)]
    # a 16 mm tall electrolytic does not fit under the board of a 1590B
    tall = Component("C99", "1000uF", part("Electrolytic D10 P5 H16"), enc.cx, enc.cy, 0, "top")
    p.components.append(tall)
    # two panel holes on top of each other
    enc.holes.append(PanelHole.of("toggle", "A", 0.0, -36.0))
    set_enclosure(p, enc)
    kinds = {(v.kind, v.severity) for v in run_pedal_checks(p)}
    assert ("enclosure", "error") in kinds
    assert ("height", "error") in kinds
    assert ("panel", "error") in kinds


def test_pedal_checks_run_inside_drc(qapp):
    from pcbpro.model.drc import run_drc
    from pcbpro.pedal.templates import PedalOptions, new_pedal_project
    p, _ = new_pedal_project(PedalOptions(enclosure="125B"))
    enc = get_enclosure(p)
    enc.holes.append(PanelHole.of("footswitch", "A", 0.0, 46.0))  # right on top of the middle knob
    set_enclosure(p, enc)
    assert any(v.kind == "panel" for v in run_drc(p))


# --------------------------------------------------------------------------- outputs

def test_drill_exports(qapp, tmp_path):
    from PySide6.QtPdf import QPdfDocument
    from pcbpro.pedal.drill import export_pdf, tayda_csv, tayda_text
    from pcbpro.pedal.templates import PedalOptions, new_pedal_project
    for key in ("125B", "1590XX", "1590DD"):
        p, _ = new_pedal_project(PedalOptions(enclosure=key, name=f"T {key}"))
        out = export_pdf(p, tmp_path / f"{key}.pdf")
        doc = QPdfDocument()
        doc.load(str(out))
        assert doc.pageCount() >= 2
    text = tayda_text(p)
    assert "Side A - Face" in text and "Side B - Top side" in text and "-0.00" not in text
    rows = tayda_csv(p).splitlines()
    assert rows[0] == "Side,Diameter,X,Y,Label,Part,Source"
    assert len(rows) - 1 == len(all_holes(p, get_enclosure(p)))


def test_build_sheet_groups_parts_and_hardware(qapp):
    from pcbpro.pedal.bom import build_rows, value_number
    from pcbpro.pedal.templates import PedalOptions, new_pedal_project
    assert value_number("4k7") == pytest.approx(4700) and value_number("2n2") == pytest.approx(2.2e-9)
    p, _ = new_pedal_project(PedalOptions(enclosure="125B", knobs=["LEVEL", "TONE", "DRIVE"]))
    rows = build_rows(p)
    sections = [r["Section"] for r in rows]
    assert sections.index("Resistors") < sections.index("Potentiometers") < sections.index("Hardware")
    knobs = next(r for r in rows if r["Part"] == "Knob for 6 mm shaft")
    assert knobs["Qty"] == 3
    assert not any(r["Designators"].startswith("W") for r in rows)  # wire pads are not parts


def test_bundled_overdrive_example_is_clean(qapp):
    from pcbpro.examples import EXAMPLE_DIR, load_example
    from pcbpro.model.connectivity import get_connectivity
    from pcbpro.model.copper import fill_all_zones
    from pcbpro.model.drc import run_drc
    p = load_example(EXAMPLE_DIR / "Three_Knob_Overdrive_125B.pcbpro")
    fill_all_zones(p)
    assert get_connectivity(p).unrouted_count() == 0
    errors = [v.message for v in run_drc(p) if v.severity == "error"]
    assert errors == []
    assert get_enclosure(p).model == "125B"


def test_value_on_silkscreen(qapp):
    from pcbpro.model.artwork import component_silk
    c = Component("R1", "4k7", _part("Resistor axial 1/4 W P10.16"), 10, 10)
    plain = component_silk(c).area
    c.show_value = True
    assert component_silk(c).area > plain


def test_package_includes_pedal_documents(qapp, tmp_path):
    from pcbpro.export.package import export_package
    from pcbpro.pedal.templates import PedalOptions, new_pedal_project
    p, _ = new_pedal_project(PedalOptions(enclosure="125B", name="Pkg"))
    res = export_package(p, tmp_path)
    names = {f.name for f in res.pedal_files}
    assert {"Pkg_Tayda_drill.txt", "Pkg_build_sheet.csv", "Pkg_drill_template.pdf"} <= names


def test_pedal_meshes(qapp):
    from pcbpro.pedal.mesh3d import flip_for_pedal_view, pedal_parts
    from pcbpro.pedal.templates import PedalOptions, new_pedal_project
    p, _ = new_pedal_project(PedalOptions(enclosure="125B"))
    parts = pedal_parts(p)
    assert len(parts) >= 5
    arr = next(iter(parts.values()))
    assert arr.shape[1] == 8 and not (arr != arr).any()  # no NaNs
    f = flip_for_pedal_view(arr)
    assert (f[:, 0] == -arr[:, 0]).all() and (f[:, 2] == -arr[:, 2]).all()


# --------------------------------------------------------------------------- UI

def test_pedal_ui(qapp):
    from PySide6.QtTest import QTest
    from pcbpro.pedal.templates import new_pedal_project
    from pcbpro.ui.main_window import MainWindow
    from pcbpro.ui.pedal_ui import PedalWizardDialog
    w = MainWindow()
    w.resize(1500, 900)
    w.show()
    assert any(a.text().replace("&", "") == "Pedal" for a in w.menuBar().actions())
    dlg = PedalWizardDialog(w)
    dlg.knobs.setValue(2)
    opts = dlg.options()
    assert opts.knobs == ["LEVEL", "TONE"] and opts.enclosure == "125B"
    p, _ = new_pedal_project(opts)
    w.doc.set_project(p)
    page = w.enclosure_page
    w.tabs.setCurrentWidget(page)
    QTest.qWait(100)
    n = len(get_enclosure(w.doc.project).holes)
    page._add_at("E", 0.0, -10.0)
    assert len(get_enclosure(w.doc.project).holes) == n + 1
    assert page.table.rowCount() == len(all_holes(w.doc.project, get_enclosure(w.doc.project)))
    w.doc.undo()
    assert len(get_enclosure(w.doc.project).holes) == n
    w.tabs.setCurrentWidget(w.page3d)
    w.page3d.pedal_cb.setChecked(True)
    QTest.qWait(500)
    w.page3d.view.repaint()
    QTest.qWait(200)
    assert w.page3d.view._flip and len(w.page3d.view.meshes) > 10
    w.canvas.repaint()  # enclosure overlay paints without errors
    w.doc.dirty = False
    w.close()
