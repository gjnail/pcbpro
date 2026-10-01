"""Shared helpers for footprint generators: 3D composite primitives and common land patterns."""
from __future__ import annotations

from ..model.board import Footprint, Graphic, Pad
from ..model.footprints import _arc, _circle, _fp, _line, _rect  # noqa: F401 - re-exported

VERIFY = " Verify against the manufacturer datasheet before ordering."


def r4(v: float) -> float:
    return round(float(v), 4)


# --------------------------------------------------------------------------- 3D composite primitives

def B(x0, y0, z0, x1, y1, z1, c="#1e1e20", m=False, **kw) -> dict:
    return {"s": "box", "p": [r4(x0), r4(y0), r4(z0), r4(x1), r4(y1), r4(z1)], "c": c, "m": int(m), **kw}


def CYL(cx, cy, z0, z1, r, c="#1e1e20", m=False, **kw) -> dict:
    return {"s": "cyl", "p": [r4(cx), r4(cy), r4(z0), r4(z1), r4(r)], "c": c, "m": int(m), **kw}


def CYLX(x0, x1, cy, cz, r, c="#1e1e20", m=False, **kw) -> dict:
    return {"s": "cylx", "p": [r4(x0), r4(x1), r4(cy), r4(cz), r4(r)], "c": c, "m": int(m), **kw}


def CYLY(y0, y1, cx, cz, r, c="#1e1e20", m=False, **kw) -> dict:
    return {"s": "cyly", "p": [r4(y0), r4(y1), r4(cx), r4(cz), r4(r)], "c": c, "m": int(m), **kw}


def DOME(cx, cy, z0, r, c="#1e1e20", m=False, **kw) -> dict:
    return {"s": "dome", "p": [r4(cx), r4(cy), r4(z0), r4(r)], "c": c, "m": int(m), **kw}


def PRISM(pts, z0, z1, c="#1e1e20", m=False, **kw) -> dict:
    return {"s": "prism", "pts": [(r4(x), r4(y)) for x, y in pts], "p": [r4(z0), r4(z1)], "c": c, "m": int(m), **kw}


def composite(*parts, pins=None, leads=None, **kw) -> dict:
    m = {"type": "composite", "parts": [p for p in parts if p]}
    if pins:
        m["pins"] = pins
    if leads:
        m["leads"] = [r4(leads[0]), r4(leads[1])]
    m.update(kw)
    return m


METAL = "#c9ccd2"
GOLD = "#dcb04a"
BLACK = "#161618"
DARK = "#0c0c0d"


# --------------------------------------------------------------------------- land patterns

def two_terminal_smd(name, desc, pw, ph, cx, body_l, body_w, model, polarity=False, silk=True) -> Footprint:
    pads = [Pad("1", -cx, 0, pw, ph, "roundrect"), Pad("2", cx, 0, pw, ph, "roundrect")]
    g: list[Graphic] = []
    if silk:
        gap = cx - pw / 2 - 0.2
        yy = max(body_w / 2, ph / 2) + 0.15
        if gap > 0.15:
            g += [_line(-gap, -yy, gap, -yy), _line(-gap, yy, gap, yy)]
        else:
            ext = cx + pw / 2 + 0.2
            g += [_line(-ext, -yy, ext, -yy), _line(-ext, yy, ext, yy)]
    if polarity:
        x = -(cx + pw / 2 + 0.25)
        g.append(_line(x, -ph / 2, x, ph / 2, 0.15))
    g += _rect(-body_l / 2, -body_w / 2, body_l / 2, body_w / 2, 0.1, "fab")
    return _fp(name, desc, pads, g, (-body_l / 2, -body_w / 2, body_l / 2, body_w / 2), model)


def inline_tht(n: int, pitch: float, pad: float, drill: float, first_square=True, shape="circle",
               pad_h: float | None = None, y: float = 0.0) -> list[Pad]:
    x0 = -(n - 1) * pitch / 2
    out = []
    for i in range(n):
        sh = "rect" if (i == 0 and first_square) else shape
        out.append(Pad(str(i + 1), r4(x0 + i * pitch), y, pad, pad_h or pad, sh, "tht", drill))
    return out


def grid_tht(cols: int, rows: int, pitch: float, pad: float, drill: float, row_pitch: float | None = None,
             first_square=True, shape="circle") -> list[Pad]:
    """IDC / 2xN header numbering: pin 1 bottom-left, pin 2 directly above it, pin 3 right of pin 1 ...

    (Identical to the KiCad / connector-datasheet convention with the long axis turned horizontal.)
    """
    rp = row_pitch or pitch
    x0 = -(cols - 1) * pitch / 2
    y0 = -(rows - 1) * rp / 2
    out = []
    n = 1
    for c in range(cols):
        for r in range(rows):
            sh = "rect" if (n == 1 and first_square) else shape
            out.append(Pad(str(n), r4(x0 + c * pitch), r4(y0 + (rows - 1 - r) * rp), pad, pad, sh, "tht", drill))
            n += 1
    return out


def row_major_tht(cols: int, rows: int, pitch: float, row_pitch: float, pw: float, ph: float, drill: float,
                  shape="circle") -> list[Pad]:
    """Molex Micro-Fit / Mini-Fit style numbering: 1..n along the first row, n+1..2n along the next."""
    x0 = -(cols - 1) * pitch / 2
    y0 = -(rows - 1) * row_pitch / 2
    out = []
    for r in range(rows):
        for c in range(cols):
            n = r * cols + c + 1
            out.append(Pad(str(n), r4(x0 + c * pitch), r4(y0 + r * row_pitch), pw, ph,
                           "roundrect" if n == 1 else shape, "tht", drill))
    return out


def dual_row_numbering(n: int, pitch: float, row: float, pw: float, ph: float, shape="roundrect",
                       kind="smd", drill=0.0) -> list[Pad]:
    """DIP-style counter-clockwise numbering: 1..n/2 down the left side, then up the right side."""
    half = n // 2
    pads = []
    for i in range(half):
        pads.append(Pad(str(i + 1), -row, r4((i - (half - 1) / 2) * pitch), pw, ph, shape, kind, drill))
    for i in range(half):
        pads.append(Pad(str(half + i + 1), row, r4(((half - 1) / 2 - i) * pitch), pw, ph, shape, kind, drill))
    return pads
