"""Guitar-pedal parts: board-mount pots, footswitches, 1/4" and DC jacks, toggles, lettered transistor
footprints and labelled off-board wire pads.

Footprints that go through the enclosure carry ``model["panel"]`` metadata, which the pedal tools use to
derive the drill template automatically:

``{"face": "A", "kind": "pot", "d": 7.5, "at": [x, y], "standoff": 10.7, "body_r": 8.5}``
    a part whose bushing goes through the face; ``at`` is the hole centre in footprint coordinates
    (defaults to the origin) and ``standoff`` the distance from the PCB to the panel's inner surface.
``{"face": "side", "kind": "jack", "d": 11.1, "at": [x, y], "dir": 0, "axis_h": 9.1, ...}``
    a part that points at a side wall; ``dir`` is the direction the opening faces in footprint coordinates
    (degrees, counter-clockwise on screen) and ``axis_h`` the height of its axis above the PCB.

Pot footprints are drawn as seen from the front of the pot (shaft towards you, terminals down), which is the
view from the side of the board the pot is soldered to. Pin 1 is on the left; turning the shaft clockwise
moves the wiper towards pin 3.
"""
from __future__ import annotations

from ..model.board import Footprint, Graphic, Pad
from .shapes import B, CYL, CYLX, DARK, VERIFY, _circle, _fp, _line, _rect, composite, r4

# --------------------------------------------------------------------------- stroke font for silk labels

_GLYPHS: dict[str, list[list[tuple[float, float]]]] = {
    "0": [[(1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0)], [(0.6, 5.2), (3.4, 0.8)]],
    "1": [[(1, 1), (2, 0), (2, 6)], [(1, 6), (3, 6)]],
    "2": [[(0, 1), (1, 0), (3, 0), (4, 1), (4, 2), (0, 6), (4, 6)]],
    "3": [[(0, 0), (4, 0), (2, 2.5), (3, 2.5), (4, 3.5), (4, 5), (3, 6), (1, 6), (0, 5)]],
    "4": [[(3, 6), (3, 0), (0, 4), (4, 4)]],
    "5": [[(4, 0), (0, 0), (0, 2.5), (3, 2.5), (4, 3.5), (4, 5), (3, 6), (0, 6)]],
    "6": [[(3, 0), (1, 0), (0, 1), (0, 5), (1, 6), (3, 6), (4, 5), (4, 3.5), (3, 2.5), (0, 2.5)]],
    "7": [[(0, 0), (4, 0), (1.5, 6)]],
    "8": [[(1, 0), (3, 0), (4, 1), (4, 2), (3, 3), (1, 3), (0, 2), (0, 1), (1, 0)],
          [(1, 3), (0, 4), (0, 5), (1, 6), (3, 6), (4, 5), (4, 4), (3, 3)]],
    "9": [[(4, 3.5), (1, 3.5), (0, 2.5), (0, 1), (1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6)]],
    "A": [[(0, 6), (0, 2), (2, 0), (4, 2), (4, 6)], [(0, 3.6), (4, 3.6)]],
    "B": [[(0, 3), (3, 3), (4, 4), (4, 5), (3, 6), (0, 6), (0, 0), (3, 0), (4, 1), (4, 2), (3, 3)]],
    "C": [[(4, 1), (3, 0), (1, 0), (0, 1), (0, 5), (1, 6), (3, 6), (4, 5)]],
    "D": [[(0, 0), (2.5, 0), (4, 1.5), (4, 4.5), (2.5, 6), (0, 6), (0, 0)]],
    "E": [[(4, 0), (0, 0), (0, 6), (4, 6)], [(0, 3), (3, 3)]],
    "F": [[(4, 0), (0, 0), (0, 6)], [(0, 3), (3, 3)]],
    "G": [[(4, 1), (3, 0), (1, 0), (0, 1), (0, 5), (1, 6), (3, 6), (4, 5), (4, 3.5), (2.5, 3.5)]],
    "H": [[(0, 0), (0, 6)], [(4, 0), (4, 6)], [(0, 3), (4, 3)]],
    "I": [[(1, 0), (3, 0)], [(2, 0), (2, 6)], [(1, 6), (3, 6)]],
    "J": [[(4, 0), (4, 5), (3, 6), (1, 6), (0, 5)]],
    "K": [[(0, 0), (0, 6)], [(4, 0), (0, 3.5)], [(1.3, 2.7), (4, 6)]],
    "L": [[(0, 0), (0, 6), (4, 6)]],
    "M": [[(0, 6), (0, 0), (2, 3), (4, 0), (4, 6)]],
    "N": [[(0, 6), (0, 0), (4, 6), (4, 0)]],
    "O": [[(1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0)]],
    "P": [[(0, 6), (0, 0), (3, 0), (4, 1), (4, 2), (3, 3), (0, 3)]],
    "Q": [[(1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0)], [(2.5, 4.5), (4, 6)]],
    "R": [[(0, 6), (0, 0), (3, 0), (4, 1), (4, 2), (3, 3), (0, 3)], [(2, 3), (4, 6)]],
    "S": [[(4, 1), (3, 0), (1, 0), (0, 1), (0, 2), (1, 3), (3, 3), (4, 4), (4, 5), (3, 6), (1, 6), (0, 5)]],
    "T": [[(0, 0), (4, 0)], [(2, 0), (2, 6)]],
    "U": [[(0, 0), (0, 5), (1, 6), (3, 6), (4, 5), (4, 0)]],
    "V": [[(0, 0), (2, 6), (4, 0)]],
    "W": [[(0, 0), (1, 6), (2, 3), (3, 6), (4, 0)]],
    "X": [[(0, 0), (4, 6)], [(4, 0), (0, 6)]],
    "Y": [[(0, 0), (2, 3), (4, 0)], [(2, 3), (2, 6)]],
    "Z": [[(0, 0), (4, 0), (0, 6), (4, 6)]],
    "+": [[(0, 3), (4, 3)], [(2, 1), (2, 5)]],
    "-": [[(0.5, 3), (3.5, 3)]],
    "/": [[(0, 6), (4, 0)]],
    ".": [[(1.8, 5.6), (2.2, 6)]],
    " ": [],
}


