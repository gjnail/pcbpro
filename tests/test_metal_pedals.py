"""Metal pedals: every board is complete and enclosure-clean, and the circuits do what they claim when the simulator
plays through them (tight low cut, clipping, a gate that closes on quiet signals, a working tone stack)."""
import numpy as np
import pytest

from pcbpro.amp.metal_pedals import METAL_EXAMPLES, PEDALS, build_pedal


@pytest.fixture(scope="module")
def pedals(qapp):
    return {k: build_pedal(k, route=False) for k in PEDALS}


def _pots(p):
    from pcbpro.sim.netlist import build_circuit
    ck = build_circuit(p)
    assert not [i.ref for i in ck.parts.values() if i.status in ("unsupported", "error")]
    return {c.label.split()[-1]: c.key for c in ck.controls if c.kind == "pot"}


def _db(h):
    return 20 * np.log10(np.maximum(np.abs(h), 1e-12))


def _at(f, h, hz):
    return float(np.interp(np.log10(hz), np.log10(f), _db(h)))


@pytest.mark.parametrize("key", list(PEDALS))
def test_pedal_boards_are_complete_and_fit_the_box(pedals, key):
    from pcbpro.model.drc import run_drc
    from pcbpro.pedal.enclosure import get_enclosure
    p = pedals[key]
    kind = PEDALS[key]
    assert get_enclosure(p).model == kind.enclosure
    assert not [c.ref for c in p.components if abs(c.x) < 0.01 and abs(c.y) < 0.01]  # nothing left at the origin
    pots = [c for c in p.components if c.ref.startswith("RV")]
    assert len(pots) == len(kind.knobs) and all(c.pad_nets.get("2") for c in pots)  # every knob is wired
    errors = [v.message for v in run_drc(p) if v.severity == "error" and v.kind != "unrouted"]
    assert not errors, errors
    assert not [v.message for v in run_drc(p) if v.kind == "courtyard"]  # the knob rows do not overlap
    assert kind.title in p.notes and "3PDT" in p.notes


@pytest.mark.parametrize("key", list(PEDALS))
def test_bundled_metal_pedal_is_routed_and_clean(qapp, key):
    from pcbpro.examples import EXAMPLE_DIR, load_example
    from pcbpro.model.connectivity import get_connectivity
    from pcbpro.model.copper import fill_all_zones
    from pcbpro.model.drc import run_drc
    p = load_example(EXAMPLE_DIR / METAL_EXAMPLES[key])
    fill_all_zones(p)
    assert get_connectivity(p).unrouted_count() == 0
    assert [v.message for v in run_drc(p) if v.severity == "error"] == []


def test_tight_boost_cuts_the_lows_and_pushes_the_mids(pedals):
    from pcbpro.sim.audio import frequency_response
    p = pedals["tight_boost"]
    pot = _pots(p)
    base = {pot["B500K"]: 0.0, pot["A100K"]: 1.0, pot["B25K"]: 0.7}
    f, loose = frequency_response(p, controls={**base, pot["C100K"]: 0.0})
    _, mid = frequency_response(p, controls={**base, pot["C100K"]: 0.5})
    _, tight = frequency_response(p, controls={**base, pot["C100K"]: 1.0})
    # the Tube Screamer mid hump: the mids get the gain, the lows stay near unity
    assert _at(f, loose, 1000) - _at(f, loose, 82) > 12
    # TIGHT moves the low cut up: 82 Hz drops a lot, 1 kHz hardly moves, and noon is in between
    assert _at(f, loose, 82) - _at(f, tight, 82) > 9
    assert _at(f, loose, 82) > _at(f, mid, 82) > _at(f, tight, 82)
    assert abs(_at(f, loose, 1000) - _at(f, tight, 1000)) < 1.5


def test_tight_boost_model_matches_the_simulated_board(pedals):
    """The Amp Designer draws the boost from a formula; it must agree with the simulated board."""
    from pcbpro.amp.metal_pedals import tight_boost_response
    from pcbpro.sim.audio import frequency_response
    p = pedals["tight_boost"]
    pot = _pots(p)
    for tight in (0.0, 0.5, 1.0):
        f, h = frequency_response(p, controls={pot["B500K"]: 0.0, pot["A100K"]: 1.0, pot["B25K"]: 0.7,
                                               pot["C100K"]: tight})
        model = tight_boost_response(f, tight=tight)
        for hz in (82.0, 200.0, 3000.0):
            sim_rel = _at(f, h, hz) - _at(f, h, 1000)
            mod_rel = _at(f, model, hz) - _at(f, model, 1000)
            assert abs(sim_rel - mod_rel) < 2.0, (tight, hz, sim_rel, mod_rel)


