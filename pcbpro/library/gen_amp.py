"""Guitar and bass amplifier parts.

* Tube sockets that draw the tube itself in 3D. Value a socket with the tube type ("12AX7", "EL84", "6V6GT" ...):
  the 3D view, the BOM and the amp checks (pinout, heater current, plate-voltage limits) all follow the value.
  Sockets are seen from the component side, so pin numbers run counter-clockwise from the gap (noval, B7G) or the
  key (octal), which sits at the bottom.
* High-voltage supply parts: snap-in and axial electrolytics, axial film capacitors, cement power resistors and
  bridge rectifiers.
* Solid-state power stages: TO-3, LM3886, TDA7293 / TDA7294, LM1875 / TDA2050 and TPA3116D2.
* Connections: XLR, XLR/jack combo, speakON, a chassis 1/4" jack, channel-switching relays, right-angle and slide
  pots, and labelled pads for transformer, speaker and mains wiring.

Land patterns follow the manufacturers' drawings. Everything with a KiCad equivalent is cross-checked pad by pad
(see verify.py); the Belton socket hole patterns come from the Belton VT9 / VT8 series catalogue sheets.
"""
from __future__ import annotations

import math

from ..amp.tubes import TUBES
from ..model.board import Footprint, Graphic, Pad
from .gen_pedal import stroke_text, wire_pads
from .shapes import B, CYL, CYLX, CYLY, DARK, METAL, PRISM, VERIFY, _circle, _fp, _line, _rect, composite, r4

# --------------------------------------------------------------------------- tube sockets

# base -> (positions around the circle, pins, angle of pin 1 in degrees, CCW, 0 = +x)
_BASES = {"noval": (10, 9, -54.0), "b7g": (8, 7, -45.0), "octal": (8, 8, -67.5)}

SOCKETS = {
    # key: (base, pin-circle diameter, drill, pad, body diameter, body height, colour, description, mpn, maker)
    "belton_vt9": ("noval", 21.0, 1.8, 3.3, 22.8, 8.5, "#2a2523",
                   "Noval (B9A) PCB socket, Belton VT9-PT: solder tails fan out to a 21.0 mm circle, 1.8 mm holes "
                   "(Belton catalogue BVT9-1).", "VT9-PT", "Belton"),
    "noval_straight": ("noval", 11.89, 1.1, 2.2, 22.2, 10.4, "#ece8df",
                       "Noval (B9A) socket with straight pins on the tube's own 11.89 mm pin circle (ceramic PCB "
                       "sockets such as GZC9-Y)." + VERIFY, "GZC9-Y", ""),
    "b7g_straight": ("b7g", 9.53, 1.1, 2.0, 19.0, 9.0, "#ece8df",
                     "Miniature 7-pin (B7G) socket with straight pins on the tube's 9.53 mm pin circle (ceramic PCB "
                     "sockets such as GZC7-Y-B)." + VERIFY, "GZC7-Y-B", ""),
    "belton_vt8": ("octal", 17.2, 1.6, 3.0, 25.4, 9.0, "#2a2523",
                   "Octal (K8A) socket, Belton VT8-PT / VT8-PTS: 8 pins on a 17.2 mm circle, 1.6 mm holes (Belton "
                   "catalogue BVT8-1). The saddle (40 mm hole centres) mounts to the chassis.", "VT8-PT", "Belton"),
}

SOCKET_NAMES = {
    "belton_vt9": "Valve_Noval_B9A_Belton_VT9-PT",
    "noval_straight": "Valve_Noval_B9A_P11.89mm_StraightPins",
    "b7g_straight": "Valve_Miniature_B7G_P9.53mm_StraightPins",
    "belton_vt8": "Valve_Octal_K8A_Belton_VT8-PT",
}


def socket_pin_positions(base: str, circle_d: float) -> list[tuple[str, float, float]]:
    positions, pins, a1 = _BASES[base]
    step = 360.0 / positions
    r = circle_d / 2
    out = []
    for n in range(pins):
        a = math.radians(a1 + step * n)
        out.append((str(n + 1), r4(r * math.cos(a)), r4(-r * math.sin(a))))
    return out


def tube_socket(key: str) -> Footprint:
    base, circle, drill, pad, body_d, body_h, colour, desc, _, _ = SOCKETS[key]
    pads = [Pad(n, x, y, pad, pad, "rect" if (n == "1" and pad >= 3.0) else "circle", "tht", drill)
            for n, x, y in socket_pin_positions(base, circle)]
    r_pads = circle / 2 + pad / 2
    r_silk = max(body_d / 2, r_pads + 0.35) + 0.15
    g: list[Graphic] = [_circle(0, 0, r_silk)]
    # gap / key marker at the bottom, pin-1 label just outside pad 1
    g.append(_line(0, r_silk - 1.6, 0, r_silk + 0.9, 0.2))
    _, x1, y1 = socket_pin_positions(base, circle)[0]
    u = math.hypot(x1, y1)
    lab = r_silk + 1.2
    g += stroke_text("1", r4(x1 / u * lab), r4(y1 / u * lab), 1.1)
    g.append(_circle(0, 0, body_d / 2, 0.1, "fab"))
    if base == "octal":
        g.append(_circle(0, 0, 4.0, 0.1, "fab"))  # centre spigot
        g.append(_line(0, 4.0, 0, 5.5, 0.1, "fab"))  # its key
    model = {"type": "tube", "base": base, "socket_d": body_d, "socket_h": body_h, "socket_c": colour,
             "pin_r": circle / 2, "ceramic": colour.startswith("#ec")}
    rr = max(r_silk, body_d / 2)
    body = (-rr, -rr, rr, rr)
    if key == "belton_vt8":
        L, W, hole = 50.0, 34.0, 40.0
        model["saddle"] = [L, W, hole]
        # the mounting saddle sits about 9 mm up: keep it in the courtyard so nothing tall goes underneath
        g += _rect(-L / 2, -W / 2, L / 2, W / 2, 0.1, "fab")
        for sx in (-1, 1):
            g.append(_circle(sx * hole / 2, 0, 1.75, 0.1, "fab"))
        body = (-L / 2, -W / 2, L / 2, W / 2)
    return _fp(SOCKET_NAMES[key], desc, pads, g, body, model, ref_gap=1.6)


BASE_LABEL = {"noval": "Noval", "b7g": "B7G", "octal": "Octal"}


def tube_part_name(tube_name: str) -> str:
    """Library name of the tube-on-socket part for a tube type ("12AX7" -> "12AX7 / ECC83 / 7025 tube (Noval)")."""
    t = TUBES[tube_name]
    aka = f" / {' / '.join(t.aliases[:2])}" if t.aliases else ""
    return f"{t.name}{aka} tube ({BASE_LABEL[t.base]})"


