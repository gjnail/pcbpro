"""Render the sound clips on the website: guitar DI clips played through Amp Designer voicings and the bundled pedals,
each simulated part by part (the same tube and circuit models as the app's Listen tab and Play live), then through
one of the built-in speaker-cabinet IRs.

    python tools/docs_media/audio_clips.py            # every clip (skips ones already rendered in out/docs_media/audio)
    python tools/docs_media/audio_clips.py modern     # just the named clips (rendered again)
    python tools/docs_media/audio_clips.py --list

The WAVs go to out/docs_media/audio/ and the MP3s the site plays to docs/media/audio/ (FFmpeg on the PATH).
docs/media/audio/clips.json lists them with their captions. Run it with the app's environment (.venv).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pcbpro.amp.demo import metal_riff, render_design  # noqa: E402
from pcbpro.sim.audio import guitar_clip, render  # noqa: E402
from pcbpro.sim.cabinet import apply_ir, builtin_irs, load_ir  # noqa: E402

RATE = 48000
WAVS = ROOT / "out" / "docs_media" / "audio"
MP3S = ROOT / "docs" / "media" / "audio"
EQ = {"BASS": 0.5, "MIDDLE": 0.5, "TREBLE": 0.6, "PRESENCE": 0.5, "DEPTH": 0.4}


def cab(name: str) -> np.ndarray:
    path = next(p for p in builtin_irs() if Path(p).stem == name)
    return load_ir(path, RATE)


def clip(kind: str, seconds: float, level: float) -> np.ndarray:
    if kind == "metal":
        return metal_riff(RATE, seconds, level)
    return guitar_clip(kind, seconds, RATE, level)


def amp(voicing: str, knobs: dict, x: np.ndarray, **spec) -> np.ndarray:
    out = render_design({"voicing": voicing, **spec}, {**EQ, **knobs}, x, RATE, oversample=2)
    return out - np.mean(out)


KNOB_ORDER = {  # the pots in reference order (RV1, RV2 ...), as the generators make them
    "Three_Knob_Overdrive_125B.pcbpro": ("LEVEL", "TONE", "DRIVE"),
    "Metal_Tight_Boost_125B.pcbpro": ("LEVEL", "TONE", "DRIVE", "TIGHT"),
    "Metal_High_Gain_Distortion_1590BB2.pcbpro": ("LEVEL", "GAIN", "BASS", "MID", "TREBLE"),
}


def pedal(file_name: str, knobs: dict, x: np.ndarray) -> np.ndarray:
    """A bundled pedal's OUT for ``x`` at IN; ``knobs`` by the name printed on the panel (DRIVE, LEVEL ...)."""
    from pcbpro.examples import EXAMPLE_DIR, load_example
    from pcbpro.sim.netlist import build_circuit
    p = load_example(EXAMPLE_DIR / file_name)
    refs = {f"RV{i + 1}": name for i, name in enumerate(KNOB_ORDER[file_name])}
    missing = set(knobs) - set(refs.values())
    if missing:
        raise SystemExit(f"{file_name}: no knob labelled {', '.join(sorted(missing))}")
    ctl = {c.key: knobs[refs[c.label.split()[0]]] for c in build_circuit(p).controls
           if c.kind == "pot" and refs.get(c.label.split()[0]) in knobs}
    y = render(p, x, RATE, "IN", "OUT", ctl)  # the exact engine: the real-time model goes unstable on the distortion
    return y - np.mean(y)


