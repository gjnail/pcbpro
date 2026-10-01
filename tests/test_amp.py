"""Guitar / bass amp support: tube data, sockets, HV rules and checks, the amp builder, tone stacks and the UI."""
import json
import math

import numpy as np
import pytest

from pcbpro.amp import hv
from pcbpro.amp.tonestack import PRESETS, ToneStack, response_db, stack_parts, taper
from pcbpro.amp.tubes import TUBES, find_tube, heater_load, section_pins
from pcbpro.model.board import Board, Component, Project, Track
from pcbpro.model.footprints import find_part


def _part(name):
    lp = find_part(name)
    assert lp is not None, name
    return lp.make()


# --------------------------------------------------------------------------- tube data

@pytest.mark.parametrize("name", list(TUBES))
def test_tube_pinouts_are_complete(name):
    t = TUBES[name]
    n = {"noval": 9, "b7g": 7, "octal": 8}[t.base]
    assert sorted(t.pins, key=int) == [str(i) for i in range(1, n + 1)]
    assert len(t.heater_pins) == 2
    if t.kind == "triode2":
        for s in "AB":
            pins = section_pins(t, s)
            assert all(pins.values()) and len(set(pins.values())) == 3
    elif t.kind == "rectifier":
        assert t.pin("A1") and t.pin("A2") and t.i_max_ma > 0
    else:
        assert t.pin("A") and t.pin("G1") and t.pin("K")


def test_well_known_pinouts():
    assert TUBES["12AX7"].pins["1"] == "PA" and TUBES["12AX7"].pins["9"] == "HCT"
    assert TUBES["EL84"].pin("A") == "7" and TUBES["EL84"].pin("G2") == "9" and TUBES["EL84"].pin("G1") == "2"
    assert TUBES["6V6GT"].pin("A") == "3" and TUBES["6V6GT"].pin("K") == "8" and TUBES["6V6GT"].heater_pins == ["2", "7"]
    assert TUBES["EL34"].pins["1"] == "G3"
    assert TUBES["5Y3GT"].pin("HK") == "8" and {TUBES["5Y3GT"].pin("A1"), TUBES["5Y3GT"].pin("A2")} == {"4", "6"}
    assert TUBES["EZ81"].pin("K") == "3"
    assert TUBES["6AQ5"].pins["1"] == TUBES["6AQ5"].pins["7"] == "G1"
    assert TUBES["EF86"].pin("G1") == "9" and TUBES["EF86"].pin("G2") == "1"


@pytest.mark.parametrize("value,name", [("12AX7", "12AX7"), ("ECC83", "12AX7"), ("12ax7a", "12AX7"),
                                        ("EL34B", "EL34"), ("6L6GC-STR", "6L6GC"), ("GZ34", "5AR4"),
                                        ("V1 (ECC81)", "12AT7"), ("6V6", "6V6GT"), ("socket", None), ("", None)])
def test_find_tube(value, name):
    t = find_tube(value)
    assert (t.name if t else None) == name


# --------------------------------------------------------------------------- sockets & library

def test_socket_pin_geometry(qapp):
    from pcbpro.library.gen_amp import SOCKETS, socket_pin_positions, tube_socket
    for key, (base, circle, drill, pad, *_r) in SOCKETS.items():
        fp = tube_socket(key)
        pos = socket_pin_positions(base, circle)
        assert [p.number for p in fp.pads] == [n for n, _, _ in pos]
        for p in fp.pads:
            assert math.hypot(p.x, p.y) == pytest.approx(circle / 2, abs=1e-3)
            assert p.drill == drill
        # pin 1 sits just counter-clockwise of the gap / key at the bottom (screen y down)
        p1 = fp.pads[0]
        assert p1.x > 0 and p1.y > 0
        last = fp.pads[-1]
        assert last.x < 0 and last.y > 0
        assert fp.model["type"] == "tube" and fp.model["base"] == base
    belton = tube_socket("belton_vt9")
    assert math.hypot(belton.pads[0].x, belton.pads[0].y) * 2 == pytest.approx(21.0)
    assert belton.pads[0].drill == 1.8


def test_amp_parts_in_library():
    from pcbpro.library.gen_amp import tube_part_name
    for t in TUBES:
        lp = find_part(tube_part_name(t))
        assert lp is not None and lp.value == t and lp.prefix == "V"
    for name in ("Snap-in electrolytic D30 x 40 mm", "Power resistor 7 W cement L25 (lying)", "LM3886 (TO-220-11)",
                 "speakON NL4MD-H-3 (PCB)", "Relay Omron G5LE-1 (SPDT)", "Pot 16 mm right-angle (Alps RK163)",
                 "Amp wire pads HV1, CT, HV2", "Star ground point (M4, plated)", "Bridge rectifier KBU (inline)"):
        assert find_part(name) is not None, name


