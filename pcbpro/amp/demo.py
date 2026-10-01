"""Realistic guitar test signals for hearing (and measuring) amp designs.

A distorted amp is only as convincing as what goes into it. A Karplus-Strong pluck excited with white noise keeps
its upper harmonics far too long on the low strings, so its 2-4 kHz content ends up louder than the notes themselves
and every high-gain amp turns it into the same fizz. Here each note is built the way a real string and pickup make
it:

* modal synthesis: harmonic k of a string plucked at a fraction ``beta`` of its length from the bridge has an
  amplitude proportional to sin(k pi beta) / k^2 (displacement); a magnetic pickup at ``gamma`` senses velocity, so
  times k sin(k pi gamma);
* each mode decays faster the higher it is (air and bending losses), wound strings are slightly inharmonic;
* palm muting shortens every decay and damps the upper modes most;
* a short, quiet pick click;
* the pickup's own response: a resonant low pass (about 3.5 kHz with the cable's capacitance) and a gentle low cut.

The result has the spectral balance of a real DI'd guitar (most energy 80-800 Hz, the 2-4 kHz bands 15-25 dB down),
so the differences between amps - tightness, tone stack, clipping - come through.
"""
from __future__ import annotations

import math

import numpy as np

E2, F2, G2, A2, B2, C3, D3 = 82.41, 87.31, 98.0, 110.0, 123.47, 130.81, 146.83


def _note(freq: float, dur: float, rate: int, mute: float = 0.0, vel: float = 1.0, beta: float = 0.11,
          gamma: float = 0.09, inharm: float = 1.2e-4, seed: int = 0) -> np.ndarray:
    """One plucked string: ``mute`` 0 (ringing) .. 1 (hard palm mute)."""
    n = int(dur * rate)
    t = np.arange(n) / rate
    out = np.zeros(n)
    nyq = rate / 2.0
    # an open string rings for seconds; a hard palm mute kills it in a few tens of ms (geometric blend of the two)
    tau1 = 3.0 ** (1.0 - mute) * 0.035 ** mute * (110.0 / freq) ** 0.5
    k_max = int(min(60, nyq * 0.9 / freq))
    rng = np.random.default_rng(seed)
    for k in range(1, k_max + 1):
        fk = k * freq * math.sqrt(1.0 + inharm * k * k)
        if fk >= nyq * 0.95:
            break
        amp = abs(math.sin(k * math.pi * beta)) / (k * k) * k * abs(math.sin(k * math.pi * gamma))
        tau = tau1 / (1.0 + (fk / (900.0 * (1.0 - 0.6 * mute))) ** 2 * (1.0 + 4.0 * mute))
        out += amp * np.exp(-t / tau) * np.sin(2 * math.pi * fk * t + rng.uniform(0, 2 * math.pi))
    # a short pick click: band-limited noise, about 30 dB under the note
    click_n = int(0.004 * rate)
    click = rng.normal(0, 1, click_n) * np.exp(-np.arange(click_n) / (0.0008 * rate))
    out[:click_n] += np.convolve(click, np.ones(6) / 6, mode="same") * 0.03 * np.max(np.abs(out))
    # string-on-fret release at the end of a muted note
    tail = min(n, int(0.006 * rate))
    out[n - tail:] *= np.linspace(1.0, 0.0, tail)
    return vel * out


def _pickup(x: np.ndarray, rate: int, f0: float = 3500.0, q: float = 1.6, hp: float = 60.0) -> np.ndarray:
    """Humbucker + cable: resonant 2nd-order low pass at ``f0`` and a 1st-order low cut at ``hp`` (bilinear)."""
    K = 2.0 * rate
    w0 = 2 * math.pi * f0
    a0 = K * K + w0 / q * K + w0 * w0
    b = (w0 * w0 / a0, 2 * w0 * w0 / a0, w0 * w0 / a0)
    a1, a2 = (2 * w0 * w0 - 2 * K * K) / a0, (K * K - w0 / q * K + w0 * w0) / a0
    y = np.zeros_like(x)
    x1 = x2 = y1 = y2 = 0.0
    for i in range(len(x)):
        v = x[i]
        o = b[0] * v + b[1] * x1 + b[2] * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, v, y1, o
        y[i] = o
    wc = 2 * math.pi * hp
    c = (K - wc) / (K + wc)
    z = np.zeros_like(y)
    prev_x = prev_y = 0.0
    for i in range(len(y)):  # first-order high pass
        prev_y = (K / (K + wc)) * (y[i] - prev_x) + c * prev_y
        prev_x = y[i]
        z[i] = prev_y
    return z