def text_width(text: str, h: float) -> float:
    s = h / 6.0
    n = len(text)
    return max(0.0, (5 * n - 1) * s) if n else 0.0


def stroke_text(text: str, x: float, y: float, h: float = 1.0, w: float = 0.15, layer: str = "silk",
                align: str = "center") -> list[Graphic]:
    """Silkscreen text as line segments (upper-case letters, digits and + - / .), centred on (x, y)."""
    s = h / 6.0
    total = text_width(text, h)
    x0 = x - total / 2 if align == "center" else (x - total if align == "right" else x)
    y0 = y - h / 2
    out: list[Graphic] = []
    for i, ch in enumerate(text.upper()):
        ox = x0 + i * 5 * s
        for stroke in _GLYPHS.get(ch, []):
            for (ax, ay), (bx, by) in zip(stroke, stroke[1:]):
                out.append(_line(r4(ox + ax * s), r4(y0 + ay * s), r4(ox + bx * s), r4(y0 + by * s), w, layer))
    return out


# --------------------------------------------------------------------------- potentiometers

POT16_STANDOFF = 10.7  # Alpha RV16AF-41: mounting face to PCB (datasheet side view)


def _pot16_pins(parts: list, xs, y: float, top: float) -> None:
    for x in xs:
        parts.append(B(x - 0.35, y - 0.25, -1.6, x + 0.35, y + 0.25, top, "#cfd2d6", True))
        parts.append(B(x - 0.35, 7.6, top - 0.5, x + 0.35, y + 0.25, top, "#cfd2d6", True))