def test_amp_footprints_match_kicad(qapp):
    from pcbpro.library.verify import REFERENCES, compare, kicad_root, load_reference
    if kicad_root() is None:
        pytest.skip("KiCad library not installed")
    amp = [n for n in REFERENCES if find_part(n) is not None and find_part(n).category.startswith("Amp/")]
    assert len(amp) >= 35
    for name in amp:
        res = compare(find_part(name).make(), load_reference(REFERENCES[name]), name)
        assert res.ok(), res.summary()


def test_hv_wire_pads_keep_their_spacing():
    fp = _part("Amp wire pads HV1, CT, HV2")
    gaps = [b.x - a.x - (a.w + b.w) / 2 for a, b in zip(fp.pads, fp.pads[1:])]
    assert min(gaps) >= hv.ipc_clearance(2 * 460)  # both ends of a 325-0-325 V winding in anti-phase


# --------------------------------------------------------------------------- HV rules

def test_ipc_clearance_table():
    assert hv.ipc_clearance(12) == 0.1
    assert hv.ipc_clearance(40) == 0.6
    assert hv.ipc_clearance(250) == 1.25
    assert hv.ipc_clearance(450) == 2.5
    assert hv.ipc_clearance(1000) == pytest.approx(5.0)
    assert hv.ipc_clearance(450, "B4") == 0.8 and hv.ipc_clearance(450, "A6") == 1.5


def test_track_width_for_current():
    assert hv.track_width_for(1.0) == pytest.approx(0.30, abs=0.03)
    assert hv.track_width_for(3.0) == pytest.approx(1.37, abs=0.05)
    assert hv.track_width_for(3.0, oz=2.0) == pytest.approx(hv.track_width_for(3.0) / 2, rel=0.01)
    w = hv.track_width_for(2.5)
    assert hv.current_for(w) == pytest.approx(2.5, rel=0.01)


def test_parse_net_voltage():
    assert hv.parse_net_voltage("450") == (450.0, 0.0)
    assert hv.parse_net_voltage("-52V") == (-52.0, 0.0)
    dc, ac = hv.parse_net_voltage("300VAC")
    assert dc == 0 and ac == pytest.approx(300 * math.sqrt(2))


def test_annotations_and_classes_round_trip():
    p = Project("t")
    hv.set_net(p, "B+", v=450, amps=0.2)
    hv.set_net(p, "HV1", ac_rms=325)
    hv.set_net(p, "HTR", ac_rms=3.15, amps=3.0)
    hv.set_net(p, "AC", ac_rms=230, mains=True)
    hv.set_net(p, "NIL", v=0)
    assert "NIL" not in hv.net_table(p)
    notes = hv.apply_hv_netclasses(p)
    assert notes
    # classes carry the lead (pad) spacing, IPC-2221B A6; tracks keep conductor (B2) spacing pair by pair
    assert p.net_class_map["B+"] == "HV500" and p.netclasses["HV500"].clearance == 1.5
    assert hv.pair_clearance_fn(p)("B+", "GND") == 2.5 and hv.pair_clearance_fn(p)("B+", "GND", True) == 1.5
    assert p.net_class_map["AC"] == "Mains"
    assert p.netclasses[p.net_class_map["HTR"]].track_width >= hv.track_width_for(3.0)
    q = Project.from_dict(json.loads(json.dumps(p.to_dict())))
    assert q.amp == p.amp and q.net_class_map == p.net_class_map
    # pairwise spacing: both ends of an HV winding need more than either does to ground
    f = hv.pair_clearance_fn(p)
    assert f("HV1", "B+") > p.netclasses["HV500"].clearance
    assert f("B+", "B+") == 0.0


# --------------------------------------------------------------------------- checks

def _hv_project():
    p = Project("hv")
    p.board = Board(outline=[(0, 0), (120, 0), (120, 80), (0, 80)])
    hv.set_net(p, "B+", v=420)
    hv.set_net(p, "PLATE", v=390)
    return p


def test_hv_clearance_check_flags_close_copper(qapp):
    from pcbpro.model.drc import run_drc
    p = _hv_project()
    p.tracks.append(Track(10, 40, 100, 40, 0.5, "F.Cu", "B+"))
    p.tracks.append(Track(10, 41.5, 100, 41.5, 0.5, "F.Cu", "SIG"))
    p.tracks.append(Track(10, 50, 100, 50, 0.5, "F.Cu", "PLATE"))
    p.tracks.append(Track(10, 51.5, 100, 51.5, 0.5, "F.Cu", "B+"))
    hvv = [v for v in run_drc(p) if v.kind == "hv-clearance"]
    assert len(hvv) == 1 and "SIG" in hvv[0].message  # 30 V between B+ and PLATE needs only 0.1 mm


