"""Guitar cabinet simulation: a speaker impulse response (IR) convolved with the circuit's output.

A cab IR is the recorded response of a speaker cabinet and microphone; convolving the amplifier's output with it gives
the sound of that cabinet in the room. IRs are read from WAV (PCM or float) or FLAC, mixed to mono, resampled to the
engine rate, trimmed, and level-matched over the guitar band so switching cabinets keeps the loudness.

Live audio uses uniformly partitioned overlap-save FFT convolution with the audio block as the partition, so the
cabinet adds no latency. ``find_irs`` searches the usual folders of this computer for cabinet IRs.
"""
from __future__ import annotations

import os
import re
import struct
import sys
import time
import zlib
from functools import lru_cache
from pathlib import Path

import numpy as np

BUNDLED_DIR = Path(__file__).resolve().parents[1] / "resources" / "irs"
MAX_SECONDS = 0.5  # longer tails are room sound, not the cabinet
EXTENSIONS = (".wav", ".flac")


# --------------------------------------------------------------------------- reading files

def _wav_header(f) -> dict:
    """Walk the RIFF chunks: format fields and where the samples are."""
    head = f.read(12)
    if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    fmt = None
    while True:
        h = f.read(8)
        if len(h) < 8:
            break
        cid, size = h[:4], struct.unpack("<I", h[4:])[0]
        if cid == b"fmt ":
            body = f.read(size)
            tag, ch, rate, _brate, align, bits = struct.unpack("<HHIIHH", body[:16])
            if tag == 0xFFFE and len(body) >= 26:  # WAVE_FORMAT_EXTENSIBLE: the real format is in the GUID
                tag = struct.unpack("<H", body[24:26])[0]
            fmt = {"tag": tag, "channels": ch, "rate": rate, "align": align, "bits": bits}
            if size & 1:
                f.read(1)
        elif cid == b"data":
            if fmt is None:
                raise ValueError("WAV data before its format")
            fmt["offset"], fmt["size"] = f.tell(), size
            return fmt
        else:
            f.seek(size + (size & 1), 1)
    raise ValueError("WAV file has no audio data")


def _decode_wav(raw: bytes, fmt: dict) -> np.ndarray:
    ch = max(1, fmt["channels"])
    width = fmt["align"] // ch if fmt["align"] else fmt["bits"] // 8
    raw = raw[:len(raw) // (width * ch) * width * ch]
    if fmt["tag"] == 3:
        if width not in (4, 8):
            raise ValueError("unsupported float WAV")
        data = np.frombuffer(raw, "<f4" if width == 4 else "<f8").astype(float)
    elif fmt["tag"] == 1:
        if width == 1:
            data = (np.frombuffer(raw, np.uint8).astype(float) - 128) / 128
        elif width == 2:
            data = np.frombuffer(raw, "<i2") / 32768.0
        elif width == 3:
            b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
            data = ((b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)) << 8 >> 8) / 8388608.0
        elif width == 4:
            data = np.frombuffer(raw, "<i4") / 2147483648.0
        else:
            raise ValueError("unsupported WAV sample width")
    else:
        raise ValueError(f"unsupported WAV encoding (format {fmt['tag']})")
    return data.reshape(-1, ch)


def read_audio(path, max_seconds: float | None = None) -> tuple[np.ndarray, int]:
    """Samples as floats in -1..1, shaped (frames, channels), and the sample rate. WAV or FLAC."""
    path = str(path)
    if path.lower().endswith(".flac"):
        from .flac import flac_info, read_flac
        info = flac_info(path)
        cap = None if max_seconds is None else int(max_seconds * info["rate"]) + 1
        a, rate, bps = read_flac(path, cap)
        return a / float(1 << (bps - 1)), rate
    with open(path, "rb") as f:
        fmt = _wav_header(f)
        f.seek(fmt["offset"])
        n = fmt["size"]
        if max_seconds is not None:
            n = min(n, (int(max_seconds * fmt["rate"]) + 1) * max(1, fmt["align"]))
        raw = f.read(n)
    return _decode_wav(raw, fmt), int(fmt["rate"])