def pot_alpha16(dual: bool = False) -> Footprint:
    """Alpha 16 mm pot with right-angle PCB pins (RV16AF-41 / RV16A01F-41).

    Origin = shaft axis (the drill position). Datasheet: 3 x dia 1.2 mm holes at 5 mm pitch, 16 mm from the
    shaft centre; body dia 16.5 mm; M7 x 0.75 bushing.
    """
    pads = [Pad(str(i + 1), -5.0 + 5.0 * i, 16.0, 2.2, 2.2, "rect" if i == 0 else "circle", "tht", 1.3)
            for i in range(3)]
    if dual:  # second gang: VERIFY - the rear gang's terminals sit one pitch further out
        pads += [Pad(str(i + 4), -5.0 + 5.0 * i, 21.0, 2.2, 2.2, "circle", "tht", 1.3) for i in range(3)]
    g = [_circle(0, 0, 8.4), _line(-1.2, 0, 1.2, 0, 0.12), _line(0, -1.2, 0, 1.2, 0.12)]
    g += stroke_text("1", -5.0, 18.9 if not dual else 23.9, 1.0) + stroke_text("3", 5.0, 18.9 if not dual else 23.9, 1.0)
    g.append(_circle(0, 0, 3.5, 0.1, "fab"))
    can = 9.1 if not dual else 15.0
    top = POT16_STANDOFF
    parts = [CYL(0, 0, top - can, top - 0.3, 8.25, "#aeb2b8", True, seg=40),
             CYL(0, 0, top - 0.3, top, 8.5, "#c3c6cc", True, seg=40),
             B(-7.6, 6.0, top - 1.6, 7.6, 11.5, top - 0.4, "#6b4a2a"),  # terminal wafer
             CYL(0, 0, top, top + 7.0, 3.5, "#cfd2d6", True),  # M7 bushing
             CYL(0, 0, top + 7.0, top + 15.0, 3.0, "#dcdee2", True)]  # 6 mm shaft
    _pot16_pins(parts, (-5.0, 0.0, 5.0), 16.0, top - 0.4)
    if dual:
        _pot16_pins(parts, (-5.0, 0.0, 5.0), 21.0, top - can + 0.6)
    model = composite(*parts, panel={"face": "A", "kind": "pot", "d": 7.5, "standoff": top, "body_r": 8.5,
                                     "body_len": top})
    name = "Pot_Alpha_16mm_Dual_RV16A01F-41" if dual else "Pot_Alpha_16mm_RV16AF-41"
    desc = ("Alpha 16 mm pot, dual gang, right-angle PCB pins. Solder to the back of the board so the shaft points "
            "through the enclosure face." + VERIFY) if dual else (
        "Alpha 16 mm pot, right-angle PCB pins (RV16AF-41). Pins 5 mm apart, 16 mm from the shaft. Solder to the "
        "back of the board so the shaft points through the enclosure face (drill 7.5 mm).")
    return _fp(name, desc, pads, g, (-8.5, -8.5, 8.5, 8.5), model, ref_gap=1.2)


def pot_alpha9() -> Footprint:
    """Alpha 9 mm vertical pot (RD901F-40-00D style), origin = shaft axis.

    Hole pattern after KiCad's Potentiometer_Alpha_RD901F-40-00D_Single_Vertical, rotated so the terminals
    point down: pins 2.5 mm apart, 7.5 mm below the shaft; mounting lugs 4.8 mm either side of the shaft.
    """
    pads = [Pad(str(i + 1), -2.5 + 2.5 * i, 7.5, 1.8, 1.8, "rect" if i == 0 else "circle", "tht", 1.0)
            for i in range(3)]
    # mounting lugs are flat tabs facing the shaft: slots run tangentially (along Y here)
    pads += [Pad("MP", -4.8, 0.0, 2.72, 3.24, "oval", "tht", 1.1, drill_h=1.8),
             Pad("MP", 4.8, 0.0, 2.72, 3.24, "oval", "tht", 1.1, drill_h=1.8)]
    g = _rect(-4.9, -5.6, 4.9, 5.6) + stroke_text("1", -2.5, 9.6, 0.9) + [_circle(0, 0, 3.5, 0.1, "fab")]
    top = 7.0
    model = composite(B(-4.75, -5.5, 0.4, 4.75, 5.5, top, "#1d1d1f"),
                      B(-4.9, -5.6, top - 0.6, 4.9, 5.6, top, "#b8bcc2", True),
                      CYL(0, 0, top, top + 5.0, 3.5, "#cfd2d6", True),
                      CYL(0, 0, top + 5.0, top + 15.0, 3.0, "#dcdee2", True),
                      pins="tht", pin_top=0.6,
                      panel={"face": "A", "kind": "pot9", "d": 7.2, "standoff": top, "body_r": 5.8, "body_len": top})
    return _fp("Pot_Alpha_9mm_RD901F-40_Vertical", "Alpha 9 mm pot, vertical PCB mount with mounting lugs "
               "(RD901F-40 style). Shaft through the enclosure face." + VERIFY, pads, g, (-6.5, -5.6, 6.5, 5.6),
               model, ref_gap=1.0)


# --------------------------------------------------------------------------- footswitch & toggles

