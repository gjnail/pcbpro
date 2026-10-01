"""Amp board builder: turns a circuit description (parts with nets, grouped in signal-flow sections) into a placed,
annotated board, ready for routing.

Layout follows how amp boards are built: the tubes stand in a row along the rear edge, the controls and jacks sit on
the front edge with their shafts through the chassis front panel, the circuit of each stage is packed between its
tube and its controls, and the power supply takes the end of the board furthest from the input. Every net gets
its working voltage / current, the HV / mains / heater net classes are applied, and a ground pour goes on the
bottom layer (kept clear of HV copper by the net-class spacing).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import box

from ..model import footprints as fplib
from ..model.board import Board, Component, NetClass, Project, Text, Zone
from ..model.geometry import transform_point
from .hv import apply_hv_netclasses, set_net
from .tubes import TUBES

# Library parts the amp blocks use (by role).
AMP_PARTS = {
    "res": "Resistor axial 1/2 W P12.70",  # 350 V working: plate and decoupling resistors
    "res_small": "Resistor axial 1/4 W P10.16",  # grid / signal-level resistors
    "res1w": "Resistor axial 1 W P15.24",
    "res2w": "Resistor axial 2 W P20.32",
    "res3w": "Resistor axial 3 W P25.40",
    "res5w": "Power resistor 7 W cement L25 (lying)",
    "film_hv": "Film box L18 W7 P15",  # 0.022 - 0.1 uF 630 V coupling caps
    "film": "Film box L13 W5 P10",  # tone and low-voltage film caps
    "film_small": "Film box L7.2 W3.5 P5",
    "ceramic_hv": "Ceramic disc D7.5 W5 P7.5",  # pF caps rated 500 V - 1 kV
    "ceramic": "Ceramic disc D5 W3 P5",
    "elco_lv": "Electrolytic D6.3 P2.5 H11",  # cathode bypass 22-25 uF / 25-50 V
    "elco_63": "Electrolytic D10 P5 H16",  # 100-220 uF / 63 V
    "elco_hv": "Electrolytic D16 P7.5 H25",  # 16-22 uF / 450 V
    "elco_hv33": "Electrolytic D16 P7.5 H31.5",  # 32-33 uF / 450 V
    "elco_hv_big": "Electrolytic D18 P7.5 H35.5",  # 32-47 uF / 450 V
    "elco_8": "Electrolytic D8 P3.5 H11.5",  # 47 uF / 100 V (bias supply)
    "snapin": "Snap-in electrolytic D30 x 40 mm",  # 4700-10000 uF / 50 V reservoirs
    "snapin_25": "Snap-in electrolytic D25 x 40 mm",  # 100 uF / 450-500 V
    "snapin_35": "Snap-in electrolytic D35 x 50 mm",  # 220 uF / 450-500 V
    "res15w": "Power resistor 15 W cement L48 (lying)",
    "trimmer": "Trimmer 3296W multi-turn",
    "do41": "Diode DO-41",
    "do201": "Diode DO-201AD",  # 3 A rectifiers (1N5822 Schottky: DC heater bridge)
    "elco_heater": "Electrolytic D18 P7.5 H35.5",  # 10000 uF / 16 V heater reservoir
    "do35": "Diode DO-35",
    "dip8": "DIP-8 (300 mil)",
    "bridge": "Bridge rectifier KBU (inline)",
    "pot": "Pot 16 mm right-angle (Alps RK163)",
    "jack": '1/4" jack Neutrik NRJ6HF (threaded)',
    "xlr_out": "XLR male Neutrik NC3MAAH (PCB, DI out)",
    "speakon": "speakON NL4MD-H-3 (PCB)",
    "lm3886": "LM3886 (TO-220-11)",
    "hole": "Mounting hole M3",
    "star": "Star ground point (M4, plated)",
}


def amp_part(key: str):
    lp = fplib.find_part(AMP_PARTS.get(key, key))
    if lp is None:
        raise KeyError(f"Library part not found: {AMP_PARTS.get(key, key)}")
    return lp.make()


@dataclass
class P:
    """One part of an amp design."""
    prefix: str
    value: str
    part: str  # AMP_PARTS key or library part name
    nets: dict
    section: str = ""
    role: str = "body"  # body | tube | front (controls / jacks on the front edge) | pads (off-board wiring)
    label: str = ""  # front-panel legend
    fp: object = None  # a ready-made footprint (wire pads) instead of a library part
    show_value: bool = True


@dataclass
class AmpDesign:
    name: str
    sections: list  # left to right
    parts: list
    volts: dict = field(default_factory=dict)  # net -> DC volts to ground
    vac: dict = field(default_factory=dict)  # net -> AC volts rms
    amps: dict = field(default_factory=dict)  # net -> current (A)
    mains: set = field(default_factory=set)
    notes: str = ""
    height: float = 115.0
    min_width: dict = field(default_factory=dict)
    spec: dict = field(default_factory=dict)  # Amp Designer choices, saved with the board so it can be re-opened
    # the off-board output transformer, for the simulator: primary_ohms (plate to plate for push-pull),
    # secondary_ohms, nfb_polarity (+1 = SPK in phase with P1 / P) and power_w
    ot: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- part helpers for circuit descriptions

def R(value, a, b, part="res", sec=""):
    return P("R", value, part, {"1": a, "2": b}, sec)


def C(value, a, b, part="film_hv", sec=""):
    return P("C", value, part, {"1": a, "2": b}, sec)


def CP(value, plus, minus, part="elco_lv", sec=""):
    """Polarised (electrolytic) capacitor: pin 1 is +."""
    return P("C", value, part, {"1": plus, "2": minus}, sec)


def D(value, anode, cathode, part="do41", sec=""):
    return P("D", value, part, {"1": cathode, "2": anode}, sec)


def POT(value, ccw, wiper, cw, label, sec=""):
    return P("RV", value, "pot", {"1": ccw, "2": wiper, "3": cw}, sec, "front", label)


def PADS(labels, nets, use, sec="", pitch=5.08):
    from ..library.gen_amp import amp_wire_pads
    fp = amp_wire_pads(labels, use, pitch)
    return P("W", "/".join(labels), "", dict(zip(labels, nets)), sec, "pads", fp=fp, show_value=False)


def TUBE(name, nets: dict, heater=("HTR1", "HTR2"), sec=""):
    """A tube on its socket; ``nets`` maps function codes (see amp.tubes) to nets, ``heater`` the two heater wires.

    Heater-centre-tapped twin triodes are wired for 6.3 V: pins 4 + 5 to the first wire, pin 9 to the second."""
    from ..library.gen_amp import tube_part_name
    t = TUBES[name]
    pads: dict = {}
    hp = [p for p, f in t.pins.items() if f == "H"]
    for pin, fn in t.pins.items():
        if fn in nets:
            pads[pin] = nets[fn]
    if heater:
        if t.heater_ct and len(hp) == 2:
            pads[hp[0]] = pads[hp[1]] = heater[0]
            pads[t.heater_ct] = heater[1]
        elif len(hp) == 2:
            pads[hp[0]], pads[hp[1]] = heater
    return P("V", name, tube_part_name(name), pads, sec, "tube")


# --------------------------------------------------------------------------- placement

AMP_RULES = dict(clearance=0.3, track_width=0.6, min_track=0.3, edge_clearance=0.8, via_diameter=1.2, via_drill=0.6,
                 min_annular=0.2)


def amp_rules(p: Project) -> None:
    r = p.rules
    for k, v in AMP_RULES.items():
        setattr(r, k, v)
    p.netclasses["Default"] = NetClass("Default", r.clearance, r.track_width, r.via_diameter, r.via_drill)


def _make(p: Project, spec: P) -> Component:
    fp = spec.fp if spec.fp is not None else amp_part(spec.part)
    c = Component(p.next_ref(spec.prefix), spec.value, fp, 0.0, 0.0, 0.0, "top", dict(spec.nets))
    c.show_value = spec.show_value and spec.role not in ("tube", "pads")
    if spec.role == "pads":
        c.show_ref = False
    return c


def _bounds(c: Component, rotation: float) -> tuple[float, float, float, float]:
    c.rotation, c.x, c.y = rotation, 0.0, 0.0
    return c.courtyard_polygon().bounds


def _front_rotation(c: Component) -> tuple[float, float]:
    """Rotation that points a front-panel part's shaft / nose at the front (+Y) edge, and the Y offset of its
    panel face from the part origin after that rotation."""
    fr = c.footprint.model.get("front") or {"dir": 270.0, "at": c.footprint.courtyard[3]}
    rot = (270.0 - float(fr["dir"])) % 360.0
    at = float(fr["at"])
    px, py = (at, 0.0) if fr["dir"] in (0.0, 180.0) else (0.0, at)
    _, fy = transform_point(px, py, 0.0, 0.0, rot, False)
    return rot, fy


def build_amp(design: AmpDesign, route: bool = False, progress=None, attempts: int = 3,
              cancelled=None) -> tuple[Project, list[str]]:
    """Place a design on a new board (and route it). Returns (project, notes).

    When routing leaves connections open, the sections are widened a little and the board is placed and routed
    again (up to ``attempts`` times); the best attempt is kept."""
    widths = {s: design.min_width.get(s, 0.0) for s in design.sections}
    best = None
    for attempt in range(max(1, attempts if route else 1)):
        notes: list[str] = []
        for _ in range(14):
            p, unplaced = _place(design, widths)
            if not unplaced:
                break
            for sec in unplaced:
                widths[sec] = widths.get(sec, 0.0) * 1.12 + 6.0
        else:
            notes.append("Some parts did not fit; they are left at the board origin - drag them into place.")
        notes += [f"Net class {nc.name}: clearance {nc.clearance:g} mm, track {nc.track_width:g} mm"
                  for nc in p.netclasses.values() if nc.name != "Default"]
        if not route:
            return p, notes
        from ..model.copper import fill_all_zones
        from ..route.autorouter import Autorouter

        def report(a, b, msg, attempt=attempt):
            if progress is not None:
                progress(a, b, msg if attempt == 0 else f"{msg} (attempt {attempt + 1}, more room)")
        res = Autorouter(p, progress=report, cancelled=cancelled).run()
        fill_all_zones(p)
        if res.failed:
            notes.append(f"{res.failed} connection(s) left unrouted: {', '.join(res.failed_nets[:8])}")
        if best is None or res.failed < best[2]:
            best = (p, notes, res.failed)
        if not res.failed or res.cancelled:
            break
        widths = {s: w * 1.1 for s, w in widths.items()}  # _place recorded the widths it used: add room, retry
    return best[0], best[1]
def _annotate(p: Project, d: AmpDesign) -> None:
    p.amp = {"design": d.name, "copper_oz": p.board.copper_oz}
    if d.spec:
        p.amp["spec"] = dict(d.spec)
    if d.ot:
        p.amp["ot"] = dict(d.ot)
    for net in set(d.volts) | set(d.vac) | set(d.amps) | set(d.mains):
        set_net(p, net, v=d.volts.get(net), ac_rms=d.vac.get(net), amps=d.amps.get(net), mains=net in d.mains or None)


def _clearance_of(p: Project, c: Component) -> float:
    """The spacing a part needs around it: the largest net-class clearance among its nets."""
    nets = {n for n in c.pad_nets.values() if n}
    return max([p.netclass_for(n).clearance for n in nets] + [p.rules.clearance])


def _tube_slot(c: Component) -> tuple[float, tuple, float, bool]:
    """(rotation, rotated courtyard bounds, row width, hot?) of a part in the rear row. Octal sockets turn so their
    saddle runs front to back; a tube's row width covers its glass; power tubes and rectifiers run hot."""
    from .tubes import find_tube
    if c.footprint.model.get("front") and c.footprint.model.get("type") != "tube":
        # a jack on the rear panel (effects loop): turn its nose to the rear edge
        rot = (_front_rotation(c)[0] + 180.0) % 360.0
        b = _bounds(c, rot)
        return rot, b, b[2] - b[0], False
    rot = 90.0 if c.footprint.model.get("saddle") else 0.0
    b = _bounds(c, rot)
    t = find_tube(c.value) if c.footprint.model.get("type") == "tube" else None
    glass = t.shape[0] if t is not None else 0.0
    hot = t is not None and t.kind in ("power", "rectifier")
    return rot, b, max(b[2] - b[0], glass), hot


