"""Semiconductor & IC packages: SOT/SOD, SOIC/SSOP/TSSOP/MSOP, QFP, QFN/DFN, BGA, PLCC, DIP, SIP, TO-xxx."""
from __future__ import annotations

import string

from ..model.board import Footprint, Pad
from ..model.footprints import dip as _dip300, qfn as _qfn, sod, sot23, sot223
from .shapes import (B, BLACK, CYL, DARK, METAL, PRISM, VERIFY, _circle, _fp, _line, _rect, composite,
                     dual_row_numbering, inline_tht, r4)


# --------------------------------------------------------------------------- gull-wing generators

def gullwing_dual(name: str, desc: str, n: int, pitch: float, E: float, L: float, b: float, bw: float, bl: float,
                  H: float, ep: tuple | None = None) -> Footprint:
    """Dual-row gull-wing land pattern from package dimensions (IPC-7351 nominal-ish).

    E = lead span tip-to-tip, L = foot length, b = lead width, bw x bl = body.
    """
    fine = pitch < 0.8
    toe, heel = (0.45, 0.55) if fine else (0.45, 0.6)
    outer = E / 2 + toe
    inner = E / 2 - L - heel
    pl = r4(outer - inner)
    cx = r4((outer + inner) / 2)
    pw = r4(min(b + (0.15 if not fine else 0.12), pitch - 0.2))
    pads = dual_row_numbering(n, pitch, cx, pl, pw)
    if ep:
        pads.append(Pad(str(n + 1), 0, 0, ep[0], ep[1], "rect"))
    top = bl / 2 + 0.1
    g = [_line(-bw / 2, -top, bw / 2, -top), _line(-bw / 2, top, bw / 2, top),
         _line(-inner - 0.05, -top, -inner - 0.05, pads[0].y - pw / 2 - 0.1)]
    g += _rect(-bw / 2, -bl / 2, bw / 2, bl / 2, 0.1, "fab")
    model = {"type": "gullwing", "bw": bw, "bh": bl, "H": H, "body": "#1e1e1e", "standoff": 0.1, "pin1": True}
    return _fp(name, desc, pads, g, (-bw / 2, -bl / 2, bw / 2, bl / 2), model)


DUAL_FAMILIES = {
    # family: (pitch, E, L, b, body_w, H, {pins: body_len})
    "SOIC": (1.27, 6.0, 0.835, 0.42, 3.9, 1.5, {8: 4.9, 14: 8.65, 16: 9.9}),
    "SOIC-W": (1.27, 10.3, 0.835, 0.42, 7.5, 2.4, {8: 5.9, 14: 9.0, 16: 10.3, 18: 11.55, 20: 12.8, 24: 15.4, 28: 17.9}),
    "SOIC-5.3": (1.27, 7.9, 0.7, 0.42, 5.3, 1.9, {8: 5.3}),
    "SSOP": (0.65, 7.8, 0.75, 0.3, 5.3, 1.8, {8: 3.2, 14: 6.2, 16: 6.2, 18: 7.2, 20: 7.2, 24: 8.2, 28: 10.2, 30: 10.2}),
    "QSOP": (0.635, 6.0, 0.64, 0.25, 3.9, 1.5, {16: 4.9, 20: 8.65, 24: 8.65, 28: 9.9}),
    "TSSOP": (0.65, 6.4, 0.6, 0.25, 4.4, 1.1, {8: 3.0, 14: 5.0, 16: 5.0, 20: 6.5, 24: 7.8, 28: 9.7}),
    "TSSOP-0.5": (0.5, 6.4, 0.6, 0.22, 4.4, 1.1, {24: 6.5, 28: 7.8, 30: 7.8, 38: 9.7}),
    "TSSOP-6.1": (0.5, 8.1, 0.6, 0.22, 6.1, 1.1, {48: 12.5, 56: 14.0, 64: 17.0}),
    "MSOP": (0.65, 4.9, 0.55, 0.3, 3.0, 1.1, {8: 3.0}),
    "MSOP-0.5": (0.5, 4.9, 0.55, 0.22, 3.0, 1.1, {10: 3.0}),
    "VSSOP": (0.5, 3.1, 0.35, 0.2, 2.0, 0.9, {8: 2.3}),
    "SSOP-0.635": (0.635, 7.8, 0.75, 0.3, 5.3, 1.8, {}),
    "HTSSOP": (0.65, 6.4, 0.6, 0.25, 4.4, 1.1, {14: 5.0, 16: 5.0, 20: 6.5, 24: 7.8, 28: 9.7}),
}

EP_SIZES = {("HTSSOP", 14): (2.5, 3.0), ("HTSSOP", 16): (2.5, 3.0), ("HTSSOP", 20): (2.5, 4.2), ("HTSSOP", 24): (2.5, 5.5),
            ("HTSSOP", 28): (2.5, 6.5), ("SOIC", 8): (2.3, 2.3)}


def dual_label(family: str, n: int) -> str:
    """Library display name of a dual-row package."""
    return {"SOIC-W": f"SOIC-{n} wide (7.5 mm)", "SOIC-5.3": f"SOIC-{n} 5.3 mm (208 mil)",
            "TSSOP-0.5": f"TSSOP-{n} P0.5", "TSSOP-6.1": f"TSSOP-{n} 6.1 mm", "MSOP-0.5": f"MSOP-{n}",
            "SSOP-0.635": f"SSOP-{n} P0.635", "HTSSOP": f"HTSSOP-{n} (exposed pad)"}.get(family, f"{family}-{n}")


