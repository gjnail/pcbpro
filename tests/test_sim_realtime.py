"""Real-time (nodal DK) circuit model: matches the offline engine, runs faster than real time, live engine path."""
import time

import numpy as np
import pytest

from pcbpro.model.board import Component, Project
from pcbpro.model.footprints import find_part
from pcbpro.sim.audio import guitar_clip, render
from pcbpro.sim.realtime import RealtimeModel

RATE = 48000


@pytest.fixture(scope="module")
def pedal(qapp):
    from pcbpro.pedal.examples import overdrive_example
    return overdrive_example(route=False)


def _pots(project):
    from pcbpro.sim.netlist import build_circuit
    return {c.label.split()[-1]: c.key for c in build_circuit(project).controls if c.kind == "pot"}


def _match(y, ref, lag=-1):
    """Correlation after the offline renderer's one-sample input offset."""
    a = np.roll(y - y.mean(), lag)[50:]
    b = (ref - ref.mean())[50:]
    return float(np.corrcoef(a, b)[0, 1])


def _rt(project, controls=None, R=1, seconds=0.25):
    m = RealtimeModel(project, controls=controls, rate=RATE, oversample=R)
    m.warm_up()
    m.settle(seconds)
    return m


def test_overdrive_matches_offline_engine(pedal):
    pots = _pots(pedal)
    ctl = {pots["B500K"]: 0.8, pots["A100K"]: 0.7}
    clip = guitar_clip("Riff", 0.25, RATE, 0.2)
    y = _rt(pedal, ctl).process_block(clip)
    ref = render(pedal, clip, RATE, controls=ctl)
    assert _match(y, ref) > 0.9999
    assert np.max(np.abs(y)) == pytest.approx(np.max(np.abs(ref)), rel=0.01)


def test_faster_than_real_time_and_oversampling(pedal):
    pots = _pots(pedal)
    clip = guitar_clip("Riff", 0.5, RATE, 0.3)
    m = _rt(pedal, {pots["B500K"]: 1.0}, R=2)
    t0 = time.perf_counter()
    y = np.concatenate([m.process_block(clip[k:k + 128]) for k in range(0, len(clip), 128)])
    assert time.perf_counter() - t0 < 0.5  # at most the clip's duration, with 2x oversampling
    assert m.stats[0] == 0  # every sample converged
    ref = render(pedal, clip, RATE, controls={pots["B500K"]: 1.0})
    best = max(_match(y, ref, lag) for lag in range(-24, 0))
    assert best > 0.95  # same sound, minus aliasing, after the anti-alias filters' delay


def test_knob_changes_recompile(pedal):
    pots = _pots(pedal)
    clip = guitar_clip("Sine 440 Hz", 0.1, RATE, 0.1)
    m = _rt(pedal, {pots["A100K"]: 0.2})
    quiet = np.std(m.process_block(clip)[2000:])
    m.set_control(pots["A100K"], 1.0)
    loud = np.std(m.process_block(clip)[2000:])
    assert loud > 3 * quiet


def _stage_board(pnp: bool) -> Project:
    """A one-transistor stage (NPN common emitter or PNP emitter follower) between IN and OUT, 9 V supply."""
    p = Project("stage")
    to92 = find_part("TO-92 inline").make
    r = find_part("Resistor 0805").make
    c = find_part("Capacitor 0805").make
    parts = [Component("J1", "9V", find_part("Pin header 1x2 P2.54").make(), pad_nets={"1": "9V", "2": "GND"}),
             Component("C1", "100n", c(), pad_nets={"1": "IN", "2": "B"}),
             Component("R1", "470k", r(), pad_nets={"1": "9V", "2": "B"}),
             Component("R2", "100k", r(), pad_nets={"1": "B", "2": "GND"}),
             Component("C2", "1u", c(), pad_nets={"1": "COL" if not pnp else "EM", "2": "OUT"})]
    if not pnp:  # 2N3904 E-B-C
        parts += [Component("Q1", "2N3904", to92(), pad_nets={"1": "EMR", "2": "B", "3": "COL"}),
                  Component("R3", "10k", r(), pad_nets={"1": "9V", "2": "COL"}),
                  Component("R4", "1k", r(), pad_nets={"1": "EMR", "2": "GND"})]
    else:  # 2N3906 emitter follower: emitter to 9V through 4k7, collector to ground
        parts += [Component("Q1", "2N3906", to92(), pad_nets={"1": "EM", "2": "B", "3": "GND"}),
                  Component("R3", "4k7", r(), pad_nets={"1": "9V", "2": "EM"})]
    p.components += parts
    return p


