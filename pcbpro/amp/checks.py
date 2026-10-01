"""Amplifier design checks, run as part of DRC whenever the project has amp data (``project.amp``).

* HV clearance: copper of two nets must be as far apart as IPC-2221B asks for the voltage between them, and mains
  copper must keep the mains clearance from everything else.
* Track current: tracks of nets with a current annotation must be wide enough (IPC-2221).
* Part ratings: capacitor voltage ratings (written in the value, "22uF 450V") and electrolytic polarity, resistor
  power (V^2/R) and working voltage.
* Bleeders: every big high-voltage capacitor needs a resistive path to ground so it discharges at switch-off.
* Tube sockets: unused / internally connected pins used as tie points, heater wiring, plate voltage vs. rating.
"""
from __future__ import annotations

import math
import re

from shapely.ops import nearest_points, unary_union
from shapely.strtree import STRtree

from ..model.board import Project
from ..model.connectivity import get_connectivity
from ..model.copper import copper_by_layer
from ..model.drc import Violation
from ..sim.units import fmt_eng, parse_value, parse_voltage
from .hv import (NetV, amp_settings, ipc_clearance, lead_category, net_info, net_table, required_clearance,
                 track_width_for, voltage_between)
from .tubes import find_tube

GROUND_NAMES = {"GND", "0V", "AGND", "PGND", "GNDA", "GNDPWR", "STAR", "CHASSIS", "EARTH", "PE", "SGND", "GND_STAR"}


def is_ground(net: str | None) -> bool:
    if not net:
        return False
    n = net.upper().lstrip("/")
    return n in GROUND_NAMES or n.startswith("GND") or n.endswith("_GND")


def _nv(project: Project, net: str | None) -> NetV:
    nv = net_info(project, net)
    if not nv.known and is_ground(net):
        nv.known = True
    return nv


def run_amp_checks(project: Project) -> list[Violation]:
    out: list[Violation] = []
    s = amp_settings(project)
    try:
        conn = get_connectivity(project)
    except Exception:  # a broken board is reported by the main DRC
        return out
    out += _hv_clearance(project, conn, s)
    out += _track_current(project, s)
    out += _capacitors(project)
    out += _resistors(project)
    out += _bleeders(project)
    out += _tubes(project)
    return out


# --------------------------------------------------------------------------- HV clearance