def _tube_socket_for(base: str) -> str:
    return {"noval": "belton_vt9", "b7g": "b7g_straight", "octal": "belton_vt8"}[base]


# --------------------------------------------------------------------------- HV capacitors

SNAPIN = [(22, 30), (22, 40), (25, 40), (30, 40), (30, 50), (35, 50)]  # (diameter, height)


def cap_snapin(D: float, H: float) -> Footprint:
    """Snap-in electrolytic, 10 mm pitch (KiCad CP_Radial_D*_P10.00mm_SnapIn)."""
    pads = [Pad("1", -5.0, 0.0, 4.0, 4.0, "roundrect", "tht", 2.0), Pad("2", 5.0, 0.0, 4.0, 4.0, "circle", "tht", 2.0)]
    r = D / 2
    g = [_circle(0, 0, r + 0.12), _line(-r - 2.2, -2.5, -r - 0.6, -2.5, 0.15), _line(-r - 1.4, -3.3, -r - 1.4, -1.7, 0.15)]
    model = {"type": "radial_cap", "D": D, "H": H, "body": "#17191d", "stripe": "#a8adb5"}
    return _fp(f"CP_Radial_D{D:g}mm_P10.00mm_SnapIn_H{H:g}mm", f"Snap-in electrolytic capacitor, D{D:g} x {H:g} mm, "
               "10 mm pitch (HV filter / reservoir caps, e.g. 100-220 uF 450 V). Pin 1 = +.", pads, g, (-r, -r, r, r),
               model)


AXIAL_ELCO = [  # (L, D, pitch, pad, drill) after KiCad CP_Axial_*
    (18.0, 8.0, 25.0, 2.4, 1.2), (25.0, 10.0, 30.0, 2.4, 1.2), (30.0, 12.5, 35.0, 2.4, 1.2),
    (38.0, 18.0, 44.0, 2.4, 1.2), (26.5, 20.0, 33.0, 2.8, 1.4),
]


def cap_axial_elco(L: float, D: float, P: float, pad: float, drill: float) -> Footprint:
    pads = [Pad("1", -P / 2, 0.0, pad, pad, "roundrect", "tht", drill), Pad("2", P / 2, 0.0, pad, pad, "circle", "tht", drill)]
    r = D / 2
    g = _rect(-L / 2, -r, L / 2, r) + [_line(-P / 2 + pad / 2 + 0.25, 0, -L / 2, 0), _line(P / 2 - pad / 2 - 0.25, 0, L / 2, 0)]
    g += [_line(-L / 2 + 1.2, -r - 1.2, -L / 2 + 3.0, -r - 1.2, 0.15), _line(-L / 2 + 2.1, -r - 2.1, -L / 2 + 2.1, -r - 0.3, 0.15)]
    zc = r + 0.3
    model = composite(CYLX(-L / 2, L / 2, 0, zc, r, "#2a3b5c", sp=0.45),
                      CYLX(L / 2 - 4.5, L / 2 - 2.0, 0, zc, r + 0.03, "#d8dade", sp=0.4),  # negative stripe
                      CYLX(-L / 2 - 0.01, -L / 2 + 0.6, 0, zc, r * 0.7, METAL, True),  # + end seal
                      CYLX(-P / 2, -L / 2, 0, zc, 0.4, METAL, True), CYLX(L / 2, P / 2, 0, zc, 0.4, METAL, True),
                      B(-P / 2 - 0.4, -0.4, -1.5, -P / 2 + 0.4, 0.4, zc, METAL, True),
                      B(P / 2 - 0.4, -0.4, -1.5, P / 2 + 0.4, 0.4, zc, METAL, True))
    return _fp(f"CP_Axial_L{L:g}mm_D{D:g}mm_P{P:.2f}mm_Horizontal", f"Axial electrolytic capacitor, L{L:g} x D{D:g} mm, "
               f"pitch {P:g} mm (F&T / JJ style HV caps). Pin 1 = +.", pads, g, (-P / 2, -r, P / 2, r), model)


AXIAL_FILM = [(12.0, 6.5, 15.0), (17.0, 7.0, 20.0), (19.0, 7.5, 25.0), (22.0, 9.5, 27.5)]  # (L, D, pitch)


def cap_axial_film(L: float, D: float, P: float) -> Footprint:
    pads = [Pad("1", -P / 2, 0.0, 1.6, 1.6, "circle", "tht", 0.8), Pad("2", P / 2, 0.0, 1.6, 1.6, "circle", "tht", 0.8)]
    r = D / 2
    g = _rect(-L / 2, -r, L / 2, r) + [_line(-P / 2 + 1.05, 0, -L / 2, 0), _line(P / 2 - 1.05, 0, L / 2, 0)]
    model = {"type": "axial", "L": L, "D": D, "pitch": P, "body": "#e0b83c", "band": "#6b5320"}
    return _fp(f"C_Axial_L{L:g}mm_D{D:g}mm_P{P:.2f}mm_Horizontal", f"Axial film capacitor, L{L:g} x D{D:g} mm, pitch "
               f"{P:g} mm (\"mustard\" / Mallory 150 style coupling and tone caps; 400-630 V parts). The band marks the "
               "outer foil: put it towards the lower-impedance side.", pads, g, (-P / 2, -r, P / 2, r), model)


# --------------------------------------------------------------------------- power resistors

POWER_R = [  # (L, W, pitch, watts) after KiCad R_Axial_Power_* (horizontal)
    (20.0, 6.4, 25.4, 4), (25.0, 9.0, 30.48, 7), (38.0, 9.0, 45.72, 9), (48.0, 12.5, 55.88, 15),
]
POWER_R_V = [(20.0, 6.4, 5.08, 4), (25.0, 9.0, 7.62, 7)]  # standing (vertical) cement resistors


