"""Vacuum tube (valve) data: base type, pinout, heater and maximum ratings, plus the 3D outline.

Pin functions use these codes:

``PA GA KA`` / ``PB GB KB``
    plate, grid and cathode of the two sections of a dual triode. Section A is the one on the lower pin
    numbers (pins 1-2-3 on a 12AX7, the "V1A" of most guitar-amp schematics), section B the other.
``A G1 G2 G3 K``
    anode (plate), control grid, screen grid, suppressor grid and cathode of a pentode / beam tetrode.
``A1 A2 K``
    the anodes and cathode of a full-wave rectifier; ``HK`` is a filament that is also the cathode (5Y3).
``H HCT``
    heater pins and the heater centre tap.
``IS``
    internal shield (usually grounded or tied to the cathode).
``NC``
    not connected - and possibly internally connected, so never use it as a tie point.

Ratings are design-centre maximums from the manufacturers' data (plate voltage ``va_max`` in volts, plate
dissipation ``pa_max`` in watts per section). Guitar amps often run some of these hotter; the checks only warn.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Tube:
    name: str
    base: str  # noval | b7g | octal
    kind: str  # triode2 | pentode | power | rectifier
    pins: dict
    heater_v: float = 6.3
    heater_a: float = 0.3
    va_max: float = 300.0
    pa_max: float = 1.0
    mu: float = 0.0
    gm_ma: float = 0.0  # transconductance, mA/V
    ra_k: float = 0.0  # plate resistance, kOhm
    i_max_ma: float = 0.0  # rectifiers: maximum DC output current
    aliases: tuple = ()
    shape: tuple = (21.0, 44.0, 0.0)  # glass diameter, glass height above the socket, bakelite base height
    note: str = ""

    @property
    def heater_pins(self) -> list[str]:
        return [p for p, f in self.pins.items() if f in ("H", "HK")]

    @property
    def heater_ct(self) -> str | None:
        return next((p for p, f in self.pins.items() if f == "HCT"), None)

    def pin(self, function: str) -> str | None:
        """Pin number of a function code ("PA", "A", "K" ...), or None."""
        return next((p for p, f in self.pins.items() if f == function), None)

    def pinout_text(self) -> str:
        return " ".join(f"{p}={f}" for p, f in sorted(self.pins.items(), key=lambda kv: int(kv[0])))


_TRIODE9 = {"1": "PA", "2": "GA", "3": "KA", "4": "H", "5": "H", "6": "PB", "7": "GB", "8": "KB", "9": "HCT"}
_ECC88 = {"1": "PA", "2": "GA", "3": "KA", "4": "H", "5": "H", "6": "PB", "7": "GB", "8": "KB", "9": "IS"}
_EL84 = {"1": "NC", "2": "G1", "3": "K", "4": "H", "5": "H", "6": "NC", "7": "A", "8": "NC", "9": "G2"}
_EF86 = {"1": "G2", "2": "IS", "3": "K", "4": "H", "5": "H", "6": "A", "7": "IS", "8": "G3", "9": "G1"}
_EZ81 = {"1": "A2", "2": "NC", "3": "K", "4": "H", "5": "H", "6": "NC", "7": "A1", "8": "NC", "9": "NC"}
_BEAM8 = {"1": "NC", "2": "H", "3": "A", "4": "G2", "5": "G1", "6": "NC", "7": "H", "8": "K"}
_EL34 = {"1": "G3", "2": "H", "3": "A", "4": "G2", "5": "G1", "6": "NC", "7": "H", "8": "K"}
_RECT8 = {"1": "NC", "2": "H", "3": "NC", "4": "A2", "5": "NC", "6": "A1", "7": "NC", "8": "HK"}
_SN7 = {"1": "GA", "2": "PA", "3": "KA", "4": "GB", "5": "PB", "6": "KB", "7": "H", "8": "H"}
_6AQ5 = {"1": "G1", "2": "K", "3": "H", "4": "H", "5": "A", "6": "G2", "7": "G1"}
_6X4 = {"1": "A2", "2": "NC", "3": "H", "4": "H", "5": "NC", "6": "A1", "7": "K"}
_6C4 = {"1": "A", "2": "NC", "3": "H", "4": "H", "5": "A", "6": "G1", "7": "K"}

TUBES: dict[str, Tube] = {}


def _add(t: Tube) -> None:
    TUBES[t.name] = t


# --- preamp triodes (noval, 12.6 V heater with centre tap: 6.3 V = pins 4+5 to one side, pin 9 to the other)
_add(Tube("12AX7", "noval", "triode2", _TRIODE9, 6.3, 0.3, 330, 1.2, 100, 1.6, 62.5, aliases=("ECC83", "7025"),
          note="High-gain preamp triode: the first stages of nearly every guitar amp."))
_add(Tube("12AT7", "noval", "triode2", _TRIODE9, 6.3, 0.3, 330, 2.5, 60, 5.5, 11.0, aliases=("ECC81", "6201"),
          note="Medium-gain, low plate resistance: reverb drivers and phase inverters."))
_add(Tube("12AU7", "noval", "triode2", _TRIODE9, 6.3, 0.3, 330, 2.75, 17, 2.2, 7.7, aliases=("ECC82", "5814"),
          note="Low-gain triode: cathode followers, phase inverters, clean preamps."))
_add(Tube("12AY7", "noval", "triode2", _TRIODE9, 6.3, 0.3, 300, 1.5, 40, 1.75, 22.8, aliases=("6072",),
          note="Tweed-era low-gain first stage."))
_add(Tube("5751", "noval", "triode2", _TRIODE9, 6.3, 0.35, 330, 1.0, 70, 1.2, 58.0,
          note="12AX7 with about 30 % less gain."))
_add(Tube("ECC88", "noval", "triode2", _ECC88, 6.3, 0.365, 220, 1.5, 33, 12.5, 2.6, aliases=("6922", "6DJ8", "E88CC"),
          note="Low-noise frame-grid triode. Pin 9 is the internal shield between the sections (ground it). "
               "6.3 V heater only, between pins 4 and 5."))
_add(Tube("EF86", "noval", "pentode", _EF86, 6.3, 0.2, 300, 1.0, 0, 2.0, 2500.0, aliases=("6267",),
          note="Low-noise preamp pentode (Vox AC15). Ground the internal shields (pins 2 and 7); g3 (pin 8) to the "
               "cathode."))
# --- octal preamp / driver triodes
_add(Tube("6SN7", "octal", "triode2", _SN7, 6.3, 0.6, 450, 5.0, 20, 2.6, 7.7, aliases=("6SN7GT", "ECC33"),
          shape=(32.0, 62.0, 15.0), note="Octal medium-mu dual triode (drivers, phase inverters)."))
_add(Tube("6SL7", "octal", "triode2", _SN7, 6.3, 0.3, 300, 1.0, 70, 1.6, 44.0, aliases=("6SL7GT", "ECC35"),
          shape=(32.0, 62.0, 15.0), note="Octal high-mu dual triode."))
# --- power tubes
_add(Tube("EL84", "noval", "power", _EL84, 6.3, 0.76, 300, 12.0, aliases=("6BQ5", "6P14P"),
          shape=(21.6, 64.0, 0.0), note="Pins 1, 6 and 8 are internally connected: never use them as tie points."))
_add(Tube("6V6GT", "octal", "power", _BEAM8, 6.3, 0.45, 315, 12.0, aliases=("6V6", "6V6S", "6V6GTA"),
          shape=(31.0, 63.0, 15.0)))
_add(Tube("6L6GC", "octal", "power", _BEAM8, 6.3, 0.9, 500, 30.0, aliases=("6L6", "7581", "7581A"),
          shape=(38.0, 88.0, 16.0)))
_add(Tube("5881", "octal", "power", _BEAM8, 6.3, 0.9, 400, 23.0, aliases=("6L6WGB", "6L6WGC"), shape=(34.0, 80.0, 16.0)))
_add(Tube("KT66", "octal", "power", _BEAM8, 6.3, 1.27, 500, 25.0, shape=(40.0, 88.0, 16.0)))
_add(Tube("EL34", "octal", "power", _EL34, 6.3, 1.5, 800, 25.0, aliases=("6CA7",), shape=(32.0, 84.0, 16.0),
          note="Pin 1 is the suppressor grid: tie it to the cathode (pin 8)."))
_add(Tube("KT88", "octal", "power", _BEAM8, 6.3, 1.6, 800, 35.0, aliases=("KT90", "KT120"), shape=(51.0, 100.0, 18.0)))
_add(Tube("6550", "octal", "power", _BEAM8, 6.3, 1.6, 600, 35.0, aliases=("6550A", "6550C"),
          shape=(44.0, 96.0, 18.0)))
_add(Tube("6AQ5", "b7g", "power", _6AQ5, 6.3, 0.45, 275, 12.0, aliases=("6005", "EL90"), shape=(18.5, 56.0, 0.0),
          note="Seven-pin 6V6; the control grid comes out on pins 1 and 7."))
# --- rectifiers
_add(Tube("5Y3GT", "octal", "rectifier", _RECT8, 5.0, 2.0, 1400, 0, i_max_ma=125, aliases=("5Y3", "5Y3GB"),
          shape=(32.0, 70.0, 15.0), note="Filament-cathode: the rectified B+ comes out of pin 8 (a heater pin)."))
_add(Tube("5AR4", "octal", "rectifier", _RECT8, 5.0, 1.9, 1550, 0, i_max_ma=250, aliases=("GZ34",),
          shape=(32.0, 78.0, 16.0), note="Indirectly heated (slow warm-up); cathode tied to the heater at pin 8."))
_add(Tube("5U4GB", "octal", "rectifier", _RECT8, 5.0, 3.0, 1550, 0, i_max_ma=275, aliases=("5U4", "5U4G"),
          shape=(40.0, 92.0, 18.0)))
_add(Tube("EZ81", "noval", "rectifier", _EZ81, 6.3, 1.0, 1000, 0, i_max_ma=150, aliases=("6CA4",),
          shape=(21.6, 58.0, 0.0), note="Cathode (B+ out) on pin 3; its heater is at cathode potential relative to "
                                       "the other tubes - give it its own 6.3 V winding or use the PT's 6.3 V."))
_add(Tube("6X4", "b7g", "rectifier", _6X4, 6.3, 0.6, 1250, 0, i_max_ma=70, aliases=("EZ90",), shape=(18.5, 44.0, 0.0)))
_add(Tube("6C4", "b7g", "pentode", _6C4, 6.3, 0.15, 300, 3.5, 17, 2.2, 7.7, aliases=("EC90",),
          shape=(18.5, 42.0, 0.0), note="Single 12AU7 section (plate on pins 1 and 5)."))

ALIASES = {a.upper(): t.name for t in TUBES.values() for a in (t.name,) + t.aliases}


def find_tube(value: str) -> Tube | None:
    """Tube for a component value such as "12AX7", "ECC83 (V1)" or "6V6GT/JJ"."""
    if not value:
        return None
    v = value.upper().replace(" ", "")
    if v in ALIASES:
        return TUBES[ALIASES[v]]
    for tok in re.split(r"[/,;()\[\]]+", v):
        if tok in ALIASES:
            return TUBES[ALIASES[tok]]
    for key in sorted(ALIASES, key=len, reverse=True):  # "12AX7A", "EL34B", "6L6GC-STR"
        if v.startswith(key):
            return TUBES[ALIASES[key]]
    return None


def section_pins(tube: Tube, section: str = "A") -> dict:
    """{"P": pin, "G": pin, "K": pin} for one half of a dual triode (or the triode-strapped single tube)."""
    s = section.upper()
    if tube.kind == "triode2":
        return {"P": tube.pin("P" + s), "G": tube.pin("G" + s), "K": tube.pin("K" + s)}
    return {"P": tube.pin("A"), "G": tube.pin("G1"), "K": tube.pin("K")}


@dataclass
class HeaterLoad:
    tubes: list = field(default_factory=list)  # (ref, tube name, volts, amps)

    @property
    def by_voltage(self) -> dict:
        out: dict[float, float] = {}
        for _, _, v, a in self.tubes:
            out[v] = out.get(v, 0.0) + a
        return out


def heater_load(project) -> HeaterLoad:
    """Heater current per heater voltage for every tube socket in the project."""
    h = HeaterLoad()
    for c in project.components:
        if c.footprint.model.get("type") != "tube":
            continue
        t = find_tube(c.value)
        if t is not None:
            h.tubes.append((c.ref, t.name, t.heater_v, t.heater_a))
    return h