def _hv_clearance(project: Project, conn, s: dict) -> list[Violation]:
    hot = {n for n in net_table(project) if _nv(project, n).peak > 30 or _nv(project, n).mains}
    if not hot:
        return []
    peaks = sorted((_nv(project, n).peak for n in hot), reverse=True)
    worst = peaks[0] + (peaks[1] if len(peaks) > 1 else 0.0)
    reach = max(ipc_clearance(worst, s["category"]), float(s["mains_clearance"]) if any(
        _nv(project, n).mains for n in hot) else 0.0)
    out: list[Violation] = []
    seen: set = set()
    for layer, items in copper_by_layer(project).items():
        if len(items) < 2:
            continue
        nets = [conn.effective_net(it) for it in items]
        idx = [i for i, n in enumerate(nets) if n in hot]
        if not idx:
            continue
        geoms = [it.geom for it in items]
        tree = STRtree(geoms)
        # copper of a track that lies inside a pad of its own net is part of that lead termination: conductor
        # (B2) spacing only applies to the exposed rest of the track
        pad_u: dict = {}
        for it, n in zip(items, nets):
            if it.kind == "pad" and n:
                pad_u.setdefault(n, []).append(it.geom)
        pad_u = {n: unary_union(g) for n, g in pad_u.items()}
        exposed_cache: dict = {}

        def exposed(k):
            it, n = items[k], nets[k]
            if it.kind != "track" or n not in pad_u:
                return it.geom
            if k not in exposed_cache:
                exposed_cache[k] = it.geom.difference(pad_u[n])
            return exposed_cache[k]

        for i in idx:
            a, na = items[i], nets[i]
            for j in tree.query(geoms[i], predicate="dwithin", distance=reach).tolist():
                if j == i:
                    continue
                b, nb = items[j], nets[j]
                if a.node == b.node or (na is not None and na == nb):
                    continue
                if a.kind == "zone" and b.kind == "zone" and a.obj is b.obj:
                    continue
                intra = a.kind == "pad" and b.kind == "pad" and a.obj is b.obj
                if intra and (re.match(r"^(R|C|D|L|F|FB|Q|RV|VR|TP)\d", a.obj.ref.upper()) or na is None or nb is None):
                    continue  # a part's own terminals (its rating covers them) or an unused pin
                va, vb = _nv(project, na), _nv(project, nb)
                # a pad is a component lead termination: IPC-2221B rates lead-to-conductor spacing separately
                # (A6 / A7) from conductor-to-conductor spacing (B2 / B4)
                lead = a.kind == "pad" or b.kind == "pad"
                req = required_clearance(project, va, vb, s, lead)
                d = a.geom.distance(b.geom)
                if d >= req - 1e-3:
                    continue
                if not lead:  # tracks: the stretch inside their own pads only needs the lead spacing
                    req_lead = required_clearance(project, va, vb, s, True)
                    ea, eb = exposed(i), exposed(j)
                    d_exp = ea.distance(eb) if not (ea.is_empty or eb.is_empty) else float("inf")
                    if d_exp >= req - 1e-3 and d >= req_lead - 1e-3:
                        continue
                    if d_exp >= req - 1e-3:
                        req, lead = req_lead, True
                key = tuple(sorted((a.node, b.node)))
                if key in seen:
                    continue
                seen.add(key)
                pa, pb = nearest_points(a.geom, b.geom)
                dv = voltage_between(va, vb)
                why = f"{dv:.0f} V between them, IPC-2221B {lead_category(s['category']) if lead else s['category']}"
                if va.mains != vb.mains and not intra:
                    why = f"mains to non-mains copper needs {float(s['mains_clearance']):g} mm"
                la = a.describe() + (f" [{na}]" if na else "")
                lb = b.describe() + (f" [{nb}]" if nb else "")
                msg = f"HV clearance {d:.2f} mm < {req:.2f} mm ({why}) on {layer}: {la} to {lb}"
                if intra:
                    msg += " - pins of the same tube socket: keep these voltages off neighbouring pins"
                out.append(Violation("hv-clearance", msg, (pa.x + pb.x) / 2, (pa.y + pb.y) / 2,
                                     "warning" if intra else "error",
                                     [x.obj.uid for x in (a, b)], tuple(sorted(n for n in (na, nb) if n))))
    return out


# --------------------------------------------------------------------------- track current

def _track_current(project: Project, s: dict) -> list[Violation]:
    out = []
    worst: dict[str, tuple[float, object]] = {}
    for t in project.tracks:
        nv = net_info(project, t.net)
        if nv.amps <= 0:
            continue
        if t.net not in worst or t.width < worst[t.net][0]:
            worst[t.net] = (t.width, t)
    for net, (w, t) in sorted(worst.items()):
        nv = net_info(project, net)
        external = t.layer in ("F.Cu", "B.Cu")
        need = track_width_for(nv.amps, s["rise"], s["copper_oz"], external)
        if w < need - 1e-3:
            out.append(Violation("current", f"Net {net} carries {nv.amps:g} A: tracks need {need:.2f} mm on "
                                            f"{'outer' if external else 'inner'} layers ({s['copper_oz']:g} oz, "
                                            f"{s['rise']:g} degC rise, IPC-2221) but one is {w:.2f} mm",
                                 (t.x1 + t.x2) / 2, (t.y1 + t.y2) / 2, "error", [t.uid], (net,)))
    return out


# --------------------------------------------------------------------------- part ratings

def _two_pad_nets(c) -> tuple[str | None, str | None] | None:
    pads = [p for p in c.footprint.pads if p.number in ("1", "2") and p.kind != "npth"]
    if {p.number for p in pads} != {"1", "2"}:
        return None
    return c.pad_nets.get("1") or None, c.pad_nets.get("2") or None