def resistor_power(L: float, W: float, P: float, watts: int, vertical: bool = False) -> Footprint:
    pads = [Pad("1", -P / 2, 0.0, 2.4, 2.4, "circle", "tht", 1.2), Pad("2", P / 2, 0.0, 2.4, 2.4, "circle", "tht", 1.2)]
    cem = "#e8e4da"
    if vertical:  # body stands on pin 1's side, lead 2 comes down from the top
        x = -P / 2
        g = _rect(x - W / 2, -W / 2, x + W / 2, W / 2) + [_line(x + W / 2, 0, P / 2 - 1.45, 0)]
        model = composite(B(x - W / 2, -W / 2, 0.8, x + W / 2, W / 2, 0.8 + L, cem, sp=0.2),
                          B(P / 2 - 0.4, -0.4, -1.5, P / 2 + 0.4, 0.4, L + 2.0, METAL, True),
                          B(x, -0.4, L + 1.6, P / 2 + 0.4, 0.4, L + 2.0, METAL, True), pins="tht", pin_top=1.0)
        body = (x - W / 2, -W / 2, max(x + W / 2, P / 2), W / 2)
        name = f"R_Axial_Power_L{L:g}mm_W{W:g}mm_P{P:.2f}mm_Vertical"
        what = "standing"
    else:
        g = _rect(-L / 2, -W / 2, L / 2, W / 2) + [_line(-P / 2 + 1.45, 0, -L / 2, 0), _line(P / 2 - 1.45, 0, L / 2, 0)]
        zc = W / 2 + 1.0
        model = composite(B(-L / 2, -W / 2, 1.0, L / 2, W / 2, 1.0 + W, cem, sp=0.2),
                          CYLX(-P / 2, -L / 2, 0, zc, 0.4, METAL, True), CYLX(L / 2, P / 2, 0, zc, 0.4, METAL, True),
                          B(-P / 2 - 0.4, -0.4, -1.5, -P / 2 + 0.4, 0.4, zc, METAL, True),
                          B(P / 2 - 0.4, -0.4, -1.5, P / 2 + 0.4, 0.4, zc, METAL, True))
        body = (-P / 2, -W / 2, P / 2, W / 2)
        name = f"R_Axial_Power_L{L:g}mm_W{W:g}mm_P{P:.2f}mm"
        what = "lying"
    return _fp(name, f"Cement / wirewound power resistor, {watts} W, {L:g} x {W:g} x {W:g} mm, {what}, pitch {P:g} mm "
               "(cathode resistors of power tubes, dropping resistors, dummy loads). Mount 1-2 mm above the board.",
               pads, g, body, model)


# --------------------------------------------------------------------------- bridge rectifiers

def _tilde(x: float, y: float, w: float = 1.0) -> list[Graphic]:
    """An AC "~" mark as a short sine stroke on the silkscreen."""
    pts = [(x - w / 2 + w * i / 8, y - 0.22 * math.sin(math.pi * 2 * i / 8)) for i in range(9)]
    return [_line(r4(a[0]), r4(a[1]), r4(b[0]), r4(b[1]), 0.15) for a, b in zip(pts, pts[1:])]


def bridge_inline(kind: str) -> Footprint:
    """KBU / GBU inline bridge: + ~ ~ - on a 5.08 mm pitch, pin 1 (+) next to the chamfer."""
    pad, drill, (x0, y0, x1, y1), H = {"KBU": (2.8, 1.4, (-4.0, -2.0, 19.2, 5.2), 18.5),
                                        "GBU": (3.2, 1.6, (-3.4, -1.1, 18.7, 2.3), 17.5)}[kind]
    pads = [Pad(str(i + 1), r4(i * 5.08), 0.0, pad, pad, "rect" if i == 0 else "circle", "tht", drill) for i in range(4)]
    g = _rect(x0 - 0.12, y0 - 0.12, x1 + 0.12, y1 + 0.12)
    for i, lab in enumerate("+~~-"):
        g += _tilde(i * 5.08, y1 + 1.3) if lab == "~" else stroke_text(lab, i * 5.08, y1 + 1.3, 1.0)
    model = composite(B(x0, y0, 0.5, x1, y1, H, "#1b1b1d", sp=0.2), pins="tht", pin_top=0.5)
    return _fp(f"Diode_Bridge_Vishay_{kind}", f"{kind} bridge rectifier (e.g. {kind}810 / {kind}1010, 8-10 A, 1000 V), "
               "pins + ~ ~ - from the chamfered end. Bolt to the chassis for full-current use.", pads, g,
               (x0, y0, x1, y1 + 2.0), model)


def bridge_dip4() -> Footprint:
    pads = [Pad("1", 0.0, 0.0, 1.6, 1.6, "rect", "tht", 0.8), Pad("2", 0.0, 5.08, 1.6, 1.6, "oval", "tht", 0.8),
            Pad("3", 7.62, 5.08, 1.6, 1.6, "oval", "tht", 0.8), Pad("4", 7.62, 0.0, 1.6, 1.6, "oval", "tht", 0.8)]
    g = _rect(0.5, -1.95, 7.12, 6.75)
    model = composite(B(0.635, -1.8, 0.4, 6.985, 6.6, 3.6, "#1b1b1d", sp=0.2), pins="tht", pin_top=0.5)
    return _fp("Diode_Bridge_DIP-4_W7.62mm_P5.08mm", "DIP-4 bridge rectifier (DB107 / DF10M style, 1 A); check the + "
               "and ~ markings on the body.", pads, g, (0.635, -1.8, 6.985, 6.6), model)


def bridge_kbpc6() -> Footprint:
    pads = [Pad("1", 0.0, 0.0, 2.6, 2.6, "rect", "tht", 1.3), Pad("2", 0.0, 10.4, 2.6, 2.6, "circle", "tht", 1.3),
            Pad("3", 10.4, 10.4, 2.6, 2.6, "circle", "tht", 1.3), Pad("4", 10.4, 0.0, 2.6, 2.6, "circle", "tht", 1.3)]
    g = _rect(-2.7, -2.65, 12.95, 12.95)
    model = composite(B(-2.55, -2.5, 0.5, 12.8, 12.8, 7.5, "#1b1b1d", sp=0.2), pins="tht", pin_top=0.5)
    return _fp("Diode_Bridge_Vishay_KBPC6", "KBPC6 square bridge rectifier (6 A); pin 1 is the + corner, - is diagonally "
               "opposite.", pads, g, (-2.55, -2.5, 12.8, 12.8), model)


def bridge_round() -> Footprint:
    pads = [Pad("1", 0.0, 0.0, 2.0, 2.0, "rect", "tht", 1.0), Pad("2", 0.0, 5.0, 2.0, 2.0, "oval", "tht", 1.0),
            Pad("3", 5.0, 5.0, 2.0, 2.0, "oval", "tht", 1.0), Pad("4", 5.0, 0.0, 2.0, 2.0, "oval", "tht", 1.0)]
    g = [_circle(2.5, 2.5, 4.65)]
    model = composite(CYL(2.5, 2.5, 0.5, 6.0, 4.5, "#1b1b1d", sp=0.2), pins="tht", pin_top=0.5)
    return _fp("Diode_Bridge_Round_D9.0mm", "Round 1.5 A bridge rectifier (W04G / B40R, 9 mm); check the + marking.",
               pads, g, (-2.0, -2.0, 7.0, 7.0), model)


# --------------------------------------------------------------------------- power transistors & chip amps

