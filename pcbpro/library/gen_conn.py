"""Connectors: headers, sockets, IDC, JST, Molex, terminal blocks, USB, power, RF, audio, D-Sub, FFC, cards."""
from __future__ import annotations

from ..model.board import Footprint, Pad
from .shapes import (B, BLACK, CYL, CYLY, DARK, GOLD, METAL, PRISM, VERIFY, _circle, _fp, _line, _rect, composite,
                     grid_tht, inline_tht, r4)

PITCH_PADS = {2.54: (1.7, 1.0), 2.0: (1.35, 0.8), 1.27: (1.0, 0.65)}


# --------------------------------------------------------------------------- headers & sockets

def header(cols: int, rows: int, pitch: float = 2.54, kind: str = "male", angle: str = "straight") -> Footprint:
    pad, drill = PITCH_PADS[pitch]
    pads = grid_tht(cols, rows, pitch, pad, drill)
    w, h = cols * pitch, rows * pitch
    g = _rect(-w / 2, -h / 2, w / 2, h / 2) + [_line(-w / 2 - 0.4, -h / 2, -w / 2 - 0.4, -h / 2 + pitch)]
    pin_w = {2.54: 0.32, 2.0: 0.25, 1.27: 0.2}[pitch]
    body_h = {2.54: 2.5, 2.0: 2.0, 1.27: 1.5}[pitch]
    parts = []
    if kind == "male" and angle == "straight":
        return _fp(f"PinHeader_{rows}x{cols:02d}_P{pitch:.2f}mm_Vertical",
                   f"Pin header, {rows}x{cols}, {pitch} mm pitch, vertical", pads, g, (-w / 2, -h / 2, w / 2, h / 2),
                   {"type": "header", "cols": cols, "rows": rows, "pitch": pitch, "body": "#161616", "pin": "#d9b44a"})
    if kind == "male":  # right angle: body stands at the board edge side (+y), pins bend towards it
        yb = h / 2 + 1.5
        parts.append(B(-w / 2, yb, 0, w / 2, yb + body_h, pitch * rows, BLACK))
        for p in pads:
            row_i = round((p.y + h / 2 - pitch / 2) / pitch)
            z = pitch * (row_i + 0.5)
            parts.append(B(p.x - pin_w, p.y - pin_w, -3.0, p.x + pin_w, p.y + pin_w, z + pin_w, GOLD, True))
            parts.append(B(p.x - pin_w, p.y - pin_w, z - pin_w, p.x + pin_w, yb + body_h + 6.0, z + pin_w, GOLD, True))
        name = f"PinHeader_{rows}x{cols:02d}_P{pitch:.2f}mm_Horizontal"
        desc = f"Pin header, {rows}x{cols}, {pitch} mm pitch, right angle"
        body = (-w / 2, -h / 2, w / 2, yb + body_h)
        g = _rect(-w / 2, yb, w / 2, yb + body_h) + [_line(-w / 2 - 0.4, -h / 2, -w / 2 - 0.4, -h / 2 + pitch)]
    else:
        H = {2.54: 8.5, 2.0: 6.4, 1.27: 4.4}[pitch]
        parts.append(B(-w / 2, -h / 2, 0, w / 2, h / 2, H, BLACK))
        for p in pads:
            parts.append(B(p.x - pin_w * 1.3, p.y - pin_w * 1.3, H - 0.8, p.x + pin_w * 1.3, p.y + pin_w * 1.3, H + 0.005,
                           DARK))
        name = f"PinSocket_{rows}x{cols:02d}_P{pitch:.2f}mm_Vertical"
        desc = f"Female pin socket, {rows}x{cols}, {pitch} mm pitch, vertical"
        body = (-w / 2, -h / 2, w / 2, h / 2)
    model = composite(*parts, pins="tht", pin_top=0.4 if kind == "female" else 0.1, pin_color=GOLD)
    return _fp(name, desc, pads, g, body, model)


def idc_box(n: int) -> Footprint:
    cols = n // 2
    pads = grid_tht(cols, 2, 2.54, 1.7, 1.0)
    L = cols * 2.54 + 10.16
    W = 8.9
    g = _rect(-L / 2, -W / 2, L / 2, W / 2) + [_line(-2.2, W / 2, -2.2, W / 2 - 1.2), _line(2.2, W / 2, 2.2, W / 2 - 1.2),
                                                 _line(-2.2, W / 2 - 1.2, 2.2, W / 2 - 1.2)]
    wall = 0.9
    model = composite(B(-L / 2, -W / 2, 0, L / 2, W / 2, 1.5, BLACK),
                      B(-L / 2, -W / 2, 0, -L / 2 + wall, W / 2, 8.9, BLACK), B(L / 2 - wall, -W / 2, 0, L / 2, W / 2, 8.9, BLACK),
                      B(-L / 2, -W / 2, 0, L / 2, -W / 2 + wall, 8.9, BLACK),
                      B(-L / 2, W / 2 - wall, 0, -2.2, W / 2, 8.9, BLACK), B(2.2, W / 2 - wall, 0, L / 2, W / 2, 8.9, BLACK),
                      *[B(p.x - 0.32, p.y - 0.32, 1.5, p.x + 0.32, p.y + 0.32, 7.5, GOLD, True) for p in pads],
                      pins="tht", pin_top=1.5, pin_color=GOLD)
    return _fp(f"IDC-Header_2x{cols:02d}_P2.54mm_Vertical", f"Shrouded IDC box header, 2x{cols} ({n} pins), 2.54 mm",
               pads, g, (-L / 2, -W / 2, L / 2, W / 2), model)


# --------------------------------------------------------------------------- wire-to-board

