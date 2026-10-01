"""LEDs & displays, switches, relays, crystals & oscillators, buzzers, optos, modules and mechanical parts."""
from __future__ import annotations

from ..model.board import Footprint, Pad
from ..model.footprints import crystal_3225, crystal_hc49, fiducial, led_tht, mounting_hole, tactile_switch
from .shapes import (B, BLACK, CYL, DARK, DOME, GOLD, METAL, VERIFY, _circle, _fp, _line, _rect, composite, grid_tht,
                     inline_tht, r4, two_terminal_smd)
from .gen_ic import dip, dual_package


# --------------------------------------------------------------------------- LEDs & displays

def led_plcc2(code: str) -> Footprint:
    L, W = {"3528": (3.5, 2.8), "2835": (3.5, 2.8), "3014": (3.0, 1.4), "5730": (5.7, 3.0)}[code]
    model = composite(B(-L / 2, -W / 2, 0, L / 2, W / 2, 0.7, "#f2f2ee"), B(-L / 2 + 0.3, -W / 2 + 0.3, 0.7, L / 2 - 0.3,
                                                                            W / 2 - 0.3, 0.75, "#f5e7a8", sp=0.9))
    if code == "5730":  # Yuji 5730: anode pad split around the large thermal pad
        pads = [Pad("1", -2.85, 0, 1.1, 1.7, "rect"), Pad("2", 0.35, 0, 2.5, 1.7, "rect"), Pad("2", 2.85, 0, 1.1, 1.7, "rect")]
        g = [_line(-3.6, -1.1, -3.6, 1.1, 0.15)] + _rect(-L / 2 + 0.5, -W / 2, L / 2 - 0.5, W / 2, 0.1, "fab")
        return _fp("LED_Yuji_5730", "SMD LED 5730 (Yuji 5730 land pattern), pin 1 = cathode", pads, g,
                   (-3.4, -W / 2, 3.4, W / 2), model)
    if code == "2835":  # large thermal pad (pin 1) + small pad (pin 2)
        pads = [Pad("1", -0.9, 0, 2.2, 2.2, "rect"), Pad("2", 1.375, 0, 1.25, 2.2, "rect")]
        g = [_line(-2.2, -1.5, -2.2, 1.5, 0.15)] + _rect(-L / 2, -W / 2, L / 2, W / 2, 0.1, "fab")
        return _fp("LED_PLCC_2835", "SMD LED 2835 (PLCC-2), pin 1 = cathode / thermal pad", pads, g,
                   (-L / 2, -W / 2, L / 2, W / 2), model)
    pw, ph, cx = (1.0, W * 0.8, L / 2 - 0.35) if code != "5730" else (1.4, 2.4, 2.2)
    return two_terminal_smd(f"LED_PLCC-2_{code}", f"White/colour SMD LED {code} (PLCC-2), pin 1 = cathode." + VERIFY,
                            pw, ph, cx, L, W, model, polarity=True, silk=False)


def led_5050_rgb() -> Footprint:
    pads = []
    for i, y in enumerate((-1.7, 0, 1.7)):
        pads.append(Pad(str(i + 1), -2.4, y, 2.0, 1.1, "rect"))
        pads.append(Pad(str(6 - i), 2.4, y, 2.0, 1.1, "rect"))
    pads.sort(key=lambda p: int(p.number))
    g = _rect(-2.5, -2.5, 2.5, 2.5, 0.1, "fab") + [_line(-3.4, -2.6, -3.4, -1.0)]
    model = composite(B(-2.5, -2.5, 0, 2.5, 2.5, 1.5, "#f2f2ee"), CYL(0, 0, 1.5, 1.55, 2.0, "#f4f4ff", sp=0.9, seg=32))
    return _fp("LED_RGB_5050-6", "RGB LED 5050 (PLCC-6), 3 independent dice", pads, g,
               (-2.5, -2.5, 2.5, 2.5), model)


def led_ws2812b() -> Footprint:
    pads = [Pad("1", -2.45, -1.6, 1.5, 1.0, "roundrect"), Pad("2", -2.45, 1.6, 1.5, 1.0, "roundrect"),
            Pad("3", 2.45, 1.6, 1.5, 1.0, "roundrect"), Pad("4", 2.45, -1.6, 1.5, 1.0, "roundrect")]
    g = _rect(-2.5, -2.5, 2.5, 2.5, 0.1, "fab") + [_line(-3.5, -2.6, -2.5, -2.6), _line(-3.5, -2.6, -3.5, -1.6)]
    model = composite(B(-2.5, -2.5, 0, 2.5, 2.5, 1.6, "#f2f2ee"), CYL(0, 0, 1.6, 1.62, 1.9, "#fbfbff", sp=0.9, seg=32),
                      B(1.0, 1.0, 1.61, 2.5, 2.5, 1.63, "#e8e8e8"))
    return _fp("LED_WS2812B_PLCC4_5.0x5.0mm", "WS2812B addressable RGB LED (NeoPixel), 5x5 mm. 1 VDD, 2 DOUT, 3 VSS, 4 DIN",
               pads, g, (-2.5, -2.5, 2.5, 2.5), model)


def led_sk6812mini() -> Footprint:
    pads = [Pad("1", -1.75, -0.875, 1.6, 0.85, "rect"), Pad("2", -1.75, 0.875, 1.6, 0.85, "rect"),
            Pad("3", 1.75, 0.875, 1.6, 0.85, "rect"), Pad("4", 1.75, -0.875, 1.6, 0.85, "rect")]
    model = composite(B(-1.75, -1.75, 0, 1.75, 1.75, 0.9, "#f2f2ee"), CYL(0, 0, 0.9, 0.92, 1.3, "#fbfbff", sp=0.9))
    return _fp("LED_SK6812MINI_PLCC4_3.5x3.5mm", "SK6812MINI addressable RGB LED 3535", pads,
               _rect(-1.75, -1.75, 1.75, 1.75, 0.1, "fab"), (-1.75, -1.75, 1.75, 1.75), model)