def metal_riff(rate: int = 48000, seconds: float = 6.0, level: float = 0.4, bpm: float = 140.0) -> np.ndarray:
    """A DI'd metal riff in volts (``level`` = peak pickup output, about 0.4 V for a hot humbucker): palm-muted low-E
    chugs, open power chords that ring, and a short melodic line - the things a high-gain amp has to get right."""
    n = int(seconds * rate)
    out = np.zeros(n)
    eighth = 60.0 / bpm / 2.0
    seed = [0]

    def play(t0, freqs, dur, mute=0.0, vel=1.0, strum=0.004):
        for i, f in enumerate(freqs):
            s = int((t0 + i * strum) * rate)
            if s >= n:
                return
            seed[0] += 1
            note = _note(f, min(dur, (n - s) / rate), rate, mute=mute, vel=vel, seed=seed[0])
            out[s:s + len(note)] += note[:n - s]

    def power(root):  # root, fifth, octave
        return [root, root * 2 ** (7 / 12), root * 2]

    t = 0.0
    bar = 8 * eighth
    k = 0
    # bars of chug chug chug-chug on the low E with an accented power chord; always at least the chugs, and the
    # ending (a short lead line over a ringing E5) once there is room for it
    while t < seconds - 0.05 and (k == 0 or t + bar <= seconds - 1.2):
        for i in range(6):
            play(t + i * eighth, [E2, E2 * 2 ** (7 / 12)], eighth * 0.95, mute=0.85, vel=0.9 if i % 2 else 1.0)
        play(t + 6 * eighth, power(G2 if k % 2 == 0 else A2), 2 * eighth, mute=0.0, vel=1.0)
        t += bar
        k += 1
    if t + 1.0 <= seconds:
        for i, f in enumerate((329.63, 392.0, 440.0, 392.0)):
            play(t + i * eighth / 2, [f], eighth * 0.9, mute=0.1, vel=0.7)
        play(t + 2 * eighth, power(E2), seconds - t - 2 * eighth, mute=0.0, vel=1.0)
    out = _pickup(out, rate)
    peak = float(np.max(np.abs(out))) or 1.0
    return out / peak * level


# --------------------------------------------------------------------------- hearing a design

def knob_controls(project, design, knobs: dict) -> dict:
    """Simulator control values for the front-panel knobs of a built amp, given by label (GAIN, BASS ...: 0..1)."""
    from ..sim.netlist import build_circuit
    ck = build_circuit(project)
    labels = {tuple(sorted(p.nets.items())): p.label for p in design.parts if p.prefix == "RV" and p.label}
    refs = {c.ref: labels.get(tuple(sorted(c.pad_nets.items()))) for c in project.components if c.ref.startswith("RV")}
    out = {}
    for ctl in ck.controls:
        if ctl.kind == "pot":
            label = refs.get(ctl.label.split()[0])
            if label in knobs:
                out[ctl.key] = float(knobs[label])
    bad = [i.ref for i in ck.parts.values() if i.status in ("unsupported", "error")]
    if bad:
        raise RuntimeError(f"the simulator cannot model {', '.join(bad[:6])}")
    return out


def render_design(spec: dict, knobs: dict, clip: np.ndarray, rate: int = 48000, oversample: int = 2,
                  progress=None) -> np.ndarray | None:
    """Play ``clip`` (volts at the input jack) through the board an Amp Designer spec makes, tube by tube, and
    return the voltage across the speaker. ``progress(fraction)`` returns True to cancel (then None is returned)."""
    from ..sim.realtime import RealtimeModel
    from .builder import build_amp
    from .designer import AmpSpec, design_amp
    design, _rep = design_amp(AmpSpec(**{k: v for k, v in spec.items() if k in AmpSpec.__dataclass_fields__}))
    project, _notes = build_amp(design)  # placed, not routed: the simulator only needs the netlist
    if progress is not None and progress(0.05):
        return None
    ctl = knob_controls(project, design, knobs)
    model = RealtimeModel(project, "IN", "SPK", ctl, float(rate), oversample)
    model.warm_up()
    model.settle(0.3)
    out = np.zeros(len(clip))
    step = max(1024, rate // 10)
    for k in range(0, len(clip), step):
        out[k:k + step] = model.process_block(np.asarray(clip[k:k + step], dtype=float))
        if progress is not None and progress(0.05 + 0.95 * min(1.0, (k + step) / max(1, len(clip)))):
            return None
    return out


def listen_worker(conn, spec: dict, knobs: dict, opts: dict) -> None:  # pragma: no cover - child process
    """Background process for the Amp Designer's Listen tab: renders, reports progress, honours "cancel"."""
    import traceback
    try:
        def prog(f):
            conn.send({"progress": f})
            return bool(conn.poll() and conn.recv() == "cancel")
        out = render_design(spec, knobs, np.asarray(opts["clip"], dtype=float), int(opts.get("rate", 48000)),
                            int(opts.get("oversample", 2)), prog)
        conn.send({"done": out} if out is not None else {"cancelled": True})
    except Exception as e:
        conn.send({"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()})
