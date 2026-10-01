"""Parametric footprint library.

Land patterns follow common IPC-7351 nominal densities (close to the KiCad library
values). Always verify footprints against the manufacturer datasheet before ordering.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .board import Footprint, Graphic, Pad

SILK_W = 0.12


# --------------------------------------------------------------------------- helpers

def _line(x1, y1, x2, y2, w=SILK_W, layer="silk") -> Graphic:
    return Graphic("line", [(x1, y1), (x2, y2)], w, layer)


def _rect(x0, y0, x1, y1, w=SILK_W, layer="silk") -> list[Graphic]:
    return [
        _line(x0, y0, x1, y0, w, layer),
        _line(x1, y0, x1, y1, w, layer),
        _line(x1, y1, x0, y1, w, layer),
        _line(x0, y1, x0, y0, w, layer),
    ]


def _circle(cx, cy, r, w=SILK_W, layer="silk", fill=False) -> Graphic:
    return Graphic("circle", [(cx, cy)], w, layer, r=r, fill=fill)


def _arc(cx, cy, r, start, sweep, w=SILK_W, layer="silk") -> Graphic:
    return Graphic("arc", [(cx, cy)], w, layer, r=r, start=start, sweep=sweep)


def _courtyard_from(pads: list[Pad], body: tuple[float, float, float, float], margin=0.25):
    x0, y0, x1, y1 = body
    for p in pads:
        if p.shape == "poly" and p.points:
            x0 = min(x0, p.x + min(q[0] for q in p.points))
            x1 = max(x1, p.x + max(q[0] for q in p.points))
            y0 = min(y0, p.y + min(q[1] for q in p.points))
            y1 = max(y1, p.y + max(q[1] for q in p.points))
            continue
        hw, hh = (p.w / 2, p.h / 2) if p.rotation % 180 == 0 else (p.h / 2, p.w / 2)
        x0 = min(x0, p.x - hw)
        x1 = max(x1, p.x + hw)
        y0 = min(y0, p.y - hh)
        y1 = max(y1, p.y + hh)
    return (round(x0 - margin, 3), round(y0 - margin, 3), round(x1 + margin, 3), round(y1 + margin, 3))


def _fp(name, desc, pads, graphics, body, model, ref_gap=0.9) -> Footprint:
    cy = _courtyard_from(pads, body)
    return Footprint(
        name=name,
        description=desc,
        pads=pads,
        graphics=graphics + [Graphic("poly", [(cy[0], cy[1]), (cy[2], cy[1]), (cy[2], cy[3]), (cy[0], cy[3])], 0.05, "crtyd")],
        courtyard=cy,
        model=model,
        ref_pos=(0.0, round(cy[1] - ref_gap, 3)),
    )


# --------------------------------------------------------------------------- chip passives

CHIP_SIZES = {
    # code: (pad_w, pad_h, pad_cx, body_L, body_W, height)
    "01005": (0.20, 0.22, 0.20, 0.4, 0.2, 0.13),
    "0201": (0.30, 0.32, 0.29, 0.6, 0.3, 0.23),
    "0402": (0.54, 0.64, 0.51, 1.0, 0.5, 0.35),
    "0603": (0.80, 0.95, 0.825, 1.6, 0.8, 0.45),
    "0805": (1.025, 1.40, 0.9125, 2.0, 1.25, 0.5),
    "1206": (1.125, 1.75, 1.4625, 3.2, 1.6, 0.55),
    "1210": (1.125, 2.65, 1.4625, 3.2, 2.5, 0.6),
    "1806": (1.3, 1.8, 2.05, 4.5, 1.6, 0.6),
    "1812": (1.3, 3.4, 2.05, 4.5, 3.2, 0.6),
    "2010": (1.25, 2.65, 2.3, 5.0, 2.5, 0.6),
    "2220": (1.6, 5.3, 2.6, 5.7, 5.0, 1.2),
    "2512": (1.40, 3.35, 2.95, 6.3, 3.2, 0.6),
}
CHIP_METRIC = {"01005": "0402", "0201": "0603", "0402": "1005", "0603": "1608", "0805": "2012", "1206": "3216",
               "1210": "3225", "1806": "4516", "1812": "4532", "2010": "5025", "2220": "5750", "2512": "6332"}


def chip(kind: str, size: str) -> Footprint:
    pw, ph, cx, L, W, H = CHIP_SIZES[size]
    pads = [
        Pad("1", -cx, 0, pw, ph, "roundrect"),
        Pad("2", cx, 0, pw, ph, "roundrect"),
    ]
    g: list[Graphic] = []
    gap_x = cx - pw / 2 - 0.2
    if gap_x > 0.15:
        yy = W / 2 + 0.11
        g += [_line(-gap_x, -yy, gap_x, -yy), _line(-gap_x, yy, gap_x, yy)]
    g += _rect(-L / 2, -W / 2, L / 2, W / 2, 0.1, "fab")
    colors = {
        "R": ("#141414", "#d8d8d8"),
        "C": ("#b78a5a", "#c9c9c9"),
        "L": ("#2b2b2b", "#c9c9c9"),
        "FB": ("#3a3a3c", "#c9c9c9"),
        "F": ("#e8e2cf", "#c9c9c9"),
        "LED": ("#f4f4f0", "#c9c9c9"),
        "D": ("#1a1a1a", "#c9c9c9"),
    }
    body, term = colors.get(kind, colors["R"])
    if kind == "C" and size in ("1206", "1210", "1812", "2220"):
        H = max(H, W * 0.8)
    model = {"type": "chip", "L": L, "W": W, "H": H, "body": body, "term": term, "cls": kind}
    names = {"R": "R", "C": "C", "L": "L", "FB": "FB", "F": "Fuse", "LED": "LED", "D": "D"}
    desc = {"R": "Resistor", "C": "Capacitor", "L": "Inductor", "FB": "Ferrite bead", "F": "Fuse", "LED": "LED",
            "D": "Diode"}[kind]
    desc = f"{desc}, {size} ({CHIP_METRIC.get(size, '')} metric)"
    if kind in ("LED", "D"):
        # Pin 1 = cathode: polarity bar on the silkscreen
        x = -(cx + pw / 2 + 0.25)
        g.append(_line(x, -ph / 2, x, ph / 2, 0.15))
        model["polarity"] = True
    return _fp(f"{names[kind]}_{size}", f"{desc} SMD chip", pads, g, (-L / 2, -W / 2, L / 2, W / 2), model)


# --------------------------------------------------------------------------- SOT / SOD

def sot23(pins: int = 3) -> Footprint:
    pw, ph, px = (1.475, 0.6, 0.9375) if pins == 3 else (1.325, 0.6, 1.1375)
    if pins == 3:
        coords = [("1", -px, -0.95), ("2", -px, 0.95), ("3", px, 0.0)]
    elif pins == 5:
        coords = [("1", -px, -0.95), ("2", -px, 0), ("3", -px, 0.95), ("4", px, 0.95), ("5", px, -0.95)]
    else:
        coords = [("1", -px, -0.95), ("2", -px, 0), ("3", -px, 0.95), ("4", px, 0.95), ("5", px, 0), ("6", px, -0.95)]
    pads = [Pad(n, x, y, pw, ph, "roundrect") for n, x, y in coords]
    bw, bh = 1.6, 2.9
    g = [_line(-0.25, -bh / 2 - 0.1, 0.25, -bh / 2 - 0.1), _line(-0.25, bh / 2 + 0.1, 0.25, bh / 2 + 0.1)]
    g += _rect(-bw / 2, -bh / 2, bw / 2, bh / 2, 0.1, "fab")
    g.append(_circle(-px - 0.35, -1.65, 0.1, 0.1, fill=True))
    model = {"type": "gullwing", "bw": bw, "bh": bh, "H": 1.0, "body": "#1c1c1c", "lead_w": 0.4, "standoff": 0.1}
    name = "SOT-23" if pins == 3 else f"SOT-23-{pins}"
    return _fp(name, f"{name} small outline transistor package", pads, g, (-bw / 2, -bh / 2, bw / 2, bh / 2), model)


def sot223() -> Footprint:
    pads = [Pad(str(i + 1), -3.15, (i - 1) * 2.3, 2.0, 1.5, "roundrect") for i in range(3)]
    pads.append(Pad("2", 3.15, 0, 2.0, 3.8, "roundrect"))  # the tab is pin 2
    bw, bh = 3.5, 6.5
    g = [_line(-1.85, -3.4, 1.85, -3.4), _line(-1.85, 3.4, 1.85, 3.4), _line(-1.85, -3.4, -1.85, -2.9),
         _line(-1.85, 3.4, -1.85, 2.9)]
    g += _rect(-bw / 2, -bh / 2, bw / 2, bh / 2, 0.1, "fab")
    model = {"type": "gullwing", "bw": bw, "bh": bh, "H": 1.6, "body": "#1c1c1c", "lead_w": 0.7, "standoff": 0.1}
    return _fp("SOT-223-3_TabPin2", "SOT-223 power package, tab = pin 2 (e.g. AMS1117 regulator)", pads, g, (-bw / 2, -bh / 2, bw / 2, bh / 2), model)


def sod(name: str) -> Footprint:
    dims = {"SOD-123": (0.91, 1.22, 1.635, 2.7, 1.6, 1.1), "SOD-323": (0.59, 0.45, 1.1, 1.7, 1.25, 0.9),
            "SMA": (2.5, 1.7, 2.0, 4.3, 2.6, 2.1), "SMB": (2.5, 2.3, 2.15, 4.4, 3.6, 2.2)}
    pw, ph, cx, L, W, H = dims[name]
    pads = [Pad("1", -cx, 0, pw, ph, "roundrect"), Pad("2", cx, 0, pw, ph, "roundrect")]
    x = -(cx + pw / 2 + 0.25)
    g = [_line(x, -W / 2 - 0.1, x, W / 2 + 0.1, 0.15), _line(x, -W / 2 - 0.1, cx, -W / 2 - 0.1),
         _line(x, W / 2 + 0.1, cx, W / 2 + 0.1)]
    g += _rect(-L / 2, -W / 2, L / 2, W / 2, 0.1, "fab")
    model = {"type": "diode_smd", "L": L, "W": W, "H": H, "body": "#1d1d1d", "band": "#bfbfbf"}
    return _fp(f"D_{name}", f"Diode, {name} package, pin 1 = cathode", pads, g, (-L / 2, -W / 2, L / 2, W / 2), model)


# --------------------------------------------------------------------------- SOIC / TSSOP / QFP / QFN

def dual_row_smd(name: str, desc: str, n: int, pitch: float, row_x: float, pw: float, ph: float,
                 bw: float, bh: float, H: float) -> Footprint:
    half = n // 2
    pads = []
    for i in range(half):
        y = (i - (half - 1) / 2) * pitch
        pads.append(Pad(str(i + 1), -row_x, y, pw, ph, "roundrect"))
    for i in range(half):
        y = ((half - 1) / 2 - i) * pitch
        pads.append(Pad(str(half + i + 1), row_x, y, pw, ph, "roundrect"))
    top = bh / 2 + 0.1
    inner = row_x - pw / 2 - 0.2
    g = [
        _line(-bw / 2, -top, bw / 2, -top), _line(-bw / 2, top, bw / 2, top),
        _line(-inner - 0.05, -top, -inner - 0.05, pads[0].y - ph / 2 - 0.1),
    ]
    g += _rect(-bw / 2, -bh / 2, bw / 2, bh / 2, 0.1, "fab")
    model = {"type": "gullwing", "bw": bw, "bh": bh, "H": H, "body": "#1e1e1e", "lead_w": min(ph * 0.75, 0.5),
             "standoff": 0.1, "pin1": True}
    return _fp(name, desc, pads, g, (-bw / 2, -bh / 2, bw / 2, bh / 2), model)


def soic(n: int) -> Footprint:
    bh = {8: 4.9, 14: 8.65, 16: 9.9}.get(n, 1.27 * n / 2 + 0.5)
    return dual_row_smd(f"SOIC-{n}", f"SOIC-{n}, 3.9x{bh} mm body, 1.27 mm pitch", n, 1.27, 2.475, 1.95, 0.6, 3.9, bh, 1.5)


def tssop(n: int) -> Footprint:
    bh = {8: 3.0, 14: 5.0, 16: 5.0, 20: 6.5, 24: 7.8, 28: 9.7}.get(n, 0.65 * n / 2 + 1)
    return dual_row_smd(f"TSSOP-{n}", f"TSSOP-{n}, 4.4 mm body, 0.65 mm pitch", n, 0.65, 2.8625, 1.475, 0.4, 4.4, bh, 1.1)


def msop(n: int = 8) -> Footprint:
    return dual_row_smd(f"MSOP-{n}", f"MSOP-{n}, 3x3 mm body, 0.65 mm pitch", n, 0.65, 2.1125, 1.475, 0.4, 3.0, 3.0, 1.0)


def quad_pads(n: int, pitch: float, row: float, pl: float, pw: float) -> list[Pad]:
    per = n // 4
    pads = []
    idx = 1
    span = (per - 1) / 2 * pitch
    for i in range(per):  # left, top -> bottom
        pads.append(Pad(str(idx), -row, -span + i * pitch, pl, pw, "roundrect")); idx += 1
    for i in range(per):  # bottom, left -> right
        pads.append(Pad(str(idx), -span + i * pitch, row, pw, pl, "roundrect")); idx += 1
    for i in range(per):  # right, bottom -> top
        pads.append(Pad(str(idx), row, span - i * pitch, pl, pw, "roundrect")); idx += 1
    for i in range(per):  # top, right -> left
        pads.append(Pad(str(idx), span - i * pitch, -row, pw, pl, "roundrect")); idx += 1
    return pads


def qfp(n: int, body: float, pitch: float) -> Footprint:
    row = body / 2 + 0.6625
    pads = quad_pads(n, pitch, row, 1.5, min(0.55, pitch * 0.6))
    b = body / 2
    span = ((n // 4) - 1) / 2 * pitch + 0.4
    g = []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        g.append(_line(sx * b, sy * b, sx * span, sy * b))
        g.append(_line(sx * b, sy * b, sx * b, sy * span))
    g.append(_line(-b, -span, -row - 0.75, -span))
    g += _rect(-b, -b, b, b, 0.1, "fab")
    name = ("LQFP" if pitch <= 0.5 else "TQFP") + f"-{n}"
    model = {"type": "gullwing", "bw": body, "bh": body, "H": 1.4, "body": "#202020", "lead_w": min(0.3, pitch * 0.45),
             "standoff": 0.1, "pin1": True, "quad": True}
    return _fp(f"{name}_{body:g}x{body:g}mm", f"{name}, {body:g}x{body:g} mm body, {pitch} mm pitch", pads, g,
               (-b, -b, b, b), model)


def qfn(n: int, body: float, pitch: float, ep: float) -> Footprint:
    pw = round(min(pitch * 0.55, pitch - 0.2), 3) if pitch < 0.5 else (0.25 if pitch <= 0.5 else 0.3)
    outer = body / 2 + 0.3
    corner_span = ((n // 4) - 1) / 2 * pitch
    # the inner pad ends must stay clear of the neighbouring side's corner pads
    inner = max(body / 2 - 0.45, corner_span + pw / 2 + 0.15)
    pl = round(outer - inner, 3)
    row = round((outer + inner) / 2, 3)
    ep = min(ep, round(2 * (inner - 0.2), 3))
    pads = quad_pads(n, pitch, row, pl, pw)
    pads.append(Pad(str(n + 1), 0, 0, ep, ep, "roundrect", roundness=0.05))
    b = body / 2
    span = ((n // 4) - 1) / 2 * pitch + 0.4
    g = []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        g.append(_line(sx * (b + 0.1), sy * (b + 0.1), sx * span, sy * (b + 0.1)))
        g.append(_line(sx * (b + 0.1), sy * (b + 0.1), sx * (b + 0.1), sy * span))
    g.append(_circle(-b - 0.45, -b - 0.45, 0.12, 0.1, fill=True))
    g += _rect(-b, -b, b, b, 0.1, "fab")
    model = {"type": "qfn", "bw": body, "bh": body, "H": 0.85, "body": "#262626"}
    return _fp(f"QFN-{n}_{body:g}x{body:g}mm", f"QFN-{n}, {body:g}x{body:g} mm, {pitch} mm pitch, exposed pad", pads, g,
               (-b, -b, b, b), model)


# --------------------------------------------------------------------------- through-hole

def _tht_pad(num, x, y, size=1.6, drill=0.8, square=False, shape=None) -> Pad:
    return Pad(num, x, y, size, size, shape or ("rect" if square else "circle"), "tht", drill)


def dip(n: int) -> Footprint:
    half = n // 2
    pads = []
    for i in range(half):
        pads.append(_tht_pad(str(i + 1), -3.81, (i - (half - 1) / 2) * 2.54, 1.6, 0.8, square=(i == 0)))
    for i in range(half):
        pads.append(_tht_pad(str(half + i + 1), 3.81, ((half - 1) / 2 - i) * 2.54, 1.6, 0.8))
    bw, bh = 6.35, half * 2.54 + 0.3
    g = _rect(-2.5, -bh / 2, 2.5, bh / 2)
    g.append(_arc(0, -bh / 2, 0.9, 180, 180))
    g += _rect(-bw / 2, -bh / 2, bw / 2, bh / 2, 0.1, "fab")
    model = {"type": "dip", "bw": bw, "bh": bh, "H": 3.3, "body": "#1c1c1c"}
    return _fp(f"DIP-{n}_W7.62mm", f"DIP-{n} through-hole package, 300 mil row spacing", pads, g,
               (-bw / 2, -bh / 2, bw / 2, bh / 2), model)


def pin_header(cols: int, rows: int = 1, pitch: float = 2.54) -> Footprint:
    pads = []
    n = 1
    x0 = -(cols - 1) * pitch / 2
    y0 = -(rows - 1) * pitch / 2
    for c in range(cols):
        for r in range(rows):
            # pin 1 bottom-left, pin 2 directly above it (standard 2xN convention)
            pads.append(_tht_pad(str(n), x0 + c * pitch, y0 + (rows - 1 - r) * pitch, 1.7, 1.0, square=(n == 1)))
            n += 1
    w = cols * pitch
    h = rows * pitch
    g = _rect(-w / 2, -h / 2, w / 2, h / 2)
    g.append(_line(-w / 2 - 0.4, h / 2 - pitch, -w / 2 - 0.4, h / 2))
    model = {"type": "header", "cols": cols, "rows": rows, "pitch": pitch, "body": "#161616", "pin": "#d9b44a"}
    return _fp(f"PinHeader_{rows}x{cols:02d}_P{pitch}mm", f"Pin header, {rows}x{cols}, {pitch} mm pitch, vertical",
               pads, g, (-w / 2, -h / 2, w / 2, h / 2), model)


def jst(series: str, n: int) -> Footprint:
    pitch = {"PH": 2.0, "XH": 2.5}[series]
    size = {"PH": (1.2, 1.75, 0.75), "XH": (1.7, 2.0, 1.0)}[series]
    x0 = -(n - 1) * pitch / 2
    pads = [Pad(str(i + 1), x0 + i * pitch, 0, size[0], size[1], "roundrect" if i == 0 else "oval", "tht", size[2],
                roundness=0.2) for i in range(n)]
    w = (n - 1) * pitch + (3.9 if series == "PH" else 4.9)
    d0, d1 = (-1.7, 2.8) if series == "PH" else (-2.35, 3.4)
    g = _rect(-w / 2, d0, w / 2, d1)
    model = {"type": "jst", "w": w, "y0": d0, "y1": d1, "H": 4.5 if series == "PH" else 7.0, "body": "#efe7d4",
             "pitch": pitch, "n": n}
    return _fp(f"JST_{series}_B{n}B_1x{n:02d}_P{pitch}mm", f"JST {series} {n}-pin vertical connector", pads, g,
               (-w / 2, d0, w / 2, d1), model)


def terminal_block(n: int, pitch: float = 5.08) -> Footprint:
    x0 = -(n - 1) * pitch / 2
    pads = [_tht_pad(str(i + 1), x0 + i * pitch, 0, 2.6, 1.3, square=(i == 0)) for i in range(n)]
    w = n * pitch
    g = _rect(-w / 2, -4.0, w / 2, 4.2)
    model = {"type": "terminal", "w": w, "y0": -4.0, "y1": 4.2, "H": 10.0, "body": "#2f7d4a", "pitch": pitch, "n": n}
    return _fp(f"TerminalBlock_1x{n:02d}_P{pitch}mm", f"Screw terminal block, {n} pins, {pitch} mm pitch", pads, g,
               (-w / 2, -4.0, w / 2, 4.2), model)


def tactile_switch() -> Footprint:
    """6x6 mm tactile switch (Omron B3F / E-Switch TL1105 land pattern).

    Pins in the same row (6.5 mm apart) are internally connected; the switch connects pin 1 to pin 2.
    """
    pads = [
        _tht_pad("1", -3.25, -2.25, 2.0, 1.1),
        _tht_pad("1", 3.25, -2.25, 2.0, 1.1),
        _tht_pad("2", -3.25, 2.25, 2.0, 1.1),
        _tht_pad("2", 3.25, 2.25, 2.0, 1.1),
    ]
    g = [_line(-3, -3.2, 3, -3.2), _line(-3, 3.2, 3, 3.2), _line(-3.2, -1.2, -3.2, 1.2), _line(3.2, -1.2, 3.2, 1.2),
         _circle(0, 0, 1.75)]
    model = {"type": "tact", "w": 6.0, "h": 6.0, "H": 3.5, "actuator": 3.5, "act_h": 1.5}
    return _fp("SW_PUSH_6mm", "Tactile push button, 6x6 mm, through-hole. Pins in the same row are internally "
               "connected; pressing connects pin 1 to pin 2", pads, g, (-3, -3, 3, 3), model)


def cap_radial(d: float, pitch: float, height: float) -> Footprint:
    # pad / drill by can diameter (manufacturer recommended hole sizes for the lead diameter)
    if d < 5:
        size, drill = 1.2, 0.6
    elif d < 10:
        size, drill = 1.6, 0.8
    elif d < 12:
        size, drill = 2.0, 1.0
    else:
        size, drill = 2.4, 1.2
    pads = [_tht_pad("1", -pitch / 2, 0, size, drill, square=True), _tht_pad("2", pitch / 2, 0, size, drill)]
    r = d / 2
    g = [_circle(0, 0, r + 0.1), _line(-r - 1.2, -r * 0.6, -r - 0.4, -r * 0.6), _line(-r - 0.8, -r * 0.6 - 0.4, -r - 0.8, -r * 0.6 + 0.4)]
    model = {"type": "radial_cap", "D": d, "H": height, "body": "#23336b", "stripe": "#d0d0d0"}
    return _fp(f"CP_Radial_D{d:g}mm_P{pitch:g}mm", f"Electrolytic capacitor, radial, D{d:g} mm, pitch {pitch:g} mm",
               pads, g, (-r, -r, r, r), model)


def led_tht(d: float) -> Footprint:
    pads = [_tht_pad("1", -1.27, 0, 1.8, 0.9, square=True), _tht_pad("2", 1.27, 0, 1.8, 0.9)]
    r = d / 2
    g = [_arc(0, 0, r + 0.3, -150, 300), _line(-r - 0.28, -r * 0.5, -r - 0.28, r * 0.5)]
    model = {"type": "led_tht", "D": d, "H": d + 3.6, "color": "#e03030"}
    return _fp(f"LED_D{d:g}mm", f"LED, {d:g} mm round, through-hole (pin 1 = cathode)", pads, g, (-r, -r, r, r), model)


def to220() -> Footprint:
    pads = [_tht_pad(str(i + 1), (i - 1) * 2.54, 0, 1.9, 1.1, square=(i == 0), shape=None) for i in range(3)]
    for p in pads:
        p.h = 2.2
        p.shape = "rect" if p.number == "1" else "oval"
    g = _rect(-5.2, -3.2, 5.2, 1.6)
    g.append(_line(-5.2, -2.0, 5.2, -2.0))
    model = {"type": "to220", "body": "#1c1c1c", "tab": "#c9c9c9"}
    return _fp("TO-220-3_Vertical", "TO-220-3 vertical (e.g. voltage regulator, MOSFET)", pads, g, (-5.2, -3.2, 5.2, 1.6), model)


def to92() -> Footprint:
    pads = [Pad(str(i + 1), (i - 1) * 1.27, 0, 1.05, 1.5, "rect" if i == 0 else "oval", "tht", 0.75) for i in range(3)]
    g = [_arc(0, -0.2, 2.45, 15, 150), _line(-2.3, 1.0, 2.3, 1.0), _arc(0, -0.2, 2.45, -35, -110)]
    model = {"type": "to92", "body": "#1a1a1a"}
    return _fp("TO-92_Inline", "TO-92 inline (e.g. transistor, LM35)", pads, g, (-2.4, -2.7, 2.4, 1.2), model)


def crystal_hc49() -> Footprint:
    pads = [_tht_pad("1", -2.44, 0, 1.5, 0.8), _tht_pad("2", 2.44, 0, 1.5, 0.8)]
    g = [_line(-3.1, -2.3, 3.1, -2.3), _line(-3.1, 2.3, 3.1, 2.3), _arc(-3.1, 0, 2.3, 90, 180), _arc(3.1, 0, 2.3, -90, 180)]
    model = {"type": "hc49", "L": 10.9, "W": 4.65, "H": 3.6}
    return _fp("Crystal_HC49-4H", "Crystal, HC-49/US low profile, through-hole", pads, g, (-5.45, -2.33, 5.45, 2.33), model)


def crystal_3225() -> Footprint:
    pads = [Pad("1", -1.1, 0.8, 1.4, 1.15, "roundrect"), Pad("2", 1.1, 0.8, 1.4, 1.15, "roundrect"),
            Pad("3", 1.1, -0.8, 1.4, 1.15, "roundrect"), Pad("4", -1.1, -0.8, 1.4, 1.15, "roundrect")]
    g = [_line(-2.1, 1.75, 2.1, 1.75), _line(-2.1, -1.75, -2.1, 1.75)]
    model = {"type": "xtal_smd", "L": 3.2, "W": 2.5, "H": 0.8}
    return _fp("Crystal_SMD_3225-4Pin", "Crystal, SMD 3.2x2.5 mm, 4 pads", pads, g, (-1.6, -1.25, 1.6, 1.25), model)


def diode_do41() -> Footprint:
    pads = [_tht_pad("1", -5.08, 0, 2.2, 1.1, square=True), _tht_pad("2", 5.08, 0, 2.2, 1.1)]
    g = _rect(-2.6, -1.5, 2.6, 1.5) + [_line(-1.8, -1.5, -1.8, 1.5, 0.3), _line(-3.8, 0, -2.6, 0), _line(3.8, 0, 2.6, 0)]
    model = {"type": "axial", "L": 5.2, "D": 2.7, "pitch": 10.16, "body": "#1a1a1a", "band": "#c8c8c8"}
    return _fp("D_DO-41_P10.16mm", "Diode, DO-41 axial, 10.16 mm pitch (pin 1 = cathode)", pads, g, (-6.2, -1.5, 6.2, 1.5), model)


def resistor_axial() -> Footprint:
    pads = [_tht_pad("1", -5.08, 0, 1.6, 0.8, square=True), _tht_pad("2", 5.08, 0, 1.6, 0.8)]
    g = _rect(-3.2, -1.3, 3.2, 1.3) + [_line(-4.0, 0, -3.2, 0), _line(4.0, 0, 3.2, 0)]
    model = {"type": "axial", "L": 6.3, "D": 2.5, "pitch": 10.16, "body": "#d8c39a", "band": None, "bands": True}
    return _fp("R_Axial_P10.16mm", "Resistor, axial 1/4 W, 10.16 mm pitch", pads, g, (-5.9, -1.3, 5.9, 1.3), model)


def mounting_hole(size: str, plated: bool) -> Footprint:
    drill = {"M1.6": 1.7, "M2": 2.2, "M2.5": 2.7, "M3": 3.2, "M4": 4.3, "M5": 5.3, "M6": 6.4}[size]
    pad = round(drill * 2, 3)  # plated ring = 2x drill (fits the screw head / washer)
    pads = [Pad("1", 0, 0, pad if plated else drill, pad if plated else drill, "circle", "tht" if plated else "npth", drill)]
    g = [_circle(0, 0, pad / 2 + 0.15, 0.12, "fab")]
    model = {"type": "none"}
    r = pad / 2
    return _fp(f"MountingHole_{size}{'_Pad' if plated else ''}",
               f"Mounting hole for {size} screw, {'plated' if plated else 'non-plated'}", pads, g, (-r, -r, r, r), model)


def testpoint() -> Footprint:
    pads = [Pad("1", 0, 0, 1.5, 1.5, "circle", paste=False)]
    return _fp("TestPoint_Pad_D1.5mm", "SMD test point pad, 1.5 mm", pads, [_circle(0, 0, 1.0)], (-0.75, -0.75, 0.75, 0.75),
               {"type": "none"})


def fiducial() -> Footprint:
    pads = [Pad("", 0, 0, 1.0, 1.0, "circle", paste=False, mask_margin=0.5)]
    return _fp("Fiducial_1mm", "Assembly fiducial, 1 mm copper, 2 mm mask opening", pads, [], (-1, -1, 1, 1), {"type": "none"})


def usb_c_receptacle() -> Footprint:
    """Generic 16-pin USB-C (USB 2.0) mid-mount receptacle land pattern (HRO TYPE-C-31-M-12 style)."""
    names = ["A1B12", "A4B9", "B8", "A5", "B7", "A6", "A7", "B6", "A8", "B5", "B4A9", "B1A12"]
    xs = [-3.2, -2.4, -1.75, -1.25, -0.75, -0.25, 0.25, 0.75, 1.25, 1.75, 2.4, 3.2]
    widths = [0.6, 0.6, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.6, 0.6]
    pads = [Pad(n, x, -3.745, w, 1.15, "rect") for n, x, w in zip(names, xs, widths)]
    for x in (-4.32, 4.32):
        pads.append(Pad("S1", x, -3.26, 1.0, 2.1, "oval", "tht", 0.6))
        pads.append(Pad("S1", x, 0.92, 1.0, 1.6, "oval", "tht", 0.6))
    pads.append(Pad("", -2.89, -2.6, 0.65, 0.65, "circle", "npth", 0.65))
    pads.append(Pad("", 2.89, -2.6, 0.65, 0.65, "circle", "npth", 0.65))
    g = [_line(-4.47, -1.9, -4.47, 0.0), _line(4.47, -1.9, 4.47, 0.0), _line(-4.47, 3.6, 4.47, 3.6, 0.1, "fab")]
    model = {"type": "usb_c", "w": 8.94, "y0": -3.5, "y1": 3.8, "H": 3.26}
    return _fp("USB_C_Receptacle_16P", "USB Type-C receptacle, USB 2.0, 16 pins (verify against datasheet)", pads, g,
               (-4.47, -3.6, 4.47, 3.8), model)


# --------------------------------------------------------------------------- library index

@dataclass
class LibPart:
    category: str
    name: str
    prefix: str
    value: str
    factory: Callable[[], Footprint]
    keywords: str = ""
    mpn: str = ""
    manufacturer: str = ""
    description: str = ""
    lcsc: str = ""
    source: str = "builtin"  # builtin | catalog | kicad | lcsc | user

    def make(self) -> Footprint:
        return self.factory()

    @property
    def search_text(self) -> str:
        return f"{self.category} {self.name} {self.value} {self.keywords} {self.mpn} {self.manufacturer} " \
               f"{self.description} {self.lcsc}".lower()


def _all_builtin() -> list[LibPart]:
    from ..library.builtin import build_builtin
    return build_builtin()


LIBRARY: list[LibPart] = _all_builtin()
_BY_NAME: dict[str, LibPart] = {}
for _p in LIBRARY:
    _BY_NAME.setdefault(_p.name, _p)


def find_part(name: str) -> LibPart | None:
    return _BY_NAME.get(name)