WTB = {  # series: (pitch, pad_w, pad_h, drill, body_front, body_back, height, color, extra_w)
    "JST_PH": (2.0, 1.2, 1.75, 0.75, -1.7, 2.8, 4.5, "#efe7d4", 3.9),
    "JST_XH": (2.5, 1.7, 2.0, 1.0, -2.35, 3.4, 7.0, "#efe7d4", 4.9),
    "JST_EH": (2.5, 1.7, 1.95, 0.95, -1.6, 2.6, 6.0, "#efe7d4", 2.5),
    "JST_VH": (3.96, 2.7, 2.7, 1.7, -3.7, 4.8, 9.4, "#efe7d4", 3.9),
    "JST_ZH": (1.5, 1.03, 1.73, 0.73, -1.6, 2.2, 3.5, "#efe7d4", 3.0),
    "Molex_KK-254": (2.54, 1.7, 2.0, 1.2, -2.9, 3.1, 6.3, "#f3f1ea", 0.0),
    "Molex_PicoBlade": (1.25, 0.8, 1.3, 0.5, -1.0, 2.2, 4.0, "#efe7d4", 2.7),
    "Molex_Micro-Fit_1xN": (3.0, 1.9, 1.9, 1.02, -2.7, 4.6, 9.6, BLACK, 2.3),
}


def wire_to_board(series: str, n: int) -> Footprint:
    pitch, pw, ph, drill, y0, y1, H, color, extra = WTB[series]
    x0 = -(n - 1) * pitch / 2
    pads = [Pad(str(i + 1), r4(x0 + i * pitch), 0, pw, ph, "roundrect" if i == 0 else "oval", "tht", drill,
                roundness=0.2) for i in range(n)]
    w = (n - 1) * pitch + extra + pw
    g = _rect(-w / 2, y0, w / 2, y1)
    wall = 0.6 if pitch < 3 else 0.9
    model = composite(B(-w / 2, y0, 0, w / 2, y1, 1.0, color),
                      B(-w / 2, y0, 0, -w / 2 + wall, y1, H, color), B(w / 2 - wall, y0, 0, w / 2, y1, H, color),
                      B(-w / 2, y1 - wall, 0, w / 2, y1, H, color), B(-w / 2, y0, 0, w / 2, y0 + wall, H * 0.75, color),
                      *[B(p.x - 0.3, -0.3, 0.5, p.x + 0.3, 0.3, H - 0.8, GOLD, True) for p in pads],
                      pins="tht", pin_top=1.0, pin_color=GOLD)
    label = series.replace("_", " ")
    return _fp(f"{series}_1x{n:02d}_P{pitch:g}mm_Vertical", f"{label} wire-to-board header, {n} pins, {pitch} mm pitch, "
               "vertical", pads, g, (-w / 2, y0, w / 2, y1), model)


def molex_dual(series: str, n_per_row: int) -> Footprint:
    """Molex Micro-Fit 3.0 (43045, 3.0 mm) / Mini-Fit Jr (5566, 4.2 mm) dual-row headers, vertical.

    Numbering follows Molex: pins 1..n along the first row, n+1..2n along the second row.
    """
    if series == "Micro-Fit":
        pitch, row, pw, ph, drill, H, shape = 3.0, 3.0, 1.5, 1.5, 1.02, 9.6, "circle"
    else:
        pitch, row, pw, ph, drill, H, shape = 4.2, 5.5, 2.7, 3.3, 1.4, 13.5, "oval"
    from .shapes import row_major_tht
    pads = row_major_tht(n_per_row, 2, pitch, row, pw, ph, drill, shape)
    w, h = n_per_row * pitch + 2.0, row + 5.0
    g = _rect(-w / 2, -h / 2, w / 2, h / 2)
    model = composite(B(-w / 2, -h / 2, 0, w / 2, h / 2, H, BLACK), *[B(p.x - pitch * 0.35, p.y - pitch * 0.35, H - 3.0,
                                                                          p.x + pitch * 0.35, p.y + pitch * 0.35, H + 0.01,
                                                                          DARK) for p in pads],
                      pins="tht", pin_top=0.5)
    return _fp(f"Molex_{series}_2x{n_per_row:02d}_Vertical", f"Molex {series} dual row header, 2x{n_per_row}, {pitch} mm "
               f"pitch, {row} mm row spacing, vertical", pads, g, (-w / 2, -h / 2, w / 2, h / 2), model)


SMD_WTB = {  # series: (pitch, pad_w, pad_h, pad_y, mount_w, mount_h, mount_x_extra, mount_y, body_w_extra, body_d, H)
    "JST_SH": (1.0, 0.6, 1.55, -2.0, 1.2, 1.8, 1.3, 1.875, 3.0, 4.25, 2.95),
    "JST_GH": (1.25, 0.6, 1.7, -1.85, 1.0, 2.7, 1.85, 1.35, 4.0, 4.25, 4.25),
    "JST_PH_SMD": (2.0, 1.0, 3.5, -2.85, 1.5, 3.4, 2.35, 2.9, 5.5, 5.5, 5.0),
}


def wire_to_board_smd(series: str, n: int) -> Footprint:
    pitch, pw, ph, py, mw, mh, mx, my, bwx, bd, H = SMD_WTB[series]
    x0 = -(n - 1) * pitch / 2
    pads = [Pad(str(i + 1), r4(x0 + i * pitch), py, pw, ph, "roundrect") for i in range(n)]
    span = (n - 1) * pitch / 2 + mx
    pads += [Pad("MP", -span, my, mw, mh, "roundrect"), Pad("MP", span, my, mw, mh, "roundrect")]
    w = (n - 1) * pitch + bwx
    g = _rect(-w / 2, py + ph / 2 + 0.1, w / 2, py + ph / 2 + 0.1 + bd)
    model = composite(B(-w / 2, py + ph / 2 - 0.2, 0, w / 2, py + ph / 2 + bd, H, "#efe7d4"),
                      B(-w / 2 + 0.5, py + ph / 2, H * 0.3, w / 2 - 0.5, py + ph / 2 + 0.4, H - 0.4, "#b8ae98"))
    label = series.replace("_", " ")
    y1 = max(py + ph / 2 + bd, my + mh / 2)
    return _fp(f"{series}_1x{n:02d}_P{pitch:g}mm_Horizontal", f"{label} SMD wire-to-board connector, {n} pins, side entry "
               "(JST SM##B series land pattern)", pads, g, (-w / 2, py - ph / 2, w / 2, y1), model)