def _tube_gap(a, b) -> float:
    return 10.0 if (a[3] or b[3]) else 4.0


def _spacing_of(p: Project, c: Component, pair) -> float:
    """Room a part needs around it on an amp board: its net class, or the conductor (B2) spacing its nets need from
    ground copper, whichever is larger (tracks have to pass between parts at that spacing)."""
    cl = _clearance_of(p, c)
    if pair is not None:
        cl = max([cl] + [pair(n, None) for n in {n for n in c.pad_nets.values() if n}])
    return cl


def _text_box(t: Text):
    w = len(t.text) * t.size * 0.72 + 0.6
    h = t.size * 1.4
    return box(t.x - w / 2, t.y - h / 2, t.x + w / 2, t.y + h / 2)


def _pack(p: Project, comps: list[Component], region, step: float = 1.27, gap: float = 1.2) -> list[Component]:
    """Connectivity-driven placement: each part goes to the free spot nearest the pins it connects to (weighted
    towards point-to-point nets), keeping every pair of parts max(own clearance, other's clearance, the IPC spacing
    between their nets, gap) apart, so high-voltage parts get their spacing from the start and the router finds short
    paths. Long parts may turn 90 degrees to fit."""
    from collections import Counter

    from shapely.strtree import STRtree

    from ..pedal.templates import footprint_area
    from .hv import pair_clearance_fn
    board = p.board.polygon()
    area = region.intersection(board.buffer(-1.0, join_style="mitre"))
    if area.is_empty:
        return []
    pair = pair_clearance_fn(p)

    def nets_of(c):
        return frozenset(n for n in c.pad_nets.values() if n)

    def need(cl, nets, o, onets):
        req = max(cl, o, gap)
        if pair is not None:
            for a in nets:
                for b in onets:
                    req = max(req, pair(a, b))
        return req

    pins: dict = {}

    def add_pins(c):
        for pad in c.footprint.pads:
            n = c.pad_nets.get(pad.number)
            if n:
                pins.setdefault(n, []).append(c.pad_pos(pad))

    for c in p.components:
        add_pins(c)
    size = Counter(n for c in list(p.components) + list(comps) for n in c.pad_nets.values() if n)
    obstacles = [(footprint_area(c), _clearance_of(p, c), nets_of(c)) for c in p.components if c.side == "top"]
    obstacles += [(_text_box(t), 0.3, frozenset()) for t in p.texts if t.layer == "F.SilkS"]
    x0, y0, x1, y1 = area.bounds
    grid = [(round(x / step) * step, round(y / step) * step)
            for y in np.arange(y0, y1 + step, step) for x in np.arange(x0, x1 + step, step)]
    gx = np.array([g[0] for g in grid])
    gy = np.array([g[1] for g in grid])

    def footprint_size(c):
        a, b, cc, d = c.footprint.courtyard
        return (cc - a) * (d - b)

    pending = sorted(comps, key=lambda c: -footprint_size(c))
    placed = []
    while pending:
        # big parts first; among the rest, the one most tied to what is already placed
        big = [c for c in pending if footprint_size(c) >= 400.0]  # reservoir caps and the like claim room first
        if big:
            c = big[0]
        else:  # then whatever is most tied to pins already down (a grid stopper to its socket pin), small first
            c = max(pending, key=lambda q: (round(sum(1.0 / max(1, size[n] - 1) for n in nets_of(q) if n in pins
                                                      and n != "GND"), 2), -footprint_size(q)))
        pending.remove(c)
        c.side = "top"
        cl = _clearance_of(p, c)
        nets = nets_of(c)
        reqs = [need(cl, nets, o, on) for _, o, on in obstacles]
        geoms = [g for g, _, _ in obstacles]
        tree = STRtree(geoms) if geoms else None
        reach = max([cl] + reqs) + gap
        wx = wy = wsum = 0.0
        for n in nets:
            if n == "GND" or n not in pins:
                continue
            w = 1.0 / max(1, size[n] - 1) / len(pins[n])
            for px, py in pins[n]:
                wx, wy, wsum = wx + w * px, wy + w * py, wsum + w
        tx, ty = (wx / wsum, wy / wsum) if wsum else (x0, y0)
        order = np.argsort((gx - tx) ** 2 + (gy - ty) ** 2)
        a, b, cc, d = c.footprint.courtyard
        turns = [0.0, 90.0] if max(cc - a, d - b) > 2.2 * min(cc - a, d - b) else [0.0]
        done = False
        for k in order.tolist():
            for rot in turns:
                c.x, c.y, c.rotation = grid[k][0], grid[k][1], rot
                if not area.contains(c.courtyard_polygon()):
                    continue
                fa = footprint_area(c)
                if tree is not None and any(geoms[i].distance(fa) < reqs[i] - 1e-6 for i in
                                            tree.query(fa, predicate="dwithin", distance=reach).tolist()):
                    continue
                done = True
                break
            if done:
                break
        if done:
            p.components.append(c)
            obstacles.append((footprint_area(c), cl, nets))
            placed.append(c)
            add_pins(c)
        else:
            c.rotation = 0.0
    return placed


