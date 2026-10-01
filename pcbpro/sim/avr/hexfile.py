"""Intel HEX reader for AVR firmware images (as exported by the Arduino IDE or avr-objcopy)."""
from __future__ import annotations


class HexError(ValueError):
    pass


def parse_hex(text: str, size: int = 256 * 1024) -> bytearray:
    """Return the flash image (unprogrammed bytes are 0xFF)."""
    mem = bytearray(b"\xff" * size)
    base = 0
    top = 0
    seen = False
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if not line.startswith(":"):
            raise HexError(f"line {lineno}: not an Intel HEX record")
        try:
            data = bytes.fromhex(line[1:])
        except ValueError:
            raise HexError(f"line {lineno}: bad hex digits") from None
        if len(data) < 5 or len(data) != data[0] + 5:
            raise HexError(f"line {lineno}: wrong record length")
        if sum(data) & 0xFF:
            raise HexError(f"line {lineno}: checksum mismatch")
        n, addr, kind = data[0], (data[1] << 8) | data[2], data[3]
        payload = data[4:4 + n]
        if kind == 0:
            a = base + addr
            if a + n > size:
                raise HexError(f"line {lineno}: address 0x{a:x} beyond the flash")
            mem[a:a + n] = payload
            top = max(top, a + n)
            seen = True
        elif kind == 1:
            break
        elif kind == 2:
            base = ((payload[0] << 8) | payload[1]) << 4
        elif kind == 4:
            base = ((payload[0] << 8) | payload[1]) << 16
        elif kind in (3, 5):
            pass
        else:
            raise HexError(f"line {lineno}: unknown record type {kind}")
    if not seen:
        raise HexError("no data records")
    return mem[:max(top, 2)]


def to_hex(image: bytes, start: int = 0) -> str:
    """Write an image as Intel HEX (used by tests and examples)."""
    lines = []
    for off in range(0, len(image), 16):
        chunk = image[off:off + 16]
        a = start + off
        rec = bytes([len(chunk), (a >> 8) & 0xFF, a & 0xFF, 0]) + chunk
        lines.append(":" + (rec + bytes([(-sum(rec)) & 0xFF])).hex().upper())
    lines.append(":00000001FF")
    return "\n".join(lines) + "\n"