def _capacitors(project: Project) -> list[Violation]:
    out = []
    for c in project.components:
        if not c.ref.upper().startswith("C") or c.ref.upper().startswith("CN"):
            continue
        nets = _two_pad_nets(c)
        if nets is None:
            continue
        v1, v2 = _nv(project, nets[0]), _nv(project, nets[1])
        if not (v1.known or v2.known):
            continue
        across = voltage_between(v1, v2)
        rating = parse_voltage(c.value)
        if across >= 50 and rating is None:
            out.append(Violation("part-rating", f"{c.ref} ({c.value}) sees up to {across:.0f} V but its value has no "
                                                "voltage rating - write it in the value, e.g. '22uF 450V'", c.x, c.y,
                                 "warning", [c.uid]))
        elif rating is not None and across > rating + 1e-6:
            out.append(Violation("part-rating", f"{c.ref} is rated {rating:g} V but sees up to {across:.0f} V", c.x,
                                 c.y, "error", [c.uid]))
        elif rating is not None and across > 0.9 * rating and across >= 50:
            out.append(Violation("part-rating", f"{c.ref} runs at {across / rating:.0%} of its {rating:g} V rating "
                                                "(leave at least 10 % margin, more for B+ at switch-on)", c.x, c.y,
                                 "warning", [c.uid]))
        polar = c.footprint.name.upper().startswith("CP") or "ELECTROLYTIC" in c.footprint.description.upper()
        if polar and v1.known and v2.known and v1.ac == 0 and v2.ac == 0 and v1.dc < v2.dc - 0.5:
            out.append(Violation("part-rating", f"{c.ref} is an electrolytic with its + (pin 1) at {v1.dc:g} V and - "
                                                f"at {v2.dc:g} V: it is in backwards", c.x, c.y, "error", [c.uid]))
    return out


_CHIP_R = {"0201": (0.05, 25), "0402": (0.0625, 50), "0603": (0.1, 75), "0805": (0.125, 150), "1206": (0.25, 200),
           "1210": (0.5, 200), "2010": (0.75, 200), "2512": (1.0, 200)}


def resistor_rating(fp) -> tuple[float, float] | None:
    """(watts, max working volts) of a resistor footprint, or None if unknown."""
    m = re.search(r"R_(\d{4})", fp.name)
    if m and m.group(1) in _CHIP_R:
        return _CHIP_R[m.group(1)]
    text = f"{fp.name} {fp.description}"
    m = re.search(r"(\d+)\s*/\s*(\d+)\s*W", text)
    if m:
        w = int(m.group(1)) / int(m.group(2))
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s*W\b", text)
        if not m:
            return None
        w = float(m.group(1))
    if "cement" in text.lower() or "wirewound" in text.lower() or "Power" in fp.name:
        return w, 750.0
    volts = 150.0 if w < 0.2 else 250.0 if w < 0.4 else 350.0 if w < 0.9 else 500.0 if w < 2.5 else 750.0
    return w, volts


def _resistors(project: Project) -> list[Violation]:
    out = []
    for c in project.components:
        if not re.match(r"^R\d", c.ref.upper()):
            continue
        nets = _two_pad_nets(c)
        if nets is None:
            continue
        v1, v2 = _nv(project, nets[0]), _nv(project, nets[1])
        if not (v1.known and v2.known):
            continue
        ohms = parse_value(c.value)
        rating = resistor_rating(c.footprint)
        if not ohms or rating is None:
            continue
        dv = abs(v1.dc - v2.dc) + (abs(v1.ac - v2.ac) / math.sqrt(2) if (v1.ac or v2.ac) else 0.0)
        p = dv * dv / ohms
        watts, vmax = rating
        if p > watts:
            out.append(Violation("part-rating", f"{c.ref} ({c.value}) dissipates {fmt_eng(p, 'W')} "
                                                f"({dv:.0f} V across it) but its footprint is a {watts:g} W part",
                                 c.x, c.y, "error", [c.uid]))
        elif p > watts / 2:
            out.append(Violation("part-rating", f"{c.ref} ({c.value}) dissipates {fmt_eng(p, 'W')}: more than half "
                                                f"its {watts:g} W rating - use the next size up so it runs cool",
                                 c.x, c.y, "warning", [c.uid]))
        if dv > vmax:
            out.append(Violation("part-rating", f"{c.ref} has {dv:.0f} V across it; a {watts:g} W resistor is rated "
                                                f"about {vmax:g} V - use a larger or high-voltage part", c.x, c.y,
                                 "warning", [c.uid]))
    return out


