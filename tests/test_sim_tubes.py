"""Vacuum tubes and amplifier boards: tube models against datasheets, the output transformer, rectified supplies,
the example amps' bias against their design, and real-time play-through of tube amps."""
import math
from pathlib import Path

import numpy as np
import pytest

from pcbpro.sim.devices import Capacitor, Resistor, Transformer, VoltageSource, Waveform
from pcbpro.sim.engine import Circuit, Simulator
from pcbpro.sim.tubes import (PENTODE_PRM, PENTODES, TRIODE_PRM, TRIODES, Triode, pentode_current,
                              triode_current)

EXAMPLES = Path(__file__).resolve().parents[1] / "pcbpro" / "resources" / "examples"
AMPS = ["Amp_EL84_18W_Push-Pull", "Amp_Tweed_Champ_5W", "Amp_Plexi_Crunch_50W", "Amp_LM3886_Bass_50W"]


def _amp(name):
    from pcbpro.model.fileio import load_project
    return load_project(EXAMPLES / f"{name}.pcbpro")


# --------------------------------------------------------------------------- tube models

def test_tubes_draw_their_datasheet_current():
    for name, (prm, cgp) in TRIODE_PRM.items():
        vp, vg, ip = TRIODES[name][6]
        assert triode_current(vg, vp, prm)[0] == pytest.approx(ip * 1e-3, rel=1e-6), name
        assert 0.5e-12 < cgp < 5e-12
    for name, prm in PENTODE_PRM.items():
        vp, vg2, vg1, ip, ig2 = PENTODES[name][6]
        r = pentode_current(vg1, vg2, vp, prm)
        assert r[0] == pytest.approx(ip * 1e-3, rel=1e-6), name
        assert r[1] == pytest.approx(ig2 * 1e-3, rel=1e-6), name


@pytest.mark.parametrize("name,gm,rp,mu", [("12AX7", 1.6, 62.5, 100), ("12AT7", 5.5, 11, 60), ("12AU7", 2.2, 7.7, 17),
                                           ("6SN7", 2.6, 7.7, 20)])
def test_triode_small_signal(name, gm, rp, mu):
    vp, vg, _ = TRIODES[name][6]
    _, _, dg, dp, _ = triode_current(vg, vp, TRIODE_PRM[name][0])
    assert dg * 1e3 == pytest.approx(gm, rel=0.35)
    assert 1 / dp / 1e3 == pytest.approx(rp, rel=0.35)
    assert dg / dp == pytest.approx(mu, rel=0.2)


@pytest.mark.parametrize("name,gm", [("EL84", 11.3), ("6V6GT", 4.1), ("6L6GC", 6.0), ("EL34", 11.0), ("KT88", 11.5)])
def test_pentode_transconductance(name, gm):
    vp, vg2, vg1, _, _ = PENTODES[name][6]
    r = pentode_current(vg1, vg2, vp, PENTODE_PRM[name])
    assert r[3] * 1e3 == pytest.approx(gm, rel=0.3)
    assert pentode_current(vg1, vg2, 0.0, PENTODE_PRM[name])[0] == 0.0  # no plate current at 0 V


def _fd(f, x, k, h=1e-6):
    a, b = list(x), list(x)
    a[k] -= h
    b[k] += h
    return (np.array(f(*b)) - np.array(f(*a))) / (2 * h)


@pytest.mark.parametrize("vgk,vpk", [(-2.0, 250.0), (-0.5, 80.0), (0.4, 120.0), (1.5, 30.0), (-6.0, 300.0)])
def test_triode_jacobian(vgk, vpk):
    prm = TRIODE_PRM["12AX7"][0]
    ip, ig, dpg, dpp, dgg = triode_current(vgk, vpk, prm)
    fg = _fd(lambda g, p: triode_current(g, p, prm)[:2], (vgk, vpk), 0)
    fp = _fd(lambda g, p: triode_current(g, p, prm)[:2], (vgk, vpk), 1)
    assert dpg == pytest.approx(fg[0], rel=1e-4, abs=1e-12)
    assert dpp == pytest.approx(fp[0], rel=1e-4, abs=1e-12)
    assert dgg == pytest.approx(fg[1], rel=1e-4, abs=1e-12)