def audio_info(path) -> dict | None:
    """Rate, channels and length from the file header, or None if it is not readable audio."""
    try:
        if str(path).lower().endswith(".flac"):
            from .flac import flac_info
            i = flac_info(path)
            return {"rate": i["rate"], "channels": i["channels"], "seconds": i["samples"] / max(1, i["rate"])}
        with open(path, "rb") as f:
            fmt = _wav_header(f)
        if fmt["tag"] not in (1, 3) or not fmt["rate"] or not fmt["align"]:
            return None
        return {"rate": fmt["rate"], "channels": fmt["channels"],
                "seconds": fmt["size"] / fmt["align"] / fmt["rate"]}
    except (OSError, ValueError, struct.error, IndexError):
        return None


# --------------------------------------------------------------------------- preparing an IR

def resample(x: np.ndarray, src: float, dst: float) -> np.ndarray:
    """Band-limited (FFT) resampling of a short signal such as an IR."""
    x = np.asarray(x, float)
    if src == dst or len(x) < 2:
        return x.copy()
    n = len(x)
    m = max(1, int(round(n * dst / src)))
    X = np.fft.rfft(x, 2 * n)  # zero padding keeps the tail from wrapping around
    Y = np.zeros(m + 1, complex)
    k = min(len(X), len(Y))
    Y[:k] = X[:k]
    if dst < src:  # soften the new band edge so it does not ring
        t = max(1, k // 20)
        Y[k - t:k] *= np.linspace(1.0, 0.0, t)
    return np.fft.irfft(Y, 2 * m)[:m] * (m / n)


def band_level(h: np.ndarray, rate: float, lo: float = 80.0, hi: float = 5000.0) -> float:
    """RMS gain of the IR over the guitar band, averaged on a log-frequency scale."""
    n = 1 << max(13, int(np.ceil(np.log2(max(2, len(h)) * 2))))
    mag = np.abs(np.fft.rfft(h, n))
    f = np.fft.rfftfreq(n, 1.0 / rate)
    fl = np.geomspace(lo, min(hi, rate * 0.45), 256)
    return float(np.sqrt(np.mean(np.interp(fl, f, mag) ** 2)))


def prepare_ir(data: np.ndarray, src_rate: float, rate: float, max_seconds: float = MAX_SECONDS) -> np.ndarray:
    """Mono, resampled to ``rate``, silence trimmed, at most ``max_seconds`` long, unity gain over the guitar band."""
    d = np.asarray(data, float)
    h = d.mean(axis=1) if d.ndim == 2 else d
    if not len(h) or not np.any(h):
        raise ValueError("the impulse response is silent")
    h = resample(h[:int(max_seconds * src_rate * 1.2) + 16], src_rate, rate)
    peak = float(np.max(np.abs(h)))
    loud = np.flatnonzero(np.abs(h) > peak * 10 ** (-50 / 20))
    start = max(0, int(loud[0]) - 16)  # drop the leading silence (pure delay)
    tail = np.flatnonzero(np.abs(h) > peak * 10 ** (-70 / 20))
    end = min(len(h), int(tail[-1]) + 17, start + int(max_seconds * rate))
    h = h[start:end].copy()
    fade = min(len(h) // 8, int(0.004 * rate))
    if fade > 1:
        h[-fade:] *= 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, fade))
    return h / (band_level(h, rate) or 1.0)


@lru_cache(maxsize=16)
def _load(path: str, rate: float, max_seconds: float, stamp) -> np.ndarray:
    data, src = read_audio(path, max_seconds * 1.2 + 0.01)
    h = prepare_ir(data, src, rate, max_seconds)
    h.flags.writeable = False
    return h


def load_ir(path, rate: float, max_seconds: float = MAX_SECONDS) -> np.ndarray:
    """The cabinet IR in ``path`` ready to convolve at ``rate`` (cached; read-only array)."""
    p = str(path)
    st = os.stat(p)
    return _load(p, float(rate), float(max_seconds), (st.st_size, st.st_mtime_ns))


# --------------------------------------------------------------------------- convolution

