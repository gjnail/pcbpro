"""Audio play-through for pedal and amplifier boards: render a guitar clip through the circuit, and the small-signal
frequency response from the input to the output.

The guitar is a voltage source with a pickup-like 10 k source impedance on the input net; the output is loaded with
1 M (an amplifier input). Rendering starts from the DC operating point, lets the bias settle with the input held,
then runs a fixed-step transient at the audio sample rate.
"""
from __future__ import annotations

import math
import traceback
import wave

import numpy as np

from ..model.board import Project
from .devices import Resistor, VoltageSource, Waveform
from .engine import SimError, Simulator
from .netlist import auto_sources, build_circuit

PICKUP_OHMS = 10e3
AMP_LOAD = 1e6
CLIPS = ["Riff (E minor)", "Metal riff (palm mutes)", "Open chords", "Single notes", "Power chords", "Sine 440 Hz"]


# --------------------------------------------------------------------------- input clips

def _string(freq: float, seconds: float, rate: int, mute: float = 0.0, vel: float = 1.0, beta: float = 0.12,
            gamma: float = 0.1, rng=None) -> np.ndarray:
    """A plucked string as its modes, so the spectrum is a real guitar's and not white noise.

    Harmonic k of a string plucked at ``beta`` of its length from the bridge starts with a displacement
    ~ sin(k pi beta) / k^2; a magnetic pickup at ``gamma`` senses velocity, so ~ k sin(k pi gamma). Higher modes
    decay faster (air and bending losses), wound strings are slightly inharmonic, and ``mute`` (0 ringing .. 1 hard
    palm mute) shortens every decay and damps the upper modes most. A quiet pick click starts the note."""
    rng = rng or np.random.default_rng(1)
    n = max(1, int(seconds * rate))
    t = np.arange(n) / rate
    out = np.zeros(n)
    tau1 = 3.0 ** (1.0 - mute) * 0.035 ** mute * (110.0 / freq) ** 0.5  # decay of the fundamental
    for k in range(1, int(min(60, 8000.0 / freq)) + 1):
        fk = k * freq * math.sqrt(1.0 + 1.2e-4 * k * k)
        if fk >= 0.45 * rate:
            break
        amp = abs(math.sin(k * math.pi * beta) * math.sin(k * math.pi * gamma)) / k
        tau = tau1 / (1.0 + (fk / (900.0 * (1.0 - 0.6 * mute))) ** 2 * (1.0 + 4.0 * mute))
        m = min(n, int(tau * 12 * rate) + 1)  # skip the part that has decayed below -100 dB
        out[:m] += amp * np.exp(-t[:m] / tau) * np.sin(2 * math.pi * fk * t[:m] + rng.uniform(0, 2 * math.pi))
    c = min(n, int(0.004 * rate))
    click = rng.normal(0, 1, c) * np.exp(-np.arange(c) / (0.0008 * rate))
    out[:c] += np.convolve(click, np.ones(6) / 6, mode="same") * 0.03 * (np.max(np.abs(out)) or 1.0)
    tail = min(n, int(0.006 * rate))  # the string released (or the next pick) at the end of the note
    out[n - tail:] *= np.linspace(1.0, 0.0, tail)
    return vel * out