def footswitch_3pdt() -> Footprint:
    """3PDT latching footswitch with PCB pins (for footswitch daughterboards / one-piece boards).

    Lugs 1-2-3 / 4-5-6 / 7-8-9; each column is one pole with its common in the middle row (4, 5, 6).
    Lug pitch 5.3 mm across the columns, 4.8 mm between rows (typical Taiwanese 3PDT).
    """
    pads = []
    n = 1
    for r in range(3):
        for c in range(3):
            pads.append(Pad(str(n), r4((c - 1) * 5.3), r4((r - 1) * 4.8), 3.4, 2.4, "rect" if n == 1 else "oval",
                            "tht", 2.3, drill_h=1.1))
            n += 1
    g = _rect(-8.8, -8.8, 8.8, 8.8) + stroke_text("1", -5.3, -7.3, 0.9)
    g.append(_circle(0, 0, 6.1, 0.1, "fab"))
    model = composite(B(-8.8, -8.8, 5.5, 8.8, 8.8, 23.5, "#18181a"),
                      CYL(0, 0, 23.5, 32.5, 6.0, "#cfd2d6", True),
                      CYL(0, 0, 32.5, 43.0, 4.6, "#dcdee2", True),
                      CYL(0, 0, 43.0, 44.5, 5.4, "#dcdee2", True),
                      pins="tht", pin_top=5.5,
                      panel={"face": "A", "kind": "footswitch", "d": 12.2, "body_r": 11.0, "body_len": 28.0})
    return _fp("Footswitch_3PDT_PCB", "3PDT latching footswitch, PCB pins (true bypass). Commons are the middle "
               "row (4, 5, 6). Panel hole 12 mm." + VERIFY, pads, g, (-8.8, -8.8, 8.8, 8.8), model)


def toggle_mini(poles: int) -> Footprint:
    """MTS-style mini toggle, 4.7 mm pitch; rows of three with the common in the middle column."""
    rows = poles
    pads = []
    n = 1
    for r in range(rows):
        for c in range(3):
            pads.append(Pad(str(n), r4((c - 1) * 4.7), r4((r - (rows - 1) / 2) * 4.7), 2.4, 2.4,
                            "rect" if n == 1 else "circle", "tht", 1.3))
            n += 1
    hw = 3 * 4.7 / 2 + 0.6
    hh = max(4.0, rows * 4.7 / 2 + 1.7)
    g = _rect(-hw, -hh, hw, hh) + [_circle(0, 0, 3.1, 0.1, "fab")]
    top = 10.5
    model = composite(B(-hw + 0.2, -hh + 0.2, 0.5, hw - 0.2, hh - 0.2, top - 2.5, "#1c1c1f"),
                      B(-hw + 0.2, -hh + 0.2, top - 2.5, hw - 0.2, hh - 0.2, top, "#c3c6cc", True),
                      CYL(0, 0, top, top + 9.0, 3.0, "#cfd2d6", True),
                      CYL(0, 0, top + 9.0, top + 19.0, 1.3, "#dcdee2", True),
                      pins="tht", pin_top=0.5,
                      panel={"face": "A", "kind": "toggle", "d": 6.2, "body_r": max(hw, hh), "body_len": top})
    name = {2: "DPDT", 3: "3PDT"}.get(poles, f"{poles}P")
    return _fp(f"Toggle_Mini_{name}_P4.7mm", f"Mini toggle switch {name} (MTS-{poles}02 style, on-on or "
               "on-off-on), PCB pins, 6 mm bushing through the face." + VERIFY, pads, g, (-hw, -hh, hw, hh), model)


# --------------------------------------------------------------------------- jacks & power

