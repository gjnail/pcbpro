"""Engineering values: parse '4k7', '100nF', '2R2', 'B500K', '16MHz', '3V3' and format them back."""
from __future__ import annotations

import math
import re

PREFIX = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3,
          "M": 1e6, "G": 1e9, "R": 1.0, "r": 1.0, "E": 1.0}

# number, optional prefix (or R / E as the decimal point), optional digits after the prefix: 4k7, 2R2, 1M5, 100n
_NUM = re.compile(r"(\d+(?:[.,]\d+)?|[.,]\d+)\s*(meg|[fpnuµμmkKMGRrE])?(\d*)")


def parse_value(text: str | None, default: float | None = None) -> float | None:
    """First engineering number in ``text`` ('4k7' -> 4700, '100nF' -> 1e-7, '1meg' -> 1e6)."""
    if not text:
        return default
    s = str(text).strip().replace("Ω", "").replace("ohm", "").replace("Ohm", "")
    m = _NUM.search(s)
    if not m:
        return default
    num, pre, tail = m.group(1).replace(",", "."), m.group(2) or "", m.group(3)
    scale = 1e6 if pre == "meg" else PREFIX.get(pre, 1.0)
    if pre and tail and "." not in num:
        num = f"{num}.{tail}"  # 4k7 style: the prefix is the decimal point
    try:
        return float(num) * scale
    except ValueError:
        return default


def parse_voltage(text: str | None, default: float | None = None) -> float | None:
    """A voltage in a name or value: '9V', '+5V', '3V3', '3.3V', 'BZX84C3V3' (3.3), '5V1' (5.1), 'VCC_12V'."""
    if not text:
        return default
    s = str(text).upper()
    m = re.search(r"(\d+)V(\d+)", s)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = re.search(r"(\d+(?:\.\d+)?)\s*V(?![A-Z])", s)
    if m:
        return float(m.group(1))
    return default


def parse_pot(text: str | None, default_ohms: float = 10e3) -> tuple[str, float]:
    """Pot value and taper: 'B500K' -> ('B', 500e3), 'A100K' -> ('A', 1e5), '10k' -> ('B', 1e4)."""
    s = (text or "").strip()
    taper = "B"
    m = re.match(r"^\s*([ABCW])\s*(?=\d)", s, re.I)
    if m:
        taper = m.group(1).upper()
    else:
        m = re.search(r"\d\s*[kKmM]?\s*([ABC])\s*$", s)
        if m:
            taper = m.group(1).upper()
        elif re.search(r"\blog\b", s, re.I):
            taper = "A"
    if taper == "W":
        taper = "B"
    return taper, parse_value(s, default_ohms) or default_ohms


def parse_frequency(text: str | None, default: float | None = None) -> float | None:
    v = parse_value(text, None)
    if v is None:
        return default
    return v


def fmt_eng(v: float, unit: str = "", digits: int = 3) -> str:
    """4700 -> '4.7 k', with ``unit`` appended ('4.7 kΩ')."""
    if v is None or not math.isfinite(v):
        return "—"
    if v == 0:
        return f"0 {unit}".rstrip()
    a = abs(v)
    for scale, p in ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1.0, ""), (1e-3, "m"), (1e-6, "µ"), (1e-9, "n"),
                     (1e-12, "p")):
        if a >= scale * 0.9995:
            n = v / scale
            text = f"{n:.{digits}g}"
            if "e" in text:  # 100 with 2 digits: '1e+02' -> '100'
                text = f"{n:.0f}"
            return f"{text} {p}{unit}".rstrip()
    return f"{v:.{digits}g} {unit}".rstrip()
