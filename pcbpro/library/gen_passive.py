"""Passive component footprints: resistors, capacitors, inductors, fuses, potentiometers."""
from __future__ import annotations

import math

from ..model.board import Footprint, Pad
from .shapes import (B, BLACK, CYL, CYLX, CYLY, DARK, GOLD, METAL, VERIFY, _arc, _circle, _fp, _line, _rect,
                     composite, inline_tht, r4, two_terminal_smd)

# --------------------------------------------------------------------------- resistor arrays


def resistor_array(n: int, size: str) -> Footprint:
    """Convex chip resistor arrays (e.g. 4x0603 in a 1206 body)."""
    dims = {"0402": (0.5, 0.3, 0.6, 0.55, 1.0), "0603": (0.8, 0.5, 0.9, 0.85, 1.6)}
    pitch, pw, ph, row, bw = dims[size]
    L = pitch * n
    x0 = -(n - 1) * pitch / 2
    pads = [Pad(str(i + 1), r4(x0 + i * pitch), row, pw, ph, "roundrect") for i in range(n)]
    pads += [Pad(str(n + i + 1), r4(-x0 - i * pitch), -row, pw, ph, "roundrect") for i in range(n)]
    g = _rect(-L / 2, -bw / 2, L / 2, bw / 2, 0.1, "fab") + [_line(-L / 2 - 0.3, row, -L / 2 - 0.3, row + ph / 2)]
    model = composite(B(-L / 2, -bw / 2 + 0.2, 0.02, L / 2, bw / 2 - 0.2, 0.45, BLACK),
                      *[B(p.x - pw * 0.4, (p.y - 0.2) if p.y > 0 else (p.y - 0.12), 0, p.x + pw * 0.4,
                          (p.y + 0.12) if p.y > 0 else (p.y + 0.2), 0.46, METAL, True) for p in pads])
    return _fp(f"R_Array_Convex_{n}x{size}", f"Chip resistor array, {n} resistors, {size} elements", pads, g,
               (-L / 2, -bw / 2, L / 2, bw / 2), model)


# --------------------------------------------------------------------------- MELF

def melf(kind: str, name: str) -> Footprint:
    dims = {"MicroMELF": (0.8, 1.3, 1.0, 2.0, 1.1), "MiniMELF": (1.2, 1.6, 1.6, 3.5, 1.5),
            "MELF": (1.6, 2.6, 2.55, 5.8, 2.5)}
    pw, ph, cx, L, D = dims[name]
    body = "#3d5fa8" if kind == "R" else "#cc7a2a"
    model = composite(CYLX(-L / 2 + 0.35, L / 2 - 0.35, 0, D / 2, D / 2, body, sp=0.6),
                      CYLX(-L / 2, -L / 2 + 0.4, 0, D / 2, D / 2 * 1.02, METAL, True),
                      CYLX(L / 2 - 0.4, L / 2, 0, D / 2, D / 2 * 1.02, METAL, True),
                      CYLX(-L / 2 + 0.5, -L / 2 + 0.8, 0, D / 2, D / 2 * 1.03, "#222222") if kind == "D" else None)
    what = "Resistor" if kind == "R" else "Diode"
    return two_terminal_smd(f"{'R' if kind == 'R' else 'D'}_{name}", f"{what}, {name} cylindrical SMD package",
                            pw, ph, cx, L, D, model, polarity=(kind == "D"))


# --------------------------------------------------------------------------- tantalum & SMD electrolytic

TANTALUM = {  # case: (EIA code, pad_w, pad_h, cx, L, W, H)
    "A": ("3216-18", 1.35, 1.5, 1.4, 3.2, 1.6, 1.8),
    "B": ("3528-21", 1.5, 2.35, 1.55, 3.5, 2.8, 2.1),
    "C": ("6032-28", 2.25, 2.35, 2.5, 6.0, 3.2, 2.8),
    "D": ("7343-31", 2.25, 2.55, 3.15, 7.3, 4.3, 3.1),
    "E": ("7343-43", 2.25, 2.55, 3.15, 7.3, 4.3, 4.3),
    "V": ("7361-38", 2.25, 3.6, 3.15, 7.3, 6.1, 3.8),
}


