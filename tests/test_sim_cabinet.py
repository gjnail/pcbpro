"""Cabinet IRs: WAV/FLAC reading, IR preparation, streaming convolution, finding IRs on disk, the picker widget."""
import hashlib
import struct
from pathlib import Path

import numpy as np
import pytest

from pcbpro.sim.cabinet import (BUNDLED_DIR, Convolver, apply_ir, audio_info, band_level, builtin_irs, describe,
                                find_irs, ir_response, is_cab_path, load_ir, prepare_ir, read_audio, resample)
from pcbpro.sim.flac import _crc16, flac_info, read_flac

RNG = np.random.default_rng(7)


def _ir(n=2000, rate=44100):
    """A cab-like IR: a few resonances under a fast decay."""
    t = np.arange(n) / rate
    h = sum(np.sin(2 * np.pi * f * t) * a for f, a in ((110, 0.6), (900, 1.0), (2600, 0.8), (4200, 0.4)))
    return h * np.exp(-t * 250) + RNG.normal(0, 0.01, n) * np.exp(-t * 400)


# --------------------------------------------------------------------------- WAV

def _wav(path, data, rate, tag=1, width=2, extensible=False):
    data = np.asarray(data, float).reshape(len(data), -1)
    ch = data.shape[1]
    if tag == 3:
        raw = data.astype("<f4" if width == 4 else "<f8").tobytes()
    elif width == 2:
        raw = np.round(data * 32767).astype("<i2").tobytes()
    elif width == 3:
        raw = np.round(data * 8388607).astype("<i4").view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    else:
        raw = np.round(data * 2147483647).astype("<i4").tobytes()
    align = ch * width
    fmt = struct.pack("<HHIIHH", 0xFFFE if extensible else tag, ch, rate, rate * align, align, width * 8)
    if extensible:
        fmt += struct.pack("<HHI", 22, width * 8, 0) + struct.pack("<H", tag) + bytes(14)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"LIST" + struct.pack("<I", 5) + b"abcde\x00"  # an odd-sized chunk before the samples
    body += b"data" + struct.pack("<I", len(raw)) + raw
    Path(path).write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)


@pytest.mark.parametrize("tag,width,ext,tol", [(1, 2, False, 1e-4), (1, 3, False, 1e-6), (1, 4, False, 1e-8),
                                               (3, 4, False, 1e-7), (3, 8, False, 1e-12), (1, 3, True, 1e-6),
                                               (3, 4, True, 1e-7)])
def test_wav_formats(tmp_path, tag, width, ext, tol):
    x = np.stack([_ir(500), -_ir(500)], axis=1) * 0.5
    p = tmp_path / "ir.wav"
    _wav(p, x, 48000, tag, width, ext)
    y, rate = read_audio(p)
    assert rate == 48000 and y.shape == x.shape
    assert np.max(np.abs(y - x)) < tol
    info = audio_info(p)
    assert info["channels"] == 2 and info["seconds"] == pytest.approx(500 / 48000)
    assert audio_info(tmp_path / "missing.wav") is None


def test_bundled_cabinets():
    paths = builtin_irs()
    assert [Path(p).name for p in paths] == ["1x12_open.wav", "2x12_closed.wav", "4x12_slant.wav",
                                             "4x12_straight.wav"]
    assert (BUNDLED_DIR / "README.txt").is_file()
    for p in paths:
        data, rate = read_audio(p)
        assert rate == 44100 and data.shape[1] == 2  # float stereo
        h = load_ir(p, 48000)
        assert np.all(np.isfinite(h)) and 200 < len(h) <= 24000
        assert band_level(h, 48000) == pytest.approx(1.0, rel=1e-6)
        assert describe(p)[0] == "Built-in"
    assert describe(paths[0])[1] == "1x12 open"


# --------------------------------------------------------------------------- FLAC