def test_tight_boost_clips_when_driven(pedals):
    from pcbpro.sim.audio import render
    p = pedals["tight_boost"]
    pot = _pots(p)
    rate = 24000
    t = np.arange(int(0.05 * rate)) / rate
    out = render(p, 0.3 * np.sin(2 * np.pi * 440 * t), rate,
                 controls={pot["B500K"]: 1.0, pot["A100K"]: 1.0, pot["C100K"]: 0.3, pot["B25K"]: 0.7})
    ac = out[len(out) // 2:] - np.mean(out[len(out) // 2:])
    assert np.all(np.isfinite(out)) and np.max(np.abs(ac)) > 0.1
    assert np.max(np.abs(ac)) / np.sqrt(np.mean(ac ** 2)) < 1.38  # squashed peaks (a sine is 1.414)


def test_distortion_clips_hard_and_the_tone_stack_works(pedals):
    from pcbpro.sim.audio import frequency_response, render
    p = pedals["distortion"]
    pot = _pots(p)
    knobs = {pot["B500K"]: 0.0, pot["A100K"]: 1.0, pot["A250K"]: 0.5, pot["A1M"]: 0.5, pot["B25K"]: 0.5}
    f, flat = frequency_response(p, controls=knobs)
    _, bright = frequency_response(p, controls={**knobs, pot["A250K"]: 1.0})
    _, scoop = frequency_response(p, controls={**knobs, pot["B25K"]: 0.0})
    assert _at(f, bright, 3000) - _at(f, flat, 3000) > 3  # TREBLE
    assert _at(f, flat, 700) - _at(f, scoop, 700) > 2  # MID scoops the middle
    assert _at(f, flat, 1000) - _at(f, flat, 82) > 6  # the 720 Hz pre-emphasis keeps the lows tight
    rate = 24000
    t = np.arange(int(0.05 * rate)) / rate
    out = render(p, 0.1 * np.sin(2 * np.pi * 220 * t), rate, controls={**knobs, pot["B500K"]: 1.0,
                                                                         pot["A100K"]: 0.5})
    ac = out[len(out) // 2:] - np.mean(out[len(out) // 2:])
    assert np.max(np.abs(ac)) > 0.05
    assert np.max(np.abs(ac)) / np.sqrt(np.mean(ac ** 2)) < 1.3  # two hard clippers: close to a square wave


def test_noise_gate_passes_playing_and_mutes_the_hiss(pedals):
    """Played through with RETURN unplugged (its switch normals the buffered guitar back in): a loud note passes
    at about unity, the quiet tail after it is cut once the release has run out."""
    from pcbpro.model.board import Component
    from pcbpro.pedal.templates import part
    from pcbpro.sim.audio import render
    p = pedals["noise_gate"]
    link = Component(p.next_ref("R"), "1R", part("res"), 300.0, 300.0, 0, "top", {"1": "SEND", "2": "RET"})
    p.components.append(link)
    try:
        pot = _pots(p)
        rate = 24000
        t1, t2 = 0.06, 0.12
        t = np.arange(int((t1 + t2) * rate)) / rate
        clip = np.sin(2 * np.pi * 220 * t) * np.where(t < t1, 0.2, 0.003)
        out = render(p, clip, rate, controls={pot["B10K"]: 0.5, pot["B1M"]: 0.0})

        def tone(a, b):  # the 220 Hz amplitude over 6 whole cycles from time a (the output also drifts slowly)
            n0, n = int(a * rate), int(6 / 220 * rate)
            seg, tt = out[n0:n0 + n], t[n0:n0 + n]
            return 2 * abs(np.mean(seg * np.exp(-2j * np.pi * 220 * tt)))
        assert 0.15 < tone(0.025, None) < 0.25  # open: about unity gain for a 0.2 V note
        assert 20 * np.log10(tone(t1 + 0.09, None) / 0.003) < -20  # closed: the 3 mV hiss after it is cut
    finally:
        p.components.remove(link)


def test_metal_pedal_menu_opens_a_board(qapp, monkeypatch):
    from pcbpro.ui import amp_ui
    from pcbpro.ui.main_window import MainWindow
    win = MainWindow()
    try:
        monkeypatch.setattr(win, "_confirm_discard", lambda: True)
        assert any("Metal pedals" in a.text().replace("&", "") for a in win.amp_menu.actions())
        amp_ui.open_metal_pedal(win, "tight_boost")
        p = win.doc.project
        assert any(c.value == "TL072" for c in p.components) and p.tracks
    finally:
        win.close()