def tantalum(case: str) -> Footprint:
    eia, pw, ph, cx, L, W, H = TANTALUM[case]
    model = composite(B(-L / 2 + 0.3, -W / 2, 0.05, L / 2 - 0.3, W / 2, H, "#d9a53c", sp=0.35),
                      B(-L / 2 + 0.55, -W / 2 + 0.1, H, -L / 2 + 1.1, W / 2 - 0.1, H + 0.01, "#6b4a14"),
                      B(-L / 2, -W * 0.35, 0, -L / 2 + 0.6, W * 0.35, 0.4, METAL, True),
                      B(L / 2 - 0.6, -W * 0.35, 0, L / 2, W * 0.35, 0.4, METAL, True))
    return two_terminal_smd(f"CP_Tantalum_Case-{case}_EIA-{eia}", f"Tantalum capacitor, case {case} (EIA {eia}), "
                            "pin 1 = anode (+)", pw, ph, cx, L, W, model, polarity=True)


ELCO_SMD = {  # (D, H): (pad_len, pad_w, center)  - manufacturer recommended land patterns
    (4.0, 5.4): (2.6, 1.6, 1.8), (5.0, 5.4): (3.0, 1.6, 2.2), (6.3, 5.4): (3.5, 1.6, 2.8), (6.3, 7.7): (3.5, 1.6, 2.7),
    (8.0, 6.5): (4.0, 2.5, 3.05), (8.0, 10.0): (3.5, 2.5, 3.25), (10.0, 10.0): (4.0, 2.5, 4.0),
    (10.0, 12.5): (4.4, 2.5, 4.2), (12.5, 13.5): (5.3, 2.5, 4.9), (16.0, 17.5): (6.5, 3.0, 6.3),
}


def elco_smd(D: float, H: float) -> Footprint:
    pl, pw, cx = ELCO_SMD[(D, H)]
    s = D + 0.3
    pads = [Pad("1", -cx, 0, pl, pw, "roundrect"), Pad("2", cx, 0, pl, pw, "roundrect")]
    c = s / 2
    ch = s * 0.25
    g = [_line(-c + ch, -c, c, -c), _line(c, -c, c, -pw / 2 - 0.3), _line(c, c, c, pw / 2 + 0.3), _line(-c + ch, c, c, c),
         _line(-c, -c + ch, -c + ch, -c), _line(-c, c - ch, -c + ch, c), _line(-c, -c + ch, -c, -pw / 2 - 0.3),
         _line(-c, c - ch, -c, pw / 2 + 0.3), _line(-c - 1.0, -c + 0.3, -c - 0.2, -c + 0.3),
         _line(-c - 0.6, -c - 0.1, -c - 0.6, -c + 0.7)]
    r = D / 2
    model = composite(B(-c, -c, 0, c, c, 0.5, "#1b1b1b"),
                      CYL(0, 0, 0.5, H - 0.3, r, "#c3c6cc", True, seg=36),
                      CYL(0, 0, H - 0.3, H, r * 0.95, "#aeb2b8", True, seg=36),
                      B(-r * 0.95, -r * 0.55, H, -r * 0.45, r * 0.55, H + 0.01, "#1c2d6b"))
    return _fp(f"CP_Elec_{D:g}x{H:g}", f"Aluminium electrolytic capacitor, SMD, D{D:g} x H{H:g} mm, pin 1 = +",
               pads, g, (-c, -c, c, c), model)


# --------------------------------------------------------------------------- through-hole capacitors

ELCO_THT = [(4, 1.5, 7), (5, 2.0, 11), (5, 2.5, 11), (6.3, 2.5, 11), (8, 2.5, 11.5), (8, 3.5, 11.5), (8, 3.8, 14),
            (10, 5.0, 16), (10, 5.0, 20), (12.5, 5.0, 20), (12.5, 5.0, 25), (13, 5.0, 25), (16, 7.5, 25),
            (16, 7.5, 31.5), (18, 7.5, 35.5), (22, 10.0, 40), (25, 10.0, 45)]