def led_ws2812b_2020() -> Footprint:
    pads = [Pad("1", -0.915, -0.55, 0.7, 0.7, "rect"), Pad("2", -0.915, 0.55, 0.7, 0.7, "rect"),
            Pad("3", 0.915, 0.55, 0.7, 0.7, "rect"), Pad("4", 0.915, -0.55, 0.7, 0.7, "rect")]
    model = composite(B(-1.0, -1.0, 0, 1.0, 1.0, 0.84, "#f2f2ee"), CYL(0, 0, 0.84, 0.85, 0.7, "#fbfbff", sp=0.9))
    return _fp("LED_WS2812B-2020_PLCC4_2.0x2.0mm", "WS2812B-2020 addressable RGB LED, 2x2 mm", pads, [],
               (-1.27, -1.0, 1.27, 1.0), model)


def led_rgb_tht(d: float) -> Footprint:
    pads = inline_tht(4, 1.27, 1.2, 0.7, shape="oval", pad_h=1.8)
    g = [_circle(0, 0, d / 2 + 0.3)]
    r = d / 2
    model = composite(CYL(0, 0, 1.0, d + 3.6 - r, r, "#f4f6ff", sp=0.9, seg=32), DOME(0, 0, d + 3.6 - r, r, "#f4f6ff"),
                      CYL(0, 0, 0.6, 1.6, r + 0.4, "#f4f6ff", seg=32), pins="tht")
    return _fp(f"LED_RGB_D{d:g}mm_4pin", f"RGB LED {d:g} mm, 4 leads (common anode/cathode)", pads, g, (-r, -r, r, r), model)


def led_rect_tht() -> Footprint:
    pads = inline_tht(2, 2.54, 1.8, 0.9)
    g = _rect(-2.5, -1.0, 2.5, 1.0)
    model = composite(B(-2.5, -1.0, 1.0, 2.5, 1.0, 7.0, "#ff2a1a", sp=0.9), pins="tht")
    return _fp("LED_Rectangular_5x2mm", "Rectangular LED 5x2 mm, through-hole", pads, g, (-2.5, -1.0, 2.5, 1.0), model)


def seven_segment(digits: int) -> Footprint:
    """0.56 inch 7-segment displays: 1 digit (LTS-6760 / 5161 pinout, 10 pins) or 4 digits (CA56-12 / 5641, 12 pins).

    Rows 15.24 mm apart, pins numbered like a DIP: 1..n/2 along one row, then back along the other.
    """
    if digits == 1:
        n, w, h, pw, ph, drill, shape, ref = 10, 12.6, 19.05, 1.524, 2.524, 0.8, "oval", "LTS-6760"
    else:
        n, w, h, pw, ph, drill, shape, ref = 12, 50.3, 19.0, 1.5, 1.5, 1.0, "circle", "CA56-12"
    per = n // 2
    pads = []
    x0 = -(per - 1) * 2.54 / 2
    for i in range(per):
        pads.append(Pad(str(i + 1), r4(x0 + i * 2.54), 7.62, pw, ph, "rect" if i == 0 else shape, "tht", drill))
    for i in range(per):
        pads.append(Pad(str(per + i + 1), r4(-x0 - i * 2.54), -7.62, pw, ph, shape, "tht", drill))
    g = _rect(-w / 2, -h / 2, w / 2, h / 2)
    model = composite(B(-w / 2, -h / 2, 0.5, w / 2, h / 2, 8.0, "#141414"), pins="tht")
    return _fp(f"7Segment_{digits}Digit_0.56in", f"7-segment LED display, {digits} digit(s), 0.56 inch ({ref} pinout)",
               pads, g, (-w / 2, -h / 2, w / 2, h / 2), model)


# --------------------------------------------------------------------------- switches

def tactile_smd(size: str) -> Footprint:
    """SMD tactile switches. Pads in the same row are internally connected; pressing connects 1 to 2."""
    dims = {  # body w, h, pad x, pad y, pad w, pad h, height, reference
        "6x6": (6.0, 6.0, 3.98, 2.25, 1.55, 1.3, 3.5, "C&K PTS645 SMT"),
        "5.2x5.2": (5.2, 5.2, 3.15, 1.9, 1.7, 1.0, 1.5, "E-Switch TL3342"),
        "4x4": (4.0, 4.0, 2.75, 1.2, 1.0, 0.75, 1.5, "generic 4x4"),
        "3x6": (6.0, 3.5, 3.9, 0.0, 1.6, 1.4, 2.5, "generic 3x6, 2 pads"),
        "12x12": (12.0, 12.0, 7.0, 4.25, 2.0, 1.4, 4.3, "generic 12x12"),
    }
    w, h, px, py, pw, ph, H, ref = dims[size]
    if py == 0:
        pads = [Pad("1", -px, 0, pw, ph, "roundrect"), Pad("2", px, 0, pw, ph, "roundrect")]
    else:
        pads = [Pad("1", -px, -py, pw, ph, "roundrect"), Pad("1", px, -py, pw, ph, "roundrect"),
                Pad("2", -px, py, pw, ph, "roundrect"), Pad("2", px, py, pw, ph, "roundrect")]
    g = _rect(-w / 2, -h / 2, w / 2, h / 2) + [_circle(0, 0, min(w, h) * 0.28)]
    model = {"type": "tact", "w": w, "h": h, "H": H, "actuator": min(w, h) * 0.55, "act_h": 0.6 if H < 2 else 1.2}
    verify = "" if ref[0] in "CE" else VERIFY
    return _fp(f"SW_Push_SMD_{size}mm", f"Tactile push button, SMD {size} mm ({ref} land pattern).{verify}", pads, g,
               (-w / 2, -h / 2, w / 2, h / 2), model)