class _BW:
    def __init__(self):
        self.bits = []

    def u(self, v, n):
        self.bits.extend((int(v) >> (n - 1 - i)) & 1 for i in range(n))

    def i(self, v, n):
        self.u(int(v) & ((1 << n) - 1), n)

    def unary(self, q):
        self.bits.extend([0] * q + [1])

    def data(self):
        self.bits.extend([0] * (-len(self.bits) % 8))
        return np.packbits(np.array(self.bits, np.uint8)).tobytes()


def _residual(w, r, order, B, escape_second):
    porder = 1 if B % 2 == 0 else 0
    w.u(0, 2)
    w.u(porder, 4)
    idx = 0
    for p in range(1 << porder):
        n = (B >> porder) - (order if p == 0 else 0)
        seg = [int(v) for v in r[idx:idx + n]]
        idx += n
        if escape_second and p == 1:
            bits = max(1, max(abs(v) for v in seg).bit_length() + 1)
            w.u(15, 4)
            w.u(bits, 5)
            for v in seg:
                w.i(v, bits)
            continue
        k = min(14, max(0, int(np.log2(np.mean(np.abs(seg)) + 1)))) if seg else 0
        w.u(k, 4)
        for v in seg:
            u = 2 * v if v >= 0 else -2 * v - 1
            w.unary(u >> k)
            if k:
                w.u(u & ((1 << k) - 1), k)


def _subframe(w, x, bps, kind):
    x = [int(v) for v in x]
    w.u(0, 1)
    if all(v == x[0] for v in x):
        w.u(0, 6)
        w.u(0, 1)
        w.i(x[0], bps)
        return
    wasted = 2 if kind == "fixed" and all(v % 4 == 0 for v in x) else 0
    if kind == "verbatim":
        w.u(1, 6)
        w.u(0, 1)
        for v in x:
            w.i(v, bps)
        return
    if kind == "fixed":
        w.u(8 + 2, 6)
        w.u(1 if wasted else 0, 1)
        if wasted:
            w.unary(wasted - 1)
            x = [v >> wasted for v in x]
        for v in x[:2]:
            w.i(v, bps - wasted)
        r = [x[i] - (2 * x[i - 1] - x[i - 2]) for i in range(2, len(x))]
        _residual(w, r, 2, len(x), escape_second=False)
        return
    coefs, shift, prec = (115, -50), 6, 9  # LPC order 2
    w.u(32 + 1, 6)
    w.u(0, 1)
    for v in x[:2]:
        w.i(v, bps)
    w.u(prec - 1, 4)
    w.i(shift, 5)
    for c in coefs:
        w.i(c, prec)
    r = [x[i] - ((coefs[0] * x[i - 1] + coefs[1] * x[i - 2]) >> shift) for i in range(2, len(x))]
    _residual(w, r, 2, len(x), escape_second=True)


def _flac(path, samples, rate=44100, bps=16, block=1024):
    """A FLAC writer covering every channel mode and subframe type the decoder handles."""
    n, ch = samples.shape
    frames = b""
    modes = ["indep", "ms", "ls", "rs"]
    kinds = ["fixed", "lpc", "verbatim"]
    for fi, k in enumerate(range(0, n, block)):
        blk = samples[k:k + block].astype(np.int64)
        B = len(blk)
        w = _BW()
        w.u(0xFFF8, 16)
        w.u(6 if B <= 256 else 7, 4)
        w.u(9, 4)  # 44.1 kHz
        L, R = blk[:, 0], blk[:, -1]
        mode = modes[fi % 4] if ch == 2 else "indep"
        if mode == "indep":
            w.u(ch - 1, 4)
            chans, extra = [blk[:, c] for c in range(ch)], [0] * ch
        elif mode == "ls":
            w.u(8, 4)
            chans, extra = [L, L - R], [0, 1]
        elif mode == "rs":
            w.u(9, 4)
            chans, extra = [L - R, R], [1, 0]
        else:
            w.u(10, 4)
            chans, extra = [(L + R) >> 1, L - R], [0, 1]
        w.u({16: 4, 24: 6}[bps], 3)
        w.u(0, 1)
        w.u(fi, 8)
        w.u(B - 1, 8 if B <= 256 else 16)
        w.u(0, 8)  # header CRC-8 (covered by the frame CRC-16, which the decoder checks)
        for c, (x, e) in enumerate(zip(chans, extra)):
            _subframe(w, x, bps + e, kinds[(fi + c) % 3])
        data = w.data()
        frames += data + _crc16(data).to_bytes(2, "big")
    raw = samples.astype("<i2").tobytes() if bps == 16 else         samples.astype("<i4").view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    md5 = hashlib.md5(raw).digest()
    si = _BW()
    for v, nb in ((block, 16), (block, 16), (0, 24), (0, 24), (rate, 20), (ch - 1, 3), (bps - 1, 5), (n, 36)):
        si.u(v, nb)
    Path(path).write_bytes(b"fLaC" + bytes([0x80]) + (34).to_bytes(3, "big") + si.data() + md5 + frames)