def apply_ir(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    """``x`` through the cabinet (FFT convolution), the same length as ``x``."""
    x = np.asarray(x, float)
    if not len(x) or h is None or not len(h):
        return x.copy()
    n = len(x) + len(h) - 1
    nfft = 1 << int(np.ceil(np.log2(n)))
    return np.fft.irfft(np.fft.rfft(x, nfft) * np.fft.rfft(h, nfft), nfft)[:len(x)]


def ir_response(h: np.ndarray, rate: float, freqs) -> np.ndarray:
    """Complex frequency response of the IR at ``freqs`` (for plotting)."""
    nfft = 1 << max(16, int(np.ceil(np.log2(max(2, len(h))))))
    H = np.fft.rfft(np.asarray(h, float), nfft)
    f = np.fft.rfftfreq(nfft, 1.0 / rate)
    fr = np.asarray(freqs, float)
    return np.interp(fr, f, H.real) + 1j * np.interp(fr, f, H.imag)


class Convolver:
    """Streaming convolution: uniformly partitioned overlap-save with a frequency-domain delay line.

    The partition is the audio block, so ``process`` returns each block's output with no added latency. A block of a
    different size re-partitions the IR (and restarts its history)."""

    def __init__(self, h: np.ndarray, block: int = 128):
        self.h = np.asarray(h, float)
        self._setup(int(block))

    def _setup(self, block: int):
        B = self.B = max(1, block)
        P = max(1, -(-len(self.h) // B))
        hp = np.zeros(P * B)
        hp[:len(self.h)] = self.h
        H = np.fft.rfft(hp.reshape(P, B), 2 * B, axis=1)
        G = H[::-1]
        self._G2 = np.ascontiguousarray(np.concatenate([G, G]))  # reversed twice: a contiguous slice per block
        self._X = np.zeros((P, B + 1), complex)  # spectra of the last P input blocks (ring)
        self._head = 0
        self._buf = np.zeros(2 * B)

    def reset(self):
        self._setup(self.B)

    def _block(self, x: np.ndarray) -> np.ndarray:
        B = self.B
        buf = self._buf
        buf[:B] = buf[B:]
        buf[B:] = x
        P = len(self._X)
        self._head = (self._head + 1) % P
        self._X[self._head] = np.fft.rfft(buf)
        s = (P - 1 - self._head) % P
        Y = np.einsum("ij,ij->j", self._X, self._G2[s:s + P])
        return np.fft.irfft(Y, 2 * B)[B:]

    def process(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, float)
        n = len(x)
        if n == 0:
            return np.zeros(0)
        if n % self.B:
            self._setup(n)
        if n == self.B:
            return self._block(x)
        return np.concatenate([self._block(x[k:k + self.B]) for k in range(0, n, self.B)])


# --------------------------------------------------------------------------- finding IRs

_CAB_WORDS = {"cab", "cabs", "cabinet", "cabinets", "speaker", "speakers", "amp", "amps", "combo", "stack",
              "greenback", "creamback", "jensen", "celestion", "eminence", "alnico", "vintage30", "v30", "sm57",
              "md421", "r121", "e906", "e609", "m160", "royer", "ownhammer", "redwirez", "kalthallen", "guitarhack"}
_CAB_PATTERNS = re.compile(r"^(\d+x\d+|g12\w*|g10\w*|p1[02]\w*|c1[02]\w*|v30\w*|sm57\w*|md421\w*|e906\w*)$")
_IR_WORDS = {"ir", "irs", "impulse", "impulses", "impulseresponse", "impulseresponses"}
_REVERB = {"reverb", "reverbs", "verb", "hall", "halls", "plate", "plates", "chamber", "chambers", "church",
           "cathedral", "tunnel", "stairwell", "echo", "delay", "drum", "drums", "kick", "snare", "loop", "loops",
           "vocal", "vocals", "vowels", "reflections", "microphone", "microphones"}
_NOT_CAB = {"room", "rooms", "ambience", "ambient", "space", "spaces", "body", "fx"}
_SKIP_DIRS = {"node_modules", "__pycache__", "site-packages", ".git", ".svn", ".venv", "venv", "appdata", "dist",
              "build", "_internal", "windows", "microsoft", "package cache", "packages", "$recycle.bin", "temp",
              "tmp", "cache", "caches", "steamapps", "nvidia", "intel", "amd", "onedrivetemp"}
_GENERIC = {"amps", "amp", "impulses", "impulse", "irs", "ir", "cabs", "cab", "cabinets", "cabinet", "wav", "wavs",
            "flac", "44k", "44.1k", "48k", "96k", "44khz", "48khz", "96khz", "44.1khz", "mono", "stereo",
            "impulse responses", "speaker cabinets", "guitar cabinets", "box", "factory", "factory_samples",
            "samples", "dependencies", "presets", "content", "library", "data", "resources", "documents", "downloads"}


_SYSTEM = {"users", "programdata", "program files", "program files (x86)", "public", "library", "volumes"}


def _tokens(text: str) -> set[str]:
    return set(re.split(r"[^a-z0-9]+", text.lower())) - {""}


def is_cab_path(rel_parts) -> bool:
    """Whether a file's name and folders (relative to the search root) suggest a guitar cabinet IR."""
    toks: set[str] = set()
    for k, part in enumerate(rel_parts):
        toks |= _tokens(Path(part).stem if k == len(rel_parts) - 1 else part)
    if toks & _REVERB:
        return False
    if toks & _CAB_WORDS or any(_CAB_PATTERNS.match(t) for t in toks):
        return True
    return not toks & _NOT_CAB and bool(toks & _IR_WORDS) and bool(toks & {"guitar", "bass"})


def default_roots() -> list[Path]:
    home = Path.home()
    roots = [home / "Documents", home / "Downloads", home / "Music", home / "Desktop", home / "OneDrive" / "Documents"]
    if sys.platform == "win32":
        for env in ("PROGRAMDATA", "PUBLIC"):
            if os.environ.get(env):
                roots.append(Path(os.environ[env]) / ("Documents" if env == "PUBLIC" else ""))
    elif sys.platform == "darwin":
        roots += [Path("/Library/Audio/Impulse Responses"), home / "Library" / "Audio" / "Impulse Responses"]
    seen, out = set(), []
    for r in roots:
        try:
            key = str(r.resolve()).lower()
        except OSError:
            continue
        if key not in seen and r.is_dir():
            seen.add(key)
            out.append(r)
    return out


def builtin_irs() -> list[str]:
    return sorted(str(p) for p in BUNDLED_DIR.glob("*") if p.suffix.lower() in EXTENSIONS)


def find_irs(roots=None, max_depth: int = 7, deadline: float = 30.0, cancel=None, progress=None) -> list[str]:
    """Cabinet IR files under ``roots`` (default: Documents, Downloads, Music, Desktop, ProgramData, ...).

    A file qualifies when its name or folders suggest a guitar cabinet (and not a reverb), and its header says it is
    readable audio of at most about a second. Identical files found in several places are listed once."""
    roots = default_roots() if roots is None else [Path(r) for r in roots]
    t_end = time.monotonic() + deadline
    found: list[str] = []
    seen_content = set()
    bundled = str(BUNDLED_DIR).lower()

    def consider(path: str, rel_parts):
        if not path.lower().endswith(EXTENSIONS) or not is_cab_path(rel_parts):
            return
        try:
            size = os.path.getsize(path)
        except OSError:
            return
        if size > 4_000_000 or size < 64:
            return
        info = audio_info(path)
        if info is None or not (0.002 < info["seconds"] <= 1.1) or info["channels"] > 2 or info["rate"] < 16000:
            return
        try:
            with open(path, "rb") as f:
                key = (size, zlib.crc32(f.read()))
        except OSError:
            return
        if key not in seen_content:
            seen_content.add(key)
            found.append(path)

    def walk(root: Path):
        stack = [(str(root), ())]
        while stack:
            if time.monotonic() > t_end or (cancel is not None and cancel()):
                return
            d, rel = stack.pop()
            if progress is not None:
                progress(d)
            try:
                with os.scandir(d) as it:
                    entries = list(it)
            except OSError:
                continue
            for e in entries:
                try:
                    if e.is_dir(follow_symlinks=False):
                        name = e.name.lower()
                        if len(rel) < max_depth and name not in _SKIP_DIRS and not name.startswith(".") \
                                and e.path.lower() != bundled:
                            stack.append((e.path, rel + (e.name,)))
                    elif e.is_file(follow_symlinks=False):
                        consider(e.path, rel + (e.name,))
                except OSError:
                    continue

    for r in roots:
        walk(r)
    found.sort(key=lambda p: (describe(p)[0].lower(), describe(p)[1].lower()))
    return found


def describe(path) -> tuple[str, str]:
    """(group, name) for menus: the bundled set is "Built-in"; others are named after their folders."""
    p = Path(path)
    try:
        if p.parent.resolve() == BUNDLED_DIR.resolve():
            return "Built-in", p.stem.replace("_", " ")
    except OSError:
        pass
    parent = p.parent.name
    try:
        stop = {Path.home().resolve(), *Path.home().resolve().parents}
    except OSError:
        stop = set()
    above = ""
    for a in list(p.parents)[1:]:
        if a in stop or not a.name or a.name.lower() in _SYSTEM:
            break
        if a.name.lower() not in _GENERIC:
            above = a.name
            break
    group = " · ".join(dict.fromkeys(x for x in (above, parent) if x))
    return group or "IR", p.stem