def tactile_12mm() -> Footprint:
    """12x12 mm tactile switch, through-hole. Pins in the same row are internally connected."""
    pads = [Pad("1", -6.25, -2.5, 3.2, 1.9, "oval", "tht", 1.3), Pad("1", 6.25, -2.5, 3.2, 1.9, "oval", "tht", 1.3),
            Pad("2", -6.25, 2.5, 3.2, 1.9, "oval", "tht", 1.3), Pad("2", 6.25, 2.5, 3.2, 1.9, "oval", "tht", 1.3)]
    g = _rect(-6.0, -6.0, 6.0, 6.0) + [_circle(0, 0, 3.5)]
    model = {"type": "tact", "w": 12.0, "h": 12.0, "H": 4.3, "actuator": 7.0, "act_h": 3.0}
    return _fp("SW_PUSH-12mm", "Tactile push button, 12x12 mm, through-hole", pads, g, (-6.0, -6.0, 6.0, 6.0), model)


def slide_switch_tht() -> Footprint:
    """Slide switch SPDT, through-hole, straight (C&K OS102011MS2Q). Pin 2 = common; unnumbered pads = lugs."""
    pads = [Pad("1", -2.0, 0, 1.5, 2.5, "rect", "tht", 0.8), Pad("2", 0.0, 0, 1.5, 2.5, "oval", "tht", 0.8),
            Pad("3", 2.0, 0, 1.5, 2.5, "oval", "tht", 0.8),
            Pad("", -4.1, 0, 2.2, 3.5, "oval", "tht", 1.5), Pad("", 4.1, 0, 2.2, 3.5, "oval", "tht", 1.5)]
    g = _rect(-4.3, -2.15, 4.3, 2.15)
    model = composite(B(-4.3, -2.15, 0, 4.3, 2.15, 3.5, METAL, True), B(-0.75, -0.75, 3.5, 0.75, 0.75, 7.5, BLACK),
                      pins="tht")
    return _fp("SW_Slide_SPDT_Straight_CK_OS102011MS2Q", "Slide switch SPDT, through-hole (C&K OS102011MS2Q)", pads, g,
               (-5.2, -2.15, 5.2, 2.15), model)


def slide_switch_smd() -> Footprint:
    """Miniature slide switch SPDT, SMD (Shouhan MSK12C02 land pattern). Pin 2 = common."""
    pads = [Pad("1", -2.25, -1.95, 0.6, 1.3, "roundrect"), Pad("2", 0.75, -1.95, 0.6, 1.3, "roundrect"),
            Pad("3", 2.25, -1.95, 0.6, 1.3, "roundrect")]
    for x, y in ((-3.675, -1.1), (-3.675, 1.1), (3.675, -1.1), (3.675, 1.1)):
        pads.append(Pad("SH", x, y, 1.05, 0.7, "roundrect"))
    pads += [Pad("", -1.5, 0, 0.85, 0.85, "circle", "npth", 0.85), Pad("", 1.5, 0, 0.85, 0.85, "circle", "npth", 0.85)]
    model = composite(B(-3.35, -1.4, 0, 3.35, 1.4, 1.5, METAL, True), B(-0.5, 1.4, 0.4, 0.5, 2.85, 1.1, BLACK))
    return _fp("SW_SPDT_Shouhan_MSK12C02", "Miniature slide switch SPDT, SMD (Shouhan MSK12C02)", pads, [],
               (-4.2, -2.6, 4.2, 2.85), model)


def dip_switch(n: int, smd: bool = False) -> Footprint:
    if smd:
        from .shapes import dual_row_numbering
        pads = dual_row_numbering(2 * n, 2.54, 4.0, 2.0, 1.2)
        name = f"SW_DIP_SPSTx{n:02d}_SMD"
    else:
        from .shapes import dual_row_numbering
        pads = dual_row_numbering(2 * n, 2.54, 3.81, 1.6, 1.6, "circle", "tht", 0.8)
        pads[0].shape = "rect"
        name = f"SW_DIP_SPSTx{n:02d}_THT"
    L = n * 2.54 + 1.0
    g = _rect(-3.4, -L / 2, 3.4, L / 2)
    parts = [B(-3.3, -L / 2, 0.5, 3.3, L / 2, 4.2, "#c8222b")]
    for p in pads[:n]:
        parts.append(B(-1.2, p.y - 0.5, 4.2, 1.2, p.y + 0.5, 4.25, "#303030"))
        parts.append(B(-1.1, p.y - 0.4, 4.2, -0.2, p.y + 0.4, 4.9, "#f5f5f5"))
    model = composite(*parts, pins="tht" if not smd else None)
    return _fp(name, f"DIP switch, {n} positions, {'SMD' if smd else 'through-hole'}", pads, g, (-3.4, -L / 2, 3.4, L / 2),
               model)


def rotary_encoder_ec11() -> Footprint:
    """Rotary encoder with push switch (Alps EC11E land pattern). A/C/B encoder, S1/S2 switch, MP mounting lugs."""
    cx, cy = 7.25, 2.5
    spec = [("A", 0, 0, "rect"), ("C", 0, 2.5, "circle"), ("B", 0, 5.0, "circle"), ("S2", 14.5, 0, "circle"),
            ("S1", 14.5, 5.0, "circle")]
    pads = [Pad(n, x - cx, y - cy, 2.0, 2.0, sh, "tht", 1.0) for n, x, y, sh in spec]
    pads += [Pad("MP", 7.5 - cx, -3.1 - cy, 3.2, 2.0, "rect", "tht", 2.8, drill_h=1.5),
             Pad("MP", 7.5 - cx, 8.1 - cy, 3.2, 2.0, "rect", "tht", 2.8, drill_h=1.5)]
    g = _rect(1.5 - cx, -3.3 - cy, 13.5 - cx, 8.3 - cy)
    model = composite(B(1.5 - cx, -3.3 - cy, 0.5, 13.5 - cx, 8.3 - cy, 7.0, METAL, True), CYL(0, 0, 7.0, 12.0, 3.5, "#c0c3c8", True),
                      CYL(0, 0, 12.0, 20.0, 3.0, "#b3b6bb", True), pins="tht")
    return _fp("RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm", "Rotary encoder with push switch (Alps EC11E)", pads, g,
               (-8.75, -6.6, 8.75, 6.6), model)