def to3() -> Footprint:
    """TO-3 (TO-204AA) on its mounting flange: pin 1 base, pin 2 emitter, the case (pads "3") is the collector."""
    pads = [Pad("1", 0.0, 0.0, 2.6, 2.6, "rect", "tht", 1.3), Pad("2", 0.0, 10.92, 2.6, 2.6, "circle", "tht", 1.3),
            Pad("3", -13.3, 5.45, 6.35, 6.35, "circle", "tht", 4.0), Pad("3", 16.9, 5.45, 6.35, 6.35, "circle", "tht", 4.0)]
    cx, cy = 1.8, 5.45
    # the flange is the convex hull of the can (r 13.6) and the two screw lobes (r 5 round the holes)
    from shapely.geometry import Point
    from shapely.ops import unary_union
    hull = unary_union([Point(cx, cy).buffer(13.6, 24), Point(-13.3, 5.45).buffer(5.0, 12),
                        Point(16.9, 5.45).buffer(5.0, 12)]).convex_hull
    flange = [(r4(x), r4(y)) for x, y in list(hull.exterior.coords)[:-1]]
    g = [Graphic("poly", flange + [flange[0]], 0.12, "silk"), _circle(cx, cy, 10.0, 0.1, "fab")]
    model = composite(PRISM(flange, 1.0, 2.6, "#c7cad0", True),
                      CYL(cx, cy, 2.6, 9.0, 10.0, "#cdd0d6", True, seg=48),
                      CYL(cx, cy, 9.0, 9.6, 8.5, "#d9dce1", True, seg=48),
                      pins="tht", pin_top=1.2)
    return _fp("TO-3", "TO-3 power transistor / regulator (2N3055, MJ15003, LM338K). Pin 1 base, pin 2 emitter, case = "
               "collector (the two screw pads). Usually mounted on a heatsink with an insulator.", pads, g,
               (-18.3, -7.5, 21.9, 18.4), model)


def _zip_ic(name: str, n: int, pitch: float, row: float, body: tuple, desc: str, drill: float = 1.0,
            tab_y: float = -7.98) -> Footprint:
    """Vertical staggered multi-lead TO-220 (KiCad TO-220-n_P..._StaggerOdd): odd pins on the front row."""
    pads = []
    for i in range(n):
        x = r4(i * pitch / 2)
        y = 0.0 if i % 2 == 0 else -row
        pads.append(Pad(str(i + 1), x, y, 1.8, 1.8, "rect" if i == 0 else "circle", "tht", drill))
    x0, y0, x1, y1 = body
    g = _rect(x0 - 0.12, y0 - 0.12, x1 + 0.12, y1 + 0.12) + [_line(x0, tab_y, x1, tab_y, 0.1, "fab")]
    mid = (x0 + x1) / 2
    model = composite(B(x0, tab_y, 4.0, x1, y1, 20.0, "#1a1a1c", sp=0.25),
                      B(x0, y0, 4.0, x1, tab_y, 26.0, "#c9ccd2", True),
                      CYLY(y0 - 0.01, tab_y + 0.01, mid, 23.0, 1.8, DARK))
    for p in pads:  # leads: down from the body, jogging to the staggered row
        model["parts"].append(B(p.x - 0.4, y1 - 0.5, 2.5, p.x + 0.4, y1, 4.2, METAL, True))
        model["parts"].append(B(p.x - 0.4, min(p.y, y1) - 0.25, 2.5, p.x + 0.4, max(p.y, y1) + 0.25, 3.0, METAL, True))
        model["parts"].append(B(p.x - 0.4, p.y - 0.25, -1.6, p.x + 0.4, p.y + 0.25, 3.0, METAL, True))
    return _fp(name, desc, pads, g, (x0, y0, x1, max(y1, 0.9)), model)


def lm3886() -> Footprint:
    return _zip_ic("TO-220-11_P3.4x5.08mm_StaggerOdd_Lead4.58mm_Vertical", 11, 3.4, 5.08, (-1.6, -9.58, 18.6, -4.58),
                   "LM3886T / LM3886TF power amplifier (68 W), TO-220-11 staggered. Pins: 1 +V, 3 OUT, 4 -V, 5 +V, "
                   "7 GND, 8 MUTE (pull >0.5 mA out to un-mute), 9 IN-, 10 IN+; 2, 6, 11 not connected. The "
                   "LM3886T tab is at -V: use the isolated LM3886TF or an insulator.")


def tda7293() -> Footprint:
    return _zip_ic("TO-220-15_P2.54x5.08mm_StaggerOdd_Lead4.58mm_Vertical", 15, 2.54, 5.08, (-1.21, -9.58, 18.99, -4.58),
                   "Multiwatt-15 power amplifier (TDA7293 / TDA7294, 100 W), staggered vertical. TDA7294: 1 standby "
                   "GND, 2 IN-, 3 IN+, 4 IN+ mute, 6 bootstrap, 7 +Vs, 8 -Vs, 9 standby, 10 mute, 13 +PVs, 14 OUT, "
                   "15 -PVs. The tab is at -Vs." + VERIFY)


def pentawatt() -> Footprint:
    return _zip_ic("TO-220-5_P3.4x3.7mm_StaggerOdd_Lead3.8mm_Vertical", 5, 3.4, 3.7, (-1.6, -8.2, 8.4, -3.8),
                   "Pentawatt / TO-220-5 power amplifier (LM1875, TDA2050, TDA2030A): 1 IN+, 2 IN-, 3 -V (tab), "
                   "4 OUT, 5 +V.", drill=1.1, tab_y=-6.93)


def tpa3116() -> Footprint:
    """TI DAD (HTSSOP-32) with the PowerPAD on TOP - the heatsink sits on the package, nothing under it."""
    pads = []
    for i in range(16):
        y = r4(-4.875 + 0.65 * i)
        pads.append(Pad(str(i + 1), -3.7125, y, 1.575, 0.4, "roundrect", "smd"))
    for i in range(16):
        y = r4(4.875 - 0.65 * i)
        pads.append(Pad(str(17 + i), 3.7125, y, 1.575, 0.4, "roundrect", "smd"))
    g = [_line(-3.05, -5.6, 3.05, -5.6), _line(-3.05, 5.6, 3.05, 5.6), _line(-4.7, -5.4, -3.2, -5.4)]
    g += _rect(-3.05, -5.5, 3.05, 5.5, 0.1, "fab")
    model = composite(B(-3.05, -5.5, 0.1, 3.05, 5.5, 1.1, "#1a1a1c", sp=0.25),
                      B(-1.855, -1.905, 1.1, 1.855, 1.905, 1.16, "#c9ccd2", True),
                      leads=(6.1, 11.0), lead_z=0.55)
    return _fp("Texas_DAD0032A_HTSSOP-32_6.1x11mm_P0.65mm_TopEP3.71x3.81mm", "TPA3116D2 / TPA3118 / TPA3130 class-D "
               "amplifier in the DAD package: thermal pad on TOP (clamp a heatsink onto it), no pad underneath.",
               pads, g, (-3.05, -5.5, 3.05, 5.5), model)