def test_part_rating_and_bleeder_checks(qapp):
    from pcbpro.amp.checks import run_amp_checks
    p = _hv_project()
    p.components.append(Component("C1", "47uF 350V", _part("Electrolytic D16 P7.5 H25"), 20, 20, 0, "top",
                                  {"1": "B+", "2": "GND"}))
    p.components.append(Component("C2", "22nF", _part("Film box L18 W7 P15"), 50, 20, 0, "top",
                                  {"1": "PLATE", "2": "GRID"}))
    p.components.append(Component("C3", "100uF 450V", _part("Electrolytic D16 P7.5 H25"), 80, 20, 0, "top",
                                  {"1": "GND", "2": "B+"}))
    p.components.append(Component("R1", "1k", _part("Resistor axial 1/4 W P10.16"), 20, 60, 0, "top",
                                  {"1": "B+", "2": "PLATE"}))
    msgs = [v.message for v in run_amp_checks(p)]
    assert any("C1 is rated 350 V" in m for m in msgs)
    assert any("C2" in m and "no voltage rating" in m for m in msgs)
    assert any("C3" in m and "backwards" in m for m in msgs)
    assert any("R1" in m and "dissipates" in m for m in msgs)
    assert any("no resistive path" in m for m in msgs)
    p.components.append(Component("R2", "220k", _part("Resistor axial 2 W P20.32"), 60, 60, 0, "top",
                                  {"1": "B+", "2": "GND"}))
    assert not any("no resistive path" in v.message for v in run_amp_checks(p))


def test_tube_wiring_checks():
    from pcbpro.amp.checks import run_amp_checks
    from pcbpro.library.gen_amp import tube_part_name
    p = _hv_project()
    p.components.append(Component("V1", "EL84", _part(tube_part_name("EL84")), 40, 40, 0, "top",
                                  {"7": "PLATE", "6": "B+", "4": "H", "5": "H"}))
    p.components.append(Component("V2", "12AX7", _part(tube_part_name("12AX7")), 80, 40, 0, "top",
                                  {"4": "HA", "5": "HB", "9": "HB"}))
    p.components.append(Component("V3", "6V6GT", _part(tube_part_name("12AX7")), 100, 40, 0, "top", {}))
    msgs = [v.message for v in run_amp_checks(p)]
    assert any("V1 pin 6" in m and "tie point" in m for m in msgs)
    assert any("V1" in m and "shorted" in m for m in msgs)
    assert any("V1" in m and "above the 300 V" in m for m in msgs)
    assert any("V2" in m and "for 6.3 V tie pins 4 and 5" in m for m in msgs)
    assert any("V3" in m and "octal socket" in m for m in msgs)


def test_heater_load():
    from pcbpro.library.gen_amp import tube_part_name
    p = Project("h")
    for i, t in enumerate(("12AX7", "12AX7", "EL84", "EL84", "EZ81")):
        p.components.append(Component(f"V{i + 1}", t, _part(tube_part_name(t)), 30 * i, 0, 0))
    assert heater_load(p).by_voltage[6.3] == pytest.approx(0.3 * 2 + 0.76 * 2 + 1.0)


# --------------------------------------------------------------------------- tone stacks

def test_tone_stack_controls_do_what_they_say():
    f = np.array([60.0, 500.0, 6000.0])
    ts = PRESETS["Fender Bassman 5F6-A"]
    lo_b, hi_b = response_db(ts, 5, 0, 5, f), response_db(ts, 5, 10, 5, f)
    assert hi_b[0] > lo_b[0] + 3  # bass knob lifts the lows
    lo_t, hi_t = response_db(ts, 0, 5, 5, f), response_db(ts, 10, 5, 5, f)
    assert hi_t[2] > lo_t[2] + 3  # treble knob lifts the highs
    lo_m, hi_m = response_db(ts, 5, 5, 0, f), response_db(ts, 5, 5, 10, f)
    assert hi_m[1] > lo_m[1] + 2  # middle knob fills in the scoop
    assert np.all(response_db(ts, 10, 10, 10, f) < 0.5)  # a passive stack never gains


def test_tone_stack_matches_the_analytic_treble_case():
    """Treble full, bass and mid at zero: the stack collapses to C1 into the treble pot || load."""
    ts = ToneStack(250e-12, 56e3, 20e-9, 20e-9, 250e3, 1e6, 25e3, rs=1.0, rl=1e6)
    f = np.array([200.0, 3000.0, 20000.0])
    r = 250e3 * 1e6 / (250e3 + 1e6)
    exact = [20 * math.log10(abs(2j * math.pi * x * 250e-12 * r / (1 + 2j * math.pi * x * 250e-12 * r))) for x in f]
    got = response_db(ts, 10, 0, 0, f)
    assert np.allclose(got, exact, atol=0.15)