def dual_package(family: str, n: int, with_ep: bool = False) -> Footprint:
    pitch, E, L, b, bw, H, lens = DUAL_FAMILIES[family]
    bl = lens.get(n, pitch * n / 2 + 0.6)
    ep = EP_SIZES.get((family, n)) if (with_ep or family == "HTSSOP") else None
    label = dual_label(family, n)
    name = label.split(" (")[0].replace(" ", "_") + ("-1EP" if ep else "")
    desc = f"{label}, {bw:g} x {bl:g} mm body, {pitch} mm pitch" + (", exposed pad" if ep else "")
    return gullwing_dual(name, desc, n, pitch, E, L, b, bw, bl, H, ep)


def quad_pads_numbered(n: int, pitch: float, row: float, pl: float, pw: float) -> list[Pad]:
    per = n // 4
    span = (per - 1) / 2 * pitch
    pads = []
    idx = 1
    for i in range(per):
        pads.append(Pad(str(idx), -row, r4(-span + i * pitch), pl, pw, "roundrect")); idx += 1
    for i in range(per):
        pads.append(Pad(str(idx), r4(-span + i * pitch), row, pw, pl, "roundrect")); idx += 1
    for i in range(per):
        pads.append(Pad(str(idx), row, r4(span - i * pitch), pl, pw, "roundrect")); idx += 1
    for i in range(per):
        pads.append(Pad(str(idx), r4(span - i * pitch), -row, pw, pl, "roundrect")); idx += 1
    return pads