def _place(d: AmpDesign, widths: dict) -> tuple[Project, list[str]]:
    p = Project(d.name)
    p.notes = d.notes
    amp_rules(p)
    p.board = Board(outline=[(0, 0), (100, 0), (100, d.height), (0, d.height)], layers=2, mask_color="Black",
                    silk_color="White")
    p.board.copper_oz = 2.0
    _annotate(p, d)
    apply_hv_netclasses(p)  # net classes first: placement keeps their spacing
    H = d.height
    margin = 3.0
    corner = 9.5  # keep the tube row and the controls clear of the corner mounting holes
    comps: dict[str, list[tuple[P, Component]]] = {s: [] for s in d.sections}
    for spec in d.parts:
        c = _make(p, spec)
        p.components.append(c)  # reserve the reference
        comps.setdefault(spec.section or d.sections[-1], []).append((spec, c))
    p.components.clear()

    # --- section widths ----------------------------------------------------------------------------------
    from .hv import pair_clearance_fn
    pair = pair_clearance_fn(p)
    sec_w = {}
    for k, s in enumerate(d.sections):
        tw = fw = area = 0.0
        tube_h = front_h = 0.0
        for spec, c in comps.get(s, []):
            cl = _spacing_of(p, c, pair)
            if spec.role == "front":
                rot, _ = _front_rotation(c)
                x0, y0, x1, y1 = _bounds(c, rot)
                fw += (x1 - x0) + 5.0
                front_h = max(front_h, (y1 - y0) + (3.5 if spec.label else 1.5))
            else:
                x0, y0, x1, y1 = _bounds(c, 0.0)
                if spec.role in ("tube", "rear"):
                    rot, b, w, hot = _tube_slot(c)
                    tw += w + (10.0 if hot else 4.0)
                    tube_h = max(tube_h, b[3] - b[1])
                else:
                    area += (x1 - x0 + cl + 1.2) * (y1 - y0 + cl + 2.4)
        ends = corner * ((k == 0) + (k == len(d.sections) - 1))
        body_h = max(25.0, H - 2 * margin - (tube_h + 4.0 if tube_h else 0.0) - front_h - 2.0)
        need = max(tw + ends, fw + ends, area * 1.5 / body_h, 30.0)
        sec_w[s] = max(need, widths.get(s, 0.0))
        widths[s] = sec_w[s]
    W = round(sum(sec_w.values()) + 2 * margin, 1)
    p.board = Board(outline=[(0, 0), (W, 0), (W, H), (0, H)], layers=2, mask_color="Black", silk_color="White")
    p.board.copper_oz = 2.0

    # --- mounting holes ----------------------------------------------------------------------------------
    for x, y in ((4.5, 4.5), (W - 4.5, 4.5), (4.5, H - 4.5), (W - 4.5, H - 4.5)):
        mh = Component(p.next_ref("H"), "M3", amp_part("hole"), x, y, 0.0, "top")
        mh.show_ref = False
        p.components.append(mh)

    unplaced: list[str] = []
    x = margin
    pending = []
    for k, s in enumerate(d.sections):
        w = sec_w[s]
        x0, x1 = x, x + w
        x = x1
        ux0 = x0 + (corner if k == 0 else 0.0)  # usable span for the tube row and the controls
        ux1 = x1 - (corner if k == len(d.sections) - 1 else 0.0)
        items = comps.get(s, [])
        rear = [(spec, c) for spec, c in items if spec.role in ("tube", "rear")]  # the rear-edge row
        tubes = [c for _spec, c in rear]
        fronts = [(spec, c) for spec, c in items if spec.role == "front"]
        rest = [c for spec, c in items if spec.role in ("body", "pads")]
        # tubes along the rear edge, far enough apart for their glass and an air gap round the hot ones
        top_y = margin
        if tubes:
            slots = [_tube_slot(c) for c in tubes]
            total = sum(sl[2] for sl in slots) + sum(_tube_gap(a, b) for a, b in zip(slots, slots[1:]))
            cx = ux0 + (ux1 - ux0 - total) / 2
            row_h = max(sl[1][3] - sl[1][1] for sl in slots)
            for k, ((spec, c), (rot, b, w, hot)) in enumerate(zip(rear, slots)):
                c.rotation = rot
                c.x = round((cx + w / 2 - (b[0] + b[2]) / 2) / 0.635) * 0.635
                c.y = round((margin + 2.0 - b[1]) / 0.635) * 0.635
                if spec.role == "rear" and c.footprint.model.get("front"):  # panel face on the rear edge
                    _r, fy = _front_rotation(c)
                    c.y = round(0.3 + fy, 3)
                    if spec.label:
                        cy1 = c.courtyard_polygon().bounds[3]
                        p.texts.append(Text(spec.label.upper(), round(c.x, 2), round(cy1 + 1.6, 2), 1.2, "F.SilkS"))
                cx += w + (_tube_gap(slots[k], slots[k + 1]) if k + 1 < len(slots) else 0.0)
                p.components.append(c)
            top_y = margin + 2.0 + row_h + 2.0
        # controls and jacks on the front edge
        front_top = H - margin
        if fronts:
            spans = []
            for spec, c in fronts:
                rot, fy = _front_rotation(c)
                spans.append((rot, fy, _bounds(c, rot)))
            total = sum(b[2] - b[0] for _, _, b in spans) + 5.0 * (len(fronts) - 1)
            cx = ux0 + (ux1 - ux0 - total) / 2
            for (spec, c), (rot, fy, b) in zip(fronts, spans):
                c.rotation = rot
                c.x = round((cx - b[0]) / 0.635) * 0.635
                c.y = round(H - 0.3 - fy, 3)
                cx += (b[2] - b[0]) + 5.0
                p.components.append(c)
                cy0 = c.courtyard_polygon().bounds[1]
                front_top = min(front_top, cy0 - 1.0)
                if spec.label:
                    p.texts.append(Text(spec.label.upper(), round(c.x, 2), round(cy0 - 1.6, 2), 1.4, "F.SilkS"))
                    front_top = min(front_top, cy0 - 3.0)
        rest.sort(key=lambda c: -((c.footprint.courtyard[2] - c.footprint.courtyard[0])
                                  * (c.footprint.courtyard[3] - c.footprint.courtyard[1])))
        pending.append((s, rest, box(x0 + 0.5, top_y, x1 - 0.5, front_top)))
    # pack after every tube and control is down, so their spacing is respected from both sides
    for s, rest, region in pending:
        placed = _pack(p, rest, region)
        missing = [c for c in rest if c not in placed]
        if missing:
            unplaced.append(s)
            for c in missing:
                c.x, c.y = 0.0, 0.0
                p.components.append(c)
    # ground pour on the bottom, kept off HV copper by the net-class clearances
    p.zones.append(Zone("B.Cu", "GND", list(p.board.outline), clearance=0.5, min_width=0.4, thermal_gap=0.5,
                        spoke_width=0.6))
    hv = any(v > 60 for v in d.volts.values())
    warn = "DANGER: HIGH VOLTAGE - FILTER CAPS STAY CHARGED" if hv else "PCBPro amp"
    bw = max(len(d.name) * 2.0 * 0.72, len(warn) * 1.4 * 0.72) + 2.0
    tx, ty = _free_spot(p, bw, 10.0)
    p.texts.append(Text(d.name.upper(), tx, ty - 2.5, 2.0, "B.SilkS"))
    p.texts.append(Text(warn, tx, ty + 2.5, 1.4 if hv else 1.2, "B.SilkS"))
    return p, unplaced