def toggle_switch() -> Footprint:
    pads = inline_tht(3, 4.7, 2.5, 1.5, shape="oval")
    g = _rect(-6.5, -3.5, 6.5, 3.5)
    model = composite(B(-6.5, -3.5, 0, 6.5, 3.5, 9.0, METAL, True), CYL(0, 0, 9.0, 18.0, 1.5, METAL, True), pins="tht")
    return _fp("SW_Toggle_SPDT_P4.7mm", "Miniature toggle switch SPDT, through-hole." + VERIFY, pads, g, (-6.5, -3.5, 6.5, 3.5),
               model)


# --------------------------------------------------------------------------- relays & buzzers

def relay_srd() -> Footprint:
    """Power relay SPDT (Songle / Sanyou SRD series). 1 COM, 2/5 coil, 3 NC, 4 NO."""
    pads = [Pad("1", 0, 0, 3.0, 3.0, "circle", "tht", 1.3), Pad("2", 1.95, 6.05, 2.5, 2.5, "circle", "tht", 1.0),
            Pad("3", 14.15, 6.05, 3.0, 3.0, "circle", "tht", 1.3), Pad("4", 14.2, -6.0, 3.0, 3.0, "circle", "tht", 1.3),
            Pad("5", 1.95, -5.95, 2.5, 2.5, "circle", "tht", 1.0)]
    g = _rect(-1.3, -7.7, 18.3, 7.7)
    model = composite(B(-1.3, -7.7, 0, 18.3, 7.7, 15.0, "#2458b8"), pins="tht")
    return _fp("Relay_SPDT_SRD_Series_Form_C", "Power relay SPDT, Songle / Sanyou SRD-xxVDC-SL-C. 1 COM, 2/5 coil, 3 NC, "
               "4 NO", pads, g, (-1.3, -7.7, 18.3, 7.7), model)


def relay_g5v1() -> Footprint:
    """Signal relay SPDT (Omron G5V-1). Pin numbers follow the Omron datasheet: 1/10 coil, 2/9 COM..., 5/6 contacts."""
    pads = [Pad("1", 0, 0, 2.0, 2.0, "rect", "tht", 1.0), Pad("2", 0, 2.54, 2.0, 2.0, "circle", "tht", 1.0),
            Pad("5", 0, 10.16, 2.0, 2.0, "circle", "tht", 1.0), Pad("6", 5.08, 10.16, 2.0, 2.0, "circle", "tht", 1.0),
            Pad("9", 5.08, 2.54, 2.0, 2.0, "circle", "tht", 1.0), Pad("10", 5.08, 0, 2.0, 2.0, "circle", "tht", 1.0)]
    g = _rect(-1.2, -1.1, 6.2, 11.2)
    model = composite(B(-1.2, -1.1, 0.2, 6.2, 11.2, 10.0, "#1c1c1c"), pins="tht")
    return _fp("Relay_SPDT_Omron_G5V-1", "Signal relay SPDT (Omron G5V-1)", pads, g, (-1.2, -1.1, 6.2, 11.2), model)


def relay_dpdt_hk19f() -> Footprint:
    pads = dip(8).pads
    g = _rect(-5.0, -10.0, 5.0, 10.0)
    model = composite(B(-5.0, -10.0, 0.3, 5.0, 10.0, 10.5, "#1c1c1c"), pins="tht")
    return _fp("Relay_DPDT_DIP-8", "Signal relay DPDT in DIP-8 style footprint (HK19F / TQ2 style)." + VERIFY, pads, g,
               (-5.0, -10.0, 5.0, 10.0), model)


def buzzer(d: float, pitch: float, h: float) -> Footprint:
    pads = inline_tht(2, pitch, 1.8, 1.0)
    g = [_circle(0, 0, d / 2)]
    model = composite(CYL(0, 0, 0.3, h, d / 2, BLACK, seg=40), CYL(0, 0, h - 0.5, h + 0.01, 1.0, DARK), pins="tht")
    return _fp(f"Buzzer_D{d:g}mm_P{pitch:g}mm", f"Magnetic/piezo buzzer, D{d:g} mm, pitch {pitch:g} mm", pads, g,
               (-d / 2, -d / 2, d / 2, d / 2), model)


def buzzer_smd() -> Footprint:
    pads = [Pad("1", -4.3, -3.6, 1.6, 1.4, "rect"), Pad("2", 4.3, 3.6, 1.6, 1.4, "rect")]
    model = composite(B(-4.25, -4.25, 0, 4.25, 4.25, 3.0, BLACK), CYL(0, 0, 3.0, 3.01, 0.7, DARK))
    return _fp("Buzzer_SMD_8.5x8.5mm", "Magnetic buzzer, SMD 8.5x8.5 mm." + VERIFY, pads, _rect(-4.25, -4.25, 4.25, 4.25),
               (-5.1, -4.3, 5.1, 4.3), model)


# --------------------------------------------------------------------------- crystals & oscillators

def crystal_smd_4pad(L: float, W: float) -> Footprint:
    # manufacturer land patterns for the standard ceramic packages: pad w, pad h, x, y
    table = {(2.0, 1.6): (0.9, 0.8, 0.7, 0.55), (2.5, 2.0): (1.15, 1.0, 0.875, 0.7), (3.2, 2.5): (1.4, 1.2, 1.1, 0.85),
             (5.0, 3.2): (1.6, 1.3, 1.65, 1.0), (7.0, 5.0): (2.1, 1.7, 2.95, 1.35)}
    if (L, W) in table:
        pw, ph, cx, cy = table[(L, W)]
    else:
        pw, ph = r4(L * 0.35), r4(W * 0.35)
        cx, cy = r4(L / 2 - pw / 2 + 0.05), r4(W / 2 - ph / 2 + 0.05)
    pads = [Pad("1", -cx, cy, pw, ph, "roundrect"), Pad("2", cx, cy, pw, ph, "roundrect"),
            Pad("3", cx, -cy, pw, ph, "roundrect"), Pad("4", -cx, -cy, pw, ph, "roundrect")]
    e = max(L / 2, cx + pw / 2) + 0.2
    g = [_line(-e, W / 2 + 0.2, e, W / 2 + 0.2), _line(-e, -W / 2 - 0.2, -e, W / 2 + 0.2)]
    model = {"type": "xtal_smd", "L": L, "W": W, "H": 0.8 if L < 4 else 1.2}
    return _fp(f"Crystal_SMD_{int(L * 10)}{int(W * 10)}-4Pin_{L:g}x{W:g}mm",
               f"Quartz crystal / oscillator, SMD {L:g}x{W:g} mm, 4 pads", pads, g, (-L / 2, -W / 2, L / 2, W / 2), model)


