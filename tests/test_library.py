import os

import pytest
from shapely.geometry import box
from shapely.strtree import STRtree

from pcbpro.model.board import Component, Project
from pcbpro.model.copper import pad_geom
from pcbpro.model.footprints import LIBRARY, find_part

BUILTIN = [p for p in LIBRARY if p.source != "catalog"]


def test_library_is_large():
    assert len(BUILTIN) > 1000
    cats = {p.category.split("/")[0] for p in BUILTIN}
    for needed in ("Resistors", "Capacitors", "Inductors", "Diodes", "Transistors", "ICs", "Connectors", "LEDs",
                   "Switches", "Relays", "Crystals & oscillators", "Modules", "Mechanical", "Batteries"):
        assert needed in cats
    assert len({p.name for p in LIBRARY}) == len(LIBRARY), "library part names must be unique"


@pytest.mark.parametrize("part", BUILTIN, ids=lambda p: p.name)
def test_every_builtin_footprint(qapp, part):
    from pcbpro.ui.mesh import component_parts
    fp = part.make()
    assert fp.pads
    x0, y0, x1, y1 = fp.courtyard
    court = box(x0, y0, x1, y1).buffer(1e-3)
    c = Component("X1", part.value, fp)
    geoms = []
    for pad in fp.pads:
        g = pad_geom(c, pad)
        assert g.is_valid and g.area > 0
        assert court.contains(g), f"pad {pad.number} outside courtyard"
        if pad.kind == "tht":
            assert pad.drill < min(pad.w, pad.h) + 1e-9 or pad.is_slot
            if pad.is_slot:
                assert pad.drill < pad.w and pad.drill_h < pad.h
        geoms.append((pad, g))
    tree = STRtree([g for _, g in geoms])
    left, right = tree.query([g for _, g in geoms], predicate="dwithin", distance=0.05)
    for i, j in zip(left.tolist(), right.tolist()):
        if i < j:
            pa, pb = geoms[i][0], geoms[j][0]
            if pa.number != pb.number and "npth" not in (pa.kind, pb.kind) and "bridged" not in part.name:
                pytest.fail(f"pads {pa.number} and {pb.number} are closer than 0.05 mm")
    # 3D body must build for every part
    parts = component_parts(c)
    if fp.model.get("type") not in ("none",):
        assert parts.items, "no 3D geometry"


def test_catalog_resolves():
    from pcbpro.library.catalog import unresolved
    by_name = {p.name: p for p in LIBRARY}
    assert unresolved(by_name) == []
    cat = [p for p in LIBRARY if p.source == "catalog"]
    assert len(cat) > 200
    ne555 = find_part("NE555DR")
    assert ne555 and ne555.mpn == "NE555DR" and ne555.make().name == "SOIC-8"
    assert find_part("RP2040").make().pads[-1].w == 3.2


def test_search_ranking():
    from pcbpro.library.index import LibraryIndex
    idx = LibraryIndex()
    assert idx.search("NE555")[0].name.startswith("NE555")
    assert any(p.name == "Resistor 0805" for p in idx.search("0805 resistor"))
    assert any("USB-C" in p.name for p in idx.search("usb c"))
    assert idx.search("jst ph 4")[0].name.startswith("JST PH 4")
    assert idx.tree("builtin")


KICAD6 = """(footprint "R_0805_2012Metric" (version 20221018) (generator pcbnew)
  (layer "F.Cu")
  (descr "Resistor SMD 0805 (2012 Metric)")
  (fp_text reference "REF**" (at 0 -1.65) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
  (fp_line (start -0.227064 -0.735) (end 0.227064 -0.735) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))
  (fp_line (start -1 0.625) (end -1 -0.625) (stroke (width 0.1) (type solid)) (layer "F.Fab"))
  (fp_line (start 1 -0.625) (end 1 0.625) (stroke (width 0.1) (type solid)) (layer "F.Fab"))
  (fp_rect (start -1.68 -0.95) (end 1.68 0.95) (stroke (width 0.05) (type solid)) (fill none) (layer "F.CrtYd"))
  (fp_arc (start 0 -1) (mid 0.7071 -0.7071) (end 1 0) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))
  (pad "1" smd roundrect (at -0.9125 0) (size 1.025 1.4) (layers "F.Cu" "F.Paste" "F.Mask") (roundrect_rratio 0.243902))
  (pad "2" smd roundrect (at 0.9125 0) (size 1.025 1.4) (layers "F.Cu" "F.Paste" "F.Mask") (roundrect_rratio 0.243902))
)"""