# --------------------------------------------------------------------------- connectors

def _npth(x, y, d) -> Pad:
    return Pad("", x, y, d, d, "circle", "npth", d)


def _front_connector(name, desc, pads, g, body, rear, flange, nose_r, axis, face, front, model_extra=None):
    """Panel connector: rear housing box, a flange plate and a round nose pointing along +x (face="x") or +y.

    The courtyard stops at the panel face (the nose goes through the panel), and ``model["front"]`` records the
    face position and direction so the amp builder can put the part on the board's front edge."""
    if face == "x":
        body = (body[0], body[1], min(body[2], front[0]), body[3])
    else:
        body = (body[0], body[1], body[2], min(body[3], front[0]))
    model_extra = dict(model_extra or {})
    model_extra.setdefault("front", {"dir": 0.0 if face == "x" else 270.0, "at": front[0]})
    zf = flange[4] if len(flange) > 4 else 2 * axis[2]
    parts = [B(rear[0], rear[1], 0.3, rear[2], rear[3], rear[4], "#1d1d20", sp=0.25)]
    fx0, fy0, fx1, fy1 = flange[:4]
    parts.append(B(fx0, fy0, 0.0, fx1, fy1, zf, "#2a2b2f", sp=0.35))
    if face == "x":
        parts.append(CYLX(front[0], front[1], axis[1], axis[2], nose_r, "#c9ccd2", True))
        parts.append(CYLX(front[1] - 0.05, front[1] + 0.01, axis[1], axis[2], nose_r * 0.8, DARK))
    else:
        parts.append(CYLY(front[0], front[1], axis[0], axis[2], nose_r, "#c9ccd2", True))
        parts.append(CYLY(front[1] - 0.05, front[1] + 0.01, axis[0], axis[2], nose_r * 0.8, DARK))
    model = composite(*parts, pins="tht", pin_top=0.4, **(model_extra or {}))
    return _fp(name, desc, pads, g, body, model)


def xlr_female_nc3fah() -> Footprint:
    pads = [Pad("1", 0.0, 0.0, 3.4, 3.4, "rect", "tht", 1.6), Pad("2", -0.635, 7.62, 3.4, 3.4, "circle", "tht", 1.6),
            Pad("3", -4.45, 3.81, 2.9, 2.9, "circle", "tht", 1.2), _npth(3.81, 7.62, 1.6), _npth(8.89, 0.0, 1.6)]
    g = _rect(-6.92, -4.31, 12.82, 14.68) + [_line(6.2, -8.69, 6.2, 16.61, 0.1, "fab"), _line(12.7, -8.69, 12.7, 16.61, 0.1, "fab")]
    g += stroke_text("1", 2.4, -2.6, 1.0)
    return _front_connector("Jack_XLR_Neutrik_NC3FAH_Horizontal", "Neutrik NC3FAH female XLR, horizontal PCB mount "
                            "(mic / line input). Pin 1 shield, 2 hot, 3 cold. The front flange sits at the board edge.",
                            pads, g, (-6.8, -8.69, 15.4, 16.61), (-6.8, -4.19, 6.2, 14.56, 19.0),
                            (6.2, -8.69, 12.7, 16.61, 26.0), 9.5, (0, 3.96, 13.0), "x", (12.7, 15.4))


def xlr_male_nc3maah() -> Footprint:
    pads = [Pad("1", 0.0, 0.0, 3.4, 3.4, "rect", "tht", 1.6), Pad("2", 7.62, 0.0, 3.4, 3.4, "circle", "tht", 1.6),
            Pad("3", 3.81, 0.0, 2.9, 2.9, "circle", "tht", 1.2), Pad("G", 3.81, 5.08, 2.9, 2.9, "circle", "tht", 1.2),
            _npth(0.0, 8.89, 1.6), _npth(7.62, 13.97, 1.6)]
    g = _rect(-5.41, -1.54, 13.03, 11.55) + [_line(-8.99, 11.43, 16.31, 11.43, 0.1, "fab"),
                                              _line(-8.99, 17.78, 16.31, 17.78, 0.1, "fab")]
    return _front_connector("Jack_XLR_Neutrik_NC3MAAH_Horizontal", "Neutrik NC3MAAH male XLR, horizontal PCB mount "
                            "(balanced DI / line out). Pin 1 shield, 2 hot, 3 cold, G = housing. Front faces +Y.",
                            pads, g, (-8.99, -1.42, 16.31, 20.48), (-5.29, -1.42, 12.91, 11.43, 19.0),
                            (-8.99, 11.43, 16.31, 17.78, 26.0), 9.5, (3.66, 0, 13.0), "y", (17.78, 20.48))


def xlr_combo_ncj6fa() -> Footprint:
    pads = [Pad("1", 0.0, 0.0, 2.9, 2.9, "circle", "tht", 1.2), Pad("2", -0.635, 13.97, 2.9, 2.9, "circle", "tht", 1.2),
            Pad("3", -5.08, 6.985, 2.7, 2.7, "circle", "tht", 1.2), Pad("G", 11.43, -1.27, 3.2, 3.2, "circle", "tht", 1.6),
            Pad("R", -4.445, 9.842, 2.7, 2.7, "circle", "tht", 1.2), Pad("S", -4.445, 4.128, 2.7, 2.7, "circle", "tht", 1.2),
            Pad("T", 2.54, 2.54, 3.4, 3.4, "circle", "tht", 1.6), Pad("T", 2.54, 11.43, 3.4, 3.4, "circle", "tht", 1.6),
            _npth(8.89, 6.985, 1.6), _npth(12.065, 1.27, 1.6), _npth(12.065, 12.7, 1.6)]
    g = _rect(-6.82, -3.0, 12.18, 15.31) + [_line(12.06, -5.51, 12.06, 19.48, 0.1, "fab")]
    return _front_connector("Jack_XLR-6.35mm_Neutrik_NCJ6FA-H_Horizontal", "Neutrik NCJ6FA-H combo input: female XLR "
                            "(1 shield, 2 hot, 3 cold) plus a 1/4\" TRS jack (T, R, S) in one housing; G = front "
                            "shield. Horizontal PCB mount, front at the board edge.", pads, g,
                            (-6.08, -5.51, 22.11, 19.48), (-6.08, -1.22, 12.06, 15.19, 22.0),
                            (12.06, -5.51, 18.41, 19.48, 31.0), 11.0, (0, 6.98, 15.5), "x", (18.41, 22.11))