# --------------------------------------------------------------------------- terminal blocks

TERMINAL_PITCH = {2.54: (1.7, 1.0, 6.5, 8.0), 3.5: (2.2, 1.2, 7.0, 8.5), 3.81: (2.2, 1.2, 7.2, 9.0),
                  5.0: (2.6, 1.3, 9.0, 10.0), 5.08: (2.6, 1.3, 9.0, 10.0), 7.5: (3.0, 1.5, 10.5, 13.0),
                  10.16: (3.5, 1.8, 12.0, 15.0)}


def terminal(n: int, pitch: float) -> Footprint:
    pad, drill, depth, H = TERMINAL_PITCH[pitch]
    pads = inline_tht(n, pitch, pad, drill)
    w = n * pitch
    y0, y1 = -depth * 0.45, depth * 0.55
    g = _rect(-w / 2, y0, w / 2, y1)
    model = {"type": "terminal", "w": w, "y0": y0, "y1": y1, "H": H, "body": "#2f7d4a" if pitch >= 5 else "#2d5fa8",
             "pitch": pitch, "n": n}
    return _fp(f"TerminalBlock_1x{n:02d}_P{pitch:g}mm", f"Screw terminal block, {n} poles, {pitch} mm pitch", pads, g,
               (-w / 2, y0, w / 2, y1), model)


# --------------------------------------------------------------------------- USB

def usb_c_16p() -> Footprint:
    """USB Type-C receptacle, USB 2.0, 16 pins, mid-mount (HRO TYPE-C-31-M-12 land pattern).

    Paired contacts (e.g. A1/B12) share one pad; the pad names list both pins.
    """
    names = ["A1B12", "A4B9", "B8", "A5", "B7", "A6", "A7", "B6", "A8", "B5", "B4A9", "B1A12"]
    xs = [-3.25, -2.45, -1.75, -1.25, -0.75, -0.25, 0.25, 0.75, 1.25, 1.75, 2.45, 3.25]
    widths = [0.6, 0.6, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.6, 0.6]
    pads = [Pad(nm, x, -4.045, w, 1.45, "rect") for nm, x, w in zip(names, xs, widths)]
    for x in (-4.32, 4.32):
        pads.append(Pad("SH", x, -3.13, 1.0, 2.1, "oval", "tht", 0.6, drill_h=1.7))
        pads.append(Pad("SH", x, 1.05, 1.0, 1.6, "oval", "tht", 0.6, drill_h=1.2))
    pads.append(Pad("", -2.89, -2.6, 0.65, 0.65, "circle", "npth", 0.65))
    pads.append(Pad("", 2.89, -2.6, 0.65, 0.65, "circle", "npth", 0.65))
    g = [_line(-4.47, -1.9, -4.47, 0.0), _line(4.47, -1.9, 4.47, 0.0), _line(-4.47, 3.6, 4.47, 3.6, 0.1, "fab")]
    model = {"type": "usb_c", "w": 8.94, "y0": -3.5, "y1": 3.8, "H": 3.26}
    return _fp("USB_C_Receptacle_HRO_TYPE-C-31-M-12", "USB Type-C receptacle, USB 2.0, 16 pins, mid-mount "
               "(HRO TYPE-C-31-M-12 / LCSC C165948)", pads, g, (-4.47, -4.77, 4.47, 3.8), model)


def usb_c_6p() -> Footprint:
    """USB Type-C receptacle, power only, 6 pins, top mount (GCT USB4125 land pattern)."""
    spec = [("B12", -2.75, 0.8), ("B9", -1.52, 0.76), ("A5", -0.5, 0.7), ("B5", 0.5, 0.7), ("A9", 1.52, 0.76),
            ("A12", 2.75, 0.8)]
    pads = [Pad(nm, x, -3.08, w, 1.2, "roundrect") for nm, x, w in spec]
    for x in (-4.32, 4.32):
        pads.append(Pad("SH", x, -3.0, 1.1, 1.7, "oval", "tht", 0.6, drill_h=1.2))
        pads.append(Pad("SH", x, 0.8, 1.1, 1.7, "oval", "tht", 0.6, drill_h=1.2))
    g = [_line(-4.47, -1.9, -4.47, -0.2), _line(4.47, -1.9, 4.47, -0.2)]
    model = {"type": "usb_c", "w": 8.94, "y0": -3.4, "y1": 3.4, "H": 3.2}
    return _fp("USB_C_Receptacle_GCT_USB4125_6P", "USB Type-C receptacle, power only (6 pins: GND A12/B12, VBUS A9/B9, "
               "CC1 A5, CC2 B5), GCT USB4125 land pattern", pads, g, (-5.0, -4.0, 5.0, 3.4), model)


def usb_micro_b() -> Footprint:
    """USB Micro-B receptacle, mid-mount SMD (Molex 47346-0001 land pattern)."""
    pads = [Pad(str(i + 1), r4(-1.3 + i * 0.65), -1.46, 0.45, 1.38, "roundrect") for i in range(5)]
    for x, y, w, h in ((-3.375, 1.2, 1.65, 1.3), (-2.4875, -1.375, 1.425, 1.55), (-1.15, 1.2, 1.8, 1.9),
                       (1.55, 1.2, 1.0, 1.9), (2.4875, -1.375, 1.425, 1.55), (3.375, 1.2, 1.65, 1.3)):
        pads.append(Pad("SH", x, y, w, h, "roundrect"))
    g = [_line(-3.75, 2.65, 3.75, 2.65, 0.1, "fab")]
    model = composite(B(-3.75, -1.65, 0, 3.75, 3.35, 2.5, METAL, True), B(-2.8, 3.05, 0.5, 2.8, 3.4, 2.0, DARK))
    return _fp("USB_Micro-B_Molex_47346-0001", "USB Micro-B receptacle, mid-mount SMD (Molex 47346-0001)", pads, g,
               (-4.2, -2.15, 4.2, 3.35), model)