def _free_spot(p: Project, w: float, h: float) -> tuple[float, float]:
    """Centre of a w x h area free of through-hole pads and holes (for bottom-side legends), nearest the middle."""
    from shapely.ops import unary_union

    from ..model.copper import pad_geom
    board = p.board.polygon().buffer(-2.0, join_style="mitre")
    blocked = unary_union([pad_geom(c, pad).buffer(1.0) for c in p.components for pad in c.footprint.pads
                           if pad.kind in ("tht", "npth")])
    x0, y0, x1, y1 = board.bounds
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    best = None
    y = y0 + h / 2
    while y <= y1 - h / 2:
        x = x0 + w / 2
        while x <= x1 - w / 2:
            r = box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)
            if board.contains(r) and not r.intersects(blocked):
                dist = (x - cx) ** 2 + (y - cy) ** 2
                if best is None or dist < best[0]:
                    best = (dist, x, y)
            x += 2.0
        y += 2.0
    return (round(best[1], 2), round(best[2], 2)) if best else (round(cx, 2), round(cy, 2))


# --------------------------------------------------------------------------- designs

def champ_5w() -> AmpDesign:
    """Tweed Champ-style 5 W single-ended amp: 12AX7 preamp, 6V6GT output, 5Y3GT rectifier."""
    pre, pwr, psu = "Preamp", "Power", "Supply"
    parts = [
        P("J", "INPUT", "jack", {"T": "IN", "S": "GND"}, pre, "front", "INPUT"),
        POT("A1M", "GND", "V1B_G", "VOL_IN", "VOLUME", pre),
        R("1M", "IN", "GND", "res_small", pre), R("68k", "IN", "V1A_G", "res_small", pre),
        TUBE("12AX7", {"PA": "V1A_P", "GA": "V1A_G", "KA": "V1A_K", "PB": "V1B_P", "GB": "V1B_G", "KB": "V1B_K"},
             sec=pre),
        R("1k5", "V1A_K", "GND", "res_small", pre), CP("25uF 25V", "V1A_K", "GND", "elco_lv", pre),
        R("100k", "B+3", "V1A_P", "res", pre), C("22nF 400V", "V1A_P", "VOL_IN", "film_hv", pre),
        R("1k5", "V1B_K", "GND", "res_small", pre), CP("25uF 25V", "V1B_K", "GND", "elco_lv", pre),
        R("100k", "B+3", "V1B_P", "res", pre), C("22nF 400V", "V1B_P", "V2_GL", "film_hv", pre),
        R("22k", "SPK", "V1B_K", "res_small", pre),  # negative feedback from the speaker
        TUBE("6V6GT", {"A": "V2_P", "G2": "B+2", "G1": "V2_G", "K": "V2_K"}, sec=pwr),
        R("220k", "V2_GL", "GND", "res_small", pwr), R("1k5", "V2_GL", "V2_G", "res_small", pwr),
        R("470R", "V2_K", "GND", "res5w", pwr), CP("25uF 50V", "V2_K", "GND", "elco_lv", pwr),
        PADS(["P", "B+"], ["V2_P", "B+1"], "output transformer primary", pwr, 10.16),
        PADS(["SPK", "COM"], ["SPK", "GND"], "output transformer secondary (8 ohm)", pwr),
        TUBE("5Y3GT", {"A1": "HV1", "A2": "HV2", "H": "FIL", "HK": "B+1"}, heater=None, sec=psu),
        PADS(["HV1", "CT", "HV2"], ["HV1", "GND", "HV2"], "PT HV secondary 325-0-325 VAC", psu, 10.16),
        PADS(["5V1", "5V2"], ["FIL", "B+1"], "PT 5 V rectifier winding", psu, 10.16),
        PADS(["H1", "H2"], ["HTR1", "HTR2"], "PT 6.3 V heater winding", psu),
        CP("16uF 450V", "B+1", "GND", "elco_hv", psu), CP("16uF 450V", "B+2", "GND", "elco_hv", psu),
        CP("16uF 450V", "B+3", "GND", "elco_hv", psu),
        R("10k", "B+1", "B+2", "res1w", psu), R("22k", "B+2", "B+3", "res", psu),
        R("220k", "B+1", "GND", "res2w", psu),  # bleeder
        R("100R", "HTR1", "GND", "res_small", psu), R("100R", "HTR2", "GND", "res_small", psu),  # artificial CT
        P("W", "STAR GND", "star", {"1": "GND"}, psu, show_value=False),
    ]
    return AmpDesign(
        "Tweed Champ 5W SE", [psu, pwr, pre], parts,
        volts={"B+1": 360, "FIL": 360, "B+2": 300, "B+3": 250, "V1A_P": 160, "V1B_P": 160, "V2_P": 350,
               "V2_K": 20, "V1A_K": 1.5, "V1B_K": 1.5},
        vac={"HV1": 325, "HV2": 325, "FIL": 5, "V2_P": 250, "HTR1": 3.2, "HTR2": 3.2, "SPK": 5},
        amps={"B+1": 2.0, "FIL": 2.0, "HTR1": 0.8, "HTR2": 0.8, "V2_P": 0.05, "SPK": 0.8},
        notes="Tweed Champ-style 5 W single-ended amp.\n"
              "Power transformer 325-0-325 VAC / 5 V 2 A / 6.3 V 1 A; output transformer 5k : 8 ohm.\n"
              "Mains fuse, power switch and the transformer primary are wired on the chassis, not on this board.\n"
              "B+1 ~360 V (filter caps and the 5 V winding sit at this voltage!), B+2 ~300 V screen, B+3 ~250 V "
              "preamp. The 220k bleeder discharges the caps in about 20 s - always measure before touching.\n"
              "The 6V6 plate runs above its 315 V data-sheet rating, as in the original Champ.",
        # SPK feeds V1B's cathode, whose grid signal is in phase with the 6V6 plate: SPK in phase with P
        ot={"primary_ohms": 5000, "secondary_ohms": 8, "power_w": 5, "nfb_polarity": 1, "push_pull": False})