def _stereo_ints(scale=20000):
    h = _ir(4096)
    L = np.round(h / np.max(np.abs(h)) * scale).astype(np.int64)
    R = np.round(0.7 * L + RNG.normal(0, 30, len(L))).astype(np.int64)
    x = np.stack([L, R], axis=1)
    x[3072:4096] = (x[3072:4096] // 4) * 4  # a frame whose samples have two wasted bits
    return np.concatenate([x, np.zeros((200, 2), np.int64)])  # silent tail: constant subframes, 8-bit block size


@pytest.mark.parametrize("bps", [16, 24])
def test_flac_decoder(tmp_path, bps):
    x = _stereo_ints(20000 if bps == 16 else 20000 * 256)
    p = tmp_path / "cab.flac"
    _flac(p, x, bps=bps)
    info = flac_info(p)
    assert (info["rate"], info["channels"], info["bps"], info["samples"]) == (44100, 2, bps, len(x))
    y, rate, b = read_flac(p, verify=True)
    assert rate == 44100 and b == bps
    assert np.array_equal(y, x)
    head, _, _ = read_flac(p, max_samples=1500)
    assert np.array_equal(head, x[:1500])
    f, rate = read_audio(p)
    assert np.allclose(f, x / float(1 << (bps - 1)))
    assert audio_info(p)["seconds"] == pytest.approx(len(x) / 44100)
    bad = bytearray(p.read_bytes())
    bad[-40] ^= 0x10
    (tmp_path / "bad.flac").write_bytes(bytes(bad))
    with pytest.raises(ValueError):
        read_flac(tmp_path / "bad.flac")


MELDA = Path(r"C:\ProgramData\MeldaProduction\MeldaProduction IR\Box")


@pytest.mark.skipif(not (MELDA / "G12M70.flac").is_file(), reason="MeldaProduction IRs not installed")
def test_flac_decoder_on_real_files():
    for name in ("G12M70.flac", "Box 4x12/1m A.flac"):
        y, rate, bps = read_flac(MELDA / name, verify=True)  # bit-exact against the file's MD5 signature
        assert len(y) == flac_info(MELDA / name)["samples"]


# --------------------------------------------------------------------------- preparing and convolving

def test_prepare_ir_resamples_trims_and_levels():
    h = np.concatenate([np.zeros(300), _ir(3000)])  # leading silence
    a = prepare_ir(h, 44100, 44100)
    b = prepare_ir(h, 44100, 48000)
    c = prepare_ir(np.stack([h, h], axis=1), 44100, 96000)
    for out, rate in ((a, 44100), (b, 48000), (c, 96000)):
        assert band_level(out, rate) == pytest.approx(1.0)
        assert np.argmax(np.abs(out)) < 0.004 * rate  # the delay is gone
    f = np.geomspace(100, 4000, 30)
    ra, rb = np.abs(ir_response(a, 44100, f)), np.abs(ir_response(b, 48000, f))
    assert np.max(np.abs(20 * np.log10(rb / ra))) < 0.5  # the same cabinet at another rate
    assert len(resample(np.ones(441), 44100, 48000)) == 480
    long = prepare_ir(RNG.normal(0, 1, 44100) * np.exp(-np.arange(44100) / 20000), 44100, 48000, max_seconds=0.25)
    assert len(long) <= 12000
    with pytest.raises(ValueError):
        prepare_ir(np.zeros(100), 48000, 48000)


@pytest.mark.parametrize("block,n_ir", [(32, 1000), (128, 128), (100, 5000), (64, 1)])
def test_convolver_matches_direct_convolution(block, n_ir):
    h = RNG.normal(0, 1, n_ir)
    x = RNG.normal(0, 1, block * 40)
    conv = Convolver(h, block)
    y = np.concatenate([conv.process(x[k:k + block]) for k in range(0, len(x), block)])
    ref = np.convolve(x, h)[:len(x)]
    assert np.max(np.abs(y - ref)) < 1e-9 * max(1.0, np.max(np.abs(ref)))
    conv.reset()
    y2 = conv.process(x[:block * 4])  # several blocks at once
    assert np.allclose(y2, ref[:block * 4])
    assert np.allclose(apply_ir(x, h), ref)


def test_convolver_handles_a_new_block_size():
    h = RNG.normal(0, 1, 300)
    conv = Convolver(h, 128)
    x = RNG.normal(0, 1, 96)
    assert np.allclose(conv.process(x), np.convolve(x, h)[:96])  # re-partitioned for 96-sample blocks
    assert conv.B == 96 and len(conv.process(np.zeros(0))) == 0


# --------------------------------------------------------------------------- finding IRs

@pytest.mark.parametrize("parts,ok", [
    (("iZotope", "Trash 2", "Impulses", "Amps", "Allston 2x12-dynamic.wav"), True),
    (("MeldaProduction", "MeldaProduction IR", "Box", "G12M70.flac"), True),
    (("MeldaProduction", "MeldaProduction IR", "Box", "Guitar Cabinet 01.wav"), True),
    (("MeldaProduction", "MeldaProduction IR", "Box", "Guitar body.flac"), False),
    (("MeldaProduction", "MeldaProduction IR", "Hall", "Hall 1.flac"), False),
    (("MeldaProduction", "MeldaProduction IR", "Microphone", "Sennheiser e609", "Direct.flac"), False),
    (("Downloads", "Some Cabs", "Deluxe", "SM57 cap edge.wav"), True),
    (("Neural DSP", "Impulses", "Guitar", "Mesa.wav"), True),
    (("Kilohearts", "Impulse Responses", "Cabinets Guitar", "Sweet.flac"), True),
    (("Music", "Samples", "Kick 01.wav"), False),
    (("Reverbs", "Plate", "4x12 plate.wav"), False),
])
def test_cab_path_heuristic(parts, ok):
    assert is_cab_path(parts) is ok


def test_find_irs(tmp_path):
    h = _ir(2000)[:, None] * 0.5

    def put(rel, data=h, rate=44100):
        p = tmp_path.joinpath(*rel.split("/"))
        p.parent.mkdir(parents=True, exist_ok=True)
        _wav(p, data, rate)
        return str(p)

    good = [put("iZotope/Trash 2/Impulses/Amps/Allston 2x12-dynamic.wav"),
            put("My IRs/Mesa 4x12 V30 SM57.wav", h * 0.9)]
    (tmp_path / "Guitar IRs").mkdir()
    _flac(tmp_path / "Guitar IRs" / "Greenback.flac", np.round(np.repeat(h, 2, axis=1) * 30000).astype(np.int64))
    good.append(str(tmp_path / "Guitar IRs" / "Greenback.flac"))
    put("Copies/Cabs/Allston 2x12-dynamic.wav")  # the same file again: listed once
    put("Reverbs/Hall/Big Hall.wav")
    put("Cabs/long cab.wav", np.tile(h, (60, 1)))  # 2.7 s: not a cabinet
    put("Downloads/random.wav")
    put("dist/Cabs/skipped.wav", h * 0.3)
    (tmp_path / "Cabs" / "broken.wav").write_bytes(b"RIFF junk")
    seen = []
    found = find_irs([tmp_path], progress=seen.append)
    assert sorted(Path(f).name for f in found) == sorted(Path(g).name for g in good)  # duplicate listed once
    assert seen and all("dist" not in Path(d).parts for d in seen)
    assert describe(good[0]) == ("Trash 2 · Amps", "Allston 2x12-dynamic")
    assert describe(good[1])[0].endswith("My IRs")
    assert describe(Path.home() / "Documents" / "My IRs" / "a.wav") == ("My IRs", "a")
    assert describe(Path.home() / "Documents" / "IRs" / "a.wav") == ("IRs", "a")
    assert find_irs([tmp_path], cancel=lambda: True) == []


# --------------------------------------------------------------------------- picker widget

@pytest.fixture
def cab_settings(tmp_path, monkeypatch, qapp):
    """An isolated settings file, and a fast fake search over a few files."""
    from PySide6.QtCore import QSettings

    from pcbpro.ui import cab_ui
    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(cab_ui, "settings", lambda: QSettings(ini, QSettings.IniFormat))
    found = []
    for i, name in enumerate(("Amps/Allston 2x12.wav", "Amps/Boxboro 4x12.wav", "Box 4x12/1m.wav")):
        p = tmp_path / "Trash 2" / "Impulses" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        _wav(p, _ir(800 + 100 * i)[:, None] * 0.5, 44100)
        found.append(str(p))
    monkeypatch.setattr(cab_ui, "find_irs", lambda *a, **k: list(found))
    return cab_ui, found


def _wait_search(cab_ui, qapp):
    import time
    t = time.time()
    while cab_ui.searching() and time.time() - t < 5:
        time.sleep(0.01)
    qapp.processEvents()


def test_cabinet_picker(cab_settings, qapp, tmp_path):
    cab_ui, found = cab_settings
    pick = cab_ui.CabinetPicker()
    _wait_search(cab_ui, qapp)
    pick._poll()
    assert pick.count() == 4 + len(found)
    assert pick.path() is None and "3 cabinet IRs found" in pick.note.text()
    got = []
    pick.changed.connect(got.append)
    pick.set_path(found[1])
    assert got == [found[1]] and pick.path() == found[1]
    again = cab_ui.CabinetPicker(auto_search=True)  # the choice and the search result are remembered
    assert again.path() == found[1] and again.count() == pick.count() and not cab_ui.searching()
    extra = tmp_path / "mine.wav"
    _wav(extra, _ir(600)[:, None] * 0.5, 48000)
    assert again.add_file(str(extra)) and again.path() == str(extra)
    assert again.combo.itemText(again.combo.currentIndex()) == "mine"
    pick.set_path(None)
    assert pick.path() is None and got[-1] is None


def test_audio_dialog_cabinet(cab_settings, qapp):
    from pcbpro.ui import pedal_ui
    from pcbpro.ui.audio_ui import AudioDialog
    from pcbpro.ui.main_window import MainWindow
    cab_ui, found = cab_settings
    w = MainWindow()
    pedal_ui.open_pedal_example(w)
    dlg = AudioDialog(w, w)
    _wait_search(cab_ui, qapp)
    dlg._update_bode()
    assert len(dlg.bode.curves) == 1
    dlg.cab.set_path(builtin_irs()[2])
    dlg._update_bode()
    assert [c[0] for c in dlg.bode.curves] == ["output / guitar", "with the cabinet"]
    dlg.dry = np.sin(np.arange(4800) * 0.1)
    dlg.wet = np.tanh(3 * dlg.dry)
    dlg.rate = 48000
    out = dlg._out(dlg.wet)
    assert len(out) == len(dlg.wet) and not np.allclose(out, dlg.wet)
    dlg._show_waves()
    assert dlg.wave.suffix == " + cabinet"
    dlg.cab.set_path(None)
    assert dlg._out(dlg.wet) is dlg.wet
    dlg.close()
    w.doc.dirty = False
    w.close()