# name -> (title, caption, function returning the speaker or line signal, cabinet or None)
def _clips():
    di_clean = lambda: clip("Open chords", 6.0, 0.15)  # noqa: E731  single coils
    di_crunch = lambda: clip("Power chords", 6.0, 0.3)  # noqa: E731  humbucker
    di_metal = lambda: clip("metal", 6.0, 0.4)  # noqa: E731  hot humbucker
    return {
        "di_metal": ("The DI going in", "The modelled guitar every high-gain clip plays: palm-muted chugs on the low E, "
                     "power chords and a short line, as a humbucker and cable deliver it.", di_metal, None),
        "blackface": ("Blackface clean", "Amp Designer, Blackface clean, 2 × 6V6 fixed bias. Volume 3, open chords on "
                      "single coils, 1x12 open-back cabinet.",
                      lambda: amp("blackface", {"VOLUME": 0.3}, di_clean()), "1x12_open"),
        "tweed": ("Tweed breakup", "Amp Designer, Tweed breakup, no negative feedback. Volume 7, power chords on a "
                  "humbucker, 1x12 open-back cabinet.",
                  lambda: amp("tweed", {"VOLUME": 0.7}, di_crunch()), "1x12_open"),
        "plexi": ("Plexi crunch", "Amp Designer, Plexi crunch, 2 × EL34. Volume 7, power chords on a humbucker, 4x12 "
                  "slant cabinet.", lambda: amp("plexi", {"VOLUME": 0.7, "MASTER": 0.5}, di_crunch()), "4x12_slant"),
        "chime": ("Chime", "Amp Designer, Chime, 4 × EL84 with no feedback. Volume 5, open chords on single coils, "
                  "2x12 closed cabinet.", lambda: amp("chime", {"VOLUME": 0.5}, di_clean()), "2x12_closed"),
        "highgain": ("British high gain", "Amp Designer, British high gain (3 stages), 2 × EL34. Gain 6, the metal "
                     "riff, 4x12 cabinet.", lambda: amp("highgain", {"GAIN": 0.6, "MASTER": 0.2}, di_metal()),
                     "4x12_straight"),
        "modern": ("Modern high gain", "Amp Designer, Modern high gain (4 stages), 2 × 6L6GC. Gain at noon, tightness "
                   "normal, the metal riff, 4x12 cabinet.",
                   lambda: amp("modern", {"GAIN": 0.5, "MASTER": 0.2}, di_metal()), "4x12_straight"),
        "extreme": ("Extreme high gain", "Amp Designer, Extreme high gain (5 stages), 4 × 6L6GC. Gain at noon, "
                    "tightness tight, the metal riff, 4x12 cabinet.",
                    lambda: amp("extreme", {"GAIN": 0.5, "MASTER": 0.2}, di_metal()), "4x12_straight"),
        "modern_fat": ("Tightness: fat", "Modern high gain with tightness set to fat: more bass reaches the "
                       "distortion, so the chugs bloom.",
                       lambda: amp("modern", {"GAIN": 0.5, "MASTER": 0.2}, di_metal(), tight="fat"), "4x12_straight"),
        "modern_djent": ("Tightness: djent", "Modern high gain with tightness set to djent: the bass is cut before "
                         "the distortion and put back after it, so every chug stops dead.",
                         lambda: amp("modern", {"GAIN": 0.5, "MASTER": 0.2}, di_metal(), tight="djent"),
                         "4x12_straight"),
        "overdrive": ("Three-knob overdrive", "The bundled three-knob overdrive pedal (drive 7, tone 5) in front of "
                      "the Blackface clean amp at volume 3. Both boards are simulated.",
                      lambda: amp("blackface", {"VOLUME": 0.3},
                                  pedal("Three_Knob_Overdrive_125B.pcbpro", {"DRIVE": 0.7, "TONE": 0.5, "LEVEL": 0.8},
                                        di_crunch())), "1x12_open"),
        "tight_boost": ("Tight Boost into British high gain", "The Metal Tight Boost pedal (drive down, level up, "
                        "tight at noon) in front of the British high-gain amp. Compare it with the amp alone.",
                        lambda: amp("highgain", {"GAIN": 0.6, "MASTER": 0.2},
                                    pedal("Metal_Tight_Boost_125B.pcbpro",
                                          {"DRIVE": 0.0, "LEVEL": 1.0, "TIGHT": 0.5, "TONE": 0.6}, di_metal())),
                        "4x12_straight"),
        "distortion": ("High-Gain Distortion pedal", "The Metal High-Gain Distortion pedal (gain 7, EQ at noon) into "
                       "the Blackface clean amp, the way a distortion pedal is usually played.",
                       lambda: amp("blackface", {"VOLUME": 0.3},
                                   pedal("Metal_High_Gain_Distortion_1590BB2.pcbpro",
                                         {"GAIN": 0.7, "LEVEL": 0.6, "BASS": 0.5, "MID": 0.5, "TREBLE": 0.5},
                                         di_metal())), "1x12_open"),
    }


def finish(y: np.ndarray, cabinet: str | None) -> np.ndarray:
    """Cabinet, then a common loudness (RMS -18 dBFS, peaks under -1 dBFS) and short fades."""
    if cabinet:
        y = apply_ir(y, cab(cabinet))[:len(y)]
    y = y - np.mean(y)
    rms = float(np.sqrt(np.mean(y ** 2))) or 1.0
    peak = float(np.max(np.abs(y))) or 1.0
    y = y * min(10 ** (-18 / 20) / rms, 0.89 / peak)
    fade_in, fade_out = int(0.005 * RATE), int(0.25 * RATE)
    y[:fade_in] *= np.linspace(0, 1, fade_in)
    y[-fade_out:] *= np.linspace(1, 0, fade_out)
    return y


def save_wav(path: Path, y: np.ndarray) -> None:
    import wave
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())


def encode(wav: Path, mp3: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("FFmpeg is not on the PATH")
    mp3.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "128k",
                    str(mp3)], check=True)


def main(argv: list[str]) -> None:
    clips = _clips()
    if "--list" in argv:
        for k, (title, *_rest) in clips.items():
            print(f"{k:14} {title}")
        return
    names = [a for a in argv if not a.startswith("-")]
    unknown = set(names) - set(clips)
    if unknown:
        raise SystemExit(f"unknown clips: {', '.join(sorted(unknown))}")
    for name, (title, caption, fn, cabinet) in clips.items():
        wav = WAVS / f"{name}.wav"
        if (names and name not in names) or (not names and wav.exists()):
            continue
        t = time.perf_counter()
        y = finish(np.asarray(fn(), dtype=float), cabinet)
        save_wav(wav, y)
        print(f"{name}: {time.perf_counter() - t:.0f} s", flush=True)
    index = []
    for name, (title, caption, _fn, cabinet) in clips.items():
        wav = WAVS / f"{name}.wav"
        if not wav.exists():
            continue
        encode(wav, MP3S / f"{name}.mp3")
        index.append({"key": name, "title": title, "caption": caption, "cabinet": cabinet or ""})
    (MP3S / "clips.json").write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")
    print(f"{len(index)} clips in {MP3S}")


if __name__ == "__main__":
    main(sys.argv[1:])
