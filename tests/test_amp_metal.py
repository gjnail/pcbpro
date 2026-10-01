"""High-gain / metal amps in the Amp Designer: cascades, tightness, depth, the tube effects loop, DC heaters, the
gain-staging analysis and the spec sheet, plus the boards they make."""
import numpy as np
import pytest

from pcbpro.amp import gainstage as gs
from pcbpro.amp.builder import build_amp
from pcbpro.amp.designer import POWER, AmpSpec, design_amp, report_html, report_text

HIGH_GAIN = ("highgain", "modern", "extreme")


def _design(**kw):
    return design_amp(AmpSpec(**kw))


def _all_nets(design):
    return {n for p in design.parts for n in p.nets.values()}


@pytest.mark.parametrize("voicing,n", [("highgain", 3), ("modern", 4), ("extreme", 5)])
def test_high_gain_cascades(voicing, n):
    design, rep = _design(voicing=voicing, fx_loop=False)
    gain = [d for d in rep.analysis.drive if d.note not in ("power amp", "loop recovery")]
    assert len(gain) == n
    assert sum(d.note == "cold clipper" for d in gain) == 1
    # the cold clipper really is cold: 10k unbypassed cathode
    assert any(p.value == "10k" and p.nets.get("1", "").endswith("_K") for p in design.parts if p.prefix == "R")
    # the input stage stays clean and the distortion is spread over the later stages with the gain on 10
    assert gain[0].db < 0 and sum(d.db > 0 for d in gain) >= n - 1
    assert "CF_K" in _all_nets(design) and rep.tone_name
    assert rep.analysis.hiss_margin > 8  # the hiss stays under the last stage's clipping point, even on 10
    assert rep.character.startswith(("High gain", "Crunch"))


def test_tightness_cuts_the_lows_into_the_distortion():
    for voicing in HIGH_GAIN:
        lows = [_design(voicing=voicing, tight=t)[1].analysis.lows[0][2] for t in gs.TIGHT_LEVELS]
        assert lows == sorted(lows, reverse=True), (voicing, lows)  # each step tighter at 82 Hz
        assert lows[0] - lows[3] > 6  # fat to djent is a real difference
    fat, _ = _design(voicing="modern", tight="fat")
    djent, _ = _design(voicing="modern", tight="djent")

    def caps(d):
        return sorted(p.value for p in d.parts if p.prefix == "C" and p.value.endswith(("400V", "63V", "25V")))
    assert caps(fat) != caps(djent)
    assert _design(voicing="blackface", tight="djent")[1].tight == ""  # no tightness choice on a clean voicing


def test_depth_and_presence_shape_the_power_amp():
    design, rep = _design(voicing="modern")
    fb = rep.feedback
    assert fb is not None and fb.depth_c and fb.pres_c
    flat = gs.power_response(fb, np.array([80.0, 4000.0]))
    assert gs.power_response(fb, np.array([80.0]), depth=10)[0] - flat[0] > 4
    assert gs.power_response(fb, np.array([4000.0]), presence=10)[0] - flat[1] > 4
    pots = {p.label: p for p in design.parts if p.prefix == "RV"}
    assert pots["DEPTH"].value == "B250K" and set(pots["DEPTH"].nets.values()) == {"PI_DEP", "PI_NFB"}
    assert any(p.prefix == "C" and set(p.nets.values()) == {"PI_DEP", "PI_NFB"} for p in design.parts)
    off, _ = _design(voicing="modern", depth=False)
    assert "PI_DEP" not in _all_nets(off)
    assert "Depth:" in report_text(rep) and "Presence:" in report_text(rep)


@pytest.mark.parametrize("nfb", ["normal", "off"])
def test_phase_inverter_feedback_goes_to_the_second_grid(nfb):
    """The LTP's second grid is its feedback input: its bypass cap goes to the feedback node (to ground without
    feedback). Taken to ground with feedback on, the feedback would only move both cathodes together."""
    design, _ = _design(voicing="plexi", nfb=nfb)
    cap = next(p for p in design.parts if p.prefix == "C" and "PI_GB" in p.nets.values())
    assert (set(cap.nets.values()) - {"PI_GB"}).pop() == ("PI_NFB" if nfb == "normal" else "GND")
    assert design.ot["nfb_polarity"] == 1 and design.ot["primary_ohms"] == POWER["pp_el34"].raa