KICAD_THT = """(footprint "Custom_Slot" (layer "F.Cu")
  (pad "1" thru_hole oval (at 0 0 90) (size 2 3.5) (drill oval 1 2.5) (layers "*.Cu" "*.Mask"))
  (pad "2" thru_hole circle (at 5 0) (size 1.8 1.8) (drill 1) (layers "*.Cu" "*.Mask"))
  (pad "" np_thru_hole circle (at 2.5 3) (size 1.2 1.2) (drill 1.2) (layers "*.Cu" "*.Mask"))
  (pad "3" smd custom (at 2.5 -3) (size 0.5 0.5) (layers "F.Cu" "F.Mask")
    (options (clearance outline) (anchor circle))
    (primitives (gr_poly (pts (xy -1 -0.5) (xy 1 -0.5) (xy 1 0.5) (xy -1 0.5)) (width 0) (fill yes))))
  (fp_circle (center 2.5 0) (end 5 0) (stroke (width 0.1)) (layer "F.Fab"))
)"""

KICAD5 = """(module LED_D5.0mm (layer F.Cu) (tedit 5995936A)
  (descr "LED, diameter 5.0mm, 2 pins")
  (fp_arc (start 1.27 0) (end -1.23 -1.469694) (angle 299.1) (layer F.SilkS) (width 0.12))
  (pad 1 thru_hole rect (at 0 0) (size 1.8 1.8) (drill 0.9) (layers *.Cu *.Mask))
  (pad 2 thru_hole circle (at 2.54 0) (size 1.8 1.8) (drill 0.9) (layers *.Cu *.Mask))
)"""


def test_kicad_import(qapp, tmp_path):
    from pcbpro.library.kicad import footprint_from_kicad, scan_kicad_dir
    fp = footprint_from_kicad(KICAD6)
    assert fp.name == "R_0805_2012Metric"
    assert [p.number for p in fp.pads] == ["1", "2"]
    assert fp.pads[0].shape == "roundrect" and abs(fp.pads[0].roundness - 0.2439) < 1e-3
    assert fp.model["type"] == "chip" and fp.model["L"] == 2.0
    assert fp.courtyard == (-1.68, -0.95, 1.68, 0.95)
    arcs = [g for g in fp.graphics if g.kind == "arc"]
    assert arcs and abs(arcs[0].r - 1.0) < 1e-3 and abs(abs(arcs[0].sweep) - 90) < 0.1
    tht = footprint_from_kicad(KICAD_THT)
    slot = tht.pads[0]
    assert slot.is_slot and slot.drill == 1 and slot.drill_h == 2.5 and slot.rotation == 90
    assert tht.pads[2].kind == "npth"
    custom = tht.pads[3]
    assert custom.shape == "poly" and len(custom.points) >= 4
    old = footprint_from_kicad(KICAD5)
    assert old.name == "LED_D5.0mm" and old.model["type"] == "led_tht"
    # a project using the imported footprints exports and passes basic checks
    p = Project("kicad")
    p.components.append(Component("R1", "1k", fp, 10, 10))
    p.components.append(Component("J1", "x", tht, 25, 20))
    from pcbpro.export.excellon import drill_file
    from pcbpro.export.gerber import generate_gerbers
    assert "G85" in drill_file(p, True)  # routed slot
    generate_gerbers(p)
    lib = tmp_path / "Test.pretty"
    lib.mkdir()
    (lib / "R_0805_2012Metric.kicad_mod").write_text(KICAD6)
    (lib / "Custom_Slot.kicad_mod").write_text(KICAD_THT)
    parts = scan_kicad_dir(tmp_path)
    assert {q.name for q in parts} == {"Test:R_0805_2012Metric", "Test:Custom_Slot"}
    assert parts[0].make().pads


