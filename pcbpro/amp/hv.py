"""High-voltage and high-current board rules for amplifiers.

* Conductor spacing from IPC-2221B table 6-1 (by the peak voltage between two conductors).
* Track width for a current from the IPC-2221 conductor-sizing chart: I = k * dT^0.44 * A^0.725 (A in mil^2).
* Per-net annotations kept in ``project.amp["nets"]``: DC working voltage, AC (rms) voltage, current and whether
  the net carries mains. ``net_info`` turns them into a ``NetV`` the checks and the net-class presets use.

The IPC spacings are minimums for functional insulation. Mains wiring needs safety spacing to IEC 62368-1 /
UL; ``MAINS_CLEARANCE`` is the conservative default between mains and everything else.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from ..model.board import NetClass, Project

# IPC-2221B table 6-1: (upper voltage, {category: spacing mm}); above 500 V the spacing grows per volt.
#   B1 internal conductors          B2 external, uncoated, sea level - 3050 m   B3 external, uncoated, > 3050 m
#   B4 external, permanent coating  A5 external, conformal-coated assembly       A6 component lead, uncoated
#   A7 component lead, conformal coated
IPC_TABLE = [
    (15, {"B1": 0.05, "B2": 0.1, "B3": 0.1, "B4": 0.05, "A5": 0.13, "A6": 0.13, "A7": 0.13}),
    (30, {"B1": 0.05, "B2": 0.1, "B3": 0.1, "B4": 0.05, "A5": 0.13, "A6": 0.25, "A7": 0.13}),
    (50, {"B1": 0.1, "B2": 0.6, "B3": 0.6, "B4": 0.13, "A5": 0.13, "A6": 0.4, "A7": 0.13}),
    (100, {"B1": 0.1, "B2": 0.6, "B3": 1.5, "B4": 0.13, "A5": 0.13, "A6": 0.5, "A7": 0.13}),
    (150, {"B1": 0.2, "B2": 0.6, "B3": 3.2, "B4": 0.4, "A5": 0.4, "A6": 0.8, "A7": 0.4}),
    (170, {"B1": 0.2, "B2": 1.25, "B3": 3.2, "B4": 0.4, "A5": 0.4, "A6": 0.8, "A7": 0.4}),
    (250, {"B1": 0.2, "B2": 1.25, "B3": 6.4, "B4": 0.4, "A5": 0.4, "A6": 0.8, "A7": 0.4}),
    (300, {"B1": 0.2, "B2": 1.25, "B3": 12.5, "B4": 0.4, "A5": 0.4, "A6": 0.8, "A7": 0.8}),
    (500, {"B1": 0.25, "B2": 2.5, "B3": 12.5, "B4": 0.8, "A5": 0.8, "A6": 1.5, "A7": 0.8}),
]
IPC_PER_VOLT = {"B1": 0.0025, "B2": 0.005, "B3": 0.025, "B4": 0.00305, "A5": 0.00305, "A6": 0.00305, "A7": 0.00305}
CATEGORIES = {
    "B2": "External layers, uncoated (normal bare board with solder mask), up to 3050 m",
    "B3": "External layers, uncoated, above 3050 m altitude",
    "B4": "External layers with a permanent polymer coating",
    "A5": "External layers, assembly conformally coated",
    "A6": "Component leads / terminations, uncoated",
    "B1": "Internal layers",
}
MAINS_CLEARANCE = 6.4  # mm between mains (primary) copper and everything else: reinforced-insulation practice

DEFAULTS = {"category": "B2", "rise": 10.0, "copper_oz": 1.0, "mains_clearance": MAINS_CLEARANCE}


def ipc_clearance(volts: float, category: str = "B2") -> float:
    """Minimum spacing (mm) between conductors with ``volts`` (DC or AC peak) between them."""
    v = abs(volts)
    cat = category if category in IPC_PER_VOLT else "B2"
    if v > 500:
        return round(IPC_PER_VOLT[cat] * v, 3)
    for upper, row in IPC_TABLE:
        if v <= upper:
            return row[cat]
    return IPC_TABLE[-1][1][cat]


OZ_MIL = 1.378  # 1 oz/ft^2 copper = 1.378 mil (35 um)


def track_width_for(amps: float, rise: float = 10.0, oz: float = 1.0, external: bool = True) -> float:
    """IPC-2221 track width (mm) carrying ``amps`` with a ``rise`` degC temperature rise."""
    if amps <= 0:
        return 0.0
    k = 0.048 if external else 0.024
    area = (amps / (k * rise ** 0.44)) ** (1 / 0.725)  # mil^2
    return round(area / (oz * OZ_MIL) * 0.0254, 3)


def current_for(width_mm: float, rise: float = 10.0, oz: float = 1.0, external: bool = True) -> float:
    """Current (A) a ``width_mm`` track carries at a ``rise`` degC temperature rise (IPC-2221)."""
    k = 0.048 if external else 0.024
    area = width_mm / 0.0254 * oz * OZ_MIL
    return k * rise ** 0.44 * area ** 0.725


# --------------------------------------------------------------------------- net annotations

@dataclass
class NetV:
    dc: float = 0.0  # DC working voltage to ground
    ac: float = 0.0  # AC peak voltage (rms * sqrt 2)
    amps: float = 0.0  # continuous current (rms)
    mains: bool = False
    known: bool = False

    @property
    def peak(self) -> float:
        return abs(self.dc) + self.ac

    def describe(self) -> str:
        parts = []
        if self.dc:
            parts.append(f"{self.dc:g} V")
        if self.ac:
            parts.append(f"{self.ac / math.sqrt(2):.0f} VAC")
        if self.mains:
            parts.append("mains")
        return " + ".join(parts) or "0 V"


_V = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*(k?)\s*(V)?\s*(AC|RMS|VAC)?", re.I)


def parse_net_voltage(text: str) -> tuple[float, float]:
    """'450', '450V', '-52V', '300VAC', '6.3 VAC', '330V rms' -> (dc, ac peak)."""
    s = (text or "").strip()
    if not s:
        return 0.0, 0.0
    m = _V.search(s)
    if not m:
        return 0.0, 0.0
    v = float(m.group(1)) * (1000.0 if m.group(2) else 1.0)
    if m.group(4) or re.search(r"\b(ac|rms|vac)\b", s, re.I):
        return 0.0, abs(v) * math.sqrt(2)
    return v, 0.0


def amp_settings(project: Project) -> dict:
    s = dict(DEFAULTS)
    s.update({k: v for k, v in (getattr(project, "amp", None) or {}).items() if k in DEFAULTS})
    return s


def net_table(project: Project) -> dict:
    return (getattr(project, "amp", None) or {}).get("nets", {})


def net_info(project: Project, net: str | None) -> NetV:
    if not net:
        return NetV()
    d = net_table(project).get(net)
    if not d:
        return NetV()
    return NetV(float(d.get("v", 0.0) or 0.0), float(d.get("ac", 0.0) or 0.0) * math.sqrt(2),
                float(d.get("i", 0.0) or 0.0), bool(d.get("mains")), True)


def set_net(project: Project, net: str, v: float | None = None, ac_rms: float | None = None,
            amps: float | None = None, mains: bool | None = None) -> None:
    """Annotate a net (volts DC to ground, VAC rms, current in A, mains flag)."""
    if not isinstance(getattr(project, "amp", None), dict):
        project.amp = {}
    d = project.amp.setdefault("nets", {}).setdefault(net, {})
    if v is not None:
        d["v"] = float(v)
    if ac_rms is not None:
        d["ac"] = float(ac_rms)
    if amps is not None:
        d["i"] = float(amps)
    if mains is not None:
        d["mains"] = bool(mains)
    for k in [k for k, val in d.items() if not val]:
        del d[k]
    if not d:
        del project.amp["nets"][net]


def voltage_between(a: NetV, b: NetV) -> float:
    """Worst-case peak voltage between two nets (AC components taken in anti-phase)."""
    return abs(a.dc - b.dc) + a.ac + b.ac


# IPC-2221B gives component leads / terminations (pads) their own columns: A6 uncoated, A7 coated
LEAD_CATEGORY = {"B2": "A6", "B4": "A7", "A5": "A7"}


def lead_category(category: str) -> str:
    return LEAD_CATEGORY.get(category, category)


def required_clearance(project: Project, a: NetV, b: NetV, settings: dict | None = None, lead: bool = False) -> float:
    """IPC spacing between copper of two nets. ``lead``: one side is a pad (a component lead termination), which
    IPC-2221B rates separately from conductor-to-conductor spacing (e.g. A6 instead of B2)."""
    s = settings or amp_settings(project)
    cat = lead_category(s["category"]) if lead else s["category"]
    req = ipc_clearance(voltage_between(a, b), cat)
    if a.mains != b.mains:
        req = max(req, float(s["mains_clearance"]))
    return req


# --------------------------------------------------------------------------- net-class presets

def _bracket(volts: float) -> int:
    """Upper voltage of the IPC-2221B table row that covers ``volts`` (above 500 V: rounded up to 100 V)."""
    for upper, _ in IPC_TABLE:
        if volts <= upper:
            return upper
    return int(math.ceil(volts / 100.0) * 100)


def _up(v: float, step: float = 0.05) -> float:
    return round(math.ceil(v / step - 1e-9) * step, 3)


def apply_hv_netclasses(project: Project) -> list[str]:
    """Create HV / mains / power net classes from the net annotations and assign the annotated nets to them, so
    the router, the zone fills and the standard DRC keep the IPC spacing to ground and the current-carrying widths.

    A net goes into the class of the IPC table row its peak voltage falls in (classes with the same spacing are
    merged under the highest voltage). Spacing between two live nets (e.g. B+ next to a heater wire, or the two
    ends of an HV winding) depends on both: the autorouter and the amp checks handle that pair by pair."""
    s = amp_settings(project)
    if not isinstance(getattr(project, "amp", None), dict):
        project.amp = {}
    base = project.netclasses.get("Default") or NetClass("Default")
    for net in [n for n, c in project.net_class_map.items() if c in _amp_class_names(project)]:
        del project.net_class_map[net]  # re-derive from the current annotations
    groups: dict[float, list] = {}
    power: list = []
    for net in sorted(net_table(project)):
        nv = net_info(project, net)
        if nv.mains:
            groups.setdefault(-1.0, []).append((net, nv))
        elif nv.peak > 30:
            groups.setdefault(ipc_clearance(_bracket(nv.peak), lead_category(s["category"])), []).append((net, nv))
        elif nv.amps >= 0.25:
            power.append((net, nv))
    notes = []
    made = []

    def make(name: str, cl: float, members: list) -> None:
        w = max([base.track_width] + [_up(track_width_for(nv.amps, s["rise"], s["copper_oz"])) for _, nv in members])
        nc = NetClass(name, _up(max(base.clearance, cl), 0.01), w, max(base.via_diameter, 1.2 if cl > 1 else 1.0),
                      max(base.via_drill, 0.6 if cl > 1 else 0.5))
        project.netclasses[name] = nc
        for net, _ in members:
            project.net_class_map[net] = name
        made.append(name)
        notes.append(f"{name}: clearance {nc.clearance:g} mm, track {nc.track_width:g} mm ({len(members)} nets)")

    for cl, members in sorted(groups.items()):
        if cl < 0:
            peak = max(nv.peak for _, nv in members)
            make("Mains", max(float(s["mains_clearance"]) / 2, ipc_clearance(peak, s["category"]), 2.5), members)
        else:
            top = max(_bracket(nv.peak) for _, nv in members)
            make(f"HV{top}", cl, members)
    if power:
        make("Power", base.clearance, power)
    for name in [n for n in _amp_class_names(project) if n not in made and n in project.netclasses]:
        del project.netclasses[name]  # stale classes from earlier annotations
    project.amp["classes"] = made
    return notes


def _amp_class_names(project: Project) -> list[str]:
    return list((getattr(project, "amp", None) or {}).get("classes", []))


def pair_clearance_fn(project: Project):
    """f(net_a, net_b, lead=False) -> the IPC spacing two annotated nets need from each other (``lead``: one side
    is a pad), or None when the project has no voltage annotations. Used by the autorouter, the zone fill and the
    placer so live nets keep conductor spacing from each other."""
    if not net_table(project):
        return None
    s = amp_settings(project)
    cache: dict = {}

    def f(a: str | None, b: str | None, lead: bool = False) -> float:
        if a is not None and a == b:
            return 0.0
        key = ((a, b) if (a or "") <= (b or "") else (b, a)) + (bool(lead),)
        v = cache.get(key)
        if v is None:
            v = cache[key] = required_clearance(project, net_info(project, a), net_info(project, b), s, bool(lead))
        return v
    return f
