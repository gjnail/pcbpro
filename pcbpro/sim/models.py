"""Simulation models for board parts: what electrical device a component is, its parameters and how its pads map
to the device terminals.

Resolution order for a component:
  1. a per-component override (``project.sim["parts"][uid]``),
  2. the part table, matched on the MPN or the value (longest known prefix wins),
  3. heuristics from the reference prefix, the footprint and the value,
  4. otherwise "unsupported": the part's pads are left open.

Pinouts come from the manufacturers' datasheets. Entries marked ``verify`` were not checked against a datasheet
and are flagged in the Simulation panel so they can be confirmed or overridden.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .units import parse_pot, parse_value, parse_voltage

# --------------------------------------------------------------------------- resolution result


@dataclass
class Resolution:
    kind: str  # builder kind, "none" (connection point only) or "unsupported"
    model: str = ""  # human-readable model name
    params: dict = field(default_factory=dict)
    pins: dict = field(default_factory=dict)  # terminal -> list of pad numbers
    source: str = "auto"  # override | table | auto
    note: str = ""
    verify: bool = False

    @property
    def simulated(self) -> bool:
        return self.kind not in ("none", "unsupported", "excluded")


# --------------------------------------------------------------------------- LEDs

LED_TYPES = {  # colour word -> (Vf at 10 mA, emission colour)
    "red": (1.85, "#ff2a1a"), "orange": (1.95, "#ff7a12"), "amber": (2.0, "#ffb300"), "yellow": (2.0, "#ffd21f"),
    "green": (2.1, "#27e05a"), "blue": (2.9, "#2a6bff"), "white": (2.9, "#f4f6ff"), "pink": (2.9, "#ff4fa8"),
    "purple": (3.0, "#8a3cff"), "violet": (3.0, "#8a3cff"), "uv": (3.3, "#8a3cff"), "ir": (1.25, "#3a0a0a"),
    "infrared": (1.25, "#3a0a0a"), "warm": (2.9, "#ffd9a0"), "cyan": (2.9, "#30e0ff"),
}


def led_params(value: str, big: bool = False) -> dict:
    v = (value or "").lower()
    colour = "red"
    for k in LED_TYPES:
        if re.search(rf"\b{k}", v) or v.startswith(k):
            colour = k
            break
    vf, hexcol = LED_TYPES[colour]
    return {"vf": vf, "color": hexcol, "colour": colour, "imax": 0.15 if big else 0.03, "rs": 2.0 if big else 6.0}


# --------------------------------------------------------------------------- part table

def _d(**p):
    return ("diode", p)


DIODES = {
    "1N4148": _d(is_=4.352e-9, n=1.906, rs=0.6458, bv=100, imax=0.3),
    "1N914": _d(is_=4.352e-9, n=1.906, rs=0.6458, bv=100, imax=0.3),
    "1N4448": _d(is_=4.352e-9, n=1.906, rs=0.6458, bv=100, imax=0.3),
    "LL4148": _d(is_=4.352e-9, n=1.906, rs=0.6458, bv=100, imax=0.3),
    "1N4001": _d(is_=14.11e-9, n=1.984, rs=0.0339, bv=50, imax=1.0),
    "1N4002": _d(is_=14.11e-9, n=1.984, rs=0.0339, bv=100, imax=1.0),
    "1N4003": _d(is_=14.11e-9, n=1.984, rs=0.0339, bv=200, imax=1.0),
    "1N4004": _d(is_=14.11e-9, n=1.984, rs=0.0339, bv=400, imax=1.0),
    "1N4005": _d(is_=14.11e-9, n=1.984, rs=0.0339, bv=600, imax=1.0),
    "1N4006": _d(is_=14.11e-9, n=1.984, rs=0.0339, bv=800, imax=1.0),
    "1N4007": _d(is_=14.11e-9, n=1.984, rs=0.0339, bv=1000, imax=1.0),
    "US1M": _d(is_=14.11e-9, n=1.984, rs=0.05, bv=1000, imax=1.0),
    "1N5408": _d(is_=5e-8, n=1.9, rs=0.015, bv=1000, imax=3.0),
    "1N5817": _d(is_=31.7e-6, n=1.373, rs=0.051, bv=20, imax=1.0),
    "1N5818": _d(is_=31.7e-6, n=1.373, rs=0.051, bv=30, imax=1.0),
    "1N5819": _d(is_=31.7e-6, n=1.373, rs=0.051, bv=40, imax=1.0),
    "B5819W": _d(is_=31.7e-6, n=1.373, rs=0.08, bv=40, imax=1.0),
    "SS14": _d(is_=31.7e-6, n=1.373, rs=0.06, bv=40, imax=1.0),
    "SS34": _d(is_=1.5e-5, n=1.3, rs=0.03, bv=40, imax=3.0),
    "1N5822": _d(is_=1.5e-5, n=1.3, rs=0.03, bv=40, imax=3.0),
    "BAT54": _d(is_=4.2e-9, n=1.0, rs=2.0, bv=30, imax=0.2),
    "BAT41": _d(is_=4.2e-9, n=1.0, rs=5.0, bv=100, imax=0.1),
    "BAT46": _d(is_=4.2e-9, n=1.0, rs=4.0, bv=100, imax=0.15),
    "BAT85": _d(is_=4.2e-9, n=1.0, rs=3.0, bv=30, imax=0.2),
    "1N34A": _d(is_=1.3e-7, n=1.3, rs=5.0, bv=60, imax=0.05),
    "1N60": _d(is_=1.3e-7, n=1.3, rs=5.0, bv=40, imax=0.05),
    "1N270": _d(is_=1.3e-7, n=1.3, rs=5.0, bv=80, imax=0.1),
}
DIODE_EXACT = {"M1": "1N4001", "M2": "1N4002", "M3": "1N4003", "M4": "1N4004", "M5": "1N4005", "M6": "1N4006",
               "M7": "1N4007", "S1M": "1N4007", "D1N4148": "1N4148"}

# 1N47xx Zener series (1 W)
ZENER_1N47 = {28: 3.3, 29: 3.6, 30: 3.9, 31: 4.3, 32: 4.7, 33: 5.1, 34: 5.6, 35: 6.2, 36: 6.8, 37: 7.5, 38: 8.2,
              39: 9.1, 40: 10, 41: 11, 42: 12, 43: 13, 44: 15, 45: 16, 46: 18, 47: 20, 48: 22, 49: 24, 50: 27,
              51: 30, 52: 33, 53: 36, 54: 39, 55: 43, 56: 47, 57: 51, 58: 56, 59: 62, 60: 68, 61: 75, 62: 82,
              63: 91, 64: 100}


def _q(pol, is_, bf, br, vaf, imax, pmax, pins, **kw):
    return ("bjt", dict(pol=pol, is_=is_, bf=bf, br=br, vaf=vaf, imax=imax, pmax=pmax, pinout=pins, **kw))


TO92_EBC = {"TO-92": "EBC"}
SOT23_BEC = {"SOT-23": "BEC"}
BJTS = {
    "2N3904": _q(1, 6.734e-15, 416.4, 0.7371, 74.03, 0.2, 0.625, {"TO-92": "EBC", "SOT-23": "BEC"}),
    "MMBT3904": _q(1, 6.734e-15, 416.4, 0.7371, 74.03, 0.2, 0.35, SOT23_BEC),
    "2N3906": _q(-1, 1.41e-15, 180.7, 4.977, 18.7, 0.2, 0.625, {"TO-92": "EBC", "SOT-23": "BEC"}),
    "MMBT3906": _q(-1, 1.41e-15, 180.7, 4.977, 18.7, 0.2, 0.35, SOT23_BEC),
    "PN2222": _q(1, 14.34e-15, 255.9, 6.092, 74.03, 1.0, 0.625, TO92_EBC),
    "2N2222": _q(1, 14.34e-15, 255.9, 6.092, 74.03, 0.8, 0.5, {"TO-92": "EBC", "TO-5": "EBC", "SOT-23": "BEC"}),
    "MMBT2222": _q(1, 14.34e-15, 255.9, 6.092, 74.03, 0.6, 0.35, SOT23_BEC),
    "2N4401": _q(1, 26.03e-15, 300, 4.0, 90.7, 0.6, 0.625, TO92_EBC),
    "2N4403": _q(-1, 650.6e-18, 200, 4.0, 115.7, 0.6, 0.625, TO92_EBC),
    "BC547": _q(1, 1.8e-14, 400, 6.0, 63, 0.1, 0.5, {"TO-92": "CBE", "SOT-23": "BEC"}),
    "BC548": _q(1, 1.8e-14, 400, 6.0, 63, 0.1, 0.5, {"TO-92": "CBE"}),
    "BC549": _q(1, 1.8e-14, 500, 6.0, 63, 0.1, 0.5, {"TO-92": "CBE"}),
    "BC550": _q(1, 1.8e-14, 500, 6.0, 63, 0.1, 0.5, {"TO-92": "CBE"}),
    "BC557": _q(-1, 1.2e-14, 250, 6.0, 40, 0.1, 0.5, {"TO-92": "CBE"}),
    "BC558": _q(-1, 1.2e-14, 250, 6.0, 40, 0.1, 0.5, {"TO-92": "CBE"}),
    "BC559": _q(-1, 1.2e-14, 300, 6.0, 40, 0.1, 0.5, {"TO-92": "CBE"}),
    "BC560": _q(-1, 1.2e-14, 300, 6.0, 40, 0.1, 0.5, {"TO-92": "CBE"}),
    "BC846": _q(1, 1.8e-14, 300, 6.0, 63, 0.1, 0.25, SOT23_BEC),
    "BC847": _q(1, 1.8e-14, 300, 6.0, 63, 0.1, 0.25, SOT23_BEC),
    "BC848": _q(1, 1.8e-14, 300, 6.0, 63, 0.1, 0.25, SOT23_BEC),
    "BC849": _q(1, 1.8e-14, 450, 6.0, 63, 0.1, 0.25, SOT23_BEC),
    "BC857": _q(-1, 1.2e-14, 250, 6.0, 40, 0.1, 0.25, SOT23_BEC),
    "BC858": _q(-1, 1.2e-14, 250, 6.0, 40, 0.1, 0.25, SOT23_BEC),
    "S8050": _q(1, 1e-14, 200, 5.0, 100, 0.5, 0.3, {"SOT-23": "BEC", "TO-92": "EBC"}),
    "S8550": _q(-1, 1e-14, 200, 5.0, 100, 0.5, 0.3, {"SOT-23": "BEC", "TO-92": "EBC"}),
    "S9012": _q(-1, 1e-14, 150, 5.0, 100, 0.5, 0.625, TO92_EBC),
    "S9013": _q(1, 1e-14, 150, 5.0, 100, 0.5, 0.625, TO92_EBC),
    "S9014": _q(1, 1e-14, 400, 5.0, 100, 0.1, 0.45, TO92_EBC),
    "S9015": _q(-1, 1e-14, 300, 5.0, 100, 0.1, 0.45, TO92_EBC),
    "2SC1815": _q(1, 1e-14, 200, 5.0, 100, 0.15, 0.4, {"TO-92": "ECB"}),
    "2SA1015": _q(-1, 1e-14, 200, 5.0, 100, 0.15, 0.4, {"TO-92": "ECB"}),
    "2N5088": _q(1, 5.9e-15, 700, 6.0, 100, 0.05, 0.625, TO92_EBC),
    "2N5089": _q(1, 5.9e-15, 900, 6.0, 100, 0.05, 0.625, TO92_EBC),
    "MPSA18": _q(1, 5e-15, 1000, 6.0, 100, 0.2, 0.625, TO92_EBC),
    "BC107": _q(1, 1.8e-14, 300, 6.0, 63, 0.1, 0.3, {"TO-92": "EBC", "TO-5": "EBC"}),
    "BC108": _q(1, 1.8e-14, 400, 6.0, 63, 0.1, 0.3, {"TO-92": "EBC", "TO-5": "EBC"}),
    "BC109": _q(1, 1.8e-14, 500, 6.0, 63, 0.1, 0.3, {"TO-92": "EBC", "TO-5": "EBC"}),
    "TIP31": _q(1, 1e-12, 50, 5.0, 100, 3.0, 40, {"TO-220": "BCE"}),
    "TIP32": _q(-1, 1e-12, 50, 5.0, 100, 3.0, 40, {"TO-220": "BCE"}),
    "TIP41": _q(1, 1e-12, 50, 5.0, 100, 6.0, 65, {"TO-220": "BCE"}),
    "TIP42": _q(-1, 1e-12, 50, 5.0, 100, 6.0, 65, {"TO-220": "BCE"}),
    "TIP120": _q(1, 1e-12, 1000, 5.0, 100, 5.0, 65, {"TO-220": "BCE"}, darlington=True),
    "TIP121": _q(1, 1e-12, 1000, 5.0, 100, 5.0, 65, {"TO-220": "BCE"}, darlington=True),
    "TIP122": _q(1, 1e-12, 1000, 5.0, 100, 5.0, 65, {"TO-220": "BCE"}, darlington=True),
    "TIP125": _q(-1, 1e-12, 1000, 5.0, 100, 5.0, 65, {"TO-220": "BCE"}, darlington=True),
    "TIP127": _q(-1, 1e-12, 1000, 5.0, 100, 5.0, 65, {"TO-220": "BCE"}, darlington=True),
    "MPSA13": _q(1, 1e-14, 5000, 5.0, 100, 0.5, 0.625, TO92_EBC, darlington=True),
    "MPSA14": _q(1, 1e-14, 10000, 5.0, 100, 0.5, 0.625, TO92_EBC, darlington=True),
    "BD135": _q(1, 1e-13, 100, 5.0, 100, 1.5, 12.5, {"TO-126": "ECB"}),
    "BD137": _q(1, 1e-13, 100, 5.0, 100, 1.5, 12.5, {"TO-126": "ECB"}),
    "BD139": _q(1, 1e-13, 100, 5.0, 100, 1.5, 12.5, {"TO-126": "ECB"}),
    "BD136": _q(-1, 1e-13, 100, 5.0, 100, 1.5, 12.5, {"TO-126": "ECB"}),
    "BD138": _q(-1, 1e-13, 100, 5.0, 100, 1.5, 12.5, {"TO-126": "ECB"}),
    "BD140": _q(-1, 1e-13, 100, 5.0, 100, 1.5, 12.5, {"TO-126": "ECB"}),
    "BCX56": _q(1, 1e-13, 100, 5.0, 100, 1.0, 1.0, {"SOT-89": "BCE"}),
    "BCP56": _q(1, 1e-13, 100, 5.0, 100, 1.0, 1.5, {"SOT-223": "BCE"}),
    # germanium (fuzz pedals)
    "AC128": _q(-1, 4e-7, 90, 5.0, 20, 1.0, 1.0, {"TO-92": "EBC", "TO-5": "EBC"}, ge=True),
    "AC125": _q(-1, 4e-7, 110, 5.0, 20, 0.2, 0.5, {"TO-92": "EBC", "TO-5": "EBC"}, ge=True),
    "AC126": _q(-1, 4e-7, 140, 5.0, 20, 0.2, 0.5, {"TO-92": "EBC", "TO-5": "EBC"}, ge=True),
    "OC44": _q(-1, 4e-7, 90, 5.0, 20, 0.1, 0.1, {"TO-92": "EBC", "TO-5": "EBC"}, ge=True),
    "OC71": _q(-1, 4e-7, 50, 5.0, 20, 0.1, 0.1, {"TO-92": "EBC", "TO-5": "EBC"}, ge=True),
    "NKT275": _q(-1, 4e-7, 90, 5.0, 20, 0.1, 0.1, {"TO-92": "EBC", "TO-5": "EBC"}, ge=True),
    "2N404": _q(-1, 4e-7, 50, 5.0, 20, 0.1, 0.15, {"TO-92": "EBC", "TO-5": "EBC"}, ge=True),
}


def _m(pol, vth, k, imax, pmax, pins, lam=0.01, body=True):
    return ("fet", dict(pol=pol, vth=vth, k=k, lam=lam, imax=imax, pmax=pmax, pinout=pins, body=body))


SOT23_GSD = {"SOT-23": "GSD"}
TO220_GDS = {"TO-220": "GDS", "TO-263": "GDS", "TO-252": "GDS", "TO-247": "GDS"}
SO8_FET = {"8": "SSSGDDDD"}
PPAK = {"PowerPAK": "SSSGD"}
MOSFETS = {
    "2N7000": _m(1, 2.1, 0.03, 0.2, 0.4, {"TO-92": "SGD"}),
    "BS170": _m(1, 2.1, 0.05, 0.5, 0.83, {"TO-92": "DGS"}),
    "2N7002": _m(1, 2.1, 0.03, 0.3, 0.35, SOT23_GSD),
    "BSS138": _m(1, 1.3, 0.1, 0.22, 0.36, SOT23_GSD),
    "BSS84": _m(-1, 1.6, 0.05, 0.13, 0.36, SOT23_GSD),
    "AO3400": _m(1, 1.05, 10.0, 5.7, 1.4, SOT23_GSD),
    "AO3401": _m(-1, 0.9, 8.0, 4.0, 1.4, SOT23_GSD),
    "SI2302": _m(1, 0.7, 8.0, 2.6, 1.25, SOT23_GSD),
    "SI2301": _m(-1, 0.7, 5.0, 2.3, 1.25, SOT23_GSD),
    "DMG2305": _m(-1, 0.7, 8.0, 4.2, 1.4, SOT23_GSD),
    "IRLML6344": _m(1, 0.8, 10.0, 5.0, 1.3, SOT23_GSD),
    "IRLML2502": _m(1, 0.8, 8.0, 4.2, 1.25, SOT23_GSD),
    "IRLML6402": _m(-1, 0.8, 6.0, 3.7, 1.3, SOT23_GSD),
    "AO4406": _m(1, 1.8, 30.0, 13.0, 3.1, SO8_FET),
    "AO4407": _m(-1, 1.9, 25.0, 12.0, 3.1, SO8_FET),
    "IRF7404": _m(-1, 0.7, 15.0, 6.7, 2.5, SO8_FET),
    "IRLZ44": _m(1, 1.5, 13.0, 47.0, 110.0, TO220_GDS),
    "IRFZ44": _m(1, 3.0, 8.0, 49.0, 94.0, TO220_GDS),
    "IRF540": _m(1, 3.0, 3.2, 33.0, 130.0, TO220_GDS),
    "IRF520": _m(1, 3.0, 1.5, 9.7, 48.0, TO220_GDS),
    "IRF3205": _m(1, 3.0, 18.0, 110.0, 200.0, TO220_GDS),
    "IRF9540": _m(-1, 3.0, 1.2, 23.0, 140.0, TO220_GDS),
    "IRF9Z34": _m(-1, 3.0, 2.0, 19.0, 68.0, TO220_GDS),
    "IRLB8721": _m(1, 1.8, 30.0, 62.0, 65.0, TO220_GDS),
    "IRLR024": _m(1, 1.5, 4.4, 17.0, 45.0, TO220_GDS),
    "IRLR7843": _m(1, 1.8, 40.0, 160.0, 140.0, TO220_GDS),
    "CSD17578": _m(1, 1.6, 50.0, 25.0, 2.8, PPAK),
    "BSC014N04": _m(1, 1.6, 80.0, 100.0, 3.0, PPAK),
}

JFETS = {  # pol, pinch-off, Idss, pinout
    "J201": ("jfet", dict(pol=1, vp=-0.8, idss=0.6e-3, pinout={"TO-92": "DSG"})),
    "J113": ("jfet", dict(pol=1, vp=-1.5, idss=2e-3, pinout={"TO-92": "DSG"})),
    "2N5457": ("jfet", dict(pol=1, vp=-1.5, idss=3e-3, pinout={"TO-92": "DSG"})),
    "2N5458": ("jfet", dict(pol=1, vp=-2.5, idss=6e-3, pinout={"TO-92": "DSG"})),
    "2N5459": ("jfet", dict(pol=1, vp=-3.5, idss=9e-3, pinout={"TO-92": "DSG"})),
    "MPF102": ("jfet", dict(pol=1, vp=-3.0, idss=6e-3, pinout={"TO-92": "DSG"})),
    "2N5952": ("jfet", dict(pol=1, vp=-2.5, idss=5e-3, pinout={"TO-92": "DSG"}, verify=True)),
    "2N3819": ("jfet", dict(pol=1, vp=-3.0, idss=10e-3, pinout={"TO-92": "SGD"}, verify=True)),
    "BF245": ("jfet", dict(pol=1, vp=-2.5, idss=10e-3, pinout={"TO-92": "DSG"}, verify=True)),
    "2SK30": ("jfet", dict(pol=1, vp=-1.0, idss=2e-3, pinout={"TO-92": "SGD"}, verify=True)),
    "J175": ("jfet", dict(pol=-1, vp=-3.0, idss=20e-3, pinout={"TO-92": "DSG"}, verify=True)),
}


def _oa(a0, gbw, sr, hh, hl, ilim, iq, vmax, rout=50.0):
    return dict(a0=a0, gbw=gbw, sr=sr, hh=hh, hl=hl, ilim=ilim, iq=iq, vmax=vmax, rout=rout)


DUAL8 = {"OUT1": "1", "IN1-": "2", "IN1+": "3", "V-": "4", "IN2+": "5", "IN2-": "6", "OUT2": "7", "V+": "8"}
QUAD14 = {"OUT1": "1", "IN1-": "2", "IN1+": "3", "V+": "4", "IN2+": "5", "IN2-": "6", "OUT2": "7", "OUT3": "8",
          "IN3-": "9", "IN3+": "10", "V-": "11", "IN4+": "12", "IN4-": "13", "OUT4": "14"}
SINGLE8 = {"IN1-": "2", "IN1+": "3", "V-": "4", "OUT1": "6", "V+": "7"}
SOT235_A = {"OUT1": "1", "V-": "2", "IN1+": "3", "IN1-": "4", "V+": "5"}  # MCP6001 style
SOT235_B = {"IN1+": "1", "V-": "2", "IN1-": "3", "OUT1": "4", "V+": "5"}  # LMV321 / TI DBV style
LM339_14 = {"OUT2": "1", "OUT1": "2", "V+": "3", "IN1-": "4", "IN1+": "5", "IN2-": "6", "IN2+": "7", "IN3-": "8",
            "IN3+": "9", "IN4-": "10", "IN4+": "11", "V-": "12", "OUT4": "13", "OUT3": "14"}

LM358 = _oa(1e5, 1e6, 0.3e6, 1.5, 0.02, 0.04, 0.35e-3, 32)
TL07X = _oa(2e5, 3e6, 13e6, 1.5, 1.5, 0.03, 1.4e-3, 36)
NE5532 = _oa(1e5, 10e6, 9e6, 1.2, 1.2, 0.038, 4e-3, 44, 30.0)
OPA134 = _oa(1e6, 8e6, 20e6, 1.0, 1.0, 0.035, 4e-3, 36, 30.0)
MCP600X = _oa(4e5, 1e6, 0.6e6, 0.025, 0.025, 0.023, 0.1e-3, 6)
LMV3XX = _oa(1e5, 1e6, 1e6, 0.06, 0.06, 0.04, 0.1e-3, 5.5)
RC4558 = _oa(1e5, 3e6, 1.7e6, 1.5, 1.5, 0.025, 2.5e-3, 36)
LM741 = _oa(2e5, 1e6, 0.5e6, 1.5, 1.5, 0.025, 1.7e-3, 36, 75.0)
# power op-amps (chip amps): high output current, a few volts of headroom at full load
LM3886 = _oa(5e5, 8e6, 19e6, 2.5, 2.5, 7.0, 50e-3, 84, 0.1)
LM1875 = _oa(3e5, 5.5e6, 8e6, 2.0, 2.0, 4.0, 70e-3, 60, 0.1)
TO220_11 = {"V+": ["1", "5"], "OUT1": "3", "V-": "4", "IN1-": "9", "IN1+": "10"}  # LM3886T / TF
TO220_5 = {"IN1+": "1", "IN1-": "2", "V-": "3", "OUT1": "4", "V+": "5"}  # LM1875, TDA2030, TDA2050

OPAMPS = {
    "LM358": ("opamp", dict(LM358, units=2, pinmaps={"8": DUAL8})),
    "LM2904": ("opamp", dict(LM358, units=2, pinmaps={"8": DUAL8})),
    "LM324": ("opamp", dict(LM358, units=4, pinmaps={"14": QUAD14})),
    "LM2902": ("opamp", dict(LM358, units=4, pinmaps={"14": QUAD14})),
    "TL071": ("opamp", dict(TL07X, units=1, pinmaps={"8": SINGLE8})),
    "TL072": ("opamp", dict(TL07X, units=2, pinmaps={"8": DUAL8})),
    "TL074": ("opamp", dict(TL07X, units=4, pinmaps={"14": QUAD14})),
    "TL081": ("opamp", dict(TL07X, units=1, pinmaps={"8": SINGLE8})),
    "TL082": ("opamp", dict(TL07X, units=2, pinmaps={"8": DUAL8})),
    "TL084": ("opamp", dict(TL07X, units=4, pinmaps={"14": QUAD14})),
    "NE5532": ("opamp", dict(NE5532, units=2, pinmaps={"8": DUAL8})),
    "SA5532": ("opamp", dict(NE5532, units=2, pinmaps={"8": DUAL8})),
    "NE5534": ("opamp", dict(NE5532, units=1, pinmaps={"8": SINGLE8})),
    "OPA2134": ("opamp", dict(OPA134, units=2, pinmaps={"8": DUAL8})),
    "OPA134": ("opamp", dict(OPA134, units=1, pinmaps={"8": SINGLE8})),
    "OPA4134": ("opamp", dict(OPA134, units=4, pinmaps={"14": QUAD14})),
    "MCP6001": ("opamp", dict(MCP600X, units=1, pinmaps={"SOT-23-5": SOT235_A, "8": SINGLE8})),
    "MCP6002": ("opamp", dict(MCP600X, units=2, pinmaps={"8": DUAL8})),
    "MCP6004": ("opamp", dict(MCP600X, units=4, pinmaps={"14": QUAD14})),
    "LMV321": ("opamp", dict(LMV3XX, units=1, pinmaps={"SOT-23-5": SOT235_B})),
    "LMV358": ("opamp", dict(LMV3XX, units=2, pinmaps={"8": DUAL8})),
    "LMV324": ("opamp", dict(LMV3XX, units=4, pinmaps={"14": QUAD14})),
    "RC4558": ("opamp", dict(RC4558, units=2, pinmaps={"8": DUAL8})),
    "JRC4558": ("opamp", dict(RC4558, units=2, pinmaps={"8": DUAL8})),
    "NJM4558": ("opamp", dict(RC4558, units=2, pinmaps={"8": DUAL8})),
    "4558": ("opamp", dict(RC4558, units=2, pinmaps={"8": DUAL8})),
    "LM741": ("opamp", dict(LM741, units=1, pinmaps={"8": SINGLE8})),
    "UA741": ("opamp", dict(LM741, units=1, pinmaps={"8": SINGLE8})),
    "LM833": ("opamp", dict(NE5532, units=2, pinmaps={"8": DUAL8})),
    "LM3886": ("opamp", dict(LM3886, units=1, pinmaps={"TO-220": TO220_11, "11": TO220_11})),
    "LM1875": ("opamp", dict(LM1875, units=1, pinmaps={"TO-220": TO220_5, "5": TO220_5})),
    "TDA2050": ("opamp", dict(LM1875, units=1, pinmaps={"TO-220": TO220_5, "5": TO220_5})),
    "TDA2030": ("opamp", dict(LM1875, ilim=3.5, units=1, pinmaps={"TO-220": TO220_5, "5": TO220_5})),
    "LM393": ("comparator", dict(units=2, pinmaps={"8": DUAL8}, iq=0.4e-3)),
    "LM2903": ("comparator", dict(units=2, pinmaps={"8": DUAL8}, iq=0.4e-3)),
    "LM339": ("comparator", dict(units=4, pinmaps={"14": LM339_14}, iq=0.8e-3)),
    "LM2901": ("comparator", dict(units=4, pinmaps={"14": LM339_14}, iq=0.8e-3)),
    "LM311": ("comparator", dict(units=1, pinmaps={"8": {"V-": "1", "IN1+": "2", "IN1-": "3", "OUT1": "7",
                                                          "V+": "8"}}, iq=5e-3)),
    "LM386": ("audioamp", dict(pinmaps={"8": {"GAIN1": "1", "IN-": "2", "IN+": "3", "GND": "4", "OUT": "5", "VS": "6",
                                                "BYP": "7", "GAIN8": "8"}})),
}

TIMER8 = {"GND": "1", "TRIG": "2", "OUT": "3", "RESET": "4", "CTRL": "5", "THR": "6", "DIS": "7", "VCC": "8"}
TIMER556 = {"DIS1": "1", "THR1": "2", "CTRL1": "3", "RESET1": "4", "OUT1": "5", "TRIG1": "6", "GND": "7",
            "TRIG2": "8", "OUT2": "9", "RESET2": "10", "CTRL2": "11", "THR2": "12", "DIS2": "13", "VCC": "14"}
TIMERS = {
    "NE555": ("timer555", dict(cmos=False, units=1, pinmaps={"8": TIMER8})),
    "LM555": ("timer555", dict(cmos=False, units=1, pinmaps={"8": TIMER8})),
    "SA555": ("timer555", dict(cmos=False, units=1, pinmaps={"8": TIMER8})),
    "NA555": ("timer555", dict(cmos=False, units=1, pinmaps={"8": TIMER8})),
    "555": ("timer555", dict(cmos=False, units=1, pinmaps={"8": TIMER8})),
    "TLC555": ("timer555", dict(cmos=True, units=1, pinmaps={"8": TIMER8})),
    "ICM7555": ("timer555", dict(cmos=True, units=1, pinmaps={"8": TIMER8})),
    "LMC555": ("timer555", dict(cmos=True, units=1, pinmaps={"8": TIMER8})),
    "NE556": ("timer555", dict(cmos=False, units=2, pinmaps={"14": TIMER556})),
    "LM556": ("timer555", dict(cmos=False, units=2, pinmaps={"14": TIMER556})),
    "TLC556": ("timer555", dict(cmos=True, units=2, pinmaps={"14": TIMER556})),
}

SOT223_REG = {"SOT-223": {"REF": "1", "OUT": ["2", "4"], "IN": "3"}}
TO220_78 = {"TO-220": {"IN": "1", "REF": "2", "OUT": "3"}, "TO-263": {"IN": "1", "REF": "2", "OUT": "3"},
            "TO-252": {"IN": "1", "REF": "2", "OUT": "3"}}
TO92_78L = {"TO-92": {"OUT": "1", "REF": "2", "IN": "3"}, "SOT-89": {"OUT": "1", "REF": "2", "IN": "3"}}
TO220_79 = {"TO-220": {"REF": "1", "IN": "2", "OUT": "3"}}
LM317_PINS = {"TO-220": {"REF": "1", "OUT": "2", "IN": "3"}, "SOT-223": {"REF": "1", "OUT": ["2", "4"], "IN": "3"},
              "TO-263": {"REF": "1", "OUT": "2", "IN": "3"}}
LM337_PINS = {"TO-220": {"REF": "1", "IN": "2", "OUT": "3"}}


def _reg(vdo, ilim, iq, pins, adj=False, pol=1, vset=None, vmax=20.0, **kw):
    return ("regulator", dict(vdo=vdo, ilim=ilim, iq=iq, pinmaps=pins, adj=adj, pol=pol, vset=vset, vmax=vmax, **kw))


REGULATORS = {
    "AMS1117": _reg(1.1, 1.0, 5e-3, SOT223_REG, vmax=15),
    "LM1117": _reg(1.2, 0.8, 5e-3, SOT223_REG, vmax=15),
    "LD1117": _reg(1.1, 0.8, 5e-3, SOT223_REG, vmax=15),
    "AP2112": _reg(0.25, 0.6, 55e-6, {"SOT-23-5": {"IN": "1", "REF": "2", "EN": "3", "OUT": "5"}}, vmax=6.5),
    "XC6206": _reg(0.25, 0.25, 1e-6, {"SOT-23": {"REF": "1", "OUT": "2", "IN": "3"}}, vmax=6.5),
    "MCP1700": _reg(0.18, 0.25, 2e-6, {"SOT-23": {"REF": "1", "OUT": "2", "IN": "3"},
                                        "TO-92": {"REF": "1", "IN": "2", "OUT": "3"}}, vmax=6.5),
    "HT73": _reg(0.1, 0.25, 4e-6, {"SOT-89": {"REF": "1", "IN": "2", "OUT": "3"},
                                    "TO-92": {"REF": "1", "IN": "2", "OUT": "3"}}, vmax=12),
    "L78L": _reg(1.7, 0.1, 3e-3, TO92_78L, vmax=30),
    "MC78L": _reg(1.7, 0.1, 3e-3, TO92_78L, vmax=30),
    "L78": _reg(2.0, 1.5, 5e-3, TO220_78, vmax=35),
    "LM78": _reg(2.0, 1.5, 5e-3, TO220_78, vmax=35),
    "MC78": _reg(2.0, 1.5, 5e-3, TO220_78, vmax=35),
    "7805": _reg(2.0, 1.5, 5e-3, TO220_78, vmax=35, vset=5.0),
    "7809": _reg(2.0, 1.5, 5e-3, TO220_78, vmax=35, vset=9.0),
    "7812": _reg(2.0, 1.5, 5e-3, TO220_78, vmax=35, vset=12.0),
    "L79": _reg(1.5, 1.5, 3e-3, TO220_79, pol=-1, vmax=35),
    "LM79": _reg(1.5, 1.5, 3e-3, TO220_79, pol=-1, vmax=35),
    "MC79": _reg(1.5, 1.5, 3e-3, TO220_79, pol=-1, vmax=35),
    "LM317": _reg(1.8, 1.5, 2e-3, LM317_PINS, adj=True, vset=1.25, vmax=40),
    "LM337": _reg(1.8, 1.5, 2e-3, LM337_PINS, adj=True, vset=1.25, pol=-1, vmax=40),
}

SHUNT_REFS = {
    "TL431": ("shuntref", dict(vref=2.495, pinmaps={"TO-92": {"REF": "1", "A": "2", "K": "3"},
                                                     "SOT-23": {"REF": "1", "K": "2", "A": "3"}},
                               verify_pkg=("SOT-23",))),
    "LM4040": ("zener_ref", dict(bv=2.5, pinmaps={"SOT-23": {"K": "1", "A": "2"}}, verify=True)),
    "LM336": ("zener_ref", dict(bv=2.49, pinmaps={"TO-92": {"A": "1", "K": "2"}}, verify=True)),
}

SENSORS = {
    "LM35": ("sensor", dict(slope=0.01, offset=0.0, pinmaps={"TO-92": {"VS": "1", "OUT": "2", "GND": "3"}})),
    "TMP36": ("sensor", dict(slope=0.01, offset=0.5, pinmaps={"TO-92": {"VS": "1", "OUT": "2", "GND": "3"}})),
    "TMP35": ("sensor", dict(slope=0.01, offset=0.0, pinmaps={"TO-92": {"VS": "1", "OUT": "2", "GND": "3"}})),
    "ACS712": ("currentsensor", dict(pinmaps={"8": {"IP+": ["1", "2"], "IP-": ["3", "4"], "GND": "5", "OUT": "7",
                                                    "VCC": "8"}})),
}

OPTOS = {
    "PC817": ("opto", dict(ctr=2.0, pinmaps={"4": {"A": "1", "K": "2", "E": "3", "C": "4"}})),
    "EL817": ("opto", dict(ctr=2.0, pinmaps={"4": {"A": "1", "K": "2", "E": "3", "C": "4"}})),
    "LTV817": ("opto", dict(ctr=2.0, pinmaps={"4": {"A": "1", "K": "2", "E": "3", "C": "4"}})),
    "TLP291": ("opto", dict(ctr=1.5, pinmaps={"4": {"A": "1", "K": "2", "E": "3", "C": "4"}})),
    "TLP281": ("opto", dict(ctr=1.5, pinmaps={"4": {"A": "1", "K": "2", "E": "3", "C": "4"}})),
    "4N25": ("opto", dict(ctr=0.5, pinmaps={"6": {"A": "1", "K": "2", "E": "4", "C": "5"}})),
    "4N35": ("opto", dict(ctr=1.0, pinmaps={"6": {"A": "1", "K": "2", "E": "4", "C": "5"}})),
    "MOC3021": ("opto_switch", dict(i_on=15e-3, i_off=5e-3, pinmaps={"6": {"A": "1", "K": "2", "S1": "4",
                                                                           "S2": "6"}})),
    "MOC3041": ("opto_switch", dict(i_on=15e-3, i_off=5e-3, pinmaps={"6": {"A": "1", "K": "2", "S1": "4",
                                                                           "S2": "6"}})),
    "6N137": ("opto_switch", dict(i_on=5e-3, i_off=2e-3, pinmaps={"8": {"A": "2", "K": "3", "S1": "6",
                                                                        "S2": "5"}})),
    "HCPL-0601": ("opto_switch", dict(i_on=5e-3, i_off=2e-3, pinmaps={"8": {"A": "2", "K": "3", "S1": "6",
                                                                            "S2": "5"}})),
}

DRIVERS = {
    "ULN2003": ("uln", dict(n=7, pinmaps={"16": {**{f"IN{i}": str(i) for i in range(1, 8)}, "GND": "8", "COM": "9",
                                                  **{f"OUT{i}": str(17 - i) for i in range(1, 8)}}})),
    "ULN2803": ("uln", dict(n=8, pinmaps={"18": {**{f"IN{i}": str(i) for i in range(1, 9)}, "GND": "9", "COM": "10",
                                                  **{f"OUT{i}": str(19 - i) for i in range(1, 9)}}})),
}

SWITCHERS = ("LM2596", "LM2576", "XL6009", "MP1584", "MT3608", "SX1308", "TPS5", "TLV6256", "AP6320", "MC34063",
             "TP4056", "MCP73831", "LTC4054", "BQ2407", "IP5306", "DW01")

TABLE: dict[str, tuple] = {}
for _t in (DIODES, BJTS, MOSFETS, JFETS, OPAMPS, TIMERS, REGULATORS, SHUNT_REFS, SENSORS, OPTOS, DRIVERS):
    TABLE.update(_t)
_KEYS = sorted(TABLE, key=len, reverse=True)


def _norm(s: str) -> str:
    return re.sub(r"[\s_]", "", (s or "").upper())


def lookup(text: str) -> tuple[str, tuple] | None:
    """Longest table key that ``text`` starts with (after stripping a manufacturer prefix such as 'LM' variants)."""
    t = _norm(text)
    if not t:
        return None
    if t in DIODE_EXACT:
        k = DIODE_EXACT[t]
        return k, TABLE[k]
    for k in _KEYS:
        if t.startswith(k):
            if len(k) <= 4 and k[-1].isdigit() and len(t) > len(k) and t[len(k)].isdigit():
                continue  # '555' must not match '5551'
            return k, TABLE[k]
    # some vendors prefix the part number: KA555, UA741, MC1458...
    for k in _KEYS:
        if len(k) >= 4 and k in t[:len(k) + 3]:
            return k, TABLE[k]
    return None


def zener_voltage(text: str) -> float | None:
    t = _norm(text)
    m = re.match(r"1N47(\d\d)", t)
    if m and int(m.group(1)) in ZENER_1N47:
        return ZENER_1N47[int(m.group(1))]
    m = re.match(r"(BZX\d\d|BZT52|BZV55|BZX55|BZX79|ZMM|ZPD|MMSZ)[A-Z]?(\d+)V(\d+)", t)
    if m:
        return float(f"{m.group(2)}.{m.group(3)}")
    m = re.match(r"(BZX\d\d|BZT52|BZV55|BZX55|BZX79|ZMM|ZPD)[A-Z]?(\d+)", t)
    if m:
        return float(m.group(2))
    m = re.match(r"(SMAJ|SMBJ|SMCJ|1\.5KE|P6SMB|SMF)(\d+(?:\.\d+)?)C?A?", t)
    if m:
        v = float(m.group(2))
        return round(v * 1.11 + 0.3, 2) if m.group(1).endswith("J") or m.group(1) == "SMF" else v
    m = re.match(r"P6KE(\d+(?:\.\d+)?)", t)
    if m:
        return float(m.group(1))
    m = re.match(r"ESD\d*Z?(\d+(?:\.\d+)?)", t)
    if m:
        return round(float(m.group(1)) * 1.2, 2)
    m = re.search(r"ZENER", t)
    if m:
        return parse_voltage(text)
    return None


def regulator_voltage(text: str) -> float | None:
    t = _norm(text)
    for pat in (r"-(\d+(?:\.\d+)?)V?$", r"-(\d)\.(\d)", r"(?:AMS1117|LM1117\w*|AP2112\w*)-(\d+(?:\.\d+)?)"):
        m = re.search(pat, t)
        if m:
            if len(m.groups()) == 2:
                return float(f"{m.group(1)}.{m.group(2)}")
            try:
                return float(m.group(1))
            except ValueError:
                pass
    m = re.match(r"(?:L|LM|MC|UA|KA)?7[89]L?(\d\d)", t)
    if m:
        return float(m.group(1))
    m = re.match(r"XC6206P(\d)(\d)", t)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = re.match(r"MCP1700T?-?(\d)(\d)", t)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = re.match(r"HT73(\d)(\d)", t)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = re.match(r"LD1117\w*?(\d)(\d)(?:TR)?$", t)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    return parse_voltage(text)


# --------------------------------------------------------------------------- footprint helpers

def unique_pads(fp) -> list[str]:
    return fp.pad_numbers()


def package(comp) -> str:
    """Package family used to choose a pinout: SOT-23, SOT-23-5, SOT-223, SOT-89, TO-92, TO-220, TO-126, TO-263,
    TO-252, TO-5, PowerPAK or the pin count for dual-row ICs ('8', '14', ...)."""
    n = comp.footprint.name.upper()
    pads = [p for p in unique_pads(comp.footprint) if p and p not in ("MP", "SH")]
    if n.startswith(("SOT-23-5", "SOT-353", "SC-70-5", "SOT23-5", "TSOT-23-5")):
        return "SOT-23-5"
    if n.startswith(("SOT-23-6", "SOT-363", "SC-70-6", "SOT23-6", "TSOT-23-6")):
        return "SOT-23-6"
    if n.startswith(("SOT-23", "SOT-323", "SOT-523", "SC-70", "SOT23", "SOT-416")) and len(pads) == 3:
        return "SOT-23"
    if n.startswith("SOT-223"):
        return "SOT-223"
    if n.startswith("SOT-89"):
        return "SOT-89"
    if n.startswith("TO-92"):
        return "TO-92"
    if n.startswith(("TO-220", "TO-3P")):
        return "TO-220"
    if n.startswith("TO-247"):
        return "TO-247"
    if n.startswith("TO-126"):
        return "TO-126"
    if n.startswith("TO-263"):
        return "TO-263"
    if n.startswith("TO-252"):
        return "TO-252"
    if n.startswith(("TO-5", "TO-18", "TO-39")):
        return "TO-5"
    if n.startswith("POWERPAK"):
        return "PowerPAK"
    return str(len(pads))


def _pins(spec: dict) -> dict:
    return {t: (list(p) if isinstance(p, (list, tuple)) else [str(p)]) for t, p in spec.items()}


def _letters_map(letters: str, pads: list[str], roles: str) -> dict:
    """'EBC' over pads ['1','2','3'] -> {'E': ['1'], 'B': ['2'], 'C': ['3']} (SO-8 strings repeat letters)."""
    out: dict[str, list[str]] = {}
    for ch, p in zip(letters, pads):
        if ch in roles:
            out.setdefault(ch, []).append(p)
    return out


def _numbered(fp) -> list[str]:
    nums = [p for p in unique_pads(fp) if p.isdigit()]
    return sorted(nums, key=int)


def _pick_pinmap(pinmaps: dict, comp) -> tuple[dict | None, str]:
    pkg = package(comp)
    if pkg in pinmaps:
        return pinmaps[pkg], pkg
    for k, v in pinmaps.items():  # same pin count under a different package name (DIP-8 vs SOIC-8)
        if k.isdigit() and k == str(len(_numbered(comp.footprint))):
            return v, k
    if len(pinmaps) == 1:
        k, v = next(iter(pinmaps.items()))
        need = {p for ps in _pins(v).values() for p in ps}
        if need <= set(unique_pads(comp.footprint)):
            return v, k
    return None, pkg


# --------------------------------------------------------------------------- resolution

PASSIVE_PREFIXES = ("R", "RN", "C", "L", "FB", "F", "RV", "VR", "POT", "JP", "BT", "BZ", "LS", "Y")

GROUND_WORDS = ("GND", "VSS", "AGND", "DGND", "PGND", "GROUND", "0V", "GNDA", "GNDD", "GNDPWR", "EARTH", "COM")


def is_ground_net(name: str | None) -> bool:
    if not name:
        return False
    n = name.upper().lstrip("/")
    return n in ("0",) or n in GROUND_WORDS or n.startswith("GND") or n.endswith("_GND")


def _transistor_from_table(kind: str, p: dict, comp, name: str) -> Resolution:
    fp = comp.footprint
    pads = unique_pads(fp)
    letters = {pd for pd in pads}
    roles = "CBE" if kind == "bjt" else "DGS"
    params = {k: v for k, v in p.items() if k not in ("pinout", "verify")}
    if letters >= set(roles):  # lettered pads (pedal TO-92 footprints)
        return Resolution(kind, name, params, {r: [r] for r in roles}, "table")
    pinout = p.get("pinout", {})
    pkg = package(comp)
    nums = _numbered(fp)
    letters_str = pinout.get(pkg)
    verify = p.get("verify", False)
    if letters_str is None:
        if pkg in ("TO-252", "TO-263") and nums[:3] == ["1", "2", "3"]:
            letters_str = pinout.get("TO-220")
        if letters_str is None and pinout:
            letters_str = next(iter(pinout.values()))
            verify = True
    if letters_str is None:
        return Resolution("unsupported", name, note="unknown package for this transistor")
    pins = _letters_map(letters_str, nums, roles)
    if pkg in ("TO-252", "TO-263") and len(nums) >= 3 and "2" in nums:
        pins = _letters_map(letters_str, ["1", "2", "3"], roles)
    if set(pins) != set(roles):
        return Resolution("unsupported", name, note=f"pinout {letters_str} does not fit {fp.name}")
    return Resolution(kind, name, params, pins, "table", verify=verify)


def resolve_table(key: str, entry: tuple, comp) -> Resolution:
    kind, p = entry
    name = key
    if kind == "diode":
        return Resolution("diode", name, dict(p), _diode_pins(comp), "table")
    if kind in ("bjt", "fet"):
        return _transistor_from_table(kind, p, comp, name)
    if kind == "jfet":
        r = _transistor_from_table("fet", p, comp, name)
        if r.kind == "fet":
            r.kind = "jfet"
        return r
    pinmaps = p.get("pinmaps", {})
    pm, pkg = _pick_pinmap(pinmaps, comp)
    if pm is None:
        return Resolution("unsupported", name, note=f"no {name} pinout for footprint {comp.footprint.name}")
    params = {k: v for k, v in p.items() if k not in ("pinmaps", "verify", "verify_pkg")}
    verify = p.get("verify", False) or pkg in p.get("verify_pkg", ())
    if kind == "regulator":
        v = params.get("vset")
        if v is None:
            v = regulator_voltage(comp.mpn) or regulator_voltage(comp.value)
        if v is None:
            if params.get("adj"):
                v = 1.25
            elif "ADJ" in _norm(comp.mpn + comp.value):
                params["adj"] = True
                v = 1.25
            else:
                return Resolution("unsupported", name, note="output voltage not found in the value or MPN")
        if "ADJ" in _norm(comp.mpn + comp.value) and not params.get("adj"):
            params["adj"] = True
            v = 1.25
        params["vset"] = abs(v)
        name = f"{name} {'adj' if params['adj'] else f'{abs(v):g} V'}"
    return Resolution(kind, name, params, _pins(pm), "table", verify=verify)


def _diode_pins(comp) -> dict:
    pads = unique_pads(comp.footprint)
    if "A" in pads and "K" in pads:
        return {"A": ["A"], "K": ["K"]}
    if package(comp) == "SOT-23":  # single diode in SOT-23: 1 anode, 3 cathode
        return {"A": ["1"], "K": ["3"]}
    return {"A": ["2"], "K": ["1"]}


def _sot23_dual(t: str):
    """SOT-23 dual diodes: list of (anode pad, cathode pad)."""
    if t.endswith("S") or t.startswith("BAV99"):
        return [("1", "3"), ("3", "2")]
    if t.endswith("C") or t.startswith("BAV70"):
        return [("1", "3"), ("2", "3")]
    if t.endswith("A") or t.startswith("BAW56"):
        return [("3", "1"), ("3", "2")]
    return None


def _switch_spec(comp) -> dict | None:
    """Contacts (pad pairs) and positions of switches, keyed on the footprint."""
    fp = comp.footprint
    n = fp.name
    pads = unique_pads(fp)
    mt = fp.model.get("type")
    if mt == "tact" or n.upper().startswith(("SW_PUSH", "SW_TACT")):
        nums = [p for p in pads if p]
        if len(nums) >= 2:
            return {"contacts": [(nums[0], nums[1])], "positions": [[], [0]], "momentary": True,
                    "labels": ["released", "pressed"]}
    if n.startswith("Footswitch_3PDT") or n.startswith("Toggle_Mini") or n.startswith(("SW_Toggle", "SW_Slide",
                                                                                         "SW_SPDT")):
        if n.startswith("Footswitch_3PDT"):  # poles are columns, commons in the middle row (4, 5, 6)
            poles = [(str(4 + c), str(1 + c), str(7 + c)) for c in range(3)]
        elif n.startswith("Toggle_Mini"):  # rows of three, common in the middle column
            rows = len([p for p in pads if p.isdigit()]) // 3
            poles = [(str(3 * r + 2), str(3 * r + 1), str(3 * r + 3)) for r in range(rows)]
        else:
            poles = [("2", "1", "3")]
        contacts, a_idx, b_idx = [], [], []
        for com, t1, t2 in poles:
            a_idx.append(len(contacts))
            contacts.append((com, t1))
            b_idx.append(len(contacts))
            contacts.append((com, t2))
        return {"contacts": contacts, "positions": [a_idx, b_idx], "momentary": False,
                "labels": ["position A (1-2)", "position B (2-3)"] if len(poles) == 1 else ["up", "down"]}
    m = re.match(r"SW_DIP_SPSTx(\d+)", n)
    if m:
        k = int(m.group(1))
        return {"dip": [(str(i + 1), str(2 * k - i)) for i in range(k)]}
    if n.startswith("RotaryEncoder"):
        return {"encoder": True}
    if n.startswith("SolderJumper-2"):
        return {"contacts": [("1", "2")], "positions": [[], [0]], "momentary": False,
                "state": 1 if "Bridged" in n else 0, "labels": ["open", "bridged"]}
    if n.startswith("SolderJumper-3"):
        return {"contacts": [("1", "2"), ("2", "3")], "positions": [[], [0], [1]], "momentary": False,
                "state": 1 if "Bridged" in n else 0, "labels": ["open", "1-2", "2-3"]}
    if len(pads) == 2 and all(pads):
        return {"contacts": [(pads[0], pads[1])], "positions": [[], [0]], "momentary": False,
                "labels": ["off", "on"]}
    if len(pads) == 3 and all(pads):
        return {"contacts": [(pads[1], pads[0]), (pads[1], pads[2])], "positions": [[0], [1]], "momentary": False,
                "labels": ["1-2", "2-3"]}
    return None


def _prefix(ref: str) -> str:
    m = re.match(r"[A-Za-z]+", ref or "")
    return m.group(0).upper() if m else ""


def resolve(comp, override: dict | None = None) -> Resolution:
    """How to simulate ``comp``."""
    ov = override or {}
    if ov.get("exclude"):
        return Resolution("excluded", "excluded", source="override", note="excluded from the simulation")
    if ov.get("kind"):
        r = Resolution(ov["kind"], ov.get("model") or ov["kind"], dict(ov.get("params", {})),
                       _pins(ov.get("pins", {})), "override")
        if not r.pins:
            base = _auto(comp)
            r.pins = base.pins
        return r
    r = None
    if ov.get("model"):
        hit = lookup(ov["model"])
        if hit:
            r = resolve_table(hit[0], hit[1], comp)
            r.source = "override"
    if r is None:
        r = _auto(comp)
    if ov.get("params"):
        r.params.update(ov["params"])
    if ov.get("pins"):
        r.pins.update(_pins(ov["pins"]))
        r.verify = False
    return r


def _tube(comp) -> Resolution:
    from ..amp.tubes import find_tube
    from .tubes import model_for
    t = find_tube(comp.value) or find_tube(comp.mpn)
    if t is None:
        return Resolution("unsupported", comp.value or "tube", note="unknown tube type: set the value to e.g. 12AX7")
    pins: dict[str, list[str]] = {}
    for p, f in sorted(t.pins.items(), key=lambda kv: int(kv[0])):
        if f not in ("H", "HCT", "NC", "IS"):
            pins.setdefault(f, []).append(p)  # e.g. the 6AQ5 grid on pins 1 and 7
    if t.kind == "rectifier":
        return Resolution("rectifier", t.name, {"tube": t.name}, pins)
    m = model_for(t.name)
    if m is None:
        return Resolution("unsupported", t.name, note=f"no simulation model for the {t.name}")
    return Resolution("tube", t.name, {"tube": t.name, "model": m[0], "sections": 2 if t.kind == "triode2" else 1,
                                       "pa_max": t.pa_max}, pins)


BRIDGE_PREFIXES = ("KBU", "GBU", "KBP", "KBPC", "GBPC", "GBJ", "KBJ", "DB10", "DB15", "DB20", "W04", "W06", "W08",
                   "W10", "RS40", "RS50", "RS60", "RS80", "MB6", "MB10", "DF04", "DF06", "DF08", "DF10", "2W10")


def _bridge(comp) -> Resolution | None:
    fp = comp.footprint
    t = _norm(comp.mpn or comp.value or "")
    if not (fp.name.startswith("Diode_Bridge") or t.startswith(BRIDGE_PREFIXES)):
        return None
    pads = unique_pads(fp)
    if {"+", "-"} <= set(pads):
        ac = [p for p in pads if p not in ("+", "-")][:2]
        pins = {"+": ["+"], "-": ["-"], "AC1": [ac[0]], "AC2": [ac[1]]} if len(ac) == 2 else None
    else:
        nums = _numbered(fp)
        pins = {"+": ["1"], "AC1": ["2"], "AC2": ["3"], "-": ["4"]} if len(nums) == 4 else None  # + ~ ~ - (KBU/GBU)
    if pins is None:
        return Resolution("unsupported", comp.value, note="unknown bridge rectifier pinout")
    return Resolution("bridge", f"bridge rectifier {comp.value}", dict(DIODES["1N4007"][1]), pins, verify=True)


def _auto(comp) -> Resolution:
    fp = comp.footprint
    mt = fp.model.get("type", "")
    mcls = fp.model.get("cls")
    fpn = fp.name
    pre = _prefix(comp.ref)
    val = comp.value or ""
    ident = comp.mpn or val
    pads = unique_pads(fp)
    if mt == "tube" or fpn.startswith("Valve_"):
        return _tube(comp)
    br = _bridge(comp)
    if br is not None:
        return br
    if mt == "none" and pre in ("H", "MH", "FID", "TP", "W", "J", "P", "CN", "X", "JP") and not fpn.startswith(
            "SolderJumper"):
        return Resolution("none", "connection point")
    passive = pre in PASSIVE_PREFIXES
    idents = [t for t in (comp.mpn, None if passive else val) if t]
    # ---- logic ICs and microcontrollers (dedicated modules)
    for text in idents:
        from . import logic
        lk = logic.lookup(text)
        if lk is not None:
            pm, pkg = _pick_pinmap(lk.pinmaps, comp)
            if pm is not None:
                return Resolution("logic", lk.name, {"chip": lk.name}, _pins(pm), "table")
        from .avr import parts as avr_parts
        mk = avr_parts.lookup(text, comp)
        if mk is not None:
            return mk
    if fpn.startswith(("Module_Arduino_Nano", "Module_Arduino_Pro_Mini")):
        from .avr import parts as avr_parts
        mk = avr_parts.module(comp)
        if mk is not None:
            return mk
    # ---- table lookup (MPN first, then value)
    for text in idents:
        t = _norm(text)
        if package(comp) == "SOT-23" and t.startswith(("BAT54", "BAV99", "BAV70", "BAW56")):
            pairs = _sot23_dual(t)
            if pairs:
                base = DIODES["BAT54"][1] if t.startswith("BAT54") else DIODES["1N4148"][1]
                return Resolution("diodes", text, {**base, "pairs": pairs}, {}, "table")
        hit = lookup(text)
        if hit:
            return resolve_table(hit[0], hit[1], comp)
        zv = zener_voltage(text)
        if zv:
            return Resolution("diode", f"Zener {zv:g} V", dict(is_=1e-14, n=1.0, rs=5.0, bv=zv, ibv=5e-3,
                                                                imax=0.2), _diode_pins(comp), "table")
        if any(t.startswith(s) for s in SWITCHERS):
            return Resolution("unsupported", text, note="switching regulators and chargers are not simulated; "
                                                        "override with an LDO model to approximate the output")
    # ---- heuristics
    if pre in ("R",) and len(pads) == 2:
        return Resolution("resistor", "resistor", {"r": parse_value(val, 0.0)}, {"1": ["1"], "2": ["2"]})
    if pre == "RN" or fpn.startswith("R_Array"):
        nums = _numbered(fp)
        k = len(nums) // 2
        pairs = [(str(i + 1), str(2 * k - i)) for i in range(k)]
        return Resolution("resistor_array", "resistor array", {"r": parse_value(val, 10e3), "pairs": pairs})
    if pre in ("RV", "VR", "POT", "TR") or fpn.startswith(("Potentiometer", "Pot_")):
        taper_kind, ohms = parse_pot(val)
        pins = {"1": ["1"], "W": ["2"], "3": ["3"]}
        if {"4", "5", "6"} <= set(pads):
            pins.update({"4": ["4"], "W2": ["5"], "6": ["6"]})
        return Resolution("pot", f"pot {val}", {"r": ohms, "taper": taper_kind}, pins)
    if pre == "C" and len([p for p in pads if p]) >= 2:
        pol = fpn.startswith("CP_") or "elec" in fpn.lower() or "tantal" in fpn.lower() or mt == "radial_cap"
        vmax = None
        m = re.search(r"(\d+(?:\.\d+)?)\s*V\b", val, re.I)
        if m:
            vmax = float(m.group(1))
        return Resolution("capacitor", "polarised capacitor" if pol else "capacitor",
                          {"c": parse_value(val, 0.0), "polarized": pol, "vmax": vmax}, {"+": ["1"], "-": ["2"]})
    if pre == "L" and len(pads) == 2:
        return Resolution("inductor", "inductor", {"l": parse_value(val, 10e-6)}, {"1": ["1"], "2": ["2"]})
    if pre == "FB" or mcls == "FB":
        return Resolution("link", "ferrite bead", {"r": 0.1}, {"1": ["1"], "2": ["2"]})
    if pre in ("F", "PTC") or mcls == "F" or fpn.startswith(("Fuse", "Fuseholder")):
        return Resolution("link", "fuse", {"r": 0.05, "imax": parse_value(val, 1.0) or 1.0}, {"1": ["1"], "2": ["2"]})
    if fpn.startswith("SolderJumper") or pre == "JP":
        spec = _switch_spec(comp)
        if spec:
            return Resolution("switch", "solder jumper", spec, {})
    if pre in ("RV", "MOV") or fpn.startswith("RV_Disc") or "varistor" in fp.description.lower():
        return Resolution("none", "varistor (open below its clamp voltage)")
    is_led = (mt == "led_tht" or mcls == "LED" or fpn.startswith(("LED_", "LED-")) or
              any(k in val.lower() for k in LED_TYPES) and pre in ("D", "LED"))
    if fpn.startswith(("LED_WS2812", "LED_SK6812")) or "WS2812" in ident.upper() or "SK6812" in ident.upper():
        return Resolution("addressable", ident or "WS2812B", {}, {"VDD": ["1"], "DOUT": ["2"], "VSS": ["3"],
                                                               "DIN": ["4"]})
    if fpn.startswith("LED_RGB"):
        common_anode = "CA" in _norm(val) or "ANODE" in _norm(val)
        if fpn.startswith("LED_RGB_5050"):
            return Resolution("leds", "RGB LED", {"leds": [("6", "1", "red"), ("5", "2", "green"), ("4", "3", "blue")]},
                              {}, verify=True)
        com = "2"
        leds = [(com, k, c) if common_anode else (k, com, c) for k, c in (("1", "red"), ("3", "green"), ("4", "blue"))]
        return Resolution("leds", "RGB LED " + ("common anode" if common_anode else "common cathode"), {"leds": leds},
                          {}, verify=True)
    if fpn.startswith("7Segment"):
        return _seven_segment(comp)
    if is_led and pre in ("D", "LED", "LD", "DS") and len([p for p in pads if p]) == 2:
        big = fpn.startswith(("LED_Yuji_5730", "LED_PLCC_2835")) or "D8mm" in fpn or "D10mm" in fpn
        return Resolution("led", f"LED {led_params(val)['colour']}", led_params(val, big), _diode_pins(comp))
    if pre in ("D", "CR") and len([p for p in pads if p]) >= 2:
        if package(comp) == "SOT-23":
            return Resolution("diode", "diode (generic)", dict(DIODES["1N4148"][1]), _diode_pins(comp), verify=True)
        schottky = "SS" in val.upper()[:2] or "schottky" in fp.description.lower()
        base = DIODES["SS14" if schottky else ("1N4007" if fpn.startswith(("D_DO-41", "D_SMA", "D_SMB", "D_SMC",
                                                                             "D_DO-201", "D_DO-15"))
                                                 else "1N4148")][1]
        return Resolution("diode", "diode (generic)", dict(base), _diode_pins(comp))
    if pre in ("Q", "T", "TR"):
        return _generic_transistor(comp)
    if pre in ("SW", "S", "BTN", "KEY", "SWITCH") or mt == "tact":
        spec = _switch_spec(comp)
        if spec:
            return Resolution("switch", "switch", spec, {})
    if pre in ("K", "RL", "RLY") or fpn.startswith("Relay"):
        return _relay(comp)
    if pre == "BT" or fpn.startswith("BatteryHolder"):
        return _battery(comp)
    if pre in ("BZ", "LS", "SP", "BUZ"):
        return Resolution("buzzer", "buzzer" if pre == "BZ" else "speaker",
                          {"r": 8.0 if pre in ("LS", "SP") else 100.0}, {"+": ["1"], "-": ["2"]})
    if pre in ("Y", "X", "XTAL") or mt in ("hc49", "xtal_smd") or fpn.startswith(("Crystal", "Resonator")):
        if fpn.startswith("Oscillator"):
            return Resolution("unsupported", "oscillator", note="crystal oscillator outputs are not simulated")
        return Resolution("crystal", f"crystal {val}", {"f": parse_value(val, 16e6)}, {})
    if fpn.startswith(("DC_Jack", "BarrelJack")):
        return _dc_jack(comp)
    if fpn.startswith("Jack_6.35mm") or fpn.startswith("Jack_3.5mm"):
        return _audio_jack(comp)
    if fpn.startswith("USB_") and not fpn.startswith("USB_A"):
        return _usb(comp)
    if pre in ("J", "P", "CN", "CON", "X", "TP", "W", "H", "MH", "FID", "USB", "CONN", "HDR") or mt == "none":
        return Resolution("none", "connection point")
    if pre in ("U", "IC", "A", "M"):
        return Resolution("unsupported", ident or fpn, note="no simulation model for this part")
    return Resolution("unsupported", ident or fpn, note="no simulation model for this part")


def _generic_transistor(comp) -> Resolution:
    fp = comp.footprint
    pads = set(unique_pads(fp))
    t = _norm(comp.value + " " + comp.mpn)
    if {"D", "S", "G"} <= pads:
        return Resolution("jfet", "JFET (generic)", dict(pol=1, vp=-1.5, idss=3e-3), {r: [r] for r in "DGS"})
    if {"C", "B", "E"} <= pads:
        pol = -1 if "PNP" in t else 1
        return Resolution("bjt", "PNP (generic)" if pol < 0 else "NPN (generic)",
                          dict(pol=pol, is_=1e-14, bf=200, br=4, vaf=80, imax=0.2, pmax=0.5), {r: [r] for r in "CBE"})
    pkg = package(comp)
    fet = any(k in t for k in ("FET", "MOS", "IRF", "IRL", "AO3", "AO4", "SI23", "BSS", "2N70", "DMG"))
    pol = -1 if ("PNP" in t or "PMOS" in t or "P-CH" in t or "PCH" in t) else 1
    nums = _numbered(fp)
    if fet:
        pinout = {"SOT-23": "GSD", "TO-92": "SGD", "8": "SSSGDDDD"}.get(pkg, "GDS")
        pins = _letters_map(pinout, nums if pkg != "TO-252" else ["1", "2", "3"], "DGS")
        if set(pins) == set("DGS"):
            return Resolution("fet", "MOSFET (generic)", dict(pol=pol, vth=2.0, k=1.0, lam=0.01, imax=5, pmax=1,
                                                               body=True), pins, verify=True)
    pinout = {"SOT-23": "BEC", "TO-92": "EBC", "TO-220": "BCE", "TO-126": "ECB", "SOT-89": "BCE", "SOT-223": "BCE",
              "TO-5": "EBC"}.get(pkg)
    if pinout and len(nums) >= 3:
        pins = _letters_map(pinout, nums, "CBE")
        return Resolution("bjt", "PNP (generic)" if pol < 0 else "NPN (generic)",
                          dict(pol=pol, is_=1e-14, bf=200, br=4, vaf=80, imax=0.5, pmax=0.5), pins, verify=True)
    return Resolution("unsupported", comp.value or "transistor", note="unknown transistor package")


def _relay(comp) -> Resolution:
    fp = comp.footprint
    n = fp.name
    t = _norm(comp.value + " " + comp.mpn)
    m = re.search(r"(\d+)VDC", t) or re.search(r"DC(\d+)V", t) or re.search(r"(\d+)V", t)
    vcoil = float(m.group(1)) if m else 5.0
    if n.startswith("Relay_SPDT_SRD"):
        pins = {"COIL1": ["2"], "COIL2": ["5"], "COM1": ["1"], "NC1": ["3"], "NO1": ["4"]}
        verify = False
        r = vcoil * vcoil / 0.36
    elif n.startswith("Relay_SPDT_Omron_G5V-1"):
        pins = {"COIL1": ["1"], "COIL2": ["10"], "COM1": ["2"], "NC1": ["5"], "NO1": ["6"]}
        verify = True
        r = vcoil * vcoil / 0.15
    elif n.startswith("Relay_DPDT"):
        pins = {"COIL1": ["1"], "COIL2": ["8"], "COM1": ["3"], "NC1": ["2"], "NO1": ["4"], "COM2": ["6"],
                "NC2": ["7"], "NO2": ["5"]}
        verify = True
        r = vcoil * vcoil / 0.2
    else:
        return Resolution("unsupported", comp.value or "relay", note="unknown relay pinout")
    return Resolution("relay", f"relay {vcoil:g} V", {"vcoil": vcoil, "r": r, "l": r * 2e-3}, pins, verify=verify)


def _battery(comp) -> Resolution:
    n = comp.footprint.name
    t = (comp.value or "").upper()
    v = parse_voltage(comp.value)
    if "CR2032" in t or "CR2032" in n.upper() or "1x20mm" in n:
        v, r = v or 3.0, 15.0
    elif "18650" in t or "18650" in n:
        v, r = v or 3.7, 0.05
    elif "2XAA" in t or "2xAA" in n:
        v, r = v or 3.0, 0.3
    else:
        v, r = v or 9.0, 1.0
    return Resolution("battery", f"battery {v:g} V", {"v": v, "r": r}, {"+": ["1"], "-": ["2"]})


def _dc_jack(comp) -> Resolution:
    pedal = "Pedal" in comp.footprint.name or "negative" in comp.footprint.description.lower()
    v = parse_voltage(comp.value)
    return Resolution("dcjack", "DC power jack", {"v": v, "centre_negative": pedal, "default": 9.0 if pedal else 12.0},
                      {"CENTRE": ["1"], "SLEEVE": ["2"], "SWITCH": ["3"]})


def _audio_jack(comp) -> Resolution:
    pads = unique_pads(comp.footprint)
    pins = {p: [p] for p in pads if p}
    return Resolution("jack", "audio jack", {"switched": [p for p in ("TN", "RN", "SN") if p in pads]}, pins)


def _usb(comp) -> Resolution:
    pads = [p for p in unique_pads(comp.footprint) if p]
    if any("A4" in p or "A9" in p or "B9" in p for p in pads):
        vbus = [p for p in pads if p in ("A4B9", "B4A9", "A9", "B9", "A4", "B4")]
        gnd = [p for p in pads if p in ("A1B12", "B1A12", "A12", "B12", "A1", "B1")]
    elif "5" in pads:
        vbus, gnd = ["1"], ["5"]
    else:
        vbus, gnd = ["1"], ["4"]
    if not vbus or not gnd:
        return Resolution("none", "connection point")
    return Resolution("usb", "USB power (5 V)", {"v": 5.0}, {"VBUS": vbus, "GND": gnd})


def _seven_segment(comp) -> Resolution:
    n = comp.footprint.name
    t = _norm(comp.value + comp.mpn)
    colour = led_params(comp.value)["colour"]
    if "4Digit" in n:
        anode = "CC" not in t
        seg = {"A": "11", "B": "7", "C": "4", "D": "2", "E": "1", "F": "10", "G": "5", "DP": "3"}
        digits = ["12", "9", "8", "6"]
    else:
        anode = "CA" in t or "ANODE" in t
        seg = {"A": "7", "B": "6", "C": "4", "D": "2", "E": "1", "F": "9", "G": "10", "DP": "5"}
        digits = ["3"]
    leds = []
    for di, com in enumerate(digits):
        for s, pad in seg.items():
            a, k = (com, pad) if anode else (pad, com)
            leds.append((a, k, colour, f"{s}{di + 1 if len(digits) > 1 else ''}"))
    return Resolution("leds", f"7-segment {'common anode' if anode else 'common cathode'}",
                      {"leds": leds, "segments": True, "digits": len(digits)}, {})