def jack_neutrik_nmj6hcd2() -> Footprint:
    """Neutrik NMJ6HCD2 1/4" stereo switched jack, horizontal PCB mount (KiCad pad pattern, re-centred)."""
    pads = []
    for name, x, y in (("T", -6.35, -8.115), ("R", 0.0, -8.115), ("S", 6.35, -8.115),
                       ("TN", -6.35, 8.115), ("RN", 0.0, 8.115), ("SN", 6.35, 8.115)):
        pads.append(Pad(name, x, y, 3.0, 3.0, "circle", "tht", 1.4))
    g = _rect(-10.26, -9.1, 10.35, 9.1)
    for label, x, y in (("T", -6.35, -5.0), ("R", 0.0, -5.0), ("S", 6.35, -5.0)):
        g += stroke_text(label, x, y, 1.0)
    g += [_line(10.35, -5.7, 13.35, -5.7, 0.1, "fab"), _line(10.35, 5.7, 13.35, 5.7, 0.1, "fab")]
    axis = 9.1
    model = composite(B(-10.26, -9.1, 0.0, 10.35, 9.1, 2 * axis, "#151517"),
                      CYLX(10.35, 13.35, 0.0, axis, 5.5, "#d6d8dc", True),
                      CYLX(13.34, 13.37, 0.0, axis, 3.2, DARK),
                      pins="tht", pin_top=1.0,
                      panel={"face": "side", "kind": "jack", "d": 11.1, "at": [13.35, 0.0], "dir": 0.0,
                             "axis_h": axis, "body_r": 9.1, "body_len": 23.6})
    return _fp("Jack_6.35mm_Neutrik_NMJ6HCD2", "Neutrik NMJ6HCD2 1/4\" (6.35 mm) stereo switched jack, straight "
               "PCB pins, chrome ferrule. Pads T/R/S and the switched contacts TN/RN/SN. Panel hole 11.1 mm."
               + VERIFY, pads, g, (-10.26, -9.1, 13.35, 9.1), model, ref_gap=1.0)


def dc_jack_pcb() -> Footprint:
    """2.1 mm DC jack, PCB mount (DC-005 / PJ-002A style), slotted pins (KiCad BarrelJack_Horizontal)."""
    pads = [Pad("1", 0.0, 0.0, 3.5, 3.5, "rect", "tht", 1.0, drill_h=3.0),
            Pad("2", -6.0, 0.0, 3.0, 3.5, "roundrect", "tht", 1.0, drill_h=3.0),
            Pad("3", -3.0, 4.7, 3.5, 3.5, "roundrect", "tht", 3.0, drill_h=1.0)]
    g = _rect(-13.7, -4.5, 0.8, 4.5) + [_line(-10.2, -4.5, -10.2, 4.5, 0.1, "fab")]
    axis = 6.4
    model = composite(B(-13.7, -4.5, 0.0, 0.8, 4.5, 11.0, "#151517"),
                      CYLX(-13.72, -13.69, 0.0, axis, 3.1, DARK),
                      CYLX(-13.0, -3.0, 0.0, axis, 0.9, "#cfd2d6", True),
                      pins="tht", pin_top=1.0,
                      panel={"face": "side", "kind": "dc", "d": 8.0, "at": [-13.7, 0.0], "dir": 180.0,
                             "axis_h": axis, "body_r": 6.5, "body_len": 14.5})
    return _fp("DC_Jack_2.1mm_PCB_Pedal", "2.1 mm DC jack, PCB mount. Pin 1 = centre pin, 2 = sleeve, 3 = switch. "
               "Pedal standard is centre-negative: pin 1 to GND, pin 2 to +9V (via reverse-polarity protection). "
               "Hole 8 mm for the plug." + VERIFY, pads, g, (-13.7, -4.5, 0.8, 6.45), model)


# --------------------------------------------------------------------------- transistors (lettered pinouts)

def to92_lettered(pins: str) -> Footprint:
    """TO-92 on a 2.54 mm grid (easy to solder and socket) with pads named after the pinout, left to right as
    seen from the flat face."""
    letters = list(pins)
    pads = [Pad(l, -2.54 + 2.54 * i, 0.0, 1.8, 1.8, "rect" if i == 0 else "circle", "tht", 0.9)
            for i, l in enumerate(letters)]
    g = [Graphic("arc", [(0, -0.2)], 0.12, "silk", r=2.6, start=20, sweep=140), _line(-2.4, 1.6, 2.4, 1.6)]
    for i, l in enumerate(letters):
        g += stroke_text(l, -2.54 + 2.54 * i, 2.8, 0.9)
    model = {"type": "to92", "body": "#1a1a1a"}
    kind = "JFET" if set(letters) == set("DSG") else "BJT"
    return _fp(f"TO-92_{pins}_Wide", f"TO-92 {kind}, pins {'-'.join(letters)} (flat side facing you, left to "
               "right), 2.54 mm pitch", pads, g, (-3.4, -2.9, 3.4, 3.4), model, ref_gap=0.8)


# --------------------------------------------------------------------------- wire pads