def usb_mini_b() -> Footprint:
    """USB Mini-B receptacle, horizontal SMD (Lumberg 2486 01 land pattern)."""
    pads = [Pad(str(i + 1), r4(-1.6 + i * 0.8), -2.7, 0.5, 2.0, "roundrect") for i in range(5)]
    for x, y in ((-4.45, -2.6), (-4.45, 2.85), (4.45, -2.6), (4.45, 2.85)):
        pads.append(Pad("SH", x, y, 2.0, 1.7, "roundrect"))
    pads += [Pad("", -2.2, 0, 1.0, 1.0, "circle", "npth", 1.0), Pad("", 2.2, 0, 1.0, 1.0, "circle", "npth", 1.0)]
    model = composite(B(-3.85, -3.35, 0, 3.85, 5.85, 4.0, METAL, True), B(-2.9, 5.5, 0.8, 2.9, 5.9, 3.2, DARK))
    return _fp("USB_Mini-B_Lumberg_2486_01", "USB Mini-B receptacle, horizontal SMD (Lumberg 2486 01)", pads, [],
               (-5.45, -3.7, 5.45, 5.85), model)


def usb_a() -> Footprint:
    """USB Type-A receptacle, through-hole, horizontal (Molex 67643 land pattern)."""
    xs = [-3.5, -1.0, 1.0, 3.5]
    pads = [Pad(str(i + 1), x, 0, 1.6, 1.5 if i == 0 else 1.6, "roundrect" if i == 0 else "circle", "tht", 0.95)
            for i, x in enumerate(xs)]
    pads += [Pad("SH", -6.57, 2.71, 3.0, 3.0, "circle", "tht", 2.3), Pad("SH", 6.57, 2.71, 3.0, 3.0, "circle", "tht", 2.3)]
    g = _rect(-7.2, -2.27, 7.2, 12.99)
    model = composite(B(-7.0, -0.8, 0, 7.0, 12.99, 7.0, METAL, True), B(-6.0, 12.7, 1.0, 6.0, 13.05, 6.0, DARK),
                      B(-5.0, 5.0, 3.0, 5.0, 12.95, 4.5, "#f0f0f0"), pins="tht")
    return _fp("USB_A_Molex_67643_Horizontal", "USB Type-A receptacle, through-hole, horizontal (Molex 67643)", pads, g,
               (-8.1, -2.27, 8.1, 12.99), model)


def usb_b() -> Footprint:
    """USB Type-B receptacle, through-hole, horizontal (OST USB-B1HSxx land pattern)."""
    pads = [Pad("1", 0, 0, 1.7, 1.7, "roundrect", "tht", 0.92), Pad("2", 0, 2.5, 1.7, 1.7, "circle", "tht", 0.92),
            Pad("3", 2.0, 2.5, 1.7, 1.7, "circle", "tht", 0.92), Pad("4", 2.0, 0, 1.7, 1.7, "circle", "tht", 0.92),
            Pad("SH", 4.71, -4.77, 3.5, 3.5, "circle", "tht", 2.33), Pad("SH", 4.71, 7.27, 3.5, 3.5, "circle", "tht", 2.33)]
    g = _rect(-1.49, -4.8, 15.01, 7.3)
    model = composite(B(-1.49, -4.8, 0, 15.01, 7.3, 11.0, METAL, True), B(14.7, -3.0, 1.5, 15.05, 5.5, 9.5, DARK),
                      pins="tht")
    return _fp("USB_B_OST_USB-B1HSxx_Horizontal", "USB Type-B receptacle, through-hole (OST USB-B1HSxx)", pads, g,
               (-1.49, -6.52, 15.01, 9.02), model)


# --------------------------------------------------------------------------- power / RF / audio

def barrel_jack() -> Footprint:
    """DC barrel jack 5.5 x 2.1 mm, horizontal (CUI PJ-102AH land pattern). Plug opening towards +Y."""
    pads = [Pad("1", 0, 0, 2.6, 2.6, "rect", "tht", 1.6), Pad("2", 0, 6.0, 2.6, 2.6, "circle", "tht", 1.6),
            Pad("3", 4.7, 3.0, 2.6, 2.6, "circle", "tht", 1.6)]
    g = _rect(-4.5, -0.7, 4.5, 13.7)
    model = composite(B(-4.5, -0.7, 0, 4.5, 13.7, 11.0, BLACK),
                      {"s": "cyly", "p": [9.0, 13.75, 0, 6.3, 3.0], "c": "#0a0a0a", "m": 0},
                      {"s": "cyly", "p": [5.0, 13.8, 0, 6.3, 1.0], "c": METAL, "m": 1}, pins="tht")
    return _fp("BarrelJack_CUI_PJ-102AH_Horizontal", "DC barrel jack 5.5 x 2.1 mm, horizontal (CUI PJ-102AH). "
               "1 = centre pin, 2 = sleeve, 3 = switch", pads, g, (-4.5, -1.3, 6.0, 13.7), model)


def rj45() -> Footprint:
    """RJ45 8P8C modular jack, horizontal, no magnetics (Amphenol 54602-x08 land pattern)."""
    pads = [Pad(str(i + 1), r4(i * 1.27), 0 if i % 2 == 0 else -2.54, 1.5, 1.5, "rect" if i == 0 else "circle", "tht",
                0.76) for i in range(8)]
    pads += [Pad("", -1.27, 6.35, 3.2, 3.2, "circle", "npth", 3.2), Pad("", 10.16, 6.35, 3.2, 3.2, "circle", "npth", 3.2)]
    g = _rect(-3.205, -3.77, 12.095, 13.97)
    model = composite(B(-3.2, -3.77, 0, 12.09, 13.97, 13.5, METAL, True), B(-1.2, 13.7, 1.5, 10.1, 14.0, 10.0, DARK),
                      pins="tht")
    return _fp("RJ45_Amphenol_54602-x08_Horizontal", "RJ45 8P8C modular jack, horizontal (Amphenol 54602-x08)", pads, g,
               (-3.205, -3.77, 12.095, 13.97), model)