def crystal_smd_2pad(L: float, W: float) -> Footprint:
    pw, ph, cx = (2.0, 2.4, 1.85) if (L, W) == (5.0, 3.2) else (r4(L * 0.28), r4(W * 0.75), r4(L / 2 - L * 0.14 + 0.1))
    model = {"type": "xtal_smd", "L": L, "W": W, "H": 0.9 if L < 4 else 1.3}
    return two_terminal_smd(f"Crystal_SMD_{L:g}x{W:g}mm_2Pad", f"Quartz crystal, SMD {L:g}x{W:g} mm, 2 pads (e.g. "
                            "32.768 kHz)", pw, ph, cx, L, W, model)


def crystal_hc49u() -> Footprint:
    pads = [Pad("1", -2.44, 0, 1.5, 1.5, "circle", "tht", 0.8), Pad("2", 2.44, 0, 1.5, 1.5, "circle", "tht", 0.8)]
    g = [_line(-3.1, -2.3, 3.1, -2.3), _line(-3.1, 2.3, 3.1, 2.3)]
    model = {"type": "hc49", "L": 10.9, "W": 4.65, "H": 13.5}
    return _fp("Crystal_HC49-U_Vertical", "Crystal, HC-49/U full height, through-hole", pads, g, (-5.45, -2.33, 5.45, 2.33),
               model)


def crystal_cylinder() -> Footprint:
    pads = [Pad("1", -0.95, 0, 1.0, 1.4, "oval", "tht", 0.6), Pad("2", 0.95, 0, 1.0, 1.4, "oval", "tht", 0.6)]
    model = composite({"s": "cyly", "p": [1.0, 7.5, 0, 1.1, 1.0], "c": METAL, "m": 1}, pins="tht")
    return _fp("Crystal_Cylinder_2x6mm", "Tuning-fork crystal (32.768 kHz) cylinder 2x6 mm, lying flat", pads,
               _rect(-1.1, 0.8, 1.1, 7.6), (-1.5, -0.7, 1.5, 7.6), model)


def resonator_3pin() -> Footprint:
    pads = inline_tht(3, 2.5, 1.5, 0.8, first_square=False)
    g = _rect(-4.0, -1.5, 4.0, 1.5)
    model = composite(B(-3.6, -1.2, 0.5, 3.6, 1.2, 6.5, "#2d5fa8"), pins="tht")
    return _fp("Resonator_Ceramic_3Pin_P2.5mm", "Ceramic resonator with built-in caps, 3 pins, 2.5 mm pitch", pads, g,
               (-4.0, -1.5, 4.0, 1.5), model)


def oscillator_dip(half: bool) -> Footprint:
    if half:
        pads = [Pad("1", -3.81, -3.81, 1.6, 1.6, "rect", "tht", 0.8), Pad("4", 3.81, -3.81, 1.6, 1.6, "circle", "tht", 0.8),
                Pad("5", 3.81, 3.81, 1.6, 1.6, "circle", "tht", 0.8), Pad("8", -3.81, 3.81, 1.6, 1.6, "circle", "tht", 0.8)]
        w, h, name = 13.0, 13.0, "Oscillator_DIP-8"
    else:
        pads = [Pad("1", -7.62, -3.81, 1.6, 1.6, "rect", "tht", 0.8), Pad("7", 7.62, -3.81, 1.6, 1.6, "circle", "tht", 0.8),
                Pad("8", 7.62, 3.81, 1.6, 1.6, "circle", "tht", 0.8), Pad("14", -7.62, 3.81, 1.6, 1.6, "circle", "tht", 0.8)]
        w, h, name = 20.8, 13.0, "Oscillator_DIP-14"
    g = _rect(-w / 2, -h / 2, w / 2, h / 2)
    model = composite(B(-w / 2, -h / 2, 0.5, w / 2, h / 2, 5.5, METAL, True), pins="tht")
    return _fp(name, f"Crystal oscillator module, {'half' if half else 'full'} size metal can", pads, g,
               (-w / 2, -h / 2, w / 2, h / 2), model)


# --------------------------------------------------------------------------- optocouplers

def sop4() -> Footprint:
    from .gen_ic import gullwing_dual
    return gullwing_dual("SOP-4_4.4x2.6mm_P1.27mm", "SOP-4 optocoupler / SSR package (e.g. PC817 SMD, TLP291)", 4, 1.27,
                         7.0, 0.5, 0.4, 4.4, 2.6, 2.0)


def smd4_wide() -> Footprint:
    from .gen_ic import gullwing_dual
    return gullwing_dual("SMDIP-4_W9.53mm", "Surface-mount DIP-4 optocoupler (gull-wing, 400 mil)", 4, 2.54, 10.2, 1.0, 0.5,
                         6.5, 4.6, 3.5)


# --------------------------------------------------------------------------- modules

def _module_plate(w, h, color="#1f4ea3", z=0.0, t=1.2):
    return B(-w / 2, -h / 2, z, w / 2, h / 2, z + t, color)