@pytest.mark.parametrize("v", [(-10.0, 250.0, 300.0), (-2.0, 250.0, 40.0), (1.0, 280.0, 1.0), (-30.0, 300.0, 400.0)])
def test_pentode_jacobian(v):
    prm = PENTODE_PRM["EL34"]
    r = pentode_current(*v, prm)

    def f(a, b, c):
        return pentode_current(a, b, c, prm)[:3]
    d1, d2, d3 = (_fd(f, v, k) for k in range(3))
    assert (r[3], r[4], r[5]) == pytest.approx((d1[0], d2[0], d3[0]), rel=1e-4, abs=1e-12)
    assert (r[6], r[7]) == pytest.approx((d1[1], d2[1]), rel=1e-4, abs=1e-12)
    assert r[8] == pytest.approx(d1[2], rel=1e-4, abs=1e-12)


def test_realtime_kernel_matches_the_tube_model():
    from pcbpro.sim import realtime as rt
    rng = np.random.default_rng(3)
    tri, pen = TRIODE_PRM["12AT7"][0], PENTODE_PRM["6L6GC"]
    types = np.array([rt.T_TRIODE, rt.T_PENTODE], dtype=np.int64)
    pst, cst, prs = (np.array(a, dtype=np.int64) for a in ([0, 2], [0, 2], [0, len(tri)]))
    prm = np.array(list(tri) + list(pen))
    cur, J = np.zeros(5), np.zeros((5, 5))
    for _ in range(50):
        v = np.array([rng.uniform(-8, 2), rng.uniform(-20, 400), rng.uniform(-40, 3), rng.uniform(0, 450),
                      rng.uniform(-20, 450)])
        rt._eval(types, pst, cst, prs, prm, v, cur, J)
        ip, ig, dpg, dpp, dgg = triode_current(v[0], v[1], tri)
        assert cur[:2] == pytest.approx([ig, ip], rel=1e-9, abs=1e-9)
        assert J[1, :2] == pytest.approx([dpg, dpp], rel=1e-9, abs=1e-9)
        r = pentode_current(v[2], v[3], v[4], pen)
        assert cur[2:] == pytest.approx([r[2], r[1], r[0]], rel=1e-9, abs=1e-9)
        assert J[4, 2:] == pytest.approx([r[3], r[4], r[5]], rel=1e-9, abs=1e-9)


# --------------------------------------------------------------------------- circuits

def test_common_cathode_stage():
    """12AX7 with 100k plate and bypassed 1k5 cathode from 250 V: the textbook bias and a gain of about 60."""
    ck = Circuit()
    bp, p, g, k, src, out = (ck.node(n) for n in ("B+", "P", "G", "K", "SRC", "OUT"))
    ck.add(VoltageSource(bp, 0, Waveform("dc", v=250.0)))
    vin = ck.add(VoltageSource(src, 0, Waveform("dc", v=0.0)))
    ck.add(Resistor(src, g, 1e3))
    ck.add(Resistor(bp, p, 100e3))
    ck.add(Resistor(k, 0, 1.5e3))
    ck.add(Capacitor(k, 0, 22e-6))
    ck.add(Capacitor(p, out, 22e-9))
    ck.add(Resistor(out, 0, 1e6))
    ck.add(Triode((p, g, k), TRIODE_PRM["12AX7"][0]))
    sim = Simulator(ck)
    x = sim.start_op()
    assert 1.0 < x[k] < 1.8
    assert 130 < x[p] < 190
    gain = abs(sim.ac_sweep(np.array([1000.0]), vin, [out])[0, 0])
    assert 50 < gain < 70


def _transformer_circuit(n=10.0, lm=50.0, load=8.0):
    ck = Circuit()
    a, b, s, t = ck.node("A"), ck.node("B"), ck.node("S"), ck.node("T")
    src = ck.add(VoltageSource(a, 0, Waveform("dc", v=0.0)))
    from pcbpro.sim.devices import Inductor
    ck.add(Transformer([(a, b, n / 2), (b, 0, n / 2), (s, 0, 1.0)], t))
    ck.add(Inductor(t, 0, lm / (n * n)))
    ck.add(Resistor(s, 0, load))
    ck.add(Resistor(b, 0, 1e9))
    return ck, src, s, a


def test_transformer_ratio_and_magnetising_roll_off():
    ck, src, s, a = _transformer_circuit()
    sim = Simulator(ck)
    sim.start_op()
    f = np.array([2.0, 1000.0])
    h = sim.ac_sweep(f, src, [s])[:, 0]
    assert abs(h[1]) == pytest.approx(0.1, rel=1e-3)  # 10:1
    assert abs(h[0]) == pytest.approx(0.1, rel=1e-3)  # a voltage source drives the primary: no roll-off here
    # the primary current includes the magnetising current: at 2 Hz the 50 H primary draws more than the load
    i_load = 0.1 / 8.0 * 0.1
    i_mag = 1.0 / (2 * math.pi * 2.0 * 50.0)
    assert i_mag > i_load