def _pickup(x: np.ndarray, rate: int, f0: float = 3500.0, q: float = 1.6, hp: float = 60.0) -> np.ndarray:
    """Pickup and cable: a resonant low pass at ``f0`` (the coil's inductance with the cable capacitance) and a gentle
    low cut, applied in the frequency domain."""
    nfft = 1 << int(np.ceil(np.log2(len(x) + rate // 10)))
    s = 2j * math.pi * np.fft.rfftfreq(nfft, 1.0 / rate)
    w0, wc = 2 * math.pi * f0, 2 * math.pi * hp
    h = w0 * w0 / (s * s + s * w0 / q + w0 * w0) * s / (s + wc)
    return np.fft.irfft(np.fft.rfft(x, nfft) * h, nfft)[:len(x)]


def guitar_clip(kind: str = CLIPS[0], seconds: float = 4.0, rate: int = 48000, level: float = 0.15) -> np.ndarray:
    """A synthesised guitar clip in volts (``level`` = peak pickup output), with a DI'd guitar's spectrum: most of the
    energy at 80-800 Hz and the 4 kHz band some 20 dB below the notes."""
    n = int(seconds * rate)
    out = np.zeros(n)
    rng = np.random.default_rng(7)
    E2, A2, D3, G3, B3, E4 = 82.41, 110.0, 146.83, 196.0, 246.94, 329.63
    G2, B2 = 98.0, 123.47

    def add(t0: float, freqs, dur: float, strum: float = 0.012, gain: float = 1.0, mute: float = 0.0):
        for k, f in enumerate(freqs):
            s = int((t0 + k * strum) * rate)
            if s >= n:
                return
            seg = _string(f, min(dur, (n - s) / rate), rate, mute=mute, vel=gain, rng=rng)
            out[s:s + len(seg)] += seg[:n - s]

    def fifth(root):
        return [root, root * 2 ** (7 / 12), root * 2]

    if kind.startswith("Sine"):
        t = np.arange(n) / rate
        return np.sin(2 * math.pi * 440.0 * t) * np.minimum(1.0, t / 0.01) * level
    if kind.startswith("Metal"):  # palm-muted chugs on the low E with accented power chords, then a ringing E5
        e8 = 60.0 / 140.0 / 2.0
        t0, bar = 0.0, 8 * e8
        while t0 < seconds - 0.05:
            for i in range(6):
                add(t0 + i * e8, [E2, E2 * 2 ** (7 / 12)], e8 * 0.95, strum=0.004, mute=0.85,
                    gain=1.0 if i % 2 == 0 else 0.85)
            add(t0 + 6 * e8, fifth(G2 if int(t0 / bar) % 2 == 0 else A2), 2 * e8, strum=0.004)
            t0 += bar
            if t0 + bar > seconds - 0.8 and t0 < seconds:
                add(t0, fifth(E2), seconds - t0, strum=0.006)
                break
    elif kind.startswith("Open"):
        chords = [(E2, B2, E2 * 2, 207.65, B3, E4), (A2, E2 * 2, A2 * 2, 277.18, E4),
                  (D3, A2 * 2, D3 * 2, 369.99), (G3 / 2, B3 / 2, D3, G3, B3, 392.0)]
        for i, ch in enumerate(chords * 2):
            add(i * seconds / 8, ch, seconds / 8 + 0.6, gain=0.6)
    elif kind.startswith("Single"):
        notes = [E4, 392.0, 440.0, 493.88, 440.0, 392.0, E4, 293.66]
        for i, f in enumerate(notes):
            add(i * seconds / len(notes), [f], seconds / len(notes) + 0.3, mute=0.1)
    elif kind.startswith("Power"):
        for i, root in enumerate([E2, E2, G2, A2, E2, E2, 116.54, A2]):
            add(i * seconds / 8, fifth(root), seconds / 8 * 0.9, strum=0.006, gain=0.8)
    else:  # E minor riff: low notes with their octave, lightly muted
        riff = [E2, E2, G2, E2, A2, E2, B2, A2, E2, E2, G2, D3, 130.81, B2, G2, E2]
        for i, f in enumerate(riff):
            add(i * seconds / len(riff), [f, f * 2], seconds / len(riff) * 1.6, strum=0.004, gain=0.9,
                mute=0.4 if i % 4 else 0.0)
    out = _pickup(out, rate)
    peak = float(np.max(np.abs(out))) or 1.0
    return out / peak * level


def load_wav(path: str, rate: int = 48000, seconds: float = 8.0, level: float = 0.15) -> np.ndarray:
    """Mono clip from a PCM WAV file, resampled to ``rate`` and scaled to ``level`` volts peak."""
    with wave.open(path, "rb") as w:
        ch, width, fr, nf = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(min(nf, int(seconds * fr)))
    if width == 1:
        data = (np.frombuffer(raw, np.uint8).astype(float) - 128) / 128
    elif width == 2:
        data = np.frombuffer(raw, "<i2").astype(float) / 32768
    elif width == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        data = ((b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
                << 8 >> 8) / 8388608.0
    elif width == 4:
        data = np.frombuffer(raw, "<i4").astype(float) / 2147483648.0
    else:
        raise ValueError("unsupported WAV sample width")
    data = data.reshape(-1, ch).mean(axis=1)
    if fr != rate and len(data) > 1:
        t_new = np.arange(int(len(data) * rate / fr)) / rate
        data = np.interp(t_new, np.arange(len(data)) / fr, data)
    peak = float(np.max(np.abs(data))) or 1.0
    return data / peak * level


def save_wav(path: str, data: np.ndarray, rate: int = 48000, normalize: bool = True) -> None:
    d = np.asarray(data, dtype=float)
    d = d - np.mean(d)
    if normalize:
        d = d / (np.max(np.abs(d)) or 1.0) * 0.9
    pcm = (np.clip(d, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


# --------------------------------------------------------------------------- circuit

def _sources_without(project: Project, ck_probe, in_net: str) -> list[dict]:
    cfg = (project.sim or {}).get("sources")
    if cfg is None:
        cfg = auto_sources(project, ck_probe)
    return [dict(s) for s in cfg if s.get("net") != in_net and s.get("kind", "dc") == "dc"]


def build_for_audio(project: Project, in_net: str, out_net: str, controls: dict | None, wave_: Waveform | None):
    probe = build_circuit(project, "design", sources=[])
    sources = _sources_without(project, probe, in_net)
    ck = build_circuit(project, "design", sources=sources)
    if in_net not in ck.net_node:
        raise SimError(f"The input net '{in_net}' is not on the board.")
    if out_net not in ck.net_node:
        raise SimError(f"The output net '{out_net}' is not on the board.")
    n_in, n_out = ck.net_node[in_net], ck.net_node[out_net]
    mid = ck.internal("guitar")
    src = ck.add(VoltageSource(mid, 0, wave_ or Waveform("dc", v=0.0), name="guitar"))
    ck.add(Resistor(mid, n_in, PICKUP_OHMS, name="pickup"))
    ck.add(Resistor(n_out, 0, AMP_LOAD, name="amplifier input"))
    for key, value in (controls or {}).items():
        ctl = ck.control(key)
        if ctl is not None:
            ctl.apply(value)
    return ck, src, n_in, n_out


def render(project: Project, clip: np.ndarray, rate: int = 48000, in_net: str = "IN", out_net: str = "OUT",
           controls: dict | None = None, settle: float = 0.25, progress=None) -> np.ndarray:
    """Output voltage for ``clip`` (volts at ``rate``). ``progress(fraction) -> bool`` returns True to cancel."""
    wave_ = Waveform("samples", data=clip, rate=float(rate), start=settle)
    ck, src, n_in, n_out = build_for_audio(project, in_net, out_net, controls, wave_)
    sim = Simulator(ck)
    sim.start_op()
    h = 1.0 / rate
    sim.run_fixed(settle, h * 4)  # let the coupling and bias capacitors settle with the input held
    sim.t = settle
    out = np.zeros(len(clip))

    def rec(i, x):
        out[i] = x[n_out]

    ok = sim.run_fixed(settle + len(clip) / rate, h, record=rec, progress=progress)
    if ok is False:
        return out[:0]
    return out


def render_fast(project: Project, clip: np.ndarray, rate: int = 48000, in_net: str = "IN", out_net: str = "OUT",
                controls: dict | None = None, settle: float = 0.25, progress=None, oversample: int = 2) -> np.ndarray:
    """``render`` through the compiled real-time model (with oversampling): the same circuit equations, many times
    faster for tube amps. Falls back to ``render`` when the circuit cannot be compiled."""
    from .realtime import RealtimeModel
    try:
        m = RealtimeModel(project, in_net, out_net, controls, float(rate), oversample)
        m.warm_up()
    except Exception:
        return render(project, clip, rate, in_net, out_net, controls, settle, progress)
    m.settle(settle)
    out = np.zeros(len(clip))
    step = max(256, int(rate) // 20)
    for k in range(0, len(clip), step):
        out[k:k + step] = m.process_block(np.asarray(clip[k:k + step], dtype=float))
        if progress is not None and progress(min(1.0, (k + step) / max(1, len(clip)))):
            return out[:0]
    return out


def frequency_response(project: Project, in_net: str = "IN", out_net: str = "OUT", controls: dict | None = None,
                       freqs=None):
    """Complex response from the guitar source to the output (with pickup impedance and amp load)."""
    freqs = np.logspace(math.log10(20), math.log10(20000), 120) if freqs is None else np.asarray(freqs)
    ck, src, n_in, n_out = build_for_audio(project, in_net, out_net, controls, None)
    sim = Simulator(ck)
    sim.start_op()
    return freqs, sim.ac_sweep(freqs, src, [n_out])[:, 0]


def bypass_for(ck) -> dict:
    """Control values that put footswitch-like toggles in their other position (effect on/off comparison)."""
    return {c.key: 1 - int(c.value) for c in ck.controls if c.kind == "toggle"}


# --------------------------------------------------------------------------- worker process

def audio_worker(conn, project_dict: dict, opts: dict) -> None:  # pragma: no cover - child process
    try:
        project = Project.from_dict(project_dict)
        clip = np.asarray(opts["clip"], dtype=float)

        def prog(f):
            conn.send({"progress": f})
            return bool(conn.poll() and conn.recv() == "cancel")
        fn = render_fast if opts.get("fast", True) else render
        out = fn(project, clip, opts.get("rate", 48000), opts.get("in", "IN"), opts.get("out", "OUT"),
                 opts.get("controls"), progress=prog)
        conn.send({"done": out})
    except Exception as e:
        conn.send({"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()})