def el84_18w() -> AmpDesign:
    """18 W push-pull EL84: two gain stages, cathode follower driving a Marshall-style tone stack, cathodyne PI,
    cathode-biased EL84 pair and an EZ81 rectifier."""
    pre, ts, pi, pwr, psu = "Preamp", "Tone", "PI", "Power", "Supply"
    parts = [
        P("J", "INPUT", "jack", {"T": "IN", "S": "GND"}, pre, "front", "INPUT"),
        R("1M", "IN", "GND", "res_small", pre), R("68k", "IN", "V1A_G", "res_small", pre),
        TUBE("12AX7", {"PA": "V1A_P", "GA": "V1A_G", "KA": "V1A_K", "PB": "V1B_P", "GB": "V1B_G", "KB": "V1B_K"},
             sec=pre),
        R("1k5", "V1A_K", "GND", "res_small", pre), CP("22uF 25V", "V1A_K", "GND", "elco_lv", pre),
        R("100k", "B+4", "V1A_P", "res", pre), C("22nF 630V", "V1A_P", "VOL_IN", "film_hv", pre),
        POT("A1M", "GND", "V1B_G", "VOL_IN", "VOLUME", pre),
        R("820R", "V1B_K", "GND", "res_small", pre), CP("22uF 25V", "V1B_K", "GND", "elco_lv", pre),
        R("100k", "B+4", "V1B_P", "res", pre), R("470k", "V1B_P", "V2A_G", "res", pre),  # DC-coupled follower
        TUBE("12AX7", {"PA": "B+3", "GA": "V2A_G", "KA": "CF_OUT", "PB": "PI_P", "GB": "PI_G", "KB": "PI_K"}, sec=pi),
        R("100k", "CF_OUT", "GND", "res1w", ts),
        C("470pF 500V", "CF_OUT", "TS_T", "ceramic_hv", ts), R("33k", "CF_OUT", "TS_A", "res", ts),
        C("22nF 400V", "TS_A", "TS_B", "film_hv", ts), C("22nF 400V", "TS_A", "TS_M", "film_hv", ts),
        POT("A220K", "TS_B", "TS_OUT", "TS_T", "TREBLE", ts), POT("A1M", "TS_B", "TS_M", "TS_M", "BASS", ts),
        POT("B25K", "TS_M", "GND", "GND", "MIDDLE", ts),
        C("22nF 400V", "TS_OUT", "PI_G", "film_hv", pi), R("1M", "PI_G", "PI_BIAS", "res_small", pi),
        R("1k5", "PI_K", "PI_BIAS", "res_small", pi), R("100k", "PI_BIAS", "GND", "res", pi),
        R("100k", "B+3", "PI_P", "res", pi),
        C("100nF 630V", "PI_P", "V3_GL", "film_hv", pi), C("100nF 630V", "PI_K", "V4_GL", "film_hv", pi),
        TUBE("EL84", {"A": "V3_P", "G2": "V3_S", "G1": "V3_G", "K": "OUT_K"}, sec=pwr),
        TUBE("EL84", {"A": "V4_P", "G2": "V4_S", "G1": "V4_G", "K": "OUT_K"}, sec=pwr),
        R("220k", "V3_GL", "GND", "res_small", pwr), R("1k5", "V3_GL", "V3_G", "res_small", pwr),
        R("220k", "V4_GL", "GND", "res_small", pwr), R("1k5", "V4_GL", "V4_G", "res_small", pwr),
        R("1k", "B+2", "V3_S", "res1w", pwr), R("1k", "B+2", "V4_S", "res1w", pwr),
        R("150R", "OUT_K", "GND", "res5w", pwr), CP("220uF 63V", "OUT_K", "GND", "elco_63", pwr),
        PADS(["P1", "B+", "P2"], ["V3_P", "B+1", "V4_P"], "push-pull OT primary (8k a-a)", pwr, 10.16),
        TUBE("EZ81", {"A1": "HV1", "A2": "HV2", "K": "B+1"}, sec=psu),
        PADS(["HV1", "CT", "HV2"], ["HV1", "GND", "HV2"], "PT HV secondary 260-0-260 VAC", psu, 10.16),
        PADS(["H1", "H2"], ["HTR1", "HTR2"], "PT 6.3 V heater winding (3.5 A)", psu),
        CP("32uF 450V", "B+1", "GND", "elco_hv_big", psu), CP("32uF 450V", "B+2", "GND", "elco_hv_big", psu),
        CP("22uF 450V", "B+3", "GND", "elco_hv", psu), CP("22uF 450V", "B+4", "GND", "elco_hv", psu),
        R("1k", "B+1", "B+2", "res5w", psu), R("10k", "B+2", "B+3", "res1w", psu), R("10k", "B+3", "B+4", "res1w", psu),
        R("220k", "B+1", "GND", "res2w", psu),
        R("100R", "HTR1", "GND", "res_small", psu), R("100R", "HTR2", "GND", "res_small", psu),
        P("W", "STAR GND", "star", {"1": "GND"}, psu, show_value=False),
    ]
    return AmpDesign(
        "EL84 18W Push-Pull", [psu, pwr, pi, ts, pre], parts,
        volts={"B+1": 340, "B+2": 330, "B+3": 300, "B+4": 280, "V3_P": 340, "V4_P": 340, "V3_S": 325, "V4_S": 325,
               "V1A_P": 170, "V1B_P": 180, "V2A_G": 180, "CF_OUT": 182, "TS_A": 182, "PI_P": 160, "PI_K": 122,
               "PI_BIAS": 120, "PI_G": 120, "OUT_K": 11, "V1A_K": 1.5, "V1B_K": 1.2},
        vac={"HV1": 260, "HV2": 260, "V3_P": 240, "V4_P": 240, "HTR1": 3.2, "HTR2": 3.2},
        amps={"HTR1": 3.2, "HTR2": 3.2, "B+1": 0.1, "OUT_K": 0.1},
        notes="18 W EL84 push-pull amp: 12AX7 gain stages, DC-coupled cathode follower into a Marshall-style tone "
              "stack, 12AX7 cathodyne phase inverter, cathode-biased EL84 pair (150R shared), EZ81 rectifier.\n"
              "Power transformer 260-0-260 VAC 120 mA, 6.3 V 3.5 A (EZ81 heater on the same winding); output "
              "transformer 8k a-a to the speaker. Mains wiring stays on the chassis.\n"
              "B+1 ~340 V. Never use EL84 pins 1, 6 or 8 as tie points.", height=120.0,
        ot={"primary_ohms": 8000, "secondary_ohms": 8, "power_w": 18, "push_pull": True})  # no global feedback