def qfp(n: int, body: float, pitch: float, H: float = 1.4, prefix: str | None = None) -> Footprint:
    E = body + 2.0
    L = 0.6
    outer, inner = E / 2 + 0.45, E / 2 - L - 0.55
    pl, cx = r4(outer - inner), r4((outer + inner) / 2)
    pw = r4(min(pitch * 0.6, pitch - 0.2) if pitch <= 0.5 else min(0.55, pitch - 0.25))
    pads = quad_pads_numbered(n, pitch, cx, pl, pw)
    b = body / 2
    span = ((n // 4) - 1) / 2 * pitch + pw / 2 + 0.2
    g = []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        g.append(_line(sx * b, sy * b, sx * span, sy * b))
        g.append(_line(sx * b, sy * b, sx * b, sy * span))
    g.append(_line(-b, -span, -outer, -span))
    g += _rect(-b, -b, b, b, 0.1, "fab")
    fam = prefix or ("LQFP" if pitch <= 0.5 else "TQFP")
    model = {"type": "gullwing", "bw": body, "bh": body, "H": H, "body": "#202020", "standoff": 0.1, "pin1": True}
    return _fp(f"{fam}-{n}_{body:g}x{body:g}mm_P{pitch}mm", f"{fam}-{n}, {body:g}x{body:g} mm body, {pitch} mm pitch",
               pads, g, (-b, -b, b, b), model)


QFP_LIST = [(32, 7, 0.8), (44, 10, 0.8), (48, 7, 0.5), (52, 10, 0.65), (64, 10, 0.5), (64, 14, 0.8), (80, 12, 0.5),
            (80, 14, 0.65), (100, 14, 0.5), (120, 14, 0.4), (144, 20, 0.5), (176, 24, 0.5), (208, 28, 0.5)]

QFN_LIST = [  # (pins, body, pitch, exposed pad)
    (12, 3, 0.5, 1.65), (16, 3, 0.5, 1.7), (16, 4, 0.65, 2.1), (20, 3, 0.4, 1.65), (20, 4, 0.5, 2.6), (20, 5, 0.65, 3.1),
    (24, 3, 0.4, 1.7), (24, 4, 0.5, 2.65), (24, 5, 0.65, 3.2), (28, 4, 0.4, 2.6), (28, 5, 0.5, 3.35), (28, 6, 0.65, 4.2),
    (32, 4, 0.4, 2.7), (32, 5, 0.5, 3.45), (36, 6, 0.5, 4.1), (40, 5, 0.4, 3.5), (40, 6, 0.5, 4.6), (44, 7, 0.5, 5.15),
    (48, 6, 0.4, 4.4), (48, 7, 0.5, 5.15), (56, 7, 0.4, 5.2), (56, 8, 0.5, 5.6), (64, 8, 0.4, 6.0), (64, 9, 0.5, 7.15),
    (68, 8, 0.4, 5.8), (72, 10, 0.5, 6.0), (88, 10, 0.4, 7.0),
]


def dfn(n: int, bw: float, bl: float, pitch: float, ep: tuple | None) -> Footprint:
    pl = 0.7
    row = bw / 2 - 0.05
    pw = r4(min(pitch * 0.55, pitch - 0.2))
    pads = dual_row_numbering(n, pitch, row, pl, pw)
    if ep:
        # keep at least 0.2 mm between the exposed pad and the signal pads
        epw = min(ep[0], r4(2 * (row - pl / 2 - 0.2)))
        eph = min(ep[1], r4((n // 2 - 1) * pitch + pw + 0.4))
        pads.append(Pad(str(n + 1), 0, 0, epw, eph, "rect"))
    g = [_line(-bw / 2, -bl / 2 - 0.15, bw / 2, -bl / 2 - 0.15), _line(-bw / 2, bl / 2 + 0.15, bw / 2, bl / 2 + 0.15),
         _circle(-bw / 2 - 0.35, -bl / 2 - 0.35, 0.1, 0.1, fill=True)]
    g += _rect(-bw / 2, -bl / 2, bw / 2, bl / 2, 0.1, "fab")
    model = {"type": "qfn", "bw": bw, "bh": bl, "H": 0.8, "body": "#262626"}
    return _fp(f"DFN-{n}_{bw:g}x{bl:g}mm_P{pitch}mm" + ("_EP" if ep else ""),
               f"DFN/SON-{n}, {bw:g}x{bl:g} mm, {pitch} mm pitch" + (", exposed pad" if ep else ""), pads, g,
               (-bw / 2, -bl / 2, bw / 2, bl / 2), model)


DFN_LIST = [(6, 2, 2, 0.65, (0.9, 1.6)), (8, 2, 2, 0.5, (0.9, 1.6)), (8, 2, 3, 0.5, (1.6, 2.3)),
            (8, 3, 3, 0.65, (1.6, 2.4)), (10, 3, 3, 0.5, (1.65, 2.4)), (8, 4, 4, 0.8, (2.3, 3.0)),
            (12, 4, 4, 0.5, (2.6, 3.3)), (6, 1.6, 1.6, 0.5, None), (8, 3, 2, 0.5, (1.6, 1.5))]

BGA_ROWS = [c for c in string.ascii_uppercase if c not in "IOQSXZ"]


def bga_row_name(i: int) -> str:
    if i < len(BGA_ROWS):
        return BGA_ROWS[i]
    return BGA_ROWS[i // len(BGA_ROWS) - 1] + BGA_ROWS[i % len(BGA_ROWS)]


def bga(rows: int, cols: int, pitch: float, body: float, depop: int = 0) -> Footprint:
    d = {1.27: 0.6, 1.0: 0.45, 0.8: 0.4, 0.65: 0.3, 0.5: 0.25, 0.4: 0.2}.get(pitch, pitch * 0.5)
    pads = []
    x0 = -(cols - 1) * pitch / 2
    y0 = -(rows - 1) * pitch / 2
    for r in range(rows):
        for c in range(cols):
            if depop and depop <= r < rows - depop and depop <= c < cols - depop:
                continue
            pads.append(Pad(f"{bga_row_name(r)}{c + 1}", r4(x0 + c * pitch), r4(y0 + r * pitch), d, d, "circle",
                            paste=True))
    b = body / 2
    g = [_line(-b, -b + 1, -b, -b), _line(-b, -b, -b + 1, -b), _line(b, -b, b, b), _line(-b, b, b, b), _line(b, -b, -b + 1.5, -b),
         _line(-b, b, -b, -b + 1.5)]
    g += _rect(-b, -b, b, b, 0.1, "fab")
    H = 1.2 if body < 12 else 1.8
    model = composite(B(-b, -b, 0.3, b, b, H, "#1b1b1d"), B(-b + 0.1, -b + 0.1, H, b - 0.1, b - 0.1, H + 0.2, "#2a2a2c"),
                      CYL(-b + 0.9, -b + 0.9, H + 0.2, H + 0.21, 0.3, "#4a4a4a"))
    n = len(pads)
    return _fp(f"BGA-{n}_{body:g}x{body:g}mm_Layout{cols}x{rows}_P{pitch}mm",
               f"Ball grid array, {n} balls ({cols}x{rows}), {body:g}x{body:g} mm, {pitch} mm pitch", pads, g,
               (-b, -b, b, b), model)


BGA_LIST = [(6, 6, 0.5, 3.5, 0), (8, 8, 0.5, 5, 0), (7, 7, 0.8, 7, 0), (8, 8, 0.8, 8, 0), (10, 10, 0.8, 9, 0),
            (11, 11, 0.65, 8, 0), (12, 12, 0.8, 10, 0), (13, 13, 0.8, 12, 0), (12, 12, 1.0, 13, 0), (14, 14, 1.0, 15, 0),
            (16, 16, 1.0, 17, 0), (18, 18, 1.0, 19, 0), (22, 22, 1.0, 23, 0), (26, 26, 1.0, 27, 0), (15, 15, 0.8, 13, 4),
            (19, 19, 0.8, 16, 5)]


def plcc(n: int, body: float) -> Footprint:
    per = n // 4
    pitch = 1.27
    row = r4(body / 2 - 0.45)
    span = (per - 1) / 2 * pitch
    # pin 1 sits in the middle of the top side; numbering runs counter-clockwise
    top_positions = [r4(-span + i * pitch) for i in range(per)]
    mid = per // 2
    order = []
    order += [(top_positions[i], -row, "v") for i in range(mid, -1, -1)]
    order += [(-row, r4(-span + i * pitch), "h") for i in range(per)]
    order += [(r4(-span + i * pitch), row, "v") for i in range(per)]
    order += [(row, r4(span - i * pitch), "h") for i in range(per)]
    order += [(top_positions[i], -row, "v") for i in range(per - 1, mid, -1)]
    pads = []
    for k, (x, y, o) in enumerate(order, start=1):
        pads.append(Pad(str(k), x, y, 0.7 if o == "v" else 1.93, 1.93 if o == "v" else 0.7, "roundrect"))
    b = body / 2
    g = _rect(-b, -b, b, b) + [_circle(0, -b + 1.2, 0.3, 0.12)]
    model = {"type": "qfn", "bw": body, "bh": body, "H": 3.6, "body": "#1d1d1d"}
    return _fp(f"PLCC-{n}", f"PLCC-{n} J-lead package, {body:g} mm, 1.27 mm pitch (also fits SMD PLCC sockets)",
               pads, g, (-b, -b, b, b), model)


PLCC_LIST = [(20, 9.0), (28, 11.5), (44, 16.6), (52, 19.1), (68, 24.2), (84, 29.3)]


def dip(n: int, row: float = 7.62) -> Footprint:
    if abs(row - 7.62) < 1e-6:
        return _dip300(n)
    half = n // 2
    pads = dual_row_numbering(n, 2.54, row / 2, 1.6, 1.6, "circle", "tht", 0.8)
    pads[0].shape = "rect"
    bw, bh = row - 1.27, half * 2.54 + 0.3
    g = _rect(-bw / 2 + 0.6, -bh / 2, bw / 2 - 0.6, bh / 2)
    model = {"type": "dip", "bw": bw, "bh": bh, "H": 3.8, "body": "#1c1c1c"}
    return _fp(f"DIP-{n}_W{row:.2f}mm", f"DIP-{n}, {row / 2.54 * 100:.0f} mil row spacing (also IC sockets)", pads, g,
               (-bw / 2, -bh / 2, bw / 2, bh / 2), model)


def sip(n: int) -> Footprint:
    pads = inline_tht(n, 2.54, 1.6, 0.8)
    w = n * 2.54
    g = _rect(-w / 2, -1.3, w / 2, 1.3)
    model = composite(B(-w / 2, -1.25, 0.5, w / 2, 1.25, 7.0, BLACK), pins="tht", pin_top=0.6)
    return _fp(f"SIP-{n}_P2.54mm", f"SIP-{n} single in-line package (resistor networks, modules)", pads, g,
               (-w / 2, -1.3, w / 2, 1.3), model)


# --------------------------------------------------------------------------- small transistor / diode packages

def small_sot(name: str, desc: str, coords, pw, ph, bw, bh, H) -> Footprint:
    pads = [Pad(n, x, y, pw, ph, "roundrect") for n, x, y in coords]
    g = [_line(-0.2, -bh / 2 - 0.1, 0.2, -bh / 2 - 0.1), _line(-0.2, bh / 2 + 0.1, 0.2, bh / 2 + 0.1)]
    g += _rect(-bw / 2, -bh / 2, bw / 2, bh / 2, 0.1, "fab")
    model = {"type": "gullwing", "bw": bw, "bh": bh, "H": H, "body": "#1c1c1c", "standoff": 0.05}
    return _fp(name, desc, pads, g, (-bw / 2, -bh / 2, bw / 2, bh / 2), model)


def sot23_8() -> Footprint:
    ys = [-0.975, -0.325, 0.325, 0.975]
    coords = [(str(i + 1), -1.1, y) for i, y in enumerate(ys)] + [(str(8 - i), 1.1, y) for i, y in enumerate(ys)]
    coords = [(n, x * 1.1375 / 1.1, y) for n, x, y in coords]
    return small_sot("SOT-23-8", "SOT-23-8 (TSOT-23-8), 0.65 mm pitch", coords, 1.325, 0.5, 1.6, 2.9, 1.0)


def sc70(pins: int) -> Footprint:
    px, pw, ph = (0.8875, 0.925, 0.45) if pins == 3 else (0.8375, 1.025, 0.35)
    if pins == 3:
        coords = [("1", -px, -0.65), ("2", -px, 0.65), ("3", px, 0)]
    elif pins == 5:
        coords = [("1", -px, -0.65), ("2", -px, 0), ("3", -px, 0.65), ("4", px, 0.65), ("5", px, -0.65)]
    else:
        coords = [("1", -px, -0.65), ("2", -px, 0), ("3", -px, 0.65), ("4", px, 0.65), ("5", px, 0), ("6", px, -0.65)]
    name = {3: "SOT-323_SC-70", 5: "SOT-353_SC-70-5", 6: "SOT-363_SC-70-6"}[pins]
    return small_sot(name, f"SC-70 {pins}-pin (SOT-3x3), 0.65 mm pitch", coords, pw, ph, 1.25, 2.0, 0.95)


def sot523() -> Footprint:
    return small_sot("SOT-523", "SOT-523 (SC-89), 3-pin", [("1", -0.645, -0.5), ("2", -0.645, 0.5), ("3", 0.645, 0)],
                     0.51, 0.4, 0.8, 1.6, 0.75)


def sot563() -> Footprint:
    x = 0.7125
    coords = [("1", -x, -0.5), ("2", -x, 0), ("3", -x, 0.5), ("4", x, 0.5), ("5", x, 0), ("6", x, -0.5)]
    return small_sot("SOT-563", "SOT-563 (SC-89-6), 6-pin, 0.5 mm pitch", coords, 0.675, 0.35, 1.2, 1.6, 0.55)


def sot89(pins: int = 3) -> Footprint:
    """SOT-89 (JEDEC TO-243): the centre lead and the heat tab are one pad (pin 2)."""
    if pins == 3:
        tab = [(-0.738, -0.45), (-0.738, 0.45), (0.738, 0.45), (0.738, 0.867), (3.862, 0.867), (3.862, -0.867),
               (0.738, -0.867), (0.738, -0.45)]
        pads = [Pad("1", -1.95, -1.5, 1.3, 0.9, "roundrect"), Pad("2", -1.8625, 0, 1.475, 0.9, "poly", points=tab),
                Pad("3", -1.95, 1.5, 1.3, 0.9, "roundrect")]
        leads = [(-1.95, -1.5), (-1.95, 0.0), (-1.95, 1.5)]
    else:
        tab = [(0.4, 1.0), (0.9, 0.5), (2.6, 0.5), (2.6, -0.5), (0.9, -0.5), (0.4, -1.0), (-0.4, -1.0), (-0.9, -0.5),
               (-2.6, -0.5), (-2.6, 0.5), (-0.9, 0.5), (-0.4, 1.0)]
        pads = [Pad("1", -1.85, -1.5, 1.5, 0.7, "roundrect"), Pad("2", 0, 0, 0.8, 2.0, "poly", points=tab),
                Pad("3", -1.85, 1.5, 1.5, 0.7, "roundrect"), Pad("4", 1.85, 1.5, 1.5, 0.7, "roundrect"),
                Pad("5", 1.85, -1.5, 1.5, 0.7, "roundrect")]
        leads = [(-1.85, -1.5), (-1.85, 1.5), (1.85, 1.5), (1.85, -1.5)]
    g = _rect(-1.25, -2.25, 1.25, 2.25, 0.1, "fab") + [_line(-1.35, -2.35, 1.35, -2.35), _line(-1.35, 2.35, 1.35, 2.35)]
    parts = [B(-1.25, -2.25, 0.05, 1.25, 2.25, 1.5, "#1c1c1c"), B(1.25, -0.8, 0, 2.0 if pins == 3 else 1.25, 0.8, 0.4,
                                                                    METAL, True)]
    for x, y in leads:
        parts.append(B(min(x * 1.18, x / abs(x) * 1.25), y - 0.24, 0, x - (0.5 if x < 0 else -0.5), y + 0.24, 0.4, METAL,
                       True))
    return _fp(f"SOT-89-{pins}", f"SOT-89-{pins} power package, centre lead + tab = pin 2", pads, g,
               (-1.25, -2.25, 1.25, 2.25), composite(*parts))


def to252() -> Footprint:
    pads = [Pad("1", -2.28, 4.2, 1.2, 2.2, "roundrect"), Pad("3", 2.28, 4.2, 1.2, 2.2, "roundrect"),
            Pad("2", 0, -2.1, 5.8, 6.4, "roundrect", roundness=0.05)]
    g = _rect(-3.3, -3.05, 3.3, 3.05, 0.1, "fab") + [_line(-3.4, 3.2, -3.4, 2.0), _line(3.4, 3.2, 3.4, 2.0)]
    model = composite(B(-3.25, -2.2, 0.1, 3.25, 3.05, 2.3, "#1c1c1c"), B(-2.7, -3.3, 0, 2.7, -2.2, 0.55, METAL, True),
                      B(-2.6, 3.0, 0, -1.9, 5.2, 0.5, METAL, True), B(1.9, 3.0, 0, 2.6, 5.2, 0.5, METAL, True))
    return _fp("TO-252-2_DPAK", "TO-252 (DPAK) power package, tab = pin 2." + VERIFY, pads, g, (-3.3, -3.05, 3.3, 5.3), model)


def to263(pins: int) -> Footprint:
    """TO-263 (D2PAK) family. Leads point to -X; the heat tab is numbered as the centre pin."""
    pitch = {2: 5.08, 3: 2.54, 5: 1.7, 7: 1.27}[pins]
    lead_w = 0.8 if pitch < 1.5 else 1.1
    if pins == 2:
        leads = [("1", -2.54), ("3", 2.54)]
        tab = "2"
    else:
        leads = [(str(i + 1), r4((i - (pins - 1) / 2) * pitch)) for i in range(pins)]
        tab = str((pins + 1) // 2)
    pads = [Pad(num, -7.65, y, 4.6, lead_w, "roundrect") for num, y in leads]
    pads.append(Pad(tab, 1.5, 0, 9.4, 10.8, "roundrect", roundness=0.03, paste=True))
    g = _rect(-4.625, -5.0, 5.625, 5.0, 0.1, "fab") + [_line(-5.0, -5.15, 5.7, -5.15), _line(-5.0, 5.15, 5.7, 5.15)]
    parts = [B(-4.6, -5.0, 0.1, 4.4, 5.0, 4.4, "#1c1c1c"), B(4.4, -4.9, 0, 5.6, 4.9, 1.3, METAL, True)]
    for _num, y in leads:
        parts.append(B(-9.3, y - lead_w * 0.35, 0, -4.6, y + lead_w * 0.35, 0.5, METAL, True))
    name = f"TO-263-{pins}" + ("" if pins == 2 else f"_TabPin{tab}")
    return _fp(name, f"TO-263-{pins} (D2PAK) power package, tab = pin {tab}", pads, g, (-9.875, -5.4, 6.2, 5.4),
               composite(*parts))


def powerpak_so8() -> Footprint:
    """5x6 mm power MOSFET package (PowerPAK SO-8 / SuperSO8 / TDSON-8 / DFN5x6, single die)."""
    ys = [-1.905, -0.635, 0.635, 1.905]
    pads = [Pad(str(i + 1), -2.67, y, 1.27, 0.61, "rect") for i, y in enumerate(ys)]
    pads.append(Pad("5", 0.69, 0, 3.81, 3.91, "rect"))
    pads += [Pad("5", 2.795, y, 1.02, 0.61, "rect") for y in ys]
    g = _rect(-2.945, -2.45, 2.945, 2.45, 0.1, "fab") + [_line(-3.5, -2.6, -2.0, -2.6)]
    model = composite(B(-2.5, -2.45, 0.05, 2.5, 2.45, 1.0, "#1c1c1c"),
                      *[B(-2.95, y - 0.2, 0, -2.5, y + 0.2, 0.25, METAL, True) for y in ys],
                      *[B(2.5, y - 0.2, 0, 2.95, y + 0.2, 0.25, METAL, True) for y in ys])
    return _fp("PowerPAK_SO-8_Single", "Power MOSFET package 5x6 mm (PowerPAK SO-8 / SuperSO8 / TDSON-8 / DFN5x6), "
               "pins 1-3 source, 4 gate, 5 drain", pads, g, (-2.945, -2.45, 2.945, 2.45), model)


def powerpak_1212() -> Footprint:
    pads = [Pad(str(i + 1), -1.5, r4(-0.975 + i * 0.65), 0.7, 0.4, "roundrect") for i in range(4)]
    pads.append(Pad("5", 0.45, 0, 2.3, 2.3, "roundrect", roundness=0.05))
    g = _rect(-1.65, -1.65, 1.65, 1.65, 0.1, "fab") + [_line(-2.0, -1.4, -2.0, -0.8)]
    model = composite(B(-1.65, -1.65, 0.05, 1.65, 1.65, 0.9, "#1c1c1c"))
    return _fp("PowerPAK_1212-8_3.3x3.3mm", "Power MOSFET package 3.3x3.3 mm (PowerPAK 1212-8 / DFN3x3)." + VERIFY, pads,
               g, (-1.65, -1.65, 1.65, 1.65), model)


# --------------------------------------------------------------------------- through-hole transistor packages

def to92_variant(wide: bool) -> Footprint:
    pitch = 2.54 if wide else 1.27
    pads = [Pad(str(i + 1), r4((i - 1) * pitch), 0, 1.3 if wide else 1.05, 1.5, "rect" if i == 0 else "oval", "tht",
                0.75) for i in range(3)]
    g = [_line(-2.3, 1.2, 2.3, 1.2)]
    model = {"type": "to92", "body": "#1a1a1a"}
    return _fp("TO-92_Wide" if wide else "TO-92_Inline", f"TO-92, {'2.54 mm (bent leads)' if wide else '1.27 mm'} pitch",
               pads, g, (-2.4, -2.7, 2.4, 1.2), model)


def to126() -> Footprint:
    pads = [Pad(str(i + 1), r4((i - 1) * 2.28), 0, 1.71, 1.8, "rect" if i == 0 else "oval", "tht", 1.0) for i in range(3)]
    g = _rect(-4.0, -3.0, 4.0, 1.4)
    model = composite(B(-3.9, -1.6, 2.5, 3.9, 1.0, 13.5, "#1c1c1c"), CYL(0, -0.3, 10.5, 10.6, 1.5, DARK), pins="tht",
                      pin_top=2.6)
    return _fp("TO-126-3_Vertical", "TO-126 vertical (e.g. BD139/BD140)", pads, g, (-4.0, -3.0, 4.0, 1.4), model)


def to220_variant(pins: int, horizontal: bool = False, isolated: bool = False) -> Footprint:
    pitch = {2: 5.08, 3: 2.54, 5: 1.7}[pins]
    pads = [Pad(str(i + 1), r4((i - (pins - 1) / 2) * pitch), 0, 1.9 if pitch > 2 else 1.5, 2.2,
                "rect" if i == 0 else "oval", "tht", 1.1 if pitch > 2 else 0.9) for i in range(pins)]
    name = f"TO-220{'F' if isolated else ''}-{pins}_{'Horizontal' if horizontal else 'Vertical'}"
    if horizontal:
        pads.append(Pad("", 0, -13.7, 3.5, 3.5, "circle", "npth", 3.5))
        g = _rect(-5.2, -18.5, 5.2, -2.5)
        tab = "#1c1c1c" if isolated else "#c9c9c9"
        model = composite(B(-5.0, -15.5, 0, 5.0, -2.5, 4.4, "#1c1c1c"),
                          B(-5.0, -18.5, 0, 5.0, -15.5, 1.3, tab, not isolated), pins="tht", pin_top=2.0)
        body = (-5.2, -18.5, 5.2, 1.6)
    else:
        g = _rect(-5.2, -3.2, 5.2, 1.6) + [_line(-5.2, -2.0, 5.2, -2.0)]
        model = {"type": "to220", "body": "#1c1c1c", "tab": "#1c1c1c" if isolated else "#c9c9c9"}
        body = (-5.2, -3.2, 5.2, 1.6)
    return _fp(name, f"TO-220{'F (fully isolated)' if isolated else ''}, {pins} pins, "
                     f"{'lying flat' if horizontal else 'vertical'}", pads, g, body, model)


def to247(pins: int = 3) -> Footprint:
    pads = [Pad(str(i + 1), r4((i - (pins - 1) / 2) * 5.45), 0, 2.5, 4.5, "rect" if i == 0 else "oval", "tht", 1.5)
            for i in range(pins)]
    g = _rect(-8.0, -5.0, 8.0, 1.8)
    model = composite(B(-7.9, -2.5, 3.0, 7.9, 2.5, 23.5, "#1c1c1c"), B(-7.9, -4.9, 3.0, 7.9, -2.5, 23.5, "#c9c9c9", True),
                      CYL(0, -3.7, 17.0, 17.2, 1.8, DARK), pins="tht", pin_top=3.1)
    return _fp(f"TO-247-{pins}_Vertical", f"TO-247-{pins} vertical power package (IGBTs, MOSFETs)", pads, g,
               (-8.0, -5.0, 8.0, 1.8), model)


def to5() -> Footprint:
    import math
    pads = []
    for i in range(3):
        a = math.radians(90 + i * 90)
        pads.append(Pad(str(i + 1), r4(2.54 * math.cos(a)), r4(-2.54 * math.sin(a)), 1.4, 1.4,
                        "rect" if i == 0 else "circle", "tht", 0.8))
    g = [_circle(0, 0, 4.7)]
    model = composite(CYL(0, 0, 1.0, 6.5, 4.2, METAL, True, seg=36), CYL(0, 0, 0.8, 1.2, 4.7, METAL, True, seg=36),
                      pins="tht", pin_top=1.0)
    return _fp("TO-5-3", "TO-5 / TO-39 metal can, 3 leads", pads, g, (-4.7, -4.7, 4.7, 4.7), model)


# --------------------------------------------------------------------------- catalogue entries

def entries():
    out = []
    add = out.append
    # diodes
    for n in ("SOD-123", "SOD-323", "SMA", "SMB"):
        add(("Diodes/SMD", f"Diode {n}", "D", "1N4148W" if "SOD" in n else "SS34", lambda n=n: sod(n),
             "diode schottky rectifier zener tvs"))
    for n, dims in (("SOD-123F", (1.1, 1.2, 1.6, 2.7, 1.6, 1.0)), ("SOD-523", (0.5, 0.6, 0.75, 1.2, 0.8, 0.6)),
                    ("SOD-923", (0.4, 0.5, 0.55, 0.8, 0.6, 0.4)), ("SMC", (2.5, 3.3, 3.4, 7.0, 6.0, 2.3)),
                    ("SMAF", (1.5, 1.5, 1.9, 3.5, 2.6, 1.0)), ("PowerDI-123", (1.0, 1.6, 1.4, 2.8, 1.8, 1.0))):
        add(("Diodes/SMD", f"Diode {n}", "D", "SS14", lambda n=n, d=dims: _sod_generic(n, *d),
             "diode schottky rectifier zener tvs"))
    # transistors & small packages
    add(("Transistors/SMD", "SOT-23", "Q", "MMBT3904", lambda: sot23(3), "transistor mosfet bjt sot23"))
    add(("Transistors/SMD", "SOT-323 (SC-70)", "Q", "BC847W", lambda: sc70(3), "transistor sc70"))
    add(("Transistors/SMD", "SOT-523", "Q", "2N7002T", sot523, "transistor mosfet"))
    add(("Transistors/SMD", "SOT-89-3", "Q", "BCX56", lambda: sot89(3), "transistor power sot89"))
    add(("Transistors/SMD", "SOT-223", "Q", "BCP56", sot223, "transistor power"))
    add(("Transistors/SMD", "TO-252 (DPAK)", "Q", "IRLR024N", to252, "mosfet power dpak"))
    for p in (2, 3, 5, 7):
        add(("Transistors/SMD", f"TO-263-{p} (D2PAK)", "Q" if p <= 3 else "U", "IRF3205S" if p <= 3 else "LM2596S",
             lambda p=p: to263(p), "mosfet power d2pak regulator"))
    add(("Transistors/SMD", "PowerPAK SO-8 5x6 (DFN5x6)", "Q", "BSC014N04LS", powerpak_so8, "mosfet power dfn"))
    add(("Transistors/SMD", "PowerPAK 1212-8 3.3x3.3", "Q", "SiS434DN", powerpak_1212, "mosfet power dfn"))
    add(("Transistors/Through-hole", "TO-92 inline", "Q", "2N3904", lambda: to92_variant(False), "transistor bjt"))
    add(("Transistors/Through-hole", "TO-92 wide", "Q", "BC547", lambda: to92_variant(True), "transistor bjt"))
    add(("Transistors/Through-hole", "TO-126", "Q", "BD139", to126, "transistor power"))
    for p in (2, 3, 5):
        add(("Transistors/Through-hole", f"TO-220-{p} vertical", "Q", "IRLZ44N" if p == 3 else "IC",
             lambda p=p: to220_variant(p), "mosfet regulator power"))
        add(("Transistors/Through-hole", f"TO-220-{p} horizontal", "Q", "IRLZ44N" if p == 3 else "IC",
             lambda p=p: to220_variant(p, True), "mosfet regulator power lying"))
    add(("Transistors/Through-hole", "TO-220F-3 vertical (isolated)", "Q", "IC", lambda: to220_variant(3, False, True),
         "isolated fullpak"))
    for p in (2, 3):
        add(("Transistors/Through-hole", f"TO-247-{p}", "Q", "IGBT", lambda p=p: to247(p), "igbt mosfet power"))
    add(("Transistors/Through-hole", "TO-5 / TO-39 can", "Q", "2N2222", to5, "metal can"))
    # small ICs
    add(("ICs/SOT & SC-70", "SOT-23-5", "U", "IC", lambda: sot23(5), "ldo regulator logic"))
    add(("ICs/SOT & SC-70", "SOT-23-6", "U", "IC", lambda: sot23(6), "ic"))
    add(("ICs/SOT & SC-70", "SOT-23-8", "U", "IC", sot23_8, "ic"))
    add(("ICs/SOT & SC-70", "SC-70-5 (SOT-353)", "U", "IC", lambda: sc70(5), "logic gate"))
    add(("ICs/SOT & SC-70", "SC-70-6 (SOT-363)", "U", "IC", lambda: sc70(6), "dual transistor"))
    add(("ICs/SOT & SC-70", "SOT-563", "U", "IC", sot563, "ic"))
    add(("ICs/SOT & SC-70", "SOT-89-5", "U", "IC", lambda: sot89(5), "regulator"))
    add(("ICs/SOT & SC-70", "SOT-223 regulator", "U", "AMS1117-3.3", sot223, "ldo regulator"))
    # dual-row families
    for fam, (_pitch, *_rest, lens) in DUAL_FAMILIES.items():
        if not lens:
            continue
        for n in lens:
            add((f"ICs/{fam.split('-')[0]}", dual_label(fam, n), "U", "IC", lambda f=fam, n=n: dual_package(f, n),
                 f"ic {fam.lower()} opamp logic"))
    add(("ICs/SOIC", "SOIC-8 with exposed pad", "U", "IC", lambda: dual_package("SOIC", 8, True),
         "esop8 powerpad soic ep"))
    for n, body, pitch in QFP_LIST:
        fam = "LQFP" if pitch <= 0.5 else "TQFP"
        add(("ICs/QFP", f"{fam}-{n} {body}x{body} P{pitch}", "U", "IC", lambda n=n, b=body, p=pitch: qfp(n, b, p),
             "qfp mcu microcontroller fpga"))
    for n, body, pitch, ep in QFN_LIST:
        add(("ICs/QFN", f"QFN-{n} {body}x{body} P{pitch}", "U", "IC", lambda n=n, b=body, p=pitch, e=ep: _qfn(n, b, p, e),
             "qfn mlf vqfn wqfn mcu"))
    for n, bw, bl, pitch, ep in DFN_LIST:
        add(("ICs/DFN & SON", f"DFN-{n} {bw:g}x{bl:g} P{pitch}" + (" EP" if ep else ""), "U", "IC",
             lambda a=(n, bw, bl, pitch, ep): dfn(*a), "dfn son wson udfn"))
    for rows, cols, pitch, body, depop in BGA_LIST:
        balls = rows * cols - (max(0, rows - 2 * depop) * max(0, cols - 2 * depop) if depop else 0)
        add(("ICs/BGA", f"BGA-{balls} {body:g}x{body:g} P{pitch}", "U", "IC",
             lambda a=(rows, cols, pitch, body, depop): bga(*a), "bga ball grid fpga soc memory"))
    for n, body in PLCC_LIST:
        add(("ICs/PLCC", f"PLCC-{n}", "U", "IC", lambda n=n, b=body: plcc(n, b), "plcc j-lead socket"))
    for n in (4, 6, 8, 14, 16, 18, 20, 22, 24, 28):
        add(("ICs/DIP", f"DIP-{n} (300 mil)", "U", "IC" if n != 8 else "NE555P", lambda n=n: dip(n),
             "dip through hole socket"))
    for n in (24, 28, 32, 40, 48):
        add(("ICs/DIP", f"DIP-{n} (600 mil)", "U", "IC", lambda n=n: dip(n, 15.24), "dip wide through hole"))
    for n in (3, 4, 5, 6, 7, 8, 9, 10, 12):
        add(("ICs/SIP", f"SIP-{n}", "U", "IC", lambda n=n: sip(n), "sip resistor network"))
    return out


def _sod_generic(name, pw, ph, cx, L, W, H) -> Footprint:
    from .shapes import two_terminal_smd
    model = {"type": "diode_smd", "L": L, "W": W, "H": H, "body": "#1d1d1d", "band": "#bfbfbf"}
    return two_terminal_smd(f"D_{name}", f"Diode, {name} package, pin 1 = cathode", pw, ph, cx, L, W, model,
                            polarity=True)
