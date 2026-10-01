"""Amp Designer: every combination designs, the numbers are sane, options change the circuit, boards come out clean."""
import pytest

from pcbpro.amp.builder import amp_part, build_amp
from pcbpro.amp.designer import (POWER, SS_POWER, VOICINGS, AmpSpec, design_amp, e12, fmt_c, fmt_r, options_for,
                                 report_html, report_text, rpart)
from pcbpro.amp.tubes import TUBES

COMBOS = [(vk, pk) for vk, v in VOICINGS.items() for pk in options_for(v.instrument, v.tech)[1]]


def _design(**kw):
    return design_amp(AmpSpec(**kw))


def _refs(design, prefix):
    return [p for p in design.parts if p.prefix == prefix]


def _all_nets(design):
    return {n for p in design.parts for n in p.nets.values()}


# --------------------------------------------------------------------------- helpers

def test_value_helpers():
    assert e12(663e3) == 680e3 and e12(1538) == 1500 and e12(95) == 100
    assert [fmt_r(v) for v in (2.7, 470, 1500, 4700, 100e3, 1e6, 1.5e6)] == ["2R7", "470R", "1k5", "4k7", "100k", "1M",
                                                                            "1M5"]
    assert fmt_c(0.68e-6) == "680nF" and fmt_c(22e-6) == "22uF" and fmt_c(470e-12) == "470pF"
    assert rpart(100e3, 100) == "res_small"  # 0.1 W
    assert rpart(220e3, 460) == "res2w"  # 0.96 W
    assert rpart(100e3, 200) == "res1w"  # 0.4 W at 200 V: a 1 W part stays under half its rating
    assert rpart(150, 30) == "res15w"  # 6 W


# --------------------------------------------------------------------------- every combination

@pytest.mark.parametrize("voicing,power", COMBOS)
def test_every_combination_designs(voicing, power):
    v = VOICINGS[voicing]
    design, rep = _design(instrument=v.instrument, tech=v.tech, voicing=voicing, power=power)
    nets = _all_nets(design)
    assert {"IN", "GND", "SPK"} <= nets
    for p in design.parts:  # every part resolves to a library footprint
        if p.fp is None:
            amp_part(p.part)
    assert rep.pout > 0 and rep.stages and rep.buy and rep.character
    assert 0 <= rep.breakup[1] <= rep.breakup[0] <= 10
    if v.tech == "tube":
        opt = POWER[power]
        assert sum(1 for p in _refs(design, "V") if p.value == opt.tube) == opt.count
        b_nodes = [n for n in design.volts if n.startswith("B+") and n[2:].isdigit()]
        levels = [design.volts[f"B+{i}"] for i in range(1, len(b_nodes) + 1)]
        assert levels == sorted(levels, reverse=True), levels  # each filter node is lower than the one before
        assert all(t in TUBES for t in rep.tubes)
        # every tube pin that is used carries a net the circuit defines
        for tube in _refs(design, "V"):
            for pin in tube.nets:
                assert pin in TUBES[tube.value].pins
        assert design.volts["B+1"] == opt.bplus
    else:
        assert "V+" in nets and "V-" in nets


# --------------------------------------------------------------------------- operating points & choices

def test_rectifier_choice_follows_the_current():
    _, rep = _design(voicing="tweed", power="pp_6v6")
    assert "5Y3GT" in rep.tubes
    _, rep = _design(voicing="chime", power="pp_el84")
    assert "EZ81" in rep.tubes
    _, rep = _design(voicing="plexi", power="pp_el34")
    assert not any(t in ("5Y3GT", "5AR4", "5U4GB", "EZ81") for t in rep.tubes)
    _, rep = _design(voicing="plexi", power="pp_el34x4", rectifier="tube")
    assert any("No tube rectifier" in w for w in rep.warnings)
    _, rep = _design(voicing="plexi", power="pp_el34", rectifier="tube")
    assert "5AR4" in rep.tubes or "5U4GB" in rep.tubes


def test_filter_caps_are_rated_for_the_switch_on_voltage():
    design, _ = _design(voicing="plexi", power="pp_kt88")  # solid-state rectifier: about 508 V before tubes conduct
    series = [p for p in design.parts if p.prefix == "C" and any(str(n).endswith("_MID") for n in p.nets.values())]
    assert series and all("350V" in p.value for p in series)
    design, _ = _design(voicing="plexi", power="pp_el34")  # about 487 V at switch-on, 460 V working
    hv = [p for p in design.parts if p.prefix == "C" and p.nets.get("1", "").startswith("B+")]
    single = [p for p in hv if not any(str(n).endswith("_MID") for n in p.nets.values())]
    assert single and all(p.value.endswith("500V") for p in single)  # lower nodes: one 500 V part each
    assert any(p.nets["1"] == "B+1" and p.nets["2"] == "B+1_MID" for p in hv)  # 460 V > 90 % of 500 V: a pair
    from pcbpro.amp.checks import run_amp_checks
    p, _ = build_amp(design)
    assert not [v.message for v in run_amp_checks(p) if v.kind == "part-rating"]
    design, _ = _design(voicing="chime", power="pp_el84")  # EZ81 warms up slowly: rated for the working voltage
    assert not any(str(n).endswith("_MID") for n in _all_nets(design))
    assert all(p.value.endswith(("400V", "450V")) for p in design.parts
               if p.prefix == "C" and p.nets.get("1", "").startswith("B+"))