def _easyeda_fixture():
    # head at (4000, 3000); units are 10 mil (0.254 mm)
    shapes = [
        "PAD~RECT~3990~3000~4~6~1~~1~0~3986 2997 3994 2997 3994 3003 3986 3003~0~gge1~0~~Y~0",
        "PAD~RECT~4010~3000~4~6~1~~2~0~4006 2997 4014 2997 4014 3003 4006 3003~0~gge2~0~~Y~0",
        "PAD~OVAL~4000~3020~8~12~11~~3~2~~0~gge3~6~4000 3017 4000 3023~Y~0",
        "PAD~POLYGON~4000~2980~6~6~1~~4~0~3997 2977 4003 2977 4003 2983 3997 2983~0~gge4~0~~Y~0",
        "HOLE~4020~3020~3~gge5~0",
        "TRACK~1~3~~3985 2992 4015 2992~gge6~0",
        "CIRCLE~3984~2994~1~1~3~gge7~0",
        "ARC~1~3~~M 3990 3010 A 10 10 0 0 1 4010 3010~~gge8~0",
    ]
    return {"dataStr": {"head": {"c_para": {"pre": "U?", "Manufacturer": "ACME", "Manufacturer Part": "TEST-123",
                                            "package": "SOIC-4_TEST"}}},
            "title": "TEST-123", "description": "Test part",
            "packageDetail": {"title": "SOIC-4_TEST", "dataStr": {"head": {"x": 4000, "y": 3000}, "shape": shapes}}}


def test_easyeda_conversion(qapp):
    from pcbpro.library.easyeda import parse_component
    part = parse_component(_easyeda_fixture(), "C123")
    fp = part.footprint
    assert part.mpn == "TEST-123" and part.manufacturer == "ACME"
    pads = {p.number: p for p in fp.pads if p.number}
    assert abs(pads["1"].x + 2.54) < 1e-6 and abs(pads["1"].w - 1.016) < 1e-6
    assert pads["3"].kind == "tht" and pads["3"].is_slot and abs(pads["3"].drill - 1.016) < 1e-6
    assert pads["4"].shape == "poly"
    assert any(p.kind == "npth" for p in fp.pads)
    assert any(g.layer == "silk" for g in fp.graphics)


@pytest.mark.skipif(not os.environ.get("PCBPRO_ONLINE_TESTS"), reason="set PCBPRO_ONLINE_TESTS=1 to hit the LCSC API")
def test_lcsc_live(qapp):
    from pcbpro.library.easyeda import import_lcsc
    p = import_lcsc("C2040")
    assert p.mpn == "RP2040" and len(p.footprint.pads) == 57


def test_user_library_roundtrip(qapp, tmp_path):
    from pcbpro.library.userlib import load_user_parts, save_part
    fp = find_part("SOIC-8").make()
    save_part("My Chip", fp, prefix="U", value="MYCHIP", mpn="MC-1", lcsc="C999", source="lcsc", folder=tmp_path)
    parts = load_user_parts(tmp_path)
    assert len(parts) == 1 and parts[0].lcsc == "C999" and parts[0].make().name == "SOIC-8"


def test_wizard_families_build(qapp):
    from pcbpro.ui.library_dialogs import _wizard_families
    for fam, (params, fn) in _wizard_families().items():
        kwargs = {spec[0]: spec[2] for spec in params}
        fp = fn(**kwargs)
        assert fp.pads, fam


def test_standard_values():
    from pcbpro.ui.panels import standard_values
    r = standard_values("R12")
    assert "4k7" in r and "10k" in r and "1M" in r
    c = standard_values("C3")
    assert "100nF" in c and "10uF" in c and "1000uF" in c
    assert standard_values("U1") == []