def cap_disc(D: float, W: float, P: float, color="#d49a3a", prefix="C") -> Footprint:
    pad, drill = (1.6, 0.8) if P < 7 else (2.0, 1.0)
    pads = inline_tht(2, P, pad, drill, first_square=False)
    g = _rect(-D / 2, -W / 2, D / 2, W / 2)
    zc = D / 2 + 1.5
    model = composite(CYLY(-W / 2, W / 2, 0, zc, D / 2, color, sp=0.35),
                      pins="tht", pin_top=zc - D / 2 + 0.3)
    what = "Ceramic disc capacitor" if prefix == "C" else "Varistor (MOV)"
    return _fp(f"{prefix}_Disc_D{D:g}mm_W{W:g}mm_P{P:.2f}mm", f"{what}, D{D:g} mm, W{W:g} mm, pitch {P:.2f} mm",
               pads, g, (-max(D, P + pad) / 2, -W / 2, max(D, P + pad) / 2, W / 2), model)


def cap_film(L: float, W: float, P: float, H: float | None = None) -> Footprint:
    pad, drill = (1.6, 0.8) if P < 10 else (2.2, 1.1)
    pads = inline_tht(2, P, pad, drill, first_square=False)
    H = H or max(W * 1.8, 6)
    g = _rect(-L / 2, -W / 2, L / 2, W / 2)
    model = composite(B(-L / 2, -W / 2, 0.3, L / 2, W / 2, H, "#b0282b", sp=0.4), pins="tht", pin_top=0.5)
    return _fp(f"C_Rect_L{L:g}mm_W{W:g}mm_P{P:.2f}mm", f"Film box capacitor, L{L:g} x W{W:g} mm, pitch {P:.2f} mm",
               pads, g, (-L / 2, -W / 2, L / 2, W / 2), model)


def cap_mlcc_tht(P: float) -> Footprint:
    pads = inline_tht(2, P, 1.6, 0.8, first_square=False)
    L, W = max(P + 1.5, 4.0), 2.5
    g = _rect(-L / 2, -W / 2, L / 2, W / 2)
    model = composite(B(-2.0, -1.25, 0.5, 2.0, 1.25, 4.5, "#c79a3e", sp=0.35), pins="tht", pin_top=0.7)
    return _fp(f"C_Rect_Ceramic_P{P:.2f}mm", f"Multilayer ceramic capacitor, radial, pitch {P:.2f} mm", pads, g,
               (-L / 2, -W / 2, L / 2, W / 2), model)


# --------------------------------------------------------------------------- axial & vertical resistors / diodes

AXIAL_R = [  # (pitch, L, D, name)
    (7.62, 3.6, 1.6, "1/8 W"), (10.16, 6.3, 2.5, "1/4 W"), (12.7, 9.0, 3.2, "1/2 W"), (15.24, 11.0, 4.5, "1 W"),
    (20.32, 15.0, 5.0, "2 W"), (25.4, 17.5, 6.5, "3 W"),
]


def resistor_axial_p(pitch: float, L: float, D: float, power: str) -> Footprint:
    pad, drill = (1.6, 0.8) if D < 4 else (2.2, 1.1)
    pads = inline_tht(2, pitch, pad, drill)
    g = _rect(-L / 2, -D / 2, L / 2, D / 2) + [_line(-pitch / 2 + pad / 2 + 0.2, 0, -L / 2, 0),
                                                 _line(pitch / 2 - pad / 2 - 0.2, 0, L / 2, 0)]
    model = {"type": "axial", "L": L, "D": D, "pitch": pitch, "body": "#d8c39a" if D < 4 else "#3f7fb8",
             "band": None, "bands": True}
    return _fp(f"R_Axial_L{L:g}mm_D{D:g}mm_P{pitch:.2f}mm", f"Resistor, axial {power}, pitch {pitch:.2f} mm", pads,
               g, (-pitch / 2, -D / 2, pitch / 2, D / 2), model)


def resistor_vertical(pitch: float) -> Footprint:
    pads = inline_tht(2, pitch, 1.6, 0.8)
    g = [_circle(-pitch / 2, 0, 1.4), _line(-pitch / 2 + 1.4, 0, pitch / 2 - 0.9, 0)]
    x = -pitch / 2
    model = composite(CYL(x, 0, 0.5, 6.8, 1.25, "#d8c39a", sp=0.35), CYL(x, 0, 6.8, 7.0, 1.0, METAL, True),
                      B(x - 0.25, -0.25, 6.8, pitch / 2 + 0.25, 0.25, 7.3, METAL, True),
                      B(pitch / 2 - 0.25, -0.25, -1.5, pitch / 2 + 0.25, 0.25, 7.3, METAL, True), pins="tht",
                      pin_top=0.6)
    return _fp(f"R_Axial_Vertical_P{pitch:.2f}mm", f"Resistor, axial, mounted vertically, pitch {pitch:.2f} mm", pads,
               g, (-pitch / 2 - 1.4, -1.4, pitch / 2 + 0.9, 1.4), model)