def test_fixed_bias_supply_covers_the_operating_point():
    design, rep = _design(voicing="blackface", power="pp_6l6")
    assert "BIAS_OUT" in _all_nets(design) and design.volts["BIAS_OUT"] == -45
    row = dict(rep.power_rows)["Bias adjust range"]
    lo, hi = (float(x.split(" V")[0]) for x in row.split(" to "))
    assert hi < -45 < lo  # e.g. -26 V ... -55 V
    assert any(p.part == "trimmer" for p in design.parts)
    assert any(p.prefix == "W" and "K1" in p.nets for p in design.parts)  # bias measurement pads


def test_cathode_follower_elevates_the_heaters():
    design, rep = _design(voicing="plexi", power="pp_el34")
    assert "HTR_EL" in _all_nets(design) and 40 <= design.volts["HTR_EL"] <= 75
    design, _ = _design(voicing="blackface", power="pp_6v6_fixed")
    assert "HTR_EL" not in _all_nets(design)


def test_heater_current_adds_up():
    design, rep = _design(voicing="blackface", power="pp_6v6_fixed")  # 12AX7 + 12AT7 + 2 x 6V6: all on the board
    total = sum(TUBES[t].heater_a for t in rep.tubes if TUBES[t].heater_v == 6.3)
    assert design.amps["HTR1"] == pytest.approx(total, abs=0.01)
    assert f"6.3 V {total * 1.2:.1f} A" in dict(rep.buy)["Power transformer"]
    # 4 x EL84 = 3 A of heaters: the power tubes get their own twisted-pair pads, the board carries the preamp's
    design, rep = _design(voicing="chime", power="pp_el84x4")
    total = sum(TUBES[t].heater_a for t in rep.tubes if TUBES[t].heater_v == 6.3)
    assert design.amps["HTR1"] == pytest.approx(total - 4 * 0.76, abs=0.01)
    assert sum(1 for p in design.parts if p.prefix == "W" and "H1" in p.nets and "PT" in p.nets["H1"]) == 4
    assert f"6.3 V {total * 1.2:.1f} A" in dict(rep.buy)["Power transformer"]
    assert any("twisted pairs" in t for t in rep.tips)


def test_options_change_the_circuit():
    base, _ = _design(voicing="plexi", power="pp_el34", master=False, presence=False)
    labels = {p.label for p in base.parts if p.prefix == "RV"}
    assert "MASTER" not in labels and "PRESENCE" not in labels
    more, _ = _design(voicing="plexi", power="pp_el34", master=True, presence=True, bright=True)
    labels = {p.label for p in more.parts if p.prefix == "RV"}
    assert {"MASTER", "PRESENCE", "VOLUME", "TREBLE", "BASS", "MIDDLE"} <= labels
    assert any(p.prefix == "C" and p.value.startswith("470pF") and "VOL_IN" in p.nets.values() for p in more.parts)
    nofb, _ = _design(voicing="plexi", power="pp_el34", nfb="off")
    assert "PI_NFB" not in _all_nets(nofb)
    choke, _ = _design(voicing="plexi", power="pp_el34", choke=True)
    resist, _ = _design(voicing="plexi", power="pp_el34", choke=False)
    assert any("CHK1" in p.nets for p in choke.parts) and not any("CHK1" in p.nets for p in resist.parts)
    sb, _ = _design(voicing="plexi", power="pp_el34", standby=True)
    assert "B+0" in _all_nets(sb)
    ss, _ = _design(tech="ss", voicing="ss_clean", fx_loop=True)
    assert {"SEND", "RET"} <= _all_nets(ss)
    bass, _ = _design(instrument="bass", tech="ss", voicing="ss_bass")
    assert "DI_H" in _all_nets(bass)


def test_character_ordering():
    def sens(**kw):
        return _design(**kw)[1].sensitivity_mv
    hg = sens(voicing="highgain", power="pp_el34")
    plexi = sens(voicing="plexi", power="pp_el34")
    bf = sens(voicing="blackface", power="pp_6l6")
    bass = sens(voicing="bass_tube", power="pp_6l6")
    assert hg < plexi < bf < bass
    assert _design(voicing="highgain", power="pp_el34")[1].character.startswith("High gain")
    assert _design(voicing="bass_tube", power="pp_6l6")[1].character.startswith("Clean")
    # a lower-gain V1 buys clean headroom
    assert sens(voicing="blackface", power="pp_6l6", v1="12AT7") > bf