def module_esp32_wroom() -> Footprint:
    """Espressif ESP32-WROOM-32 / -32D / -32E (18 x 25.5 mm) - land pattern per the Espressif datasheet."""
    pads = []
    for i in range(14):
        pads.append(Pad(str(i + 1), -8.75, r4(-8.25 + i * 1.27), 1.5, 0.9, "rect"))
    for i in range(10):
        pads.append(Pad(str(15 + i), r4(-5.71 + i * 1.27), 9.51, 0.9, 1.5, "rect"))
    for i in range(14):
        pads.append(Pad(str(25 + i), 8.75, r4(8.26 - i * 1.27), 1.5, 0.9, "rect"))
    pads.append(Pad("39", -0.68, -0.91, 4.2, 4.2, "rect", paste=False))
    g = _rect(-9.0, -15.74, 9.0, 9.76, 0.1, "fab") + [_line(-9.0, -9.74, 9.0, -9.74, 0.1, "fab")]
    model = composite(B(-9.0, -15.74, 0, 9.0, 9.76, 0.8, "#1c1c1c"), B(-8.5, -9.2, 0.8, 8.5, 9.2, 3.1, METAL, True),
                      B(-8.8, -15.6, 0.8, 8.8, -10.0, 0.82, "#c9a13b", True))
    return _fp("ESP32-WROOM-32", "Espressif ESP32-WROOM-32 / -32D / -32E module (18x25.5 mm). Keep copper and parts "
               "out of the antenna area (top 6 mm)", pads, g, (-9.5, -15.74, 9.5, 10.26), model)


def module_esp12() -> Footprint:
    """Ai-Thinker ESP-12E / ESP-12F (ESP8266), 16 x 24 mm. 1-8 left, 9-14 bottom, 15-22 right."""
    pads = []
    for i in range(8):
        pads.append(Pad(str(i + 1), -7.6, r4(-3.5 + i * 2.0), 2.5, 1.0, "rect"))
    for i in range(6):
        pads.append(Pad(str(9 + i), r4(-5.0 + i * 2.0), 12.0, 1.0, 1.8, "rect"))
    for i in range(8):
        pads.append(Pad(str(15 + i), 7.6, r4(10.5 - i * 2.0), 2.5, 1.0, "rect"))
    g = _rect(-8.0, -12.0, 8.0, 12.0, 0.1, "fab")
    model = composite(B(-8.0, -12.0, 0, 8.0, 12.0, 0.8, "#1c1c1c"), B(-6.5, -5.0, 0.8, 6.5, 10.5, 3.0, METAL, True))
    return _fp("ESP-12E", "Ai-Thinker ESP-12E / ESP-12F (ESP8266) module, 16x24 mm", pads, g, (-8.85, -12.0, 8.85, 12.9),
               model)


def module_dip(name: str, desc: str, per_row: int, row_spacing: float, w: float, h: float, extra=None) -> Footprint:
    from .shapes import dual_row_numbering
    pads = dual_row_numbering(2 * per_row, 2.54, row_spacing / 2, 1.7, 1.7, "circle", "tht", 1.0)
    pads[0].shape = "rect"
    g = _rect(-w / 2, -h / 2, w / 2, h / 2)
    parts = [_module_plate(w, h, extra or "#1f4ea3", 2.5, 1.6), B(-w / 2 + 2, -h / 2 + 2, 0, -w / 2 + 2.5, h / 2 - 2, 2.5, BLACK),
             B(w / 2 - 2.5, -h / 2 + 2, 0, w / 2 - 2, h / 2 - 2, 2.5, BLACK),
             B(-3.5, -3.5, 4.1, 3.5, 3.5, 5.0, "#1c1c1c")]
    model = composite(*parts, pins="tht", pin_top=4.1, pin_color=GOLD)
    return _fp(name, desc, pads, g, (-w / 2, -h / 2, w / 2, h / 2), model)


def module_header_board(name, desc, header_cols, w, h, holes=None) -> Footprint:
    pads = inline_tht(header_cols, 2.54, 1.7, 1.0, y=-h / 2 + 1.6)
    for hx, hy in holes or []:
        pads.append(Pad("", hx, hy, 2.2, 2.2, "circle", "npth", 2.2))
    g = _rect(-w / 2, -h / 2, w / 2, h / 2)
    model = composite(_module_plate(w, h, "#1f4ea3", 11.0, 1.4), B(-w / 2 + 1, -h / 2 + 5, 12.4, w / 2 - 1, h / 2 - 3, 13.4,
                                                                   "#101010"), pins="tht", pin_top=11.0,
                      pin_color=GOLD)
    return _fp(name, desc, pads, g, (-w / 2, -h / 2, w / 2, h / 2), model)


# --------------------------------------------------------------------------- mechanical

def mounting_hole_vias(size: str) -> Footprint:
    import math
    drill = {"M2": 2.2, "M2.5": 2.7, "M3": 3.2, "M4": 4.3}[size]
    pad = drill + 2.4
    pads = [Pad("1", 0, 0, pad, pad, "circle", "tht", drill)]
    r = (drill + pad) / 4
    for i in range(8):
        a = math.radians(i * 45)
        pads.append(Pad("1", r4(r * math.cos(a)), r4(r * math.sin(a)), 0.7, 0.7, "circle", "tht", 0.4))
    return _fp(f"MountingHole_{size}_Pad_Via", f"Plated mounting hole for {size} with 8 stitching vias (grounded)",
               pads, [], (-pad / 2, -pad / 2, pad / 2, pad / 2), {"type": "none"})


def testpoint_smd(d: float) -> Footprint:
    pads = [Pad("1", 0, 0, d, d, "circle", paste=False)]
    return _fp(f"TestPoint_Pad_D{d:g}mm", f"SMD test point pad, {d:g} mm", pads, [_circle(0, 0, d / 2 + 0.3)],
               (-d / 2, -d / 2, d / 2, d / 2), {"type": "none"})


def testpoint_loop() -> Footprint:
    pads = [Pad("1", 0, 0, 2.5, 2.5, "circle", "tht", 1.3)]
    model = composite({"s": "xz", "pts": [(-1.3, 0), (-1.3, 4.0), (1.3, 4.0), (1.3, 0), (1.0, 0), (1.0, 3.7),
                                          (-1.0, 3.7), (-1.0, 0)], "p": [-0.3, 0.3], "c": "#d93a2b", "m": 0})
    return _fp("TestPoint_Loop_THT", "Through-hole test point loop (probe hook)", pads, [_circle(0, 0, 1.6)],
               (-1.4, -1.4, 1.4, 1.4), model)