AXIAL_D = {  # name: (pitch, L, D, pad, drill)
    "DO-35": (7.62, 4.0, 1.9, 1.6, 0.8), "DO-41": (10.16, 5.2, 2.7, 2.2, 1.1), "DO-15": (12.7, 7.6, 3.6, 2.4, 1.2),
    "DO-201AD": (15.24, 9.5, 5.3, 3.0, 1.5),
}


def diode_axial(name: str) -> Footprint:
    pitch, L, D, pad, drill = AXIAL_D[name]
    pads = inline_tht(2, pitch, pad, drill)
    g = _rect(-L / 2, -D / 2, L / 2, D / 2) + [_line(-L / 2 + 0.8, -D / 2, -L / 2 + 0.8, D / 2, 0.3),
                                                 _line(-pitch / 2 + pad / 2 + 0.2, 0, -L / 2, 0),
                                                 _line(pitch / 2 - pad / 2 - 0.2, 0, L / 2, 0)]
    glass = name == "DO-35"
    model = {"type": "axial", "L": L, "D": D, "pitch": pitch, "body": "#d9772c" if glass else "#1a1a1a",
             "band": "#1a1a1a" if glass else "#c8c8c8"}
    return _fp(f"D_{name}_P{pitch:.2f}mm", f"Diode, {name} axial, pitch {pitch:.2f} mm (pin 1 = cathode)", pads, g,
               (-pitch / 2, -D / 2, pitch / 2, D / 2), model)


# --------------------------------------------------------------------------- inductors

POWER_INDUCTORS = [(2.5, 1.2), (3.0, 1.5), (4.0, 1.8), (4.0, 3.0), (5.0, 2.0), (5.0, 4.0), (6.0, 2.8), (6.0, 4.5),
                   (7.0, 3.0), (7.0, 4.5), (8.0, 4.0), (8.0, 6.0), (10.0, 4.5), (10.0, 6.0), (12.0, 6.0), (12.0, 8.0)]


def power_inductor(size: float, H: float) -> Footprint:
    pw = r4(0.32 * size + 0.2)
    ph = r4(0.9 * size)
    cx = r4(size / 2 - pw / 2 + 0.3)
    s = size / 2
    model = composite(B(-s, -s, 0.0, s, s, H, "#3b3b3e", sp=0.25), B(-s * 0.6, -s * 0.6, H, s * 0.6, s * 0.6, H + 0.01,
                                                                       "#2a2a2c"),
                      B(-s - 0.05, -ph * 0.35, 0, -s + pw * 0.6, ph * 0.35, 0.3, METAL, True),
                      B(s - pw * 0.6, -ph * 0.35, 0, s + 0.05, ph * 0.35, 0.3, METAL, True))
    return two_terminal_smd(f"L_Power_{size:g}x{size:g}x{H:g}mm", f"Shielded SMD power inductor, "
                            f"{size:g}x{size:g} mm, H {H:g} mm (generic pad layout)." + VERIFY, pw, ph, cx, size,
                            size, model, silk=False)


def inductor_radial(D: float, P: float, H: float) -> Footprint:
    pads = inline_tht(2, P, 1.8, 1.0, first_square=False)
    g = [_circle(0, 0, D / 2 + 0.1)]
    model = composite(CYL(0, 0, 0.3, H, D / 2, "#2c2c2e", seg=36), CYL(0, 0, H * 0.3, H * 0.9, D / 2 + 0.02,
                                                                      "#8a5a2b", seg=36), pins="tht", pin_top=0.5)
    return _fp(f"L_Radial_D{D:g}mm_P{P:g}mm", f"Radial inductor, D{D:g} mm, pitch {P:g} mm", pads, g,
               (-D / 2, -D / 2, D / 2, D / 2), model)