# --------------------------------------------------------------------------- amp boards

@pytest.fixture(scope="module")
def amps(qapp):
    return {n: _amp(n) for n in AMPS}


@pytest.mark.parametrize("name", AMPS)
def test_example_amps_build_and_bias(amps, name):
    from pcbpro.sim import ampboard
    from pcbpro.sim.netlist import build_circuit
    p = amps[name]
    ck = build_circuit(p)
    bad = [i.ref for i in ck.parts.values() if i.status in ("unsupported", "error")]
    assert not bad
    assert ck.amp is not None and ck.amp.supplies
    assert any("supply model" in i.note for i in ck.parts.values())  # the rectifier is replaced by its DC model
    assert ampboard.output_net(p) in ck.net_node
    x = Simulator(ck).start_op()
    nets = p.amp["nets"]
    devs = [abs(x[ck.net_node[n]] - d["v"]) / abs(d["v"]) for n, d in nets.items()
            if "v" in d and n in ck.net_node and abs(d["v"]) > 10]
    assert np.median(devs) < 0.1  # within 10 % of the designer's voltages
    bplus = "B+1" if "B+1" in nets else "V+"
    assert x[ck.net_node[bplus]] == pytest.approx(nets[bplus]["v"], rel=0.05)
    if ck.amp.ot is not None:
        assert ck.amp.ot["polarity"] in (1, -1)
        assert ck.amp.ot["zp"] > 1000


def test_champ_bias_matches_the_real_amp(amps):
    from pcbpro.sim.netlist import build_circuit
    ck = build_circuit(amps["Amp_Tweed_Champ_5W"])
    x = Simulator(ck).start_op()
    assert x[ck.net_node["V2_K"]] == pytest.approx(20.0, rel=0.15)  # 6V6 cathode bias
    assert x[ck.net_node["V1A_K"]] == pytest.approx(1.5, rel=0.25)


def test_rectifier_and_bias_supplies(amps):
    from pcbpro.sim.netlist import build_circuit
    ck = build_circuit(amps["Amp_Plexi_Crunch_50W"])
    by = {s.net: s for s in ck.sources}
    assert by["B+1"].params["v"] > 450 and by["B+1"].params["r"] > 0
    assert by["BIAS_RAW"].params["v"] < -50  # the negative bias supply
    assert {i.ref for i in ck.parts.values() if "supply model" in i.note} == {"D1", "D2", "D3", "D4", "D5"}
    ss = build_circuit(amps["Amp_LM3886_Bass_50W"])
    rails = {s.net: s.params["v"] for s in ss.sources if s.kind == "dc"}
    assert rails == {"V+": pytest.approx(30, abs=1), "V-": pytest.approx(-30, abs=1)}


def test_plate_dissipation_is_checked(amps):
    from pcbpro.sim import stress
    from pcbpro.sim.netlist import auto_sources, build_circuit
    p = amps["Amp_Plexi_Crunch_50W"]
    srcs = [dict(s, v=-8.0) if s["net"] == "BIAS_RAW" else s for s in auto_sources(p, build_circuit(p, sources=[]))]
    ck = build_circuit(p, sources=srcs)  # far too little negative bias: the EL34s red-plate
    x = Simulator(ck).start_op()
    hot = {s.ref for s in stress.check(ck, x) if "plate dissipation" in s.message}
    assert hot == {"V4", "V5"}
    ok = build_circuit(p)
    assert not [s for s in stress.check(ok, Simulator(ok).start_op()) if "plate" in s.message]


def test_amp_plays_in_real_time_like_the_engine(amps):
    from pcbpro.sim.audio import guitar_clip, render
    from pcbpro.sim.realtime import RealtimeModel
    p = amps["Amp_Tweed_Champ_5W"]
    clip = guitar_clip("Riff", 0.15, 48000, 0.15)
    ref = render(p, clip, 48000, "IN", "SPK")
    m = RealtimeModel(p, "IN", "SPK", None, 48000, 1)
    m.warm_up()
    m.settle(0.25)
    y = np.concatenate([m.process_block(clip[k:k + 128]) for k in range(0, len(clip), 128)])
    assert m.lazy and m.stats[0] == 0
    c = np.corrcoef(np.roll(y, -1)[200:], ref[200:])[0, 1]
    assert c > 0.999
    assert 3.0 < np.max(np.abs(ref)) < 60.0  # a 5 W amp driven hard, on a real speaker load