def sma_edge() -> Footprint:
    """SMA jack, PCB edge mount for 1.6 mm boards (Samtec SMA-J-P-H-ST-EM1). Board edge at X = -1.7, cable to +X."""
    pads = [Pad("1", 0, 0, 3.2, 1.27, "roundrect", paste=False),
            Pad("2", -0.25, -2.825, 3.7, 1.35, "roundrect", paste=False),
            Pad("2", -0.25, 2.825, 3.7, 1.35, "roundrect", paste=False)]
    model = composite(B(-1.7, -3.175, -1.7, 1.6, 3.175, 1.7, "#d7b24f", True),
                      {"s": "cylx", "p": [1.6, 11.6, 0, 0.8, 3.1], "c": "#d7b24f", "m": 1},
                      {"s": "cylx", "p": [11.55, 11.62, 0, 0.8, 2.1], "c": "#f2f2f2", "m": 0})
    return _fp("SMA_Samtec_SMA-J-P-H-ST-EM1_EdgeMount", "SMA jack, PCB edge mount (Samtec SMA-J-P-H-ST-EM1, 1.6 mm "
               "board). Place with the body overhanging the board edge", pads, [], (-2.1, -3.5, 11.62, 3.5), model)


def sma_vertical() -> Footprint:
    pads = [Pad("1", 0, 0, 1.6, 1.6, "circle", "tht", 1.5)]
    for sx in (-1, 1):
        for sy in (-1, 1):
            pads.append(Pad("2", sx * 2.54, sy * 2.54, 2.2, 2.2, "rect", "tht", 1.6))
    g = _rect(-3.2, -3.2, 3.2, 3.2)
    model = composite(B(-3.15, -3.15, 0, 3.15, 3.15, 1.6, "#d7b24f", True), CYL(0, 0, 1.6, 11.0, 3.1, "#d7b24f", True),
                      CYL(0, 0, 11.0, 11.05, 2.1, "#f2f2f2"), pins="tht", pin_color=GOLD)
    return _fp("SMA_Vertical_THT", "SMA jack, vertical through-hole", pads, g, (-3.4, -3.4, 3.4, 3.4), model)


def ufl() -> Footprint:
    pads = [Pad("1", 0, 1.5, 1.0, 1.05, "rect"), Pad("2", -1.475, 0, 1.05, 2.2, "rect"), Pad("2", 1.475, 0, 1.05, 2.2, "rect")]
    model = composite(B(-1.3, -1.3, 0, 1.3, 1.3, 0.3, "#e8e3d4"), CYL(0, 0, 0.3, 1.25, 1.0, "#d7b24f", True, seg=24))
    return _fp("U.FL_Receptacle", "U.FL / IPEX MHF1 coaxial receptacle (Hirose U.FL-R-SMT style)." + VERIFY, pads, [],
               (-2.0, -1.3, 2.0, 2.1), model)


def audio_jack_smd() -> Footprint:
    """3.5 mm stereo audio jack, SMD (PJ-320D land pattern). Plug opening towards -X. T tip, R1/R2 ring, S sleeve."""
    pads = [Pad("R1", -0.175, -3.25, 1.2, 2.5, "rect"), Pad("R2", -3.175, -3.25, 1.2, 2.5, "rect"),
            Pad("S", 4.925, 3.25, 1.2, 2.5, "rect"), Pad("T", 3.825, -3.25, 1.2, 2.5, "rect"),
            Pad("", -4.775, 0, 1.5, 1.5, "circle", "npth", 1.5), Pad("", 2.225, 0, 1.5, 1.5, "circle", "npth", 1.5)]
    g = _rect(-6.225, -2.9, 5.575, 2.9)
    model = composite(B(-6.225, -2.9, 0, 5.575, 2.9, 5.0, BLACK),
                      {"s": "cylx", "p": [-8.225, -6.2, 0, 2.5, 2.5], "c": "#0a0a0a", "m": 0})
    return _fp("Jack_3.5mm_PJ320D_Horizontal", "3.5 mm stereo audio jack, SMD (PJ-320D)", pads, g,
               (-8.225, -4.5, 5.575, 4.5), model)


def audio_jack_tht() -> Footprint:
    """3.5 mm stereo audio jack, through-hole, horizontal (CUI SJ1-3523N). T tip, R ring, S sleeve; slotted pins."""
    pads = [Pad("R", -5.0, -5.0, 1.2, 2.2, "oval", "tht", 0.4, drill_h=1.4),
            Pad("S", 0.0, 0.0, 2.2, 1.2, "oval", "tht", 1.4, drill_h=0.4),
            Pad("T", 5.0, -5.0, 1.2, 2.2, "oval", "tht", 0.4, drill_h=1.4)]
    for x, y in ((-5.0, 0.0), (-5.0, 2.5), (0.0, -5.0), (5.0, 0.0), (5.0, 2.5)):
        pads.append(Pad("", x, y, 1.2, 1.2, "circle", "npth", 1.2))
    g = _rect(-6.0, -7.7, 6.0, 6.3)
    model = composite(B(-6.0, -7.7, 0, 6.0, 6.3, 5.0, BLACK),
                      {"s": "cyly", "p": [6.3, 9.3, 0, 2.5, 3.0], "c": BLACK, "m": 0}, pins="tht")
    return _fp("Jack_3.5mm_CUI_SJ1-3523N_Horizontal", "3.5 mm stereo audio jack, through-hole (CUI SJ1-3523N)", pads, g,
               (-6.0, -7.7, 6.0, 9.3), model)