def inductor_toroid(D: float, P: float) -> Footprint:
    pads = inline_tht(2, P, 2.2, 1.2, first_square=False)
    g = [_circle(0, 0, D / 2)]
    zc = D / 2 + 0.5
    model = composite(CYLY(-D * 0.15, D * 0.15, 0, zc, D / 2, "#5a3a1c", sp=0.6), CYLY(-D * 0.16, D * 0.16, 0, zc,
                                                                                         D * 0.25, "#111111"),
                      pins="tht", pin_top=1.0)
    return _fp(f"L_Toroid_Vertical_D{D:g}mm_P{P:g}mm", f"Toroidal inductor, vertical, D{D:g} mm, pitch {P:g} mm",
               pads, g, (-D / 2, -D * 0.2, D / 2, D * 0.2), model)


# --------------------------------------------------------------------------- fuses

PTC = {"1206": (1.1, 1.8, 1.45, 3.2, 1.6, 0.8), "1812": (1.5, 3.4, 2.1, 4.5, 3.2, 1.0),
       "2920": (1.9, 5.3, 3.3, 7.4, 5.1, 1.2)}


def ptc_fuse(size: str) -> Footprint:
    pw, ph, cx, L, W, H = PTC[size]
    model = {"type": "chip", "L": L, "W": W, "H": H, "body": "#1d4e2b", "term": "#c9c9c9", "cls": "F"}
    return two_terminal_smd(f"Fuse_PTC_{size}", f"Resettable PTC fuse (polyfuse), {size} SMD", pw, ph, cx, L, W, model)


def fuse_holder_5x20() -> Footprint:
    """Inline PCB clips for 5x20 mm fuses (Littelfuse 111 style: 2 clips x 2 legs, 20 x 5 mm)."""
    pads = [Pad("1", -10.0, 0, 2.0, 2.0, "roundrect", "tht", 1.05), Pad("1", -5.0, 0, 2.0, 2.0, "roundrect", "tht", 1.05),
            Pad("2", 5.0, 0, 2.0, 2.0, "circle", "tht", 1.05), Pad("2", 10.0, 0, 2.0, 2.0, "circle", "tht", 1.05)]
    g = _rect(-10.5, -2.65, 10.5, 2.65)
    model = composite(B(-10.5, -2.6, 0, -4.5, 2.6, 7.5, METAL, True), B(4.5, -2.6, 0, 10.5, 2.6, 7.5, METAL, True),
                      CYLX(-10, 10, 0, 6.5, 2.5, "#e9edf2", sp=0.9), pins="tht", pin_top=0.2)
    return _fp("Fuseholder_Clip-5x20mm_Inline_P20.00x5.00mm", "PCB fuse clips for 5x20 mm glass fuses, inline, "
               "legs 20 x 5 mm (Littelfuse 111 style)", pads, g, (-10.5, -2.65, 10.5, 2.65), model)


def fuse_tr5() -> Footprint:
    pads = inline_tht(2, 5.08, 2.0, 1.0, first_square=False)
    g = [_circle(0, 0, 4.2)]
    model = composite(CYL(0, 0, 0.5, 7.5, 4.2, "#1b1b1b", seg=32), pins="tht", pin_top=0.6)
    return _fp("Fuse_TR5_P5.08mm", "Radial micro fuse TR5 / TE5, pitch 5.08 mm", pads, g, (-4.2, -4.2, 4.2, 4.2), model)


# --------------------------------------------------------------------------- potentiometers & trimmers

def trimmer_3296w() -> Footprint:
    pads = inline_tht(3, 2.54, 1.6, 0.8)
    g = _rect(-4.8, -2.4, 4.8, 2.4)
    model = composite(B(-4.8, -2.4, 0.3, 4.8, 2.4, 10.0, "#2552a8", sp=0.35), CYL(3.3, 0, 10.0, 10.8, 1.1, "#c89f45",
                                                                                  True), pins="tht", pin_top=0.5)
    return _fp("Potentiometer_Bourns_3296W_Vertical", "Multi-turn trimmer potentiometer, Bourns 3296W style", pads, g,
               (-4.8, -2.4, 4.8, 2.4), model)


def trimmer_3362p() -> Footprint:
    pads = [Pad("1", -2.54, 0, 1.6, 1.6, "rect", "tht", 0.8), Pad("2", 0, -2.54, 1.6, 1.6, "circle", "tht", 0.8),
            Pad("3", 2.54, 0, 1.6, 1.6, "circle", "tht", 0.8)]
    g = _rect(-3.4, -4.5, 3.4, 2.4)
    model = composite(B(-3.4, -4.5, 0.3, 3.4, 2.4, 4.8, "#2552a8", sp=0.35), CYL(0, -1.05, 4.8, 5.2, 1.4, "#e8e3d4"),
                      pins="tht", pin_top=0.5)
    return _fp("Potentiometer_Bourns_3362P_Vertical", "Single-turn trimmer potentiometer, Bourns 3362P style." + VERIFY,
               pads, g, (-3.4, -4.5, 3.4, 2.4), model)