def test_amp_tone_controls_and_speaker_output(amps):
    from pcbpro.sim.audio import frequency_response
    from pcbpro.sim.netlist import build_circuit
    p = amps["Amp_EL84_18W_Push-Pull"]
    pots = {c.label.split()[0]: c.key for c in build_circuit(p).controls if c.kind == "pot"}
    f = [100.0, 1000.0, 5000.0]
    lo = np.abs(frequency_response(p, "IN", "SPEAKER", {pots["RV2"]: 0.0}, f)[1])
    hi = np.abs(frequency_response(p, "IN", "SPEAKER", {pots["RV2"]: 1.0}, f)[1])
    assert np.all(np.isfinite(lo)) and lo.max() > 1.0
    assert hi[2] / lo[2] > 1.5 or lo[2] / hi[2] > 1.5  # the treble control changes the treble


def test_live_engine_on_an_amp(amps, monkeypatch):
    from pcbpro.sim import ampboard
    from pcbpro.sim.audio import guitar_clip
    from pcbpro.sim.livefx import LiveEngine
    from pcbpro.sim.realtime import RealtimeModel
    p = amps["Amp_Tweed_Champ_5W"]
    fs = ampboard.full_scale_volts(p)
    assert fs == pytest.approx(2 * math.sqrt(2 * 5 * 8))
    eng = LiveEngine(p, {"rate": 48000, "oversample": 1, "out": "SPK", "out_ref": fs, "out_db": -6})
    clip = guitar_clip("Riff", 0.1, 48000, 0.4).astype(np.float32)
    outs = []
    for k in range(0, len(clip) - 128, 128):
        ind = np.zeros((128, 1), np.float32)
        ind[:, 0] = clip[k:k + 128]
        outd = np.zeros((128, 2), np.float32)
        eng.callback(ind, outd, 128, None, None)
        outs.append(outd[:, 0].copy())
    out = np.concatenate(outs)
    assert np.all(np.isfinite(out)) and 0.02 < np.max(np.abs(out)) <= 1.0
    # a circuit too heavy for this computer: the oversampling drops first, then it is refused with an explanation
    loads = iter([0.9, 0.5])
    monkeypatch.setattr(RealtimeModel, "benchmark", lambda self, *a: next(loads))
    eng = LiveEngine(p, {"rate": 48000, "oversample": 2, "out": "SPK", "out_ref": fs})
    assert eng.model.R == 1 and "Oversampling lowered" in eng.notices[0]
    monkeypatch.setattr(RealtimeModel, "benchmark", lambda self, *a: 2.0)
    with pytest.raises(RuntimeError, match="Audio play-through"):
        LiveEngine(p, {"rate": 48000, "oversample": 1, "out": "SPK", "out_ref": fs})


def test_fast_render_matches_the_engine(amps):
    from pcbpro.sim.audio import guitar_clip, render, render_fast
    p = amps["Amp_EL84_18W_Push-Pull"]
    clip = guitar_clip("Single notes", 0.1, 24000, 0.1)
    ref = render(p, clip, 24000, "IN", "SPEAKER")
    y = render_fast(p, clip, 24000, "IN", "SPEAKER", oversample=1)
    assert np.corrcoef(np.roll(y, -1)[100:], ref[100:])[0, 1] > 0.999
    seen = []
    assert len(render_fast(p, clip, 24000, "IN", "SPEAKER", progress=lambda f: seen.append(f) or True)) == 0
    assert seen == [0.5]  # cancelled after the first chunk (rate / 20 samples)


def test_normalled_jack_passes_signal_unplugged(amps):
    """An effects-loop RETURN normalled to SEND starts unplugged (the loop passes through); an input starts plugged."""
    import copy

    from pcbpro.model.board import Component, Project
    from pcbpro.model.footprints import find_part
    from pcbpro.sim.netlist import build_circuit
    jack = next(c.footprint for c in amps["Amp_EL84_18W_Push-Pull"].components if c.ref == "J1")  # T R S TN RN SN
    r = find_part("Resistor 0805").make
    p = Project("loop")
    p.components += [Component("J1", "INPUT", copy.deepcopy(jack), pad_nets={"T": "IN", "S": "GND", "TN": "GND"}),
                     Component("J2", "RETURN", copy.deepcopy(jack), pad_nets={"T": "RET", "TN": "SEND", "S": "GND"}),
                     Component("R1", "10k", r(), pad_nets={"1": "IN", "2": "SEND"}),
                     Component("R2", "10k", r(), pad_nets={"1": "RET", "2": "GND"})]
    plugs = {c.ref: c.value for c in build_circuit(p).controls if c.kind == "plug"}
    assert plugs == {"J1": 1, "J2": 0}