def test_tube_effects_loop():
    design, rep = _design(voicing="modern", fx_loop=True)
    jacks = {p.label: p for p in design.parts if p.prefix == "J"}
    assert jacks["FX SEND"].role == jacks["FX RETURN"].role == "rear"
    assert jacks["FX RETURN"].nets["TN"] == "SEND"  # nothing plugged in: the send comes straight back
    rec = next(d for d in rep.analysis.drive if d.label == "FXR")
    assert rec.db < -3  # the recovery stage stays clean at full gain
    assert rep.tone.rl < 0.6e6  # the send divider loads the tone stack, and the tone plot knows it
    assert 1.0 < design.volts["FX_K"] < 4.0  # the send follower idles a couple of volts up
    no_loop, _ = _design(voicing="modern", fx_loop=False)
    assert "SEND" not in _all_nets(no_loop) and len(no_loop.parts) < len(design.parts)


def test_dc_heaters_for_the_preamp():
    design, rep = _design(voicing="extreme", dc_heaters=True)
    tubes = [p for p in design.parts if p.prefix == "V"]
    pre = [t for t in tubes if t.section != "PI" and t.value == "12AX7"]
    assert pre and all(t.nets["4"] == t.nets["5"] == "HDC" and t.nets["9"] == "HTR_EL" for t in pre)
    pi = next(t for t in tubes if t.section == "PI")
    assert pi.nets["4"] == "HTR1"
    assert sum(1 for p in design.parts if p.value == "1N5822") == 4
    assert not any(p.value == "100R" and "HTR1" in p.nets.values() for p in design.parts)  # the bridge references it
    assert 6.0 <= design.volts["HDC"] - design.volts["HTR_EL"] <= 6.7
    assert any("filtered DC" in t for t in rep.tips)


def test_clean_voicings_keep_a_clean_preamp():
    _, rep = _design(voicing="blackface")
    pre = [d for d in rep.analysis.drive if d.note != "power amp"]
    assert all(d.db < 0 for d in pre)
    assert rep.analysis.drive[-1].label == "Power tubes" and "power tubes" in rep.analysis.summary
    _, hg = _design(voicing="highgain")
    assert hg.breakup_knob == "GAIN" and 0.3 < hg.breakup[1] < 4  # a JCM800 crunches low on the gain (humbuckers)


def test_metal_report_sections():
    _, rep = _design(voicing="extreme")
    html = report_html(rep)
    for text in ("Where it distorts", "Low end into the distortion", "Pedals for this amp", "pedal:noise_gate",
                 "Hiss with the gain on 10"):
        assert text in html
    assert any(t.startswith("Tightness") for t in rep.tips) and any("noise gate" in t for t in rep.tips)
    assert {k for k, _ in rep.pedals} == {"noise_gate", "tight_boost", "distortion"}
    assert "Where it distorts" in report_text(rep)


def test_modern_amp_routes_drc_clean_with_loop_and_rear_jacks(qapp):
    from pcbpro.model.drc import run_drc
    design, _ = _design(voicing="modern", power="pp_el34", dc_heaters=True)
    p, notes = build_amp(design, route=True)
    errors = [v for v in run_drc(p) if v.severity == "error"]
    assert not errors, [v.message for v in errors[:10]]
    x0, y0, x1, y1 = p.board.bounds()
    loop = [c for c in p.components if c.ref.startswith("J") and c.value in ("SEND", "RETURN")]
    assert len(loop) == 2 and all(c.courtyard_polygon().bounds[1] < y0 + 2.0 for c in loop)  # at the rear edge
    assert p.amp["ot"]["secondary_ohms"] == 8


def _knob(p, ck, net):
    """The simulator control key of the pot whose wiper is on ``net``."""
    for c in ck.controls:
        if c.kind == "pot":
            comp = next(q for q in p.components if q.ref == c.label.split()[0])
            if comp.pad_nets.get("2") == net:
                return c.key
    raise KeyError(net)