def microsd() -> Footprint:
    """microSD card socket, push-push, SMD (Hirose DM3AT-SF-PEJM5 land pattern)."""
    xs = [2.775, 1.675, 0.575, -0.525, -1.625, -2.725, -3.825, -4.925, -5.875]
    pads = [Pad(str(i + 1), x, -7.725, 0.7, 1.2, "rect") for i, x in enumerate(xs)]
    pads.append(Pad("10", -6.825, 2.775, 1.0, 0.8, "rect"))
    for x, y, w, h in ((-6.825, -3.425, 1.0, 1.2), (-6.825, 6.925, 1.0, 2.8), (4.325, -7.725, 1.0, 1.2),
                       (6.675, 7.375, 1.3, 1.9)):
        pads.append(Pad("SH", x, y, w, h, "rect"))
    model = composite(B(-6.4, -7.2, 0, 6.4, 7.7, 1.4, METAL, True))
    return _fp("microSD_Hirose_DM3AT-SF-PEJM5", "microSD card socket, push-push, SMD (Hirose DM3AT-SF-PEJM5). "
               "Pin 9 and 10 = card-detect switch", pads, [], (-7.4, -8.4, 7.4, 8.4), model)


def sim_socket() -> Footprint:
    """Micro SIM card socket, SMD (JAE SF53S006VCBR2000). C1-C3 / C5-C7 contacts."""
    spec = [("1", 2.755), ("2", 0.215), ("3", -2.325), ("5", 4.025), ("6", 1.485), ("7", -1.055)]
    pads = [Pad(n, x, -6.62, 0.65, 1.15, "roundrect") for n, x in spec]
    for x, y, w, h in ((-6.27, -4.45, 0.45, 1.3), (-6.27, -2.45, 0.45, 1.3), (-6.105, 7.11, 1.4, 1.7),
                       (-2.535, 6.53, 0.54, 0.8), (2.545, 6.53, 0.54, 0.8), (6.105, 7.11, 1.4, 1.7),
                       (6.27, -4.45, 0.45, 1.3), (6.27, -2.45, 0.45, 1.3)):
        pads.append(Pad("SH", x, y, w, h, "roundrect"))
    model = composite(B(-6.0, -7.05, 0, 6.0, 8.4, 1.4, METAL, True))
    return _fp("microSIM_JAE_SF53S006VCBR2000", "Micro SIM card socket, SMD (JAE SF53S006VCBR2000)", pads, [],
               (-6.6, -7.3, 6.6, 8.4), model)


def dsub(pins: int, female: bool) -> Footprint:
    rows = {9: (5, 4), 15: (8, 7), 25: (13, 12), 37: (19, 18)}[pins]
    hole = {9: 12.5, 15: 16.66, 25: 23.52, 37: 31.75}[pins]
    pitch, rowp = 2.77, 2.84
    pads = []
    n = 1
    x0 = -(rows[0] - 1) * pitch / 2
    order1 = range(rows[0])
    order2 = range(rows[1])
    sgn = -1 if female else 1
    for i in order1:
        pads.append(Pad(str(n), r4(sgn * (x0 + i * pitch)), -rowp / 2, 1.6, 1.6, "rect" if n == 1 else "circle", "tht", 1.0))
        n += 1
    for i in order2:
        pads.append(Pad(str(n), r4(sgn * (x0 + pitch / 2 + i * pitch)), rowp / 2, 1.6, 1.6, "circle", "tht", 1.0))
        n += 1
    pads += [Pad("SH", -hole, 0.0, 4.0, 4.0, "circle", "tht", 3.2), Pad("SH", hole, 0.0, 4.0, 4.0, "circle", "tht", 3.2)]
    w = 2 * hole + 6.4
    g = _rect(-w / 2, -3.0, w / 2, 8.0)
    shell_w = rows[0] * pitch + 4.0
    model = composite(B(-w / 2, 1.0, 0, w / 2, 1.9, 12.5, METAL, True), B(-shell_w / 2, 1.9, 2.0, shell_w / 2, 8.0, 10.5,
                                                                          METAL, True),
                      B(-(w / 2 - 1), -3.0, 0, w / 2 - 1, 1.0, 8.0, BLACK), pins="tht")
    kind = "female (socket)" if female else "male (plug)"
    return _fp(f"DSUB-{pins}_{'Female' if female else 'Male'}_Horizontal",
               f"D-Sub {pins}-pin {kind}, right-angle PCB mount, 2.77 mm pitch.", pads, g, (-w / 2, -3.0, w / 2, 8.0),
               model)


def ffc(n: int, pitch: float) -> Footprint:
    x0 = -(n - 1) * pitch / 2
    pw = 0.3 if pitch <= 0.5 else 0.6
    pads = [Pad(str(i + 1), r4(x0 + i * pitch), -1.85, pw, 1.3, "rect") for i in range(n)]
    span = (n - 1) * pitch / 2 + 1.9
    pads += [Pad("MP", -span, 1.4, 1.8, 2.2, "rect"), Pad("MP", span, 1.4, 1.8, 2.2, "rect")]
    w = (n - 1) * pitch + 5.0
    model = composite(B(-w / 2, -1.2, 0, w / 2, 3.0, 2.0, "#f0ece0"), B(-w / 2 + 0.5, 2.2, 2.0, w / 2 - 0.5, 3.4, 2.4, BLACK))
    return _fp(f"FFC_FPC_1x{n:02d}_P{pitch:g}mm_Horizontal", f"FFC/FPC connector, {n} contacts, {pitch} mm pitch, "
               "horizontal SMD (Hirose FH12 style land pattern; other brands differ - check the datasheet)", pads, [],
               (-w / 2, -2.5, w / 2, 3.4), model)


# --------------------------------------------------------------------------- batteries & wire pads

def battery_cr2032_smd() -> Footprint:
    """CR2032 coin cell holder, SMD (Keystone 3034). The negative contact is the round pad on the PCB (pin 2)."""
    pads = [Pad("1", -10.985, 0, 1.27, 5.08, "rect"), Pad("1", 10.985, 0, 1.27, 5.08, "rect"),
            Pad("2", 0, 0, 17.8, 17.8, "circle", paste=False)]
    g = [_circle(0, 0, 10.2)]
    model = composite(CYL(0, 0, 0.3, 3.5, 10.0, "#d2d5da", True, seg=48), B(-10.63, -6.0, 0, -9.6, 6.0, 3.8, METAL, True),
                      B(9.6, -6.0, 0, 10.63, 6.0, 3.8, METAL, True), B(-6.0, 8.0, 0, 6.0, 12.0, 3.8, METAL, True))
    return _fp("BatteryHolder_Keystone_3034_1x20mm", "CR2032 coin cell holder, SMD (Keystone 3034). Pin 1 = +, "
               "pin 2 = the gold pad under the cell (-)", pads, g, (-11.62, -10.2, 11.62, 12.0), model)


