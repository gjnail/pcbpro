"""Pedal audio play-through and frequency response."""
import numpy as np
import pytest

from pcbpro.sim.audio import CLIPS, frequency_response, guitar_clip, load_wav, render, save_wav


@pytest.fixture(scope="module")
def pedal(qapp):
    from pcbpro.pedal.examples import overdrive_example
    return overdrive_example(route=False)


def _pots(pedal):
    from pcbpro.sim.netlist import build_circuit
    ck = build_circuit(pedal)
    return {c.label.split()[-1]: c.key for c in ck.controls if c.kind == "pot"}


def test_clip_and_wav_roundtrip(tmp_path):
    clip = guitar_clip(seconds=0.5, rate=24000, level=0.2)
    assert len(clip) == 12000 and abs(np.max(np.abs(clip)) - 0.2) < 1e-9
    path = str(tmp_path / "c.wav")
    save_wav(path, clip, 24000)
    back = load_wav(path, rate=24000, level=0.2)
    assert len(back) == 12000 and np.corrcoef(back, clip)[0, 1] > 0.99


def test_overdrive_renders_and_clips(pedal):
    pots = _pots(pedal)
    clip = guitar_clip("Sine 440 Hz", seconds=0.05, rate=24000, level=0.3)
    out = render(pedal, clip, 24000, controls={pots["B500K"]: 1.0, pots["A100K"]: 1.0})
    assert np.all(np.isfinite(out)) and len(out) == len(clip)
    ac = out[len(out) // 2:] - np.mean(out[len(out) // 2:])
    assert np.max(np.abs(ac)) > 0.05  # audible
    # hard-clipped by the diodes: the peaks are flattened, so the crest factor is below a sine's (1.414)
    crest = np.max(np.abs(ac)) / np.sqrt(np.mean(ac ** 2))
    assert crest < 1.35


def test_tone_knob_changes_response(pedal):
    pots = _pots(pedal)
    f, dark = frequency_response(pedal, controls={pots["B25K"]: 0.0})
    _, bright = frequency_response(pedal, controls={pots["B25K"]: 1.0})
    hi = np.argmin(np.abs(f - 5000))
    assert abs(20 * np.log10(abs(bright[hi]) / abs(dark[hi]))) > 1.0


@pytest.mark.parametrize("kind", [k for k in CLIPS if not k.startswith(("Sine", "Single"))])
def test_guitar_clips_have_a_di_guitar_spectrum(kind):
    """Most of the energy in the notes (125-800 Hz), the 4 kHz band well down: otherwise every high-gain amp turns the
    clip into the same fizz."""
    x = guitar_clip(kind, 3.0, 48000, 0.3)
    X = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(len(x), 1 / 48000)

    def band(lo, hi):
        return X[(f >= lo) & (f < hi)].sum()
    assert 10 * np.log10(band(125, 800) / band(2000, 5000)) > 10
    third = {fc: band(fc / 2 ** (1 / 6), fc * 2 ** (1 / 6)) for fc in (125, 250, 500, 1000, 2000, 4000)}
    assert 10 * np.log10(max(third.values()) / third[4000]) > 15
    assert abs(np.max(np.abs(x)) - 0.3) < 1e-9 and len(x) == 144000