@pytest.mark.parametrize("pnp", [False, True])
def test_transistor_stages_match(pnp, qapp):
    p = _stage_board(pnp)
    clip = guitar_clip("Single notes", 0.15, RATE, 0.4)
    y = _rt(p).process_block(clip)
    ref = render(p, clip, RATE)
    assert np.std(ref) > 1e-3
    assert _match(y, ref) > 0.999


def test_live_engine_callback(pedal):
    from pcbpro.sim.livefx import LiveEngine
    eng = LiveEngine(pedal, {"rate": RATE, "oversample": 1, "out_db": -6})
    clip = guitar_clip("Riff", 0.2, RATE, 0.5).astype(np.float32)
    outs = []
    for k in range(0, len(clip) - 128, 128):
        ind = np.zeros((128, 2), np.float32)
        ind[:, 0] = clip[k:k + 128]
        outd = np.zeros((128, 2), np.float32)
        eng.callback(ind, outd, 128, None, None)
        outs.append(outd.copy())
    out = np.concatenate(outs)
    assert np.all(np.isfinite(out)) and np.max(np.abs(out)) <= 1.0
    assert np.allclose(out[:, 0], out[:, 1])  # every output channel gets the signal
    assert 0 < eng.load < 1.0
    eng.command(("bypass", True))
    ind = np.zeros((128, 2), np.float32)
    ind[:, 0] = 0.1
    outd = np.zeros((128, 2), np.float32)
    eng.callback(ind, outd, 128, None, None)
    assert np.all(np.isfinite(outd))


def _play(eng, clip, switch=None):
    outs = []
    for i, k in enumerate(range(0, len(clip) - 128, 128)):
        if switch and i in switch:
            eng.command(("cab", switch[i]))
        ind = np.zeros((128, 1), np.float32)
        ind[:, 0] = clip[k:k + 128]
        outd = np.zeros((128, 2), np.float32)
        eng.callback(ind, outd, 128, None, None)
        outs.append(outd[:, 0].copy())
    return np.concatenate(outs)


def test_live_engine_cabinet(pedal):
    from pcbpro.sim.cabinet import apply_ir, builtin_irs, load_ir
    from pcbpro.sim.livefx import LiveEngine
    clip = guitar_clip("Riff", 0.2, RATE, 0.3).astype(np.float32)
    opts = {"rate": RATE, "oversample": 1, "out_db": -30, "block": 128}
    dry = _play(LiveEngine(pedal, opts), clip)
    cab = builtin_irs()[3]
    eng = LiveEngine(pedal, dict(opts, cab=cab))
    wet = _play(eng, clip)
    assert eng.status(None)["cab"] == "Built-in · 4x12 straight"
    assert eng.clipped == 0
    ref = apply_ir(dry.astype(float), load_ir(cab, RATE))  # the same circuit output, through the cabinet
    assert np.max(np.abs(wet - ref)) < 1e-4 * np.max(np.abs(ref))
    assert np.std(wet - dry) > 0.1 * np.std(dry)
    # switching while playing crossfades over one block and never stops the audio
    eng2 = LiveEngine(pedal, opts)
    sw = _play(eng2, clip, {10: cab, 30: builtin_irs()[0], 50: None})
    assert np.all(np.isfinite(sw)) and eng2.cab is None and eng2.cab_name == ""
    assert np.allclose(sw[:1280], dry[:1280], atol=1e-6)
    assert np.allclose(sw[51 * 128:58 * 128], dry[51 * 128:58 * 128], atol=1e-6)
    assert np.max(np.abs(np.diff(sw))) < 2 * np.max(np.abs(np.diff(dry))) + 0.01
    with pytest.raises(Exception):
        eng2.command(("cab", "C:/no/such/cab.wav"))
    assert eng2.cab is None  # a bad file leaves the current cabinet alone