def battery_cr2032_tht() -> Footprint:
    """20 mm coin cell holder (CR2032), through-hole (Keystone 106 land pattern). Pin 1 = +."""
    pads = [Pad("1", 0, 0, 3.0, 3.0, "rect", "tht", 1.5), Pad("2", 20.49, 0, 3.0, 3.0, "circle", "tht", 1.5)]
    g = [_circle(13.6, 0, 10.5)]
    model = composite(CYL(13.6, 0, 0.3, 4.2, 10.0, BLACK, seg=48), CYL(13.6, 0, 4.2, 4.3, 8.0, "#d2d5da", True, seg=48),
                      B(-1.5, -2.5, 0, 3.0, 2.5, 4.5, METAL, True), pins="tht")
    return _fp("BatteryHolder_Keystone_106_1x20mm", "CR2032 (20 mm) coin cell holder, through-hole (Keystone 106)",
               pads, g, (-1.9, -13.85, 29.05, 13.85), model)


def battery_18650() -> Footprint:
    """Single 18650 Li-ion cell holder, SMD (Keystone 1042 land pattern)."""
    pads = [Pad("1", -39.69, 0, 7.5, 6.5, "roundrect"), Pad("2", 39.69, 0, 7.5, 6.5, "roundrect"),
            Pad("", -36.13, -8.0, 2.39, 2.39, "circle", "npth", 2.39), Pad("", -27.62, 8.0, 3.45, 3.45, "circle", "npth", 3.45),
            Pad("", 27.62, -8.0, 3.45, 3.45, "circle", "npth", 3.45)]
    g = _rect(-38.53, -10.325, 38.53, 10.325)
    model = composite(B(-38.5, -10.3, 0, 38.5, 10.3, 2.0, BLACK),
                      {"s": "cylx", "p": [-32.5, 32.5, 0, 11.0, 9.1], "c": "#2b58c7", "m": 0},
                      B(-41.0, -3.0, 0, -36.0, 3.0, 12.0, METAL, True), B(36.0, -3.0, 0, 41.0, 3.0, 12.0, METAL, True))
    return _fp("BatteryHolder_Keystone_1042_1x18650", "Single 18650 Li-ion cell holder, SMD (Keystone 1042)", pads, g,
               (-43.44, -10.325, 43.44, 10.325), model)


def battery_aa2() -> Footprint:
    """2 x AA battery holder, PCB mount (Keystone 2462 land pattern)."""
    pads = [Pad("1", 0, 0, 2.0, 2.0, "rect", "tht", 1.02), Pad("2", 0, 14.99, 2.0, 2.0, "circle", "tht", 1.02),
            Pad("", 27.165, 0, 3.3, 3.3, "circle", "npth", 3.3), Pad("", 27.165, 14.99, 3.3, 3.3, "circle", "npth", 3.3)]
    g = _rect(-2.59, -8.965, 56.92, 23.955)
    model = composite(B(-2.59, -8.965, 0, 56.92, 23.955, 2.0, BLACK),
                      {"s": "cylx", "p": [2.0, 52.0, 0.0, 9.0, 7.2], "c": "#c2402d", "m": 0},
                      {"s": "cylx", "p": [2.0, 52.0, 14.99, 9.0, 7.2], "c": "#c2402d", "m": 0}, pins="tht")
    return _fp("BatteryHolder_Keystone_2462_2xAA", "2 x AA battery holder, PCB mount (Keystone 2462)", pads, g,
               (-2.59, -8.965, 56.92, 23.955), model)


def wire_pad(drill: float) -> Footprint:
    pad = round(drill * 2 + 0.2, 2)
    pads = [Pad("1", 0, 0, pad, pad, "circle", "tht", drill)]
    return _fp(f"SolderWirePad_1x01_Drill{drill:g}mm", f"Solder pad for a wire, drill {drill:g} mm", pads,
               [_circle(0, 0, pad / 2 + 0.3)], (-pad / 2, -pad / 2, pad / 2, pad / 2), {"type": "none"})


# --------------------------------------------------------------------------- catalogue entries