def speakon_nl4() -> Footprint:
    pads = [Pad("1+", 0.0, 0.0, 3.0, 3.0, "rect", "tht", 1.2), Pad("1-", 4.44, 9.53, 3.0, 3.0, "circle", "tht", 1.2),
            Pad("2+", 4.44, 3.18, 3.0, 3.0, "circle", "tht", 1.2), Pad("2-", 4.44, -3.17, 3.0, 3.0, "circle", "tht", 1.2)]
    g = _rect(5.32, -8.84, 24.83, 15.2) + stroke_text("1+", -2.2, -2.6, 1.0)
    return _front_connector("Jack_speakON_Neutrik_NL4MDXX-H-3_Horizontal", "Neutrik speakON NL4MD-H-3, 4-pole speaker "
                            "socket, horizontal PCB mount (bass-amp speaker outputs: 1+/1- the main pair).", pads, g,
                            (-1.5, -9.82, 31.71, 16.18), (5.44, -8.72, 24.71, 15.08, 24.0),
                            (24.71, -9.82, 29.21, 16.18, 31.0), 12.0, (0, 3.18, 15.5), "x", (29.21, 31.71))


def jack_nrj6hf() -> Footprint:
    pads = [Pad("T", 0.0, 0.0, 3.0, 3.0, "rect", "tht", 1.5), Pad("R", 6.35, 0.0, 3.0, 3.0, "circle", "tht", 1.5),
            Pad("S", 12.7, 0.0, 3.0, 3.0, "circle", "tht", 1.5), Pad("TN", 0.0, 11.43, 3.0, 3.0, "circle", "tht", 1.5),
            Pad("RN", 6.35, 11.43, 3.0, 3.0, "circle", "tht", 1.5), Pad("SN", 12.7, 11.43, 3.0, 3.0, "circle", "tht", 1.5),
            _npth(3.15, 2.13, 3.0), _npth(9.5, 0.0, 2.0), _npth(9.5, 11.43, 2.0)]
    g = _rect(-7.47, -2.21, 17.07, 13.78)
    for lab, x in (("T", 0.0), ("R", 6.35), ("S", 12.7)):
        g += stroke_text(lab, x, 5.7, 1.0)
    return _front_connector("Jack_6.35mm_Neutrik_NRJ6HF_Horizontal", "Neutrik NRJ6HF 1/4\" stereo switched jack, "
                            "horizontal PCB mount with threaded bushing (amp inputs, FX loop, speaker-emulated out). "
                            "T/R/S plus the switched contacts TN/RN/SN.", pads, g, (-7.35, -2.09, 25.85, 13.66),
                            (-7.35, -2.09, 16.95, 13.66, 15.5), (16.95, 1.73, 17.0, 12.73, 0.01), 5.5,
                            (0, 7.23, 7.8), "x", (16.95, 25.85))


# --------------------------------------------------------------------------- relays & pots

def relay_g5le() -> Footprint:
    pads = [Pad("1", 0.0, 0.0, 2.5, 2.5, "rect", "tht", 1.3), Pad("2", -6.0, 2.0, 2.5, 2.5, "oval", "tht", 1.3),
            Pad("3", -6.0, 14.2, 2.5, 2.5, "oval", "tht", 1.3), Pad("4", 6.0, 14.2, 2.5, 2.5, "oval", "tht", 1.3),
            Pad("5", 6.0, 2.0, 2.5, 2.5, "oval", "tht", 1.3)]
    g = _rect(-8.37, -2.67, 8.37, 20.07)
    model = composite(B(-8.25, -2.55, 0.3, 8.25, 19.95, 18.5, "#1d2a4f", sp=0.35), pins="tht", pin_top=0.4)
    return _fp("Relay_SPDT_Omron-G5LE-1", "Omron G5LE-1 SPDT power relay (channel switching, standby / speaker "
               "muting, soft-start). Pin 1 COM, 3 NC, 4 NO, coil 2-5.", pads, g, (-8.25, -2.55, 8.25, 19.95), model)


def relay_g2rl2() -> Footprint:
    pads = [Pad("A1", 0.0, 0.0, 2.0, 2.0, "rect", "tht", 1.3), Pad("A2", 7.5, 0.0, 2.0, 2.0, "circle", "tht", 1.3)]
    for col, x in (("1", 0.0), ("2", 7.5)):
        for nn, y in (("2", 15.0), ("1", 20.0), ("4", 25.0)):
            pads.append(Pad(col + nn, x, y, 2.0, 2.0, "circle", "tht", 1.3))
    g = _rect(-2.62, -2.42, 10.12, 26.62)
    model = composite(B(-2.5, -2.3, 0.3, 10.0, 26.5, 15.7, "#2a2d33", sp=0.35), pins="tht", pin_top=0.4)
    return _fp("Relay_DPDT_Omron_G2RL-2", "Omron G2RL-2 DPDT relay (two-channel switching, bypass, loop switching). "
               "Coil A1-A2; pole 1: 11 COM, 12 NC, 14 NO; pole 2: 21 / 22 / 24.", pads, g, (-2.5, -2.3, 10.0, 26.5), model)


def pot_rk163() -> Footprint:
    """Alps RK163 16 mm pot, right-angle (shaft parallel to the board, pointing to -X)."""
    pads = [Pad(str(i + 1), 0.0, 5.0 * i, 3.0, 3.0, "rect" if i == 0 else "circle", "tht", 1.2) for i in range(3)]
    g = _rect(-3.92, -4.07, 6.82, 14.07) + [_line(-18.8, 2.0, -8.8, 2.0, 0.1, "fab"), _line(-18.8, 8.0, -8.8, 8.0, 0.1, "fab")]
    axis = 10.0
    model = composite(B(-3.8, -3.95, 1.0, 1.2, 13.95, 19.0, "#c3c6cc", True),
                      B(1.2, -3.95, 1.0, 6.7, 13.95, 18.0, "#26282c", sp=0.25),
                      CYLX(-8.8, -3.8, 5.0, axis, 3.5, "#cfd2d6", True),
                      CYLX(-18.8, -8.8, 5.0, axis, 3.0, "#dcdee2", True),
                      pins="tht", pin_top=1.5, front={"dir": 180.0, "at": -3.8})
    return _fp("Potentiometer_Alps_RK163_Single_Horizontal", "Alps RK163 16 mm pot, right-angle PCB mount (shaft "
               "parallel to the board): front-panel controls on the main amp board. Pin 1 CCW end, 2 wiper, 3 CW end.",
               pads, g, (-3.8, -3.95, 6.7, 13.95), model)