def wire_pads(labels: list[str], pitch: float = 3.81, drill: float = 1.0, pad: float = 2.2) -> Footprint:
    """A strip of labelled off-board wire pads; each pad is named after its label (so its net can be too)."""
    n = len(labels)
    x0 = -(n - 1) * pitch / 2
    pads = [Pad(lab, r4(x0 + i * pitch), 0.0, pad, pad, "rect" if i == 0 else "circle", "tht", drill)
            for i, lab in enumerate(labels)]
    g: list[Graphic] = []
    for i, lab in enumerate(labels):
        h = 1.0 if text_width(lab, 1.0) <= pitch - 0.3 else max(0.6, (pitch - 0.3) / text_width(lab, 1.0))
        g += stroke_text(lab, x0 + i * pitch, -pad / 2 - 1.1, h)
    w = (n - 1) * pitch + pad
    fp = _fp("WirePads_" + "_".join(l.replace("+", "P").replace("-", "N").replace("/", "") for l in labels),
             f"Off-board wire pads ({', '.join(labels)}), {drill:g} mm holes for 22-24 AWG hook-up wire",
             pads, g, (-w / 2, -pad / 2 - 1.8, w / 2, pad / 2), {"type": "none"}, ref_gap=0.6)
    fp.ref_pos = (0.0, r4(pad / 2 + 1.4))
    return fp


WIRE_STRIPS = [
    ["IN", "OUT"], ["9V", "GND"], ["IN", "GND", "OUT"], ["IN", "OUT", "9V", "GND"], ["9V", "GND", "IN", "OUT", "LED"],
    ["S", "T"], ["S", "R", "T"], ["1", "2", "3"], ["A", "K"], ["LED+", "LED-"],
]


# --------------------------------------------------------------------------- catalogue

def entries():
    out = []
    add = out.append
    add(("Pedal/Potentiometers", "Alpha 16 mm pot (PCB right-angle)", "RV", "B100K", pot_alpha16,
         "pot potentiometer alpha 16mm knob pedal rv16af volume gain tone",
         {"mpn": "RV16AF-41-15R1-B100K", "manufacturer": "Taiwan Alpha"}))
    add(("Pedal/Potentiometers", "Alpha 16 mm dual-gang pot (PCB)", "RV", "B100K", lambda: pot_alpha16(True),
         "pot potentiometer dual gang stereo alpha 16mm pedal", {"manufacturer": "Taiwan Alpha"}))
    add(("Pedal/Potentiometers", "Alpha 9 mm pot (PCB vertical)", "RV", "B100K", pot_alpha9,
         "pot potentiometer alpha 9mm mini pedal", {"manufacturer": "Taiwan Alpha"}))
    add(("Pedal/Switches", "3PDT footswitch (PCB pins)", "SW", "3PDT", footswitch_3pdt,
         "footswitch stomp 3pdt true bypass pedal switch"))
    add(("Pedal/Switches", "Mini toggle DPDT (on-on / on-off-on)", "SW", "DPDT", lambda: toggle_mini(2),
         "toggle switch dpdt mts-202 mode clipping pedal"))
    add(("Pedal/Switches", "Mini toggle 3PDT", "SW", "3PDT", lambda: toggle_mini(3),
         "toggle switch 3pdt mts-302 pedal"))
    add(("Pedal/Jacks", '1/4" jack stereo, Neutrik NMJ6HCD2', "J", "NMJ6HCD2", jack_neutrik_nmj6hcd2,
         "jack 6.35mm quarter inch guitar input output neutrik trs pedal",
         {"mpn": "NMJ6HCD2", "manufacturer": "Neutrik"}))
    add(("Pedal/Jacks", "DC jack 2.1 mm, centre-negative (PCB)", "J", "DC 9V", dc_jack_pcb,
         "dc jack power 9v barrel 2.1mm boss pedal"))
    for pins in ("EBC", "CBE", "ECB", "BCE", "DSG", "GSD", "SGD"):
        kind = "JFET" if set(pins) == set("DSG") else "BJT"
        value = {"EBC": "2N5088", "CBE": "BC549C", "DSG": "J201"}.get(pins, kind if kind == "JFET" else "NPN")
        add(("Pedal/Transistors", f"TO-92 {'-'.join(pins)} ({kind}, wide)", "Q", value,
             lambda p=pins: to92_lettered(p), f"transistor to92 {pins.lower()} {kind.lower()} pinout pedal"))
    for labels in WIRE_STRIPS:
        add(("Pedal/Wire pads", "Wire pads " + ", ".join(labels), "W", "/".join(labels),
             lambda l=labels: wire_pads(l), "wire pad solder off-board jack footswitch led pedal"))
    return out