# --------------------------------------------------------------------------- bleeders

def _bleeders(project: Project) -> list[Violation]:
    """Big caps on HV nets must discharge through resistors to ground (directly or through other resistors)."""
    parent: dict[str, str] = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for c in project.components:
        if re.match(r"^(R|RV|VR|L)\d", c.ref.upper()):
            nets = sorted({n for n in c.pad_nets.values() if n})
        elif all(c.pad_nets.get(k) for k in ("CHK1", "CHK2")):  # pads for an off-board filter choke
            nets = sorted({c.pad_nets["CHK1"], c.pad_nets["CHK2"]})
        else:
            continue
        for n in nets[1:]:
            parent[find(n)] = find(nets[0])
    grounded = {find(n) for n in list(parent) if is_ground(n)}
    out, done = [], set()
    for c in project.components:
        if not c.ref.upper().startswith("C"):
            continue
        nets = _two_pad_nets(c)
        if nets is None:
            continue
        farads = parse_value(c.value)
        if not farads or farads < 1e-6:
            continue
        for net in nets:
            nv = _nv(project, net)
            if not net or is_ground(net) or nv.peak < 60 or net in done:
                continue
            if find(net) not in grounded:
                done.add(net)
                out.append(Violation("bleeder", f"{c.ref} ({c.value}) on {net} ({nv.describe()}) has no resistive path "
                                                "to ground: add a bleeder (e.g. 220k 2 W from the first filter node "
                                                "to ground) so the caps discharge after switch-off", c.x, c.y,
                                     "warning", [c.uid], (net,)))
    return out


# --------------------------------------------------------------------------- tubes

def _tubes(project: Project) -> list[Violation]:
    out = []
    for c in project.components:
        if c.footprint.model.get("type") != "tube":
            continue
        t = find_tube(c.value)
        if t is None:
            continue
        if t.base != c.footprint.model.get("base"):
            out.append(Violation("tube", f"{c.ref}: a {t.name} needs a {t.base} socket, this footprint is a "
                                         f"{c.footprint.model.get('base')} socket", c.x, c.y, "error", [c.uid]))
            continue
        for pin, fn in t.pins.items():
            net = c.pad_nets.get(pin)
            if fn == "NC" and net:
                out.append(Violation("tube", f"{c.ref} pin {pin} of a {t.name} is not connected inside the tube (or "
                                             f"internally connected) - don't use it as a tie point for {net}",
                                     c.x, c.y, "warning", [c.uid], (net,)))
        hp = t.heater_pins
        hn = [c.pad_nets.get(p) for p in hp]
        if hp and not all(hn):
            out.append(Violation("tube", f"{c.ref} ({t.name}): heater pins {', '.join(hp)} are not all wired", c.x,
                                 c.y, "warning", [c.uid]))
        ct = t.heater_ct
        if ct and all(hn) and c.pad_nets.get(ct):
            if hn[0] != hn[1]:
                out.append(Violation("tube", f"{c.ref} ({t.name}): for 6.3 V tie pins {hp[0]} and {hp[1]} together "
                                             f"and feed pin {ct}; for 12.6 V feed {hp[0]} and {hp[1]} and leave {ct} "
                                             "open", c.x, c.y, "error", [c.uid]))
        elif len(hn) == 2 and all(hn) and hn[0] == hn[1] and not ct:
            out.append(Violation("tube", f"{c.ref} ({t.name}): both heater pins are on {hn[0]} - the heater is "
                                         "shorted", c.x, c.y, "error", [c.uid]))
        for fn in ("PA", "PB", "A", "A1", "A2"):
            pin = t.pin(fn)
            if pin is None or t.kind == "rectifier":
                continue
            nv = _nv(project, c.pad_nets.get(pin))
            if nv.known and nv.dc > t.va_max:
                out.append(Violation("tube", f"{c.ref} ({t.name}) plate (pin {pin}) at {nv.dc:g} V is above the "
                                             f"{t.va_max:g} V design maximum", c.x, c.y, "warning", [c.uid]))
    return out