def pot_pta4543() -> Footprint:
    """Bourns PTA4543 45 mm travel slide pot (graphic EQ faders)."""
    pads = [Pad("1", 0.0, 0.0, 1.75, 1.75, "rect", "tht", 1.2), Pad("2", 0.0, 3.5, 1.75, 1.75, "circle", "tht", 1.2),
            Pad("3", 58.5, 0.0, 1.75, 1.75, "circle", "tht", 1.2)]
    for x, y in ((4.15, 5.95), (5.35, -2.45), (53.15, -2.45), (54.35, 5.95)):
        pads.append(Pad("MP", x, y, 2.7, 2.7, "circle", "tht", 1.7))
    g = _rect(-0.87, -2.87, 59.37, 6.37) + [_line(6.75, 1.75, 51.75, 1.75, 0.1, "fab")]
    model = composite(B(-0.75, -2.75, 0.3, 59.25, 6.25, 7.0, "#c3c6cc", True),
                      B(27.8, 0.75, 7.0, 31.2, 2.75, 22.0, "#26282c", sp=0.3), pins="tht", pin_top=0.6)
    return _fp("Potentiometer_Bourns_PTA4543_Single_Slide", "Bourns PTA4543 slide potentiometer, 45 mm travel "
               "(graphic EQ on bass amps). Pins 1 / 3 ends, 2 wiper; MP = mounting tabs.", pads, g,
               (-0.75, -2.75, 59.25, 6.25), model)


# --------------------------------------------------------------------------- wire pads

HV_PITCH = 10.16  # high-voltage strips: 7 mm between 3 mm pads covers ~1400 V peak (IPC-2221B B2)
AMP_WIRES = [  # (labels, use, pitch)
    (["HV1", "CT", "HV2"], "power transformer high-voltage secondary (centre-tapped)", HV_PITCH),
    (["HV1", "HV2"], "power transformer high-voltage secondary (bridge rectifier)", HV_PITCH),
    (["H1", "H2"], "6.3 V heater winding", 5.08),
    (["H1", "CT", "H2"], "6.3 V heater winding with centre tap", 5.08),
    (["5V1", "5V2"], "5 V rectifier-heater winding (at B+ potential with a 5Y3 / 5AR4)", HV_PITCH),
    (["AC1", "AC2"], "mains primary (after the fuse and switch)", HV_PITCH),
    (["AC1", "CT", "AC2"], "low-voltage secondary for a solid-state supply (e.g. 2 x 22 VAC)", 7.62),
    (["P", "B+"], "single-ended output transformer primary", HV_PITCH),
    (["P1", "B+", "P2"], "push-pull output transformer primary", HV_PITCH),
    (["COM", "4R", "8R", "16R"], "output transformer secondary taps", 5.08),
    (["SPK", "COM"], "speaker output / negative feedback tap", 5.08),
    (["CHK1", "CHK2"], "filter choke", HV_PITCH),
    (["B+", "GND"], "B+ to another board", HV_PITCH),
    (["IN", "GND"], "input jack", 5.08),
    (["SEND", "RET", "GND"], "effects loop", 5.08),
    (["BIAS", "GND"], "bias test point / remote bias pot", 5.08),
]


def amp_wire_pads(labels: list[str], use: str = "", pitch: float = 5.08) -> Footprint:
    """Labelled pads for 18-20 AWG transformer and speaker leads: 1.3 mm holes, 3 mm pads. High-voltage strips use
    a 10.16 mm pitch so neighbouring leads keep the IPC spacing."""
    fp = wire_pads(labels, pitch=pitch, drill=1.3, pad=3.0)
    fp.name = "AmpWirePads_" + "_".join(l.replace("+", "P").replace("/", "") for l in labels)
    fp.description = (f"Off-board wire pads for the {use or 'amp wiring'} ({', '.join(labels)}): 1.3 mm holes for "
                      f"18-20 AWG leads, {pitch:g} mm pitch. Set the nets' voltages (Amp > Net voltages) so the HV "
                      "clearance check covers them.")
    return fp


def star_ground() -> Footprint:
    """Plated M4 star-ground point: a lug bolts the main ground, the input jack ground and the filter caps here."""
    pads = [Pad("1", 0.0, 0.0, 9.0, 9.0, "circle", "tht", 4.3)]
    g = [_circle(0, 0, 5.0)] + stroke_text("GND", 0.0, 6.6, 1.2)
    model = composite(CYL(0, 0, 0.0, 0.8, 4.2, METAL, True), CYL(0, 0, 0.8, 3.6, 3.5, "#b9bcc2", True, seg=6),
                      pins=None)
    fp = _fp("StarGround_M4_Plated", "Star-ground point: plated 4.3 mm hole with a 9 mm pad for an M4 bolt and "
             "solder lug. Run every ground return to it once (input jack, preamp, power, filter caps).", pads, g,
             (-4.5, -4.5, 4.5, 7.4), model)
    return fp


# --------------------------------------------------------------------------- catalogue

def _tube_entries(add) -> None:
    groups = {"triode2": "Amp/Tubes - preamp", "pentode": "Amp/Tubes - preamp", "power": "Amp/Tubes - power",
              "rectifier": "Amp/Tubes - rectifier"}
    for t in TUBES.values():
        key = _tube_socket_for(t.base)
        sock = SOCKETS[key]
        aka = f" / {' / '.join(t.aliases[:2])}" if t.aliases else ""
        heater = f"heater {t.heater_v:g} V {t.heater_a:g} A"
        desc = f"{t.name}{aka} on a {sock[8] or t.base} socket. Pinout {t.pinout_text()}; {heater}. {t.note}".strip()
        add((groups[t.kind], f"{t.name}{aka} tube ({BASE_LABEL[t.base]})", "V", t.name,
             lambda k=key: tube_socket(k),
             f"tube valve {t.name} {' '.join(t.aliases)} {t.base} socket amp guitar bass {t.kind}".lower(),
             {"mpn": sock[8], "manufacturer": sock[9], "description": desc}))