def solder_jumper(n: int, bridged: bool) -> Footprint:
    if n == 2:
        pads = [Pad("1", -0.65, 0, 1.0, 1.5, "rect", paste=False), Pad("2", 0.65, 0, 1.0, 1.5, "rect", paste=False)]
    else:
        pads = [Pad("1", -1.3, 0, 1.0, 1.5, "rect", paste=False), Pad("2", 0, 0, 1.0, 1.5, "rect", paste=False),
                Pad("3", 1.3, 0, 1.0, 1.5, "rect", paste=False)]
    if bridged:
        # a copper bridge joins pads 1 and 2 (cut it to open the jumper)
        pads[0].w = pads[0].w + 0.3
        pads[0].x += 0.15
    w = 1.3 * (n - 1) + 1.5
    g = _rect(-w / 2, -1.0, w / 2, 1.0)
    return _fp(f"SolderJumper-{n}_{'Bridged' if bridged else 'Open'}", f"Solder jumper, {n} pads, "
               f"{'bridged by default (cut to open)' if bridged else 'open (bridge with solder)'}", pads, g,
               (-w / 2, -1.0, w / 2, 1.0), {"type": "none"})


# --------------------------------------------------------------------------- catalogue entries

def entries():
    out = []
    add = out.append
    from ..model.footprints import chip
    for s in ("0402", "0603", "0805", "1206", "1210"):
        add(("LEDs/Chip", f"LED {s}", "D", "Red", lambda s=s: chip("LED", s), "led light indicator smd"))
    for code in ("2835", "3528", "3014", "5730"):
        add(("LEDs/PLCC", f"LED PLCC-2 {code}", "D", "White", lambda c=code: led_plcc2(c), "led smd lighting white"))
    add(("LEDs/RGB & addressable", "WS2812B 5050 addressable", "D", "WS2812B", led_ws2812b,
         "neopixel addressable rgb ws2812 sk6812"))
    add(("LEDs/RGB & addressable", "SK6812MINI 3535 addressable", "D", "SK6812MINI", led_sk6812mini, "neopixel mini rgb"))
    add(("LEDs/RGB & addressable", "WS2812B-2020 addressable", "D", "WS2812B-2020", led_ws2812b_2020, "neopixel tiny rgb"))
    add(("LEDs/RGB & addressable", "RGB LED 5050 (6-pin)", "D", "RGB", led_5050_rgb, "rgb led 5050"))
    for d in (3, 5, 8, 10):
        add(("LEDs/Through-hole", f"LED {d} mm THT", "D", "Red", lambda d=d: led_tht(d), "led round through hole"))
    for d in (5, 8):
        add(("LEDs/Through-hole", f"RGB LED {d} mm 4-pin", "D", "RGB", lambda d=d: led_rgb_tht(d), "rgb led through hole"))
    add(("LEDs/Through-hole", "LED rectangular 5x2 mm", "D", "Red", led_rect_tht, "led rectangular"))
    for dg in (1, 4):
        add(("Displays", f"7-segment display {dg} digit", "U", f"7SEG-{dg}", lambda d=dg: seven_segment(d),
             "seven segment display led numeric"))
    add(("Switches/Tactile", "Tactile switch 6x6 THT", "SW", "Button", tactile_switch, "button push tact"))
    add(("Switches/Tactile", "Tactile switch 12x12 THT", "SW", "Button", tactile_12mm, "button push tact big"))
    for s in ("6x6", "5.2x5.2", "4x4", "3x6", "12x12"):
        add(("Switches/Tactile", f"Tactile switch SMD {s}", "SW", "Button", lambda s=s: tactile_smd(s), "button push smd"))
    add(("Switches/Slide & toggle", "Slide switch SPDT THT", "SW", "SPDT", slide_switch_tht, "slide switch power on off"))
    add(("Switches/Slide & toggle", "Slide switch SPDT SMD", "SW", "SPDT", slide_switch_smd, "slide switch mini"))
    add(("Switches/Slide & toggle", "Toggle switch SPDT", "SW", "SPDT", toggle_switch, "toggle switch lever"))
    for n in range(1, 13):
        add(("Switches/DIP", f"DIP switch {n}-position THT", "SW", f"DIP-SW-{n}", lambda n=n: dip_switch(n),
             "dip switch configuration"))
    for n in (2, 4, 6, 8):
        add(("Switches/DIP", f"DIP switch {n}-position SMD", "SW", f"DIP-SW-{n}", lambda n=n: dip_switch(n, True),
             "dip switch smd"))
    add(("Switches/Encoders", "Rotary encoder EC11 with switch", "SW", "EC11", rotary_encoder_ec11,
         "rotary encoder knob quadrature"))
    add(("Relays", "Relay SPDT Songle SRD (10 A)", "K", "SRD-05VDC-SL-C", relay_srd, "relay power mains songle"))
    add(("Relays", "Relay SPDT Omron G5V-1 (signal)", "K", "G5V-1", relay_g5v1, "relay signal"))
    add(("Relays", "Relay DPDT DIP-8 (signal)", "K", "HK19F", relay_dpdt_hk19f, "relay dpdt signal"))
    for d, p, h in ((9.0, 4.0, 5.5), (12.0, 6.5, 9.5), (12.0, 7.6, 9.5)):
        add(("Audio/Buzzers", f"Buzzer D{d:g} P{p:g}", "BZ", "Buzzer", lambda a=(d, p, h): buzzer(*a),
             "buzzer beeper piezo magnetic"))
    add(("Audio/Buzzers", "Buzzer SMD 8.5x8.5", "BZ", "Buzzer", buzzer_smd, "buzzer smd"))
    add(("Crystals & oscillators", "Crystal HC-49/US (low profile)", "Y", "16MHz", crystal_hc49, "crystal quartz"))
    add(("Crystals & oscillators", "Crystal HC-49/U (full height)", "Y", "16MHz", crystal_hc49u, "crystal quartz"))
    for L, W in ((1.6, 1.2), (2.0, 1.6), (2.5, 2.0), (3.2, 2.5), (5.0, 3.2), (7.0, 5.0)):
        add(("Crystals & oscillators", f"Crystal / oscillator SMD {L:g}x{W:g} (4 pads)", "Y", "16MHz",
             lambda l=L, w=W: crystal_smd_4pad(l, w), "crystal oscillator tcxo smd"))
    for L, W in ((1.6, 1.0), (2.0, 1.2), (3.2, 1.5), (5.0, 3.2), (7.0, 5.0)):
        add(("Crystals & oscillators", f"Crystal SMD {L:g}x{W:g} (2 pads)", "Y", "32.768kHz",
             lambda l=L, w=W: crystal_smd_2pad(l, w), "crystal 32khz rtc smd"))
    add(("Crystals & oscillators", "Crystal cylinder 2x6 (32.768 kHz)", "Y", "32.768kHz", crystal_cylinder,
         "watch crystal rtc"))
    add(("Crystals & oscillators", "Ceramic resonator 3-pin", "Y", "16MHz", resonator_3pin, "resonator ceramic"))
    add(("Crystals & oscillators", "Oscillator DIP-8 can", "X", "OSC", lambda: oscillator_dip(True), "oscillator can"))
    add(("Crystals & oscillators", "Oscillator DIP-14 can", "X", "OSC", lambda: oscillator_dip(False), "oscillator can"))
    add(("Optocouplers", "Optocoupler DIP-4", "U", "PC817", lambda: dip(4), "optocoupler isolator pc817"))
    add(("Optocouplers", "Optocoupler DIP-6", "U", "MOC3021", lambda: dip(6), "optocoupler triac"))
    add(("Optocouplers", "Optocoupler SOP-4", "U", "TLP291", sop4, "optocoupler smd"))
    add(("Optocouplers", "Optocoupler SMD-4 (wide)", "U", "PC817S", smd4_wide, "optocoupler smd"))
    add(("Optocouplers", "Optocoupler SOIC-8", "U", "HCPL-0601", lambda: dual_package("SOIC", 8), "optocoupler digital"))
    add(("Modules", "ESP32-WROOM-32 module", "U", "ESP32-WROOM-32E", module_esp32_wroom, "esp32 wifi bluetooth"))
    add(("Modules", "ESP-12F (ESP8266) module", "U", "ESP-12F", module_esp12, "esp8266 wifi"))
    add(("Modules", "Arduino Nano", "A", "Arduino_Nano", lambda: module_dip("Module_Arduino_Nano", "Arduino Nano "
                                                                          "(2x15 pins, 0.6 in rows)", 15, 15.24, 18.0, 43.2),
         "arduino nano atmega328"))
    add(("Modules", "Arduino Pro Mini", "A", "Arduino_Pro_Mini", lambda: module_dip("Module_Arduino_Pro_Mini",
                                                                                 "Arduino Pro Mini (2x12 pins)." + VERIFY,
                                                                                 12, 15.24, 18.0, 33.0), "arduino"))
    add(("Modules", "SparkFun Pro Micro", "A", "Pro_Micro", lambda: module_dip("Module_Pro_Micro", "SparkFun Pro Micro "
                                                                            "(2x12 pins, 0.6 in rows)", 12, 15.24, 18.0,
                                                                            33.0), "arduino leonardo 32u4"))
    add(("Modules", "Raspberry Pi Pico", "A", "RPi_Pico", lambda: module_dip("Module_RaspberryPi_Pico", "Raspberry Pi "
                                                                          "Pico / Pico W (2x20 pins, 0.7 in rows)", 20,
                                                                          17.78, 21.0, 51.0, "#1b7a3a"),
         "rp2040 raspberry pi pico"))
    add(("Modules", "ESP32 DevKitC (2x19)", "A", "ESP32-DevKitC", lambda: module_dip(
        "Module_ESP32_DevKitC_V4", "ESP32-DevKitC V4 (2x19 pins, 25.4 mm rows)." + VERIFY, 19, 25.4, 28.0, 54.0, "#1c1c1c"),
         "esp32 devkit"))
    add(("Modules", "NRF24L01 module (2x4)", "U", "NRF24L01", lambda: module_header_board(
        "Module_NRF24L01", "nRF24L01+ radio module on a 2x4 header", 4, 15.0, 29.0), "nrf24 radio 2.4ghz"))
    add(("Modules", "0.96 in OLED I2C (4-pin)", "U", "SSD1306", lambda: module_header_board(
        "Module_OLED_0.96in_I2C", "0.96 inch SSD1306 OLED module, 4-pin I2C header." + VERIFY, 4, 27.3, 27.8,
        [(-11.65, -11.9), (11.65, -11.9), (-11.65, 11.9), (11.65, 11.9)]), "oled display ssd1306 i2c"))
    for s in ("M2", "M2.5", "M3", "M4"):
        add(("Mechanical/Mounting holes", f"Mounting hole {s} plated + vias", "H", s, lambda s=s: mounting_hole_vias(s),
             "mounting hole ground stitching"))
    for s in ("M1.6", "M2", "M2.5", "M3", "M4", "M5", "M6"):
        add(("Mechanical/Mounting holes", f"Mounting hole {s}", "H", s, lambda s=s: mounting_hole(s, False),
             "mounting hole screw npth"))
        add(("Mechanical/Mounting holes", f"Mounting hole {s} plated", "H", s, lambda s=s: mounting_hole(s, True),
             "mounting hole screw plated"))
    for d in (0.5, 0.75, 1.0, 1.5, 2.0, 3.0):
        add(("Mechanical/Test points", f"Test point pad D{d:g}", "TP", "TP", lambda d=d: testpoint_smd(d), "test probe pad"))
    add(("Mechanical/Test points", "Test point loop THT", "TP", "TP", testpoint_loop, "test hook loop"))
    add(("Mechanical/Fiducials", "Fiducial 1 mm", "FID", "Fiducial", fiducial, "fiducial assembly marker"))
    for n in (2, 3):
        for br in (False, True):
            add(("Mechanical/Jumpers", f"Solder jumper {n}-pad {'bridged' if br else 'open'}", "JP", "Jumper",
                 lambda n=n, b=br: solder_jumper(n, b), "solder jumper bridge config"))
    return out
