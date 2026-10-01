"""Overstress checks: parts running beyond their ratings (the canvas shows them as smoke markers)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import ics
from .devices import BJT, FET, Capacitor, Diode, Resistor
from .tubes import Pentode, Triode

CHIP_WATTS = {"01005": 0.031, "0201": 0.05, "0402": 0.063, "0603": 0.1, "0805": 0.125, "1206": 0.25, "1210": 0.5,
              "1806": 0.5, "1812": 0.75, "2010": 0.75, "2220": 1.0, "2512": 1.0}
AXIAL_WATTS = [(4.0, 0.125), (7.0, 0.25), (10.0, 0.5), (12.0, 1.0), (16.0, 2.0), (99.0, 3.0)]
PKG_WATTS = {"SOT-223": 1.0, "SOT-89": 0.5, "SOT-23": 0.3, "SOT-23-5": 0.3, "TO-92": 0.6, "TO-220": 2.0,
             "TO-263": 2.0, "TO-252": 1.5}


@dataclass
class Stress:
    uid: str
    ref: str
    severity: str  # warning | error
    message: str


def resistor_watts(fp_name: str) -> float:
    m = re.match(r"R_(\d{4,5})\b", fp_name)
    if m and m.group(1) in CHIP_WATTS:
        return CHIP_WATTS[m.group(1)]
    m = re.match(r"R_Axial_L([\d.]+)mm", fp_name)
    if m:
        length = float(m.group(1))
        for lim, w in AXIAL_WATTS:
            if length <= lim:
                return w
    if "MELF" in fp_name:
        return 0.25 if "Mini" in fp_name else (0.5 if "MELF" == fp_name[2:] else 0.2)
    return 0.25


def check(ck, x, led_avg: dict | None = None) -> list[Stress]:
    """Instantaneous overstress at solution x. ``led_avg``: LED device -> frame-averaged current."""
    out: list[Stress] = []
    from .models import package
    for info in ck.parts.values():
        comp = ck.project.component(info.ref) if hasattr(ck.project, "component") else None
        for d in info.devices:
            try:
                msg = _check_device(d, x, info, comp, led_avg)
            except Exception:
                msg = None
            if msg:
                out.append(Stress(info.uid, info.ref, msg[0], msg[1]))
                break
        if info.res.kind == "mcu":
            from .avr.bridge import McuDevice
            for d in info.devices:
                if isinstance(d, McuDevice) and d.powered:
                    vcc = float(x[d.vcc] - x[d.gnd])
                    if vcc > d.chip.vmax + 0.5:
                        out.append(Stress(info.uid, info.ref, "error", f"supply {vcc:.1f} V exceeds the "
                                                                       f"{d.chip.vmax:g} V maximum"))
                        break
                    worst = max(d.gpio, key=lambda g: abs(d.pin_current(g)), default=None)
                    if worst is not None and abs(d.pin_current(worst)) > 0.04:
                        out.append(Stress(info.uid, info.ref, "error",
                                          f"pin {worst} carries {abs(d.pin_current(worst)) * 1e3:.0f} mA "
                                          "(absolute maximum 40 mA): add a resistor"))
                        break
        if info.res.kind == "regulator" and comp is not None:
            reg = next((d for d in info.devices if isinstance(d, ics.Regulator)), None)
            if reg is not None:
                p = reg.power(x)
                lim = PKG_WATTS.get(package(comp), 1.0)
                vin = abs(float(x[reg.nodes[0]] - x[reg.nodes[1]]))
                if vin > reg.vmax:
                    out.append(Stress(info.uid, info.ref, "error", f"input {vin:.1f} V exceeds {reg.vmax:g} V"))
                elif p > lim:
                    out.append(Stress(info.uid, info.ref, "warning",
                                      f"dissipating {p:.2f} W (about {lim:g} W without a heatsink): runs hot"))
    return out


def _check_device(d, x, info, comp, led_avg):
    if isinstance(d, Resistor) and d.name == info.ref and info.res.kind in ("resistor", "resistor_array"):
        p = d.power(x)
        rating = resistor_watts(comp.footprint.name) if comp is not None else 0.25
        if p > 1.5 * rating:
            return "error", f"{p * 1e3:.0f} mW in a {rating * 1e3:.0f} mW resistor: burning"
        if p > rating:
            return "warning", f"{p * 1e3:.0f} mW exceeds the {rating * 1e3:.0f} mW rating"
    if isinstance(d, Diode):
        i = abs(led_avg.get(d, d.current(float(x[d.nodes[0]] - x[d.nodes[1]])))) if led_avg else \
            abs(d.current(float(x[d.nodes[0]] - x[d.nodes[1]])))
        if i > 1.5 * d.imax:
            return "error", f"{i * 1e3:.0f} mA through a {d.imax * 1e3:.0f} mA {'LED' if d.color else 'diode'}"
        if i > d.imax:
            return "warning", f"{i * 1e3:.0f} mA exceeds the {d.imax * 1e3:.0f} mA rating"
        if d.color and float(x[d.nodes[1]] - x[d.nodes[0]]) > 5.0:
            return "warning", "LED reverse voltage above 5 V"
    if isinstance(d, Capacitor) and d.name == info.ref:
        v = float(x[d.nodes[0]] - x[d.nodes[1]])
        if d.polarized and v < -0.5:
            return "error", f"electrolytic reverse-biased ({v:.1f} V): check its polarity"
        if d.vmax and abs(v) > d.vmax:
            return "error", f"{abs(v):.1f} V across a {d.vmax:g} V capacitor"
    if isinstance(d, BJT):
        o = d.observe(x)
        if abs(o["i"]) > 1.2 * d.imax:
            return "error", f"collector current {abs(o['i']) * 1e3:.0f} mA exceeds {d.imax * 1e3:.0f} mA"
        if o["p"] > d.pmax:
            return "warning", f"dissipating {o['p']:.2f} W (rated {d.pmax:g} W)"
    if isinstance(d, FET):
        o = d.observe(x)
        if abs(o["i"]) > 1.2 * d.imax:
            return "error", f"drain current {abs(o['i']):.2f} A exceeds {d.imax:g} A"
        if abs(o["p"]) > d.pmax:
            return "warning", f"dissipating {abs(o['p']):.2f} W (rated {d.pmax:g} W)"
    if isinstance(d, ics.OpAmp):
        v = float(x[d.nodes[3]] - x[d.nodes[4]])
        if v > d.vmax:
            return "error", f"supply {v:.1f} V exceeds the {d.vmax:g} V maximum"
    if isinstance(d, (Triode, Pentode)) and d.pa_max > 0:
        o = d.observe(x)
        if o["p"] > 1.6 * d.pa_max:
            return "error", f"plate dissipation {o['p']:.1f} W, rated {d.pa_max:g} W: red-plating (bias too hot?)"
        if o["p"] > 1.1 * d.pa_max:
            return "warning", f"plate dissipation {o['p']:.1f} W exceeds the {d.pa_max:g} W rating"
    return None
