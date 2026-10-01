"""A small pure-Python FLAC decoder for impulse responses.

Cabinet IRs are short (well under a second), so a straightforward bit-string decoder is fast enough and saves a
native dependency. Every frame's CRC-16 is checked, and ``verify=True`` also checks the stream's MD5 signature.
"""
from __future__ import annotations

import hashlib

import numpy as np

_BLOCK_SIZES = {1: 192, 2: 576, 3: 1152, 4: 2304, 5: 4608}
_SAMPLE_SIZES = {1: 8, 2: 12, 4: 16, 5: 20, 6: 24, 7: 32}
_RATES = {1: 88200, 2: 176400, 3: 192000, 4: 8000, 5: 16000, 6: 22050, 7: 24000, 8: 32000, 9: 44100, 10: 48000,
          11: 96000}
_FIXED = {0: (), 1: (1,), 2: (2, -1), 3: (3, -3, 1), 4: (4, -6, 4, -1)}


def _crc16_table():
    t = []
    for i in range(256):
        c = i << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x8005) if c & 0x8000 else (c << 1)
        t.append(c & 0xFFFF)
    return t


_CRC16 = _crc16_table()


def _crc16(data: bytes) -> int:
    c = 0
    t = _CRC16
    for b in data:
        c = ((c << 8) & 0xFFFF) ^ t[(c >> 8) ^ b]
    return c


def _start(data: bytes) -> int:
    """Offset of the "fLaC" marker, skipping an ID3v2 tag."""
    pos = 0
    if data[:3] == b"ID3" and len(data) >= 10:
        size = (data[6] & 0x7F) << 21 | (data[7] & 0x7F) << 14 | (data[8] & 0x7F) << 7 | (data[9] & 0x7F)
        pos = 10 + size
    if data[pos:pos + 4] != b"fLaC":
        raise ValueError("not a FLAC file")
    return pos + 4


def _metadata(data: bytes, pos: int) -> tuple[dict, int]:
    info = None
    while True:
        if pos + 4 > len(data):
            raise ValueError("truncated FLAC metadata")
        hdr = data[pos]
        length = int.from_bytes(data[pos + 1:pos + 4], "big")
        body = data[pos + 4:pos + 4 + length]
        if hdr & 0x7F == 0:  # STREAMINFO
            v = int.from_bytes(body[10:18], "big")
            info = {"rate": v >> 44, "channels": ((v >> 41) & 7) + 1, "bps": ((v >> 36) & 31) + 1,
                    "samples": v & ((1 << 36) - 1), "md5": bytes(body[18:34]),
                    "max_block": int.from_bytes(body[2:4], "big")}
        pos += 4 + length
        if hdr & 0x80:
            break
    if info is None:
        raise ValueError("FLAC file has no STREAMINFO")
    return info, pos


def flac_info(path) -> dict:
    """Stream parameters from the header only: rate, channels, bps, samples (per channel), md5."""
    with open(path, "rb") as f:
        head = f.read(65536)
    info, _ = _metadata(head, _start(head))
    return info


class _Bits:
    __slots__ = ("s", "p")

    def __init__(self, data: bytes):
        self.s = bin(int.from_bytes(b"\x01" + data, "big"))[3:]  # leading 1 keeps the zeros
        self.p = 0

    def u(self, n: int) -> int:
        if n == 0:
            return 0
        p = self.p
        self.p = p + n
        return int(self.s[p:p + n], 2)

    def i(self, n: int) -> int:
        v = self.u(n)
        return v - (1 << n) if n and v >> (n - 1) else v

    def unary(self) -> int:
        q = self.s.find("1", self.p)
        if q < 0:
            raise ValueError("truncated FLAC frame")
        n = q - self.p
        self.p = q + 1
        return n

    def align(self):
        self.p = (self.p + 7) & ~7


def _utf8_number(b: _Bits) -> int:
    x = b.u(8)
    if x < 0x80:
        return x
    n = 0
    while x & (0x80 >> n):
        n += 1
    v = x & (0xFF >> (n + 1))
    for _ in range(n - 1):
        v = (v << 6) | (b.u(8) & 0x3F)
    return v


def _residual(b: _Bits, block: int, order: int) -> list[int]:
    method = b.u(2)
    if method > 1:
        raise ValueError("unsupported FLAC residual coding")
    pbits, escape = (4, 15) if method == 0 else (5, 31)
    porder = b.u(4)
    parts = 1 << porder
    out: list[int] = []
    s = b.s
    for k in range(parts):
        n = (block >> porder) - (order if k == 0 else 0)
        param = b.u(pbits)
        if param == escape:
            raw = b.u(5)
            out.extend(b.i(raw) for _ in range(n))
            continue
        p = b.p
        find = s.find
        for _ in range(n):
            q = find("1", p)
            if q < 0:
                raise ValueError("truncated FLAC frame")
            if param:
                u = ((q - p) << param) | int(s[q + 1:q + 1 + param], 2)
                p = q + 1 + param
            else:
                u = q - p
                p = q + 1
            out.append((u >> 1) ^ -(u & 1))
        b.p = p
    return out


def _predict(warm: list[int], coefs, shift: int, res: list[int]) -> list[int]:
    out = list(warm)
    order = len(coefs)
    if order == 0:
        out.extend(res)
        return out
    rc = list(reversed(coefs))  # oldest first, to line up with out[i - order:i]
    i = order
    for r in res:
        acc = sum(c * x for c, x in zip(rc, out[i - order:i]))
        out.append(r + (acc >> shift))
        i += 1
    return out