def ss_amp(style: str = "bass") -> AmpDesign:
    """LM3886 ~50 W solid-state amp with an op-amp preamp and a passive TMB tone stack.

    style "bass": Fender-Bassman stack values, XLR DI output (impedance balanced) and a speakON output.
    style "guitar": Marshall stack values with a soft-clipping drive stage and a 1/4" speaker jack."""
    bass = style == "bass"
    pre, ts, out, psu = "Preamp", "Tone", "Output", "Supply"
    if bass:
        stack = ("250pF", "56k", "22nF", "22nF", "A250K", "A1M", "B25K")
    else:
        stack = ("470pF", "33k", "22nF", "22nF", "A220K", "A1M", "B25K")
    tsi = "U1A_OUT" if bass else "CLIP"  # the guitar version drives the stack from the diode clipper
    parts = [
        P("J", "INPUT", "jack", {"T": "IN", "S": "GND"}, pre, "front", "INPUT"),
        R("1M", "IN", "GND", "res_small", pre), C("100nF", "IN", "U1_INP", "film", pre),
        R("1M", "U1_INP", "GND", "res_small", pre),
        P("U", "TL072", "dip8", {"1": "U1A_OUT", "2": "U1A_FB", "3": "U1_INP", "4": "V-15", "5": "U1B_INP",
                                 "6": "U1B_FB", "7": "U1B_OUT", "8": "V+15"}, pre),
        R("10k", "U1A_FB", "U1A_GF", "res_small", pre), CP("10uF 25V", "U1A_GF", "GND", "elco_lv", pre),
        R("10k", "U1A_FB", "U1A_RV", "res_small", pre),
        POT("A100K", "U1A_RV", "U1A_OUT", "U1A_OUT", "GAIN", pre),
        C("100pF", "U1A_OUT", "U1A_FB", "ceramic", pre),
        CP("47uF 25V", "V+15", "GND", "elco_lv", pre), CP("47uF 25V", "GND", "V-15", "elco_lv", pre),
        C("100nF", "V+15", "GND", "film_small", pre), C("100nF", "GND", "V-15", "film_small", pre),
        # tone stack (driven by the op-amp: low source impedance as the stack expects)
        C(stack[0], tsi, "TS_T", "ceramic", ts), R(stack[1], tsi, "TS_A", "res_small", ts),
        C(stack[2], "TS_A", "TS_B", "film", ts), C(stack[3], "TS_A", "TS_M", "film", ts),
        POT(stack[4], "TS_B", "TS_OUT", "TS_T", "TREBLE", ts), POT(stack[5], "TS_B", "TS_M", "TS_M", "BASS", ts),
        POT(stack[6], "TS_M", "GND", "GND", "MIDDLE", ts),
        R("1M", "TS_OUT", "GND", "res_small", ts), R("10k", "TS_OUT", "U1B_INP", "res_small", ts),
        R("100k", "U1B_OUT", "U1B_FB", "res_small", ts), R("10k", "U1B_FB", "U1B_GF", "res_small", ts),
        CP("10uF 25V", "U1B_GF", "GND", "elco_lv", ts),
        POT("A10K", "GND", "MASTER", "U1B_OUT", "MASTER", out),
        # LM3886 per the datasheet: gain 21, mute released by 10k to -V, Zobel 2R7 + 100nF
        C("1uF", "MASTER", "U2_INA", "film", out), R("47k", "U2_INA", "GND", "res_small", out),
        R("1k", "U2_INA", "U2_INP", "res_small", out),
        P("U", "LM3886TF", "lm3886", {"1": "V+", "3": "SPK", "4": "V-", "5": "V+", "7": "GND", "8": "MUTE",
                                      "9": "U2_INN", "10": "U2_INP"}, out, "rear"),
        R("20k", "SPK", "U2_INN", "res_small", out), R("1k", "U2_INN", "U2_GF", "res_small", out),
        CP("47uF 25V", "U2_GF", "GND", "elco_lv", out),
        R("10k", "MUTE", "V-", "res_small", out),
        R("2R7", "SPK", "ZOB", "res1w", out), C("100nF", "ZOB", "GND", "film", out),
        CP("220uF 50V", "V+", "GND", "elco_63", out), CP("220uF 50V", "GND", "V-", "elco_63", out),
        C("100nF", "V+", "GND", "film_small", out), C("100nF", "GND", "V-", "film_small", out),
        P("U", "KBU810", "bridge", {"1": "V+", "2": "AC1", "3": "AC2", "4": "V-"}, psu),
        PADS(["AC1", "CT", "AC2"], ["AC1", "GND", "AC2"], "PT secondary 2 x 22 VAC", psu, 7.62),
        CP("10000uF 50V", "V+", "GND", "snapin", psu), CP("10000uF 50V", "GND", "V-", "snapin", psu),
        R("4k7", "V+", "GND", "res1w", psu), R("4k7", "GND", "V-", "res1w", psu),  # bleeders
        R("1k", "V+", "V+15", "res1w", psu), R("1k", "V-15", "V-", "res1w", psu),
        D("1N4744A", "GND", "V+15", "do41", psu), D("1N4744A", "V-15", "GND", "do41", psu),
        P("W", "STAR GND", "star", {"1": "GND"}, psu, show_value=False),
    ]
    if bass:
        parts += [
            P("J", "DI OUT", "xlr_out", {"1": "GND", "2": "DI_H", "3": "DI_C", "G": "GND"}, pre, "front", "DI OUT"),
            C("1uF", "U1A_OUT", "DI_A", "film", pre), R("100k", "DI_A", "GND", "res_small", pre),
            R("100R", "DI_A", "DI_H", "res_small", pre), R("100R", "DI_C", "DI_CG", "res_small", pre),
            C("1uF", "DI_CG", "GND", "film", pre),
            P("J", "SPEAKER", "speakon", {"1+": "SPK", "1-": "GND"}, out, "front", "SPEAKER"),
        ]
    else:
        parts += [
            R("4k7", "U1A_OUT", "CLIP", "res_small", pre),
            D("1N4148", "CLIP", "GND", "do35", pre), D("1N4148", "GND", "CLIP", "do35", pre),
            P("J", "SPEAKER", "jack", {"T": "SPK", "S": "GND"}, out, "front", "SPEAKER"),
        ]
    name = "LM3886 Bass Amp" if bass else "LM3886 Guitar Amp"
    return AmpDesign(
        name, [psu, out, ts, pre], parts,
        volts={"V+": 30, "V-": -30, "V+15": 15, "V-15": -15, "MUTE": -1},
        vac={"AC1": 22, "AC2": 22, "SPK": 20},
        amps={"V+": 2.5, "V-": 2.5, "AC1": 3.0, "AC2": 3.0, "SPK": 3.0, "GND": 3.0},
        notes=f"{name}: TL072 preamp ({'Bassman' if bass else 'Marshall'}-style passive tone stack with a x11 "
              "recovery stage), LM3886TF power amp (~50 W into 4-8 ohm on +/-30 V rails).\n"
              "Transformer 2 x 22 VAC 160 VA. The LM3886TF stands at the rear edge with its tab outward: bolt it to "
              "a heatsink of 1 K/W or better.\n" +("Impedance-balanced DI on the XLR (pin 2 hot), taken before the tone "
                                           "controls." if bass else "Two 1N4148s soft-clip the gain stage."),
        height=105.0)