def pot_rv09() -> Footprint:
    """9 mm rotary potentiometer, vertical PCB mount (Bourns PTV09A-1 land pattern)."""
    pads = [Pad("1", -3.5, 2.45, 1.8, 1.8, "circle", "tht", 1.0), Pad("2", -3.5, -0.05, 1.8, 1.8, "circle", "tht", 1.0),
            Pad("3", -3.5, -2.55, 1.8, 1.8, "circle", "tht", 1.0),
            Pad("MP", 3.5, -4.45, 4.4, 4.4, "circle", "tht", 2.2), Pad("MP", 3.5, 4.35, 4.4, 4.4, "circle", "tht", 2.2)]
    g = _rect(-2.5, -4.9, 9.5, 4.8)
    model = composite(B(-2.5, -4.9, 0.5, 9.5, 4.8, 6.5, "#1c1c1c"), CYLX(9.5, 15.0, 0, 4.5, 3.0, "#b8bcc2", True),
                      pins="tht", pin_top=0.8)
    return _fp("Potentiometer_Bourns_PTV09A-1_Single_Vertical", "9 mm rotary potentiometer, vertical PCB mount "
               "(Bourns PTV09A-1)", pads, g, (-4.4, -6.65, 9.5, 6.55), model)


# --------------------------------------------------------------------------- catalogue entries