def _subframe(b: _Bits, block: int, bps: int) -> list[int]:
    if b.u(1):
        raise ValueError("bad FLAC subframe padding")
    kind = b.u(6)
    wasted = 0
    if b.u(1):
        wasted = b.unary() + 1
        bps -= wasted
    if kind == 0:
        v = b.i(bps)
        out = [v] * block
    elif kind == 1:
        out = [b.i(bps) for _ in range(block)]
    elif 8 <= kind <= 12:
        order = kind - 8
        warm = [b.i(bps) for _ in range(order)]
        out = _predict(warm, _FIXED[order], 0, _residual(b, block, order))
    elif kind >= 32:
        order = kind - 31
        warm = [b.i(bps) for _ in range(order)]
        prec = b.u(4) + 1
        if prec == 16:
            raise ValueError("bad FLAC LPC precision")
        shift = b.i(5)
        coefs = [b.i(prec) for _ in range(order)]
        if shift < 0:
            raise ValueError("negative FLAC LPC shift")
        out = _predict(warm, coefs, shift, _residual(b, block, order))
    else:
        raise ValueError("reserved FLAC subframe type")
    if wasted:
        out = [v << wasted for v in out]
    return out


def _le_bytes(a: np.ndarray, width: int) -> bytes:
    """Interleaved samples as little-endian signed integers (the layout the MD5 signature is computed over)."""
    if width in (1, 2, 4):
        return a.astype({1: "i1", 2: "<i2", 4: "<i4"}[width]).tobytes()
    return (a & 0xFFFFFF).astype("<u4").view(np.uint8).reshape(-1, 4)[:, :3].tobytes()


def read_flac(path, max_samples: int | None = None, verify: bool = False) -> tuple[np.ndarray, int, int]:
    """Decode to an int64 array (samples, channels), the sample rate and the bits per sample.

    ``max_samples`` stops after that many samples per channel (an IR only needs its first part)."""
    with open(path, "rb") as f:
        data = f.read()
    info, pos = _metadata(data, _start(data))
    rate, nch, bps = info["rate"], info["channels"], info["bps"]
    chunks = []
    total = 0
    md5 = hashlib.md5()
    n_data = len(data)
    while pos + 2 <= n_data and (max_samples is None or total < max_samples):
        if data[pos] != 0xFF or (data[pos + 1] & 0xFE) != 0xF8:
            nxt = data.find(b"\xff", pos + 1)  # resynchronise (trailing tags, garbage)
            while nxt >= 0 and (nxt + 1 >= n_data or (data[nxt + 1] & 0xFE) != 0xF8):
                nxt = data.find(b"\xff", nxt + 1)
            if nxt < 0:
                break
            pos = nxt
        end_guess = min(n_data, pos + max(1 << 16, info["max_block"] * nch * 8 + 1024))
        b = _Bits(data[pos:end_guess])
        b.u(16)  # sync + reserved + blocking strategy
        bs_code, sr_code = b.u(4), b.u(4)
        ch_code, ss_code = b.u(4), b.u(3)
        b.u(1)
        _utf8_number(b)
        if bs_code == 6:
            block = b.u(8) + 1
        elif bs_code == 7:
            block = b.u(16) + 1
        elif bs_code >= 8:
            block = 256 << (bs_code - 8)
        elif bs_code in _BLOCK_SIZES:
            block = _BLOCK_SIZES[bs_code]
        else:
            raise ValueError("reserved FLAC block size")
        if sr_code == 12:
            b.u(8)
        elif sr_code in (13, 14):
            b.u(16)
        fbps = _SAMPLE_SIZES.get(ss_code, bps) if ss_code else bps
        b.u(8)  # header CRC-8 (the frame CRC-16 below covers it too)
        n_ch = ch_code + 1 if ch_code < 8 else 2
        chans = []
        for c in range(n_ch):
            extra = 1 if (ch_code == 8 and c == 1) or (ch_code == 9 and c == 0) or (ch_code == 10 and c == 1) else 0
            chans.append(_subframe(b, block, fbps + extra))
        b.align()
        flen = b.p // 8
        crc = int.from_bytes(data[pos + flen:pos + flen + 2], "big")
        if _crc16(data[pos:pos + flen]) != crc:
            raise ValueError("corrupt FLAC frame (CRC mismatch)")
        a = np.array(chans, dtype=np.int64).T
        if ch_code == 8:  # left / side
            a[:, 1] = a[:, 0] - a[:, 1]
        elif ch_code == 9:  # side / right
            a[:, 0] = a[:, 0] + a[:, 1]
        elif ch_code == 10:  # mid / side
            mid = (a[:, 0] << 1) | (a[:, 1] & 1)
            side = a[:, 1].copy()
            a[:, 0] = (mid + side) >> 1
            a[:, 1] = (mid - side) >> 1
        chunks.append(a)
        if verify:
            md5.update(_le_bytes(a.reshape(-1), (bps + 7) // 8))
        total += block
        pos += flen + 2
    out = np.concatenate(chunks) if chunks else np.zeros((0, nch), np.int64)
    if verify and info["md5"] != bytes(16) and md5.digest() != info["md5"]:
        raise ValueError("FLAC audio does not match its MD5 signature")
    if max_samples is not None:
        out = out[:max_samples]
    return out, rate, bps