DESIGNS = {
    "Tweed Champ 5 W single-ended (12AX7 / 6V6GT / 5Y3GT)": champ_5w,
    "EL84 18 W push-pull (12AX7 x2 / EL84 x2 / EZ81)": el84_18w,
    "LM3886 bass amp 50 W (tone stack, XLR DI, speakON)": lambda: ss_amp("bass"),
    "LM3886 guitar amp 50 W (drive, Marshall tone stack)": lambda: ss_amp("guitar"),
    "Plexi crunch 50 W (2 x EL34, made with the Amp Designer)": lambda: _designed(voicing="plexi", power="pp_el34",
                                                                               master=True),
    "Modern high gain 50 W (2 x 6L6GC, effects loop, depth - Amp Designer)": lambda: _designed(voicing="modern",
                                                                                             power="pp_6l6"),
    "Extreme high gain 100 W (5 stages, 4 x 6L6GC, DC heaters - Amp Designer)": lambda: _designed(
        voicing="extreme", power="pp_6l6x4", dc_heaters=True),
}


def _designed(**kw) -> AmpDesign:
    from .designer import AmpSpec, design_amp
    return design_amp(AmpSpec(**kw))[0]

# placed and routed copies shipped in resources/examples (rebuilt by tools/build_examples.py)
AMP_EXAMPLES = {
    "Tweed Champ 5 W single-ended (12AX7 / 6V6GT / 5Y3GT)": "Amp_Tweed_Champ_5W.pcbpro",
    "EL84 18 W push-pull (12AX7 x2 / EL84 x2 / EZ81)": "Amp_EL84_18W_Push-Pull.pcbpro",
    "LM3886 bass amp 50 W (tone stack, XLR DI, speakON)": "Amp_LM3886_Bass_50W.pcbpro",
    "Plexi crunch 50 W (2 x EL34, made with the Amp Designer)": "Amp_Plexi_Crunch_50W.pcbpro",
    "Modern high gain 50 W (2 x 6L6GC, effects loop, depth - Amp Designer)": "Amp_Modern_High_Gain_50W.pcbpro",
    "Extreme high gain 100 W (5 stages, 4 x 6L6GC, DC heaters - Amp Designer)": "Amp_Extreme_High_Gain_100W.pcbpro",
}