def test_simulated_amp_confirms_the_tightness_analysis(qapp):
    """Play two quiet tones (82 Hz and 1 kHz) through the designed board in the tube simulator: going from fat to
    djent must cut the low E relative to the mids by what the gain-staging analysis predicts."""
    from pcbpro.sim.audio import render_fast
    from pcbpro.sim.netlist import build_circuit
    rate = 24000
    t = np.arange(int(0.25 * rate)) / rate
    clip = 0.003 * (np.sin(2 * np.pi * 82.0 * t) + np.sin(2 * np.pi * 1000.0 * t))
    sim, predicted = [], []
    for tight in ("fat", "djent"):
        design, rep = _design(voicing="highgain", power="pp_el34", fx_loop=False, tight=tight)
        p, _ = build_amp(design)
        ck = build_circuit(p)
        assert not [i.ref for i in ck.parts.values() if i.status in ("unsupported", "error")]
        ctl = {c.key: 0.5 for c in ck.controls if c.kind == "pot"}
        ctl.update({_knob(p, ck, "V1B_G"): 0.15, _knob(p, ck, "MV_OUT"): 0.3})  # low gain: the preamp stays linear
        out = render_fast(p, clip, rate, "IN", "SPK", controls=ctl)
        seg, tt = out[int(0.1 * rate):], t[int(0.1 * rate):]
        lo, hi = (2 * abs(np.mean(seg * np.exp(-2j * np.pi * hz * tt))) for hz in (82.0, 1000.0))
        sim.append(20 * np.log10(lo / hi))
        predicted.append(rep.analysis.lows[0][2])
    assert sim[0] - sim[1] > 5  # djent really is tighter at the speaker
    assert abs((sim[0] - sim[1]) - (predicted[0] - predicted[1])) < 3  # and by about what the analysis says


def test_simulated_high_gain_amp_distorts(qapp):
    from pcbpro.sim.audio import render_fast
    from pcbpro.sim.netlist import build_circuit
    design, rep = _design(voicing="highgain", power="pp_el34", fx_loop=False)
    p, _ = build_amp(design)
    ck = build_circuit(p)
    rate = 24000
    t = np.arange(int(0.15 * rate)) / rate
    clip = 0.3 * np.sin(2 * np.pi * 110.0 * t)
    thd = {}
    for gain in (0.05, 1.0):
        ctl = {c.key: 0.5 for c in ck.controls if c.kind == "pot"}
        ctl.update({_knob(p, ck, "V1B_G"): gain, _knob(p, ck, "MV_OUT"): 0.2})
        n0 = int(0.05 * rate)
        seg, tt = render_fast(p, clip, rate, "IN", "SPK", controls=ctl)[n0:], t[n0:]
        h = [2 * abs(np.mean(seg * np.exp(-2j * np.pi * k * 110.0 * tt))) for k in range(1, 8)]
        thd[gain] = np.sqrt(sum(x * x for x in h[1:])) / h[0]
    # near zero on the GAIN the amp is clean (the analysis puts the breakup at 1-2 with this level); on 10 it is
    # thick with harmonics even after the tone stack, output transformer and speaker
    assert thd[0.05] < 0.03 and thd[1.0] > 0.1, thd
    assert rep.breakup_knob == "GAIN" and rep.breakup[1] > 0.5


def test_designer_dialog_metal_controls(qapp):
    from PySide6.QtCore import QUrl

    from pcbpro.ui.amp_designer import AmpDesignerDialog
    dlg = AmpDesignerDialog(AmpSpec(voicing="modern"))
    try:
        assert dlg.tight.isEnabled() and dlg.tight.currentData() == "normal"
        assert dlg.depth.isChecked() and dlg.fx.isChecked()
        dlg.tight.setCurrentIndex(dlg.tight.findData("djent"))
        dlg.dch.setChecked(True)
        dlg._refresh()
        s = dlg.spec()
        assert s.tight == "djent" and s.dc_heaters and dlg.report.tight == "djent"
        assert len(dlg.tplot.curves) == 5 and len(dlg.pplot.curves) == 3  # 4 tightness levels + the boost; power amp
        for i in range(dlg.voicings.count()):
            if dlg.voicings.item(i).data(0x0100) == "blackface":
                dlg.voicings.setCurrentRow(i)
        dlg._refresh()
        assert not dlg.tight.isEnabled() and not dlg.depth.isChecked()
        dlg._link(QUrl("pedal:noise_gate"))
        assert dlg.pedal == "noise_gate" and dlg.result() == 2
    finally:
        dlg.close()