def entries():
    out = []
    add = out.append
    for pitch, maxn in ((2.54, 40), (2.0, 20), (1.27, 25)):
        pname = f"{pitch:.2f}".rstrip("0").rstrip(".")
        for n in range(1, maxn + 1):
            add((f"Connectors/Pin headers {pname} mm", f"Pin header 1x{n} P{pitch}", "J", f"Conn_01x{n:02d}",
                 lambda n=n, p=pitch: header(n, 1, p), "header pins male connector"))
        for n in range(2, maxn + 1):
            add((f"Connectors/Pin headers {pname} mm", f"Pin header 2x{n} P{pitch}", "J", f"Conn_02x{n:02d}",
                 lambda n=n, p=pitch: header(n, 2, p), "header pins male connector dual"))
        for n in range(1, maxn + 1):
            add((f"Connectors/Female sockets {pname} mm", f"Pin socket 1x{n} P{pitch}", "J", f"Conn_01x{n:02d}",
                 lambda n=n, p=pitch: header(n, 1, p, "female"), "female socket header"))
        for n in range(2, maxn + 1):
            add((f"Connectors/Female sockets {pname} mm", f"Pin socket 2x{n} P{pitch}", "J", f"Conn_02x{n:02d}",
                 lambda n=n, p=pitch: header(n, 2, p, "female"), "female socket header dual"))
    for n in range(1, 21):
        add(("Connectors/Pin headers right angle", f"Pin header 1x{n} P2.54 right angle", "J", f"Conn_01x{n:02d}",
             lambda n=n: header(n, 1, 2.54, "male", "right"), "header right angle horizontal"))
    for n in range(2, 21):
        add(("Connectors/Pin headers right angle", f"Pin header 2x{n} P2.54 right angle", "J", f"Conn_02x{n:02d}",
             lambda n=n: header(n, 2, 2.54, "male", "right"), "header right angle horizontal"))
    for n in (6, 8, 10, 14, 16, 20, 26, 34, 40, 50, 64):
        add(("Connectors/IDC box headers", f"IDC box header 2x{n // 2}", "J", f"IDC-{n}", lambda n=n: idc_box(n),
             "idc shrouded box header ribbon jtag swd"))
    ranges = {"JST_PH": range(2, 17), "JST_XH": range(2, 17), "JST_EH": range(2, 16), "JST_VH": range(2, 11),
              "JST_ZH": range(2, 13), "Molex_KK-254": range(2, 17), "Molex_PicoBlade": range(2, 16),
              "Molex_Micro-Fit_1xN": range(2, 13)}
    for series, rng in ranges.items():
        for n in rng:
            label = series.replace("_", " ").replace(" 1xN", "")
            add((f"Connectors/{label}", f"{label} {n}-pin", "J", f"{label.split()[-1]}-{n}",
                 lambda s=series, n=n: wire_to_board(s, n), f"{label.lower()} wire to board crimp"))
    for series, rng in (("JST_SH", range(2, 21)), ("JST_GH", range(2, 16)), ("JST_PH_SMD", range(2, 11))):
        for n in rng:
            label = series.replace("_", " ")
            add((f"Connectors/{label}", f"{label} {n}-pin SMD", "J", f"{label.split()[1]}-{n}",
                 lambda s=series, n=n: wire_to_board_smd(s, n), f"{label.lower()} qwiic stemma smd"))
    for series, rng in (("Micro-Fit", range(1, 13)), ("Mini-Fit", range(1, 13))):
        for n in rng:
            add((f"Connectors/Molex {series}", f"Molex {series} 2x{n}", "J", f"{series}-{2 * n}",
                 lambda s=series, n=n: molex_dual(s, n), "molex power atx"))
    for pitch, maxn in ((2.54, 12), (3.5, 12), (3.81, 12), (5.0, 12), (5.08, 12), (7.5, 6), (10.16, 4)):
        for n in range(2, maxn + 1):
            add((f"Connectors/Terminal blocks {pitch:g} mm", f"Screw terminal {n}-pin P{pitch:g}", "J",
                 f"Terminal-{n}", lambda n=n, p=pitch: terminal(n, p), "screw terminal block phoenix wire"))
    add(("Connectors/USB", "USB-C receptacle 16P (USB 2.0)", "J", "USB-C", usb_c_16p, "usb type-c"))
    add(("Connectors/USB", "USB-C receptacle 6P (power only)", "J", "USB-C", usb_c_6p, "usb type-c power"))
    add(("Connectors/USB", "USB Micro-B receptacle", "J", "USB-Micro", usb_micro_b, "usb micro"))
    add(("Connectors/USB", "USB Mini-B receptacle", "J", "USB-Mini", usb_mini_b, "usb mini"))
    add(("Connectors/USB", "USB-A receptacle THT", "J", "USB-A", usb_a, "usb type-a host"))
    add(("Connectors/USB", "USB-B receptacle THT", "J", "USB-B", usb_b, "usb type-b printer"))
    add(("Connectors/Power", "DC barrel jack 5.5x2.1", "J", "DC-Jack", barrel_jack, "barrel jack dc power"))
    add(("Connectors/Ethernet", "RJ45 8P8C shielded", "J", "RJ45", rj45, "ethernet lan modular"))
    add(("Connectors/RF", "SMA edge mount", "J", "SMA", sma_edge, "sma rf antenna coax"))
    add(("Connectors/RF", "SMA vertical THT", "J", "SMA", sma_vertical, "sma rf antenna coax"))
    add(("Connectors/RF", "U.FL / IPEX receptacle", "J", "U.FL", ufl, "ufl ipex mhf rf antenna"))
    add(("Connectors/Audio", "3.5 mm audio jack SMD", "J", "Jack3.5", audio_jack_smd, "audio headphone trrs"))
    add(("Connectors/Audio", "3.5 mm audio jack THT", "J", "Jack3.5", audio_jack_tht, "audio headphone"))
    add(("Connectors/Memory cards", "microSD socket", "J", "microSD", microsd, "sd card tf"))
    add(("Connectors/Memory cards", "Micro SIM socket", "J", "SIM", sim_socket, "sim card gsm"))
    for pins in (9, 15, 25, 37):
        for female in (False, True):
            add(("Connectors/D-Sub", f"D-Sub {pins} {'female' if female else 'male'}", "J", f"DB{pins}",
                 lambda p=pins, f=female: dsub(p, f), "dsub db9 serial rs232 vga"))
    for pitch, ns in ((0.5, (4, 6, 8, 10, 12, 14, 16, 20, 24, 26, 30, 32, 34, 40, 45, 50)), (1.0, (4, 6, 8, 10, 12, 14,
                                                                                                     16, 20, 24, 30))):
        for n in ns:
            add((f"Connectors/FFC FPC {pitch} mm", f"FFC/FPC {n}-pin P{pitch}", "J", f"FPC-{n}",
                 lambda n=n, p=pitch: ffc(n, p), "ffc fpc flex ribbon display camera"))
    add(("Batteries", "CR2032 holder SMD", "BT", "CR2032", battery_cr2032_smd, "coin cell battery rtc keystone 3034"))
    add(("Batteries", "CR2032 holder THT", "BT", "CR2032", battery_cr2032_tht, "coin cell battery rtc keystone 106"))
    add(("Batteries", "18650 holder", "BT", "18650", battery_18650, "lithium li-ion cell keystone 1042"))
    add(("Batteries", "2 x AA holder", "BT", "2xAA", battery_aa2, "aa battery keystone 2462"))
    for d in (0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5):
        add(("Mechanical/Wire pads", f"Wire solder pad drill {d:g}", "TP", "Wire", lambda d=d: wire_pad(d),
             "wire pad solder"))
    return out