def entries():
    from ..model.footprints import CHIP_SIZES, chip
    out = []
    add = out.append
    sizes = list(CHIP_SIZES)
    for s in sizes:
        add(("Resistors/Chip", f"Resistor {s}", "R", "10k", lambda s=s: chip("R", s), "res resistor smd chip"))
    for s in sizes:
        add(("Capacitors/Ceramic MLCC", f"Capacitor {s}", "C", "100nF", lambda s=s: chip("C", s),
             "cap capacitor mlcc ceramic smd"))
    for s in ("0402", "0603", "0805", "1206", "1210", "1812"):
        add(("Inductors/Chip", f"Inductor {s}", "L", "10uH", lambda s=s: chip("L", s), "inductor chip smd"))
        add(("Inductors/Ferrite beads", f"Ferrite bead {s}", "FB", "600R@100MHz", lambda s=s: chip("FB", s),
             "ferrite bead emi"))
    for s in ("0402", "0603", "0805", "1206"):
        add(("Fuses", f"Chip fuse {s}", "F", "1A", lambda s=s: chip("F", s), "fuse fast blow smd"))
    for s in PTC:
        add(("Fuses", f"PTC resettable fuse {s}", "F", "500mA", lambda s=s: ptc_fuse(s), "polyfuse ptc resettable"))
    add(("Fuses", "Fuse holder 5x20 mm (clips)", "F", "2A", fuse_holder_5x20, "fuse holder glass"))
    add(("Fuses", "Fuse TR5 radial", "F", "1A", fuse_tr5, "fuse radial"))
    for n in (2, 4):
        for s in ("0402", "0603"):
            add(("Resistors/Arrays", f"Resistor array {n}x{s}", "RN", "10k", lambda n=n, s=s: resistor_array(n, s),
                 "resistor network array"))
    for name in ("MicroMELF", "MiniMELF", "MELF"):
        add(("Resistors/Chip", f"Resistor {name}", "R", "10k", lambda n=name: melf("R", n), "melf resistor"))
    for pitch, L, D, power in AXIAL_R:
        add(("Resistors/Through-hole", f"Resistor axial {power} P{pitch:.2f}", "R", "10k",
             lambda a=(pitch, L, D, power): resistor_axial_p(*a), "resistor axial tht"))
    for pitch in (2.54, 5.08):
        add(("Resistors/Through-hole", f"Resistor vertical P{pitch:.2f}", "R", "10k",
             lambda p=pitch: resistor_vertical(p), "resistor standing tht"))
    for case in TANTALUM:
        add(("Capacitors/Tantalum", f"Tantalum case {case} ({TANTALUM[case][0]})", "C", "10uF",
             lambda c=case: tantalum(c), "tantalum polarised smd"))
    for D, H in ELCO_SMD:
        add(("Capacitors/Electrolytic SMD", f"Electrolytic SMD {D:g}x{H:g}", "C", "100uF",
             lambda d=D, h=H: elco_smd(d, h), "electrolytic aluminium polarised smd can"))
    from ..model.footprints import cap_radial
    for D, P, H in ELCO_THT:
        add(("Capacitors/Electrolytic THT", f"Electrolytic D{D:g} P{P:g} H{H:g}", "C", "100uF",
             lambda d=D, p=P, h=H: cap_radial(d, p, h), "electrolytic aluminium radial polarised"))
    for D, W, P in ((3.0, 2.0, 2.5), (4.0, 2.5, 2.5), (5.0, 2.5, 5.0), (5.0, 3.0, 5.0), (7.5, 2.5, 5.0),
                    (7.5, 5.0, 7.5), (10.0, 4.0, 7.5), (12.5, 5.0, 10.0)):
        add(("Capacitors/Ceramic THT", f"Ceramic disc D{D:g} W{W:g} P{P:g}", "C", "100nF",
             lambda a=(D, W, P): cap_disc(*a), "ceramic disc capacitor tht"))
    for P in (2.54, 5.08):
        add(("Capacitors/Ceramic THT", f"MLCC radial P{P:.2f}", "C", "100nF", lambda p=P: cap_mlcc_tht(p),
             "ceramic multilayer radial"))
    for L, W, P in ((7.2, 2.5, 5.0), (7.2, 3.5, 5.0), (7.2, 4.5, 5.0), (10.0, 3.0, 7.5), (10.0, 4.0, 7.5),
                    (13.0, 4.0, 10.0), (13.0, 5.0, 10.0), (18.0, 5.0, 15.0), (18.0, 7.0, 15.0), (26.5, 6.0, 22.5),
                    (26.5, 8.5, 22.5), (31.5, 9.0, 27.5), (31.5, 11.0, 27.5)):
        add(("Capacitors/Film", f"Film box L{L:g} W{W:g} P{P:g}", "C", "100nF", lambda a=(L, W, P): cap_film(*a),
             "film polyester polypropylene mkt mkp x2"))
    for D, W, P in ((7.0, 4.0, 5.0), (10.0, 4.5, 7.5), (14.0, 5.0, 7.5), (20.0, 6.0, 10.0)):
        add(("Protection", f"Varistor MOV D{D:g}", "RV", "275V", lambda a=(D, W, P): cap_disc(*a, color="#2f59a8",
                                                                                             prefix="RV"),
             "mov varistor surge"))
    for name in AXIAL_D:
        add(("Diodes/Through-hole", f"Diode {name}", "D", "1N4007" if name != "DO-35" else "1N4148",
             lambda n=name: diode_axial(n), "diode axial rectifier"))
    for size, H in POWER_INDUCTORS:
        add(("Inductors/Power SMD", f"Power inductor {size:g}x{size:g}x{H:g}", "L", "10uH",
             lambda s=size, h=H: power_inductor(s, h), "power inductor shielded buck boost"))
    for D, P, H in ((6.0, 3.0, 8.0), (8.0, 5.0, 10.0), (10.0, 5.0, 12.0), (12.0, 5.0, 14.0), (16.0, 7.5, 16.0)):
        add(("Inductors/Through-hole", f"Radial inductor D{D:g} P{P:g}", "L", "100uH",
             lambda a=(D, P, H): inductor_radial(*a), "inductor choke radial"))
    for D, P in ((10.0, 8.0), (14.0, 10.0), (20.0, 15.0), (27.0, 20.0)):
        add(("Inductors/Through-hole", f"Toroid vertical D{D:g}", "L", "100uH", lambda a=(D, P): inductor_toroid(*a),
             "toroid choke common mode"))
    add(("Potentiometers", "Trimmer 3296W multi-turn", "RV", "10k", trimmer_3296w, "trimpot trimmer preset"))
    add(("Potentiometers", "Trimmer 3362P", "RV", "10k", trimmer_3362p, "trimpot trimmer preset"))
    add(("Potentiometers", "Potentiometer RV09 vertical", "RV", "10k", pot_rv09, "pot knob rotary 9mm ptv09 rv09"))
    return out