def test_ss_rails_respect_the_speaker():
    _, rep = _design(tech="ss", voicing="ss_clean", power="lm3886_50", speaker=4)
    assert any("4 ohm" in w for w in rep.warnings)
    assert dict(rep.power_rows)["Rails"].startswith("+/-28")


def test_report_rendering():
    design, rep = _design(voicing="blackface", power="pp_6v6_fixed")
    html = report_html(rep)
    for heading in ("Sound and gain", "Power stage", "B+ supply", "What to buy", "Tips", "First power-up",
                    "Voltage chart"):
        assert heading in html
    assert "Power transformer" in report_text(rep) and design.notes == report_text(rep)
    # the voltage chart lists every tube in board order with its pins' expected voltages
    assert [tube for _, tube, _ in rep.chart] == rep.tubes
    plates = {fn: v for ref, tube, rows in rep.chart if tube == "6V6GT" for _, fn, v in rows}
    assert plates["A"] == f"{design.volts['OT_P1']} V" and plates["G1"] == "-36 V"
    assert any("bias" in step.lower() for step in rep.powerup)


# --------------------------------------------------------------------------- boards

@pytest.mark.parametrize("kw", [dict(voicing="blackface", power="pp_6v6_fixed"),
                                dict(voicing="tweed", power="se_6v6"),
                                dict(voicing="highgain", power="pp_el34x4"),
                                dict(voicing="chime", power="pp_el84", standby=True),
                                dict(instrument="bass", voicing="bass_tube", power="pp_6l6x4"),
                                dict(tech="ss", voicing="ss_drive", fx_loop=True),
                                dict(instrument="bass", tech="ss", voicing="ss_bass")])
def test_designed_boards_place_cleanly(qapp, kw):
    from pcbpro.model.drc import run_drc
    design, _ = _design(**kw)
    p, notes = build_amp(design)
    assert not any("did not fit" in n for n in notes)
    x0, y0, x1, y1 = p.board.bounds()
    assert x1 - x0 <= 460  # four power tubes with real air gaps make a 100 W board about 440 mm long
    bad = [v for v in run_drc(p) if v.severity == "error" and v.kind != "unrouted"]
    assert not bad, [v.message for v in bad]
    noisy = [v for v in run_drc(p) if v.kind in ("hv-clearance", "bleeder")]
    assert not noisy, [v.message for v in noisy]


def test_designed_amp_routes_drc_clean(qapp):
    from pcbpro.model.drc import run_drc
    design, _ = _design(voicing="plexi", power="pp_el34", master=True)
    p, notes = build_amp(design, route=True)
    errors = [v for v in run_drc(p) if v.severity == "error"]
    assert not errors, [v.message for v in errors[:10]]


# --------------------------------------------------------------------------- UI

def test_build_my_amp_flow(qapp, monkeypatch):
    """Amp > Amp Designer > Build my amp: the board lands in the window with the spec saved for re-opening."""
    from pcbpro.ui import amp_designer
    from pcbpro.ui.main_window import MainWindow
    win = MainWindow()
    try:
        monkeypatch.setattr(amp_designer.AmpDesignerDialog, "exec", lambda self: (self.route.setChecked(False), 1)[1])
        monkeypatch.setattr(win, "_confirm_discard", lambda: True)
        amp_designer.open_designer(win)
        p = win.doc.project
        assert p.components and p.amp.get("spec", {}).get("voicing") == "blackface"
        assert "Power transformer" in p.notes
        # re-opening the designer on this board starts from its choices
        seen = {}
        monkeypatch.setattr(amp_designer.AmpDesignerDialog, "exec",
                            lambda self: seen.setdefault("voicing", self.spec().voicing) and 0)
        p.amp["spec"]["voicing"] = "plexi"
        amp_designer.open_designer(win)
        assert seen["voicing"] == "plexi"
    finally:
        win.close()


def test_designer_dialog(qapp):
    from pcbpro.ui.amp_designer import AmpDesignerDialog
    dlg = AmpDesignerDialog(AmpSpec(voicing="plexi"))
    try:
        assert dlg.report is not None and dlg.report.title.startswith("Plexi")
        for b in dlg.tech.buttons():
            if b.property("key") == "ss":
                b.click()
        dlg._refresh()
        assert dlg.spec().tech == "ss" and dlg.report.tubes == []
        for b in dlg.inst.buttons():
            if b.property("key") == "bass":
                b.click()
        dlg._refresh()
        s = dlg.spec()
        assert s.instrument == "bass" and s.voicing == "ss_bass" and s.di_out
        assert dlg.bom.rowCount() > 10
    finally:
        dlg.close()