def test_taper():
    assert taper(0.5, "A") == pytest.approx(0.1)
    assert taper(0.5, "B") == 0.5 and taper(1.0, "A") == pytest.approx(1.0)


def test_stack_parts():
    parts = stack_parts(PRESETS["Marshall JCM800 2203"], "IN", "OUT")
    assert len(parts) == 7
    pots = [p for p in parts if p.prefix == "RV"]
    assert {p.label for p in pots} == {"TREBLE", "BASS", "MIDDLE"}
    treble = next(p for p in pots if p.label == "TREBLE")
    assert treble.nets["2"] == "OUT"


# --------------------------------------------------------------------------- builder

@pytest.mark.parametrize("name", ["Tweed Champ 5 W single-ended (12AX7 / 6V6GT / 5Y3GT)",
                                  "EL84 18 W push-pull (12AX7 x2 / EL84 x2 / EZ81)",
                                  "LM3886 bass amp 50 W (tone stack, XLR DI, speakON)",
                                  "LM3886 guitar amp 50 W (drive, Marshall tone stack)"])
def test_designs_place_cleanly(qapp, name):
    from pcbpro.amp.builder import DESIGNS, build_amp
    from pcbpro.model.drc import run_drc
    p, notes = build_amp(DESIGNS[name]())
    assert not any("did not fit" in n for n in notes)
    bx0, by0, bx1, by1 = p.board.bounds()
    assert bx1 - bx0 < 320 and by1 - by0 <= 120
    for c in p.components:
        assert bx0 <= c.x <= bx1 and by0 <= c.y <= by1, c.ref
    bad = [v for v in run_drc(p) if v.severity == "error" and v.kind != "unrouted"]
    assert not bad, [v.message for v in bad]
    assert hv.net_table(p) and p.amp.get("classes")


def test_champ_routes_drc_clean(qapp):
    from pcbpro.amp.builder import champ_5w, build_amp
    from pcbpro.model.drc import run_drc
    p, notes = build_amp(champ_5w(), route=True)
    errors = [v for v in run_drc(p) if v.severity == "error"]
    assert not errors, [v.message for v in errors]
    # the 5Y3's filament winding is at B+, so its pads must keep B+ spacing from ground copper
    assert p.net_class_map["FIL"].startswith("HV")


def test_bundled_amp_examples_load(qapp):
    from pcbpro.amp.builder import AMP_EXAMPLES
    from pcbpro.examples import EXAMPLE_DIR, load_example
    for file_name in AMP_EXAMPLES.values():
        p = load_example(EXAMPLE_DIR / file_name)
        assert p.components and p.tracks and hv.net_table(p)


# --------------------------------------------------------------------------- 3D and UI

def test_tube_mesh_has_glass_and_glow(qapp):
    from pcbpro.library.gen_amp import tube_part_name
    from pcbpro.ui.mesh import component_parts
    for t in ("12AX7", "EL84", "6L6GC", "5Y3GT", "6AQ5"):
        c = Component("V1", t, _part(tube_part_name(t)), 0, 0, 0)
        mats = [m for m, _ in component_parts(c).items]
        assert any(len(m) > 6 and m[6] < 1 for m in mats), t  # see-through glass
        assert any(len(m) > 7 and m[7] > 0 for m in mats), t  # glowing heater
    bare = Component("V1", "socket", _part("Noval B9A socket, Belton VT9-PT (PCB)"), 0, 0, 0)
    assert not any(len(m) > 6 for m, _ in component_parts(bare).items)  # no tube drawn for a bare socket


def test_amp_menu_and_dialogs(qapp):
    from pcbpro.ui import amp_ui
    from pcbpro.ui.main_window import MainWindow
    win = MainWindow()
    try:
        titles = [a.text().replace("&", "") for a in win.menuBar().actions()]
        assert "Amp" in titles
        for dlg in (amp_ui.ToneStackDialog(win), amp_ui.CalculatorDialog(win), amp_ui.TubeTableDialog(win),
                    amp_ui.NetVoltageDialog(win.doc.project, win), amp_ui.NewAmpDialog(win)):
            dlg.close()
        nv = amp_ui.NetVoltageDialog(_hv_project(), win)
        nets, settings = nv.values()
        assert nets["B+"]["v"] == 420 and settings["category"] == "B2"
    finally:
        win.close()
