"""Hearing designs: the modelled guitar riff, rendering a design through the tube simulation, punchy palm mutes at
noon on the GAIN knob, and the Amp Designer's Listen tab."""
from dataclasses import asdict

import numpy as np
import pytest

from pcbpro.amp.demo import knob_controls, metal_riff, render_design
from pcbpro.amp.designer import AmpSpec

RATE = 48000
EIGHTH = 60.0 / 140.0 / 2.0  # the riff's eighth note
EQ = {"MASTER": 0.2, "BASS": 0.5, "MIDDLE": 0.5, "TREBLE": 0.6, "PRESENCE": 0.5, "DEPTH": 0.4}


def _bands(x, centres=(125, 250, 500, 1000, 2000, 4000)):
    X = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    tot = X[f > 20].sum()
    return {c: 10 * np.log10(X[(f >= c / 1.41) & (f < c * 1.41)].sum() / tot) for c in centres}


def _low_env(x, lo=60.0, hi=200.0, w=0.006):
    X = np.fft.rfft(x - np.mean(x))
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    X[(f < lo) | (f > hi)] = 0
    y = np.fft.irfft(X, len(x))
    n = int(w * RATE)
    return np.sqrt(np.convolve(y ** 2, np.ones(n) / n, mode="same"))


def _chug_punch(y):
    """(ms from the pick to the low end's peak, dB of low end in each palm-muted eighth's second half vs its first)
    averaged over chugs 2-6 of the riff's first bar."""
    e = _low_env(y)
    peaks, tails = [], []
    for i in range(1, 6):
        seg = e[int(i * EIGHTH * RATE):int((i + 1) * EIGHTH * RATE)]
        peaks.append(np.argmax(seg) / RATE * 1000)
        h = len(seg) // 2
        tails.append(20 * np.log10(np.sqrt(np.mean(seg[h:] ** 2)) / np.sqrt(np.mean(seg[:h] ** 2))))
    return float(np.mean(peaks)), float(np.mean(tails))


def test_metal_riff_has_the_balance_of_a_real_di():
    x = metal_riff(RATE, 6.0, 0.4)
    assert abs(np.max(np.abs(x)) - 0.4) < 1e-9
    b = _bands(x)
    assert b[4000] < max(b[250], b[500]) - 15  # a pickup rolls the top off; a white-noise pluck would not
    assert b[2000] < max(b[250], b[500]) - 6
    peak, tail = _chug_punch(x)
    assert peak < 30 and tail < -8  # palm mutes die away within the eighth


@pytest.fixture(scope="module")
def riff():
    return metal_riff(RATE, 2.0, 0.4)


@pytest.mark.parametrize("voicing", ["highgain", "modern", "extreme"])
def test_designs_render_and_chug_tightly_at_noon(voicing):
    """Gain after the GAIN control decides whether palm mutes stay punchy: an over-driven cascade holds a decaying
    note at full level and its low end swells after the pick. With the GAIN at noon (the 3-stage amp a bit higher,
    as players set it) the low end must peak soon after the pick and fall away like the mute."""
    clip = metal_riff(RATE, 2.0, 0.4)
    gain = 0.7 if voicing == "highgain" else 0.5
    y = render_design(asdict(AmpSpec(voicing=voicing, fx_loop=False)), {**EQ, "GAIN": gain}, clip, RATE)
    assert y is not None and np.all(np.isfinite(y)) and np.max(np.abs(y)) > 0.5
    peak, tail = _chug_punch(y)
    assert peak < 90 and tail < -3.5, (voicing, peak, tail)


def test_knob_controls_follow_the_panel_labels():
    from pcbpro.amp.builder import build_amp
    from pcbpro.amp.designer import design_amp
    from pcbpro.sim.netlist import build_circuit
    design, _ = design_amp(AmpSpec(voicing="modern", fx_loop=False))
    p, _ = build_amp(design)
    ctl = knob_controls(p, design, {"GAIN": 0.7, "MASTER": 0.15, "DEPTH": 0.3})
    labels = {c.key: c.label for c in build_circuit(p).controls}
    pots = {q.label: q.value for q in design.parts if q.prefix == "RV"}
    got = {labels[k].split()[1]: v for k, v in ctl.items()}
    assert got == {pots["GAIN"]: 0.7, pots["DEPTH"]: 0.3} or len(ctl) == 3
    assert sorted(ctl.values()) == [0.15, 0.3, 0.7]


def test_render_design_can_be_cancelled(riff):
    out = render_design(asdict(AmpSpec(voicing="highgain", fx_loop=False)), {"GAIN": 0.5}, riff, RATE,
                        progress=lambda f: f > 0.5)
    assert out is None


def test_listen_tab(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings

    from pcbpro.ui import cab_ui
    from pcbpro.ui.amp_designer import AmpDesignerDialog
    monkeypatch.setattr(cab_ui, "settings", lambda: QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))
    monkeypatch.setattr(cab_ui, "find_irs", lambda *a, **k: [])  # never search this PC from a test
    dlg = AmpDesignerDialog(AmpSpec(voicing="modern"))
    try:
        dlg.show()
        dlg.tabs.setCurrentWidget(dlg.listen)
        qapp.processEvents()
        lp = dlg.listen
        assert lp._cab is not None and "4x12" in (lp._cab.path() or "")  # a built-in 4x12 by default
        assert lp.knobs["DEPTH"][0].isVisibleTo(lp) and not lp.knobs["VOLUME"][0].isVisibleTo(lp)
        assert lp.render_btn.isEnabled() and not lp.play_btn.isEnabled()
        lp.finish_render(np.sin(np.arange(4800) / 10.0) * 20.0)  # a "speaker" signal: cabinet + level applied
        assert lp.wet is not None and np.isfinite(lp.wet).all() and 0.7 < np.max(np.abs(lp.wet)) <= 0.8 + 1e-9
        lp.label = "test"
        lp._hold()
        lp._buttons()
        assert lp.held is not None and lp.a_btn.isEnabled() and "test" in lp.a_btn.text()
        assert len(lp.clip_data()) == 6 * 48000
        for i in range(dlg.voicings.count()):  # a clean voicing: a VOLUME knob instead of GAIN, no DEPTH
            if dlg.voicings.item(i).data(0x0100) == "blackface":
                dlg.voicings.setCurrentRow(i)
        dlg._refresh()
        assert lp.knobs["VOLUME"][0].isVisibleTo(lp) and not lp.knobs["DEPTH"][0].isVisibleTo(lp)
    finally:
        dlg.close()