def entries():
    out = []
    add = out.append
    _tube_entries(add)
    for key, (base, circle, drill, pad, *_rest) in SOCKETS.items():
        value = {"noval": "12AX7", "b7g": "6AQ5", "octal": "6V6GT"}[base]
        label = {"belton_vt9": "Noval B9A socket, Belton VT9-PT (PCB)",
                 "noval_straight": "Noval B9A socket, straight pins (ceramic PCB)",
                 "b7g_straight": "B7G 7-pin socket, straight pins (ceramic PCB)",
                 "belton_vt8": "Octal socket, Belton VT8-PT"}[key]
        add(("Amp/Tube sockets", label, "V", value, lambda k=key: tube_socket(k),
             f"tube valve socket {base} b9a b7g k8a octal belton amp", {"mpn": SOCKETS[key][8],
                                                                         "manufacturer": SOCKETS[key][9]}))
    for D, H in SNAPIN:
        add(("Amp/HV capacitors", f"Snap-in electrolytic D{D:g} x {H:g} mm", "C", "100uF 450V",
             lambda d=D, h=H: cap_snapin(d, h), "electrolytic snap-in filter reservoir capacitor hv 450v amp"))
    for L, D, P, pad, drill in AXIAL_ELCO:
        add(("Amp/HV capacitors", f"Axial electrolytic L{L:g} D{D:g} P{P:g}", "C", "22uF 450V",
             lambda a=(L, D, P, pad, drill): cap_axial_elco(*a), "electrolytic axial f&t jj hv filter capacitor amp"))
    for L, D, P in AXIAL_FILM:
        add(("Amp/HV capacitors", f"Axial film L{L:g} D{D:g} P{P:g}", "C", "22nF 630V",
             lambda a=(L, D, P): cap_axial_film(*a), "film axial mustard mallory 150 coupling tone capacitor 630v amp"))
    for L, W, P, w in POWER_R:
        add(("Amp/Power resistors", f"Power resistor {w} W cement L{L:g} (lying)", "R", "1k",
             lambda a=(L, W, P, w): resistor_power(*a), "power resistor cement wirewound 5w 10w amp cathode"))
    for L, W, P, w in POWER_R_V:
        add(("Amp/Power resistors", f"Power resistor {w} W cement L{L:g} (standing)", "R", "1k",
             lambda a=(L, W, P, w): resistor_power(*a, vertical=True), "power resistor cement vertical amp"))
    add(("Amp/Rectifiers", "Bridge rectifier KBU (inline)", "D", "KBU810", lambda: bridge_inline("KBU"),
         "bridge rectifier kbu power supply amp", {"mpn": "KBU810"}))
    add(("Amp/Rectifiers", "Bridge rectifier GBU (inline, slim)", "D", "GBU810", lambda: bridge_inline("GBU"),
         "bridge rectifier gbu power supply amp", {"mpn": "GBU810"}))
    add(("Amp/Rectifiers", "Bridge rectifier DIP-4", "D", "DB107", bridge_dip4, "bridge rectifier dip4 db107"))
    add(("Amp/Rectifiers", "Bridge rectifier KBPC6 (square)", "D", "KBPC610", bridge_kbpc6, "bridge rectifier kbpc"))
    add(("Amp/Rectifiers", "Bridge rectifier round 9 mm (W04G)", "D", "W04G", bridge_round, "bridge rectifier round"))
    add(("Amp/Power amp ICs", "TO-3 power transistor", "Q", "MJ15003", to3, "to3 to-204 transistor 2n3055 power"))
    add(("Amp/Power amp ICs", "LM3886 (TO-220-11)", "U", "LM3886TF", lm3886,
         "lm3886 gainclone chip amp power amplifier 68w", {"mpn": "LM3886TF/NOPB", "manufacturer": "Texas Instruments"}))
    add(("Amp/Power amp ICs", "TDA7293 / TDA7294 (Multiwatt-15)", "U", "TDA7293", tda7293,
         "tda7293 tda7294 multiwatt power amplifier 100w", {"manufacturer": "STMicroelectronics"}))
    add(("Amp/Power amp ICs", "LM1875 / TDA2050 (Pentawatt)", "U", "LM1875T", pentawatt,
         "lm1875 tda2050 tda2030 pentawatt chip amp"))
    add(("Amp/Power amp ICs", "TPA3116D2 class-D (HTSSOP-32, top pad)", "U", "TPA3116D2", tpa3116,
         "tpa3116 class d amplifier htssop dad", {"mpn": "TPA3116D2DADR", "manufacturer": "Texas Instruments"}))
    add(("Amp/Jacks & connectors", "XLR female Neutrik NC3FAH (PCB)", "J", "NC3FAH", xlr_female_nc3fah,
         "xlr female mic input neutrik", {"mpn": "NC3FAH", "manufacturer": "Neutrik"}))
    add(("Amp/Jacks & connectors", "XLR male Neutrik NC3MAAH (PCB, DI out)", "J", "NC3MAAH", xlr_male_nc3maah,
         "xlr male di out balanced neutrik", {"mpn": "NC3MAAH", "manufacturer": "Neutrik"}))
    add(("Amp/Jacks & connectors", "XLR / 1/4\" combo Neutrik NCJ6FA-H", "J", "NCJ6FA-H", xlr_combo_ncj6fa,
         "combo xlr jack input neutrik", {"mpn": "NCJ6FA-H", "manufacturer": "Neutrik"}))
    add(("Amp/Jacks & connectors", "speakON NL4MD-H-3 (PCB)", "J", "NL4MD-H-3", speakon_nl4,
         "speakon speaker output neutrik bass", {"mpn": "NL4MD-H-3", "manufacturer": "Neutrik"}))
    add(("Amp/Jacks & connectors", "1/4\" jack Neutrik NRJ6HF (threaded)", "J", "NRJ6HF", jack_nrj6hf,
         "jack 6.35mm quarter inch input fx loop neutrik", {"mpn": "NRJ6HF", "manufacturer": "Neutrik"}))
    add(("Amp/Switching", "Relay Omron G5LE-1 (SPDT)", "K", "G5LE-1 12V", relay_g5le,
         "relay spdt channel switching omron g5le", {"mpn": "G5LE-1-DC12", "manufacturer": "Omron"}))
    add(("Amp/Switching", "Relay Omron G2RL-2 (DPDT)", "K", "G2RL-2 12V", relay_g2rl2,
         "relay dpdt channel switching omron g2rl", {"mpn": "G2RL-2-DC12", "manufacturer": "Omron"}))
    add(("Amp/Controls", "Pot 16 mm right-angle (Alps RK163)", "RV", "A1M", pot_rk163,
         "potentiometer right angle front panel amp 16mm alps"))
    add(("Amp/Controls", "Slide pot 45 mm (Bourns PTA4543)", "RV", "B10K", pot_pta4543,
         "slide fader potentiometer graphic eq bass bourns", {"mpn": "PTA4543-2015DPB103", "manufacturer": "Bourns"}))
    for labels, use, pitch in AMP_WIRES:
        add(("Amp/Wire pads", "Amp wire pads " + ", ".join(labels), "W", "/".join(labels),
             lambda l=labels, u=use, pt=pitch: amp_wire_pads(l, u, pt), f"wire pad transformer speaker heater {use} amp"))
    add(("Amp/Wire pads", "Star ground point (M4, plated)", "W", "STAR GND", star_ground,
         "star ground lug bolt chassis amp"))
    return out
