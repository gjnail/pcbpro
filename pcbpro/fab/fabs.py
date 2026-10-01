"""PCB fabrication houses: capabilities, DFM checks and price estimation.

Prices are *estimates* derived from publicly advertised pricing structures and change
frequently. The final price is always the one shown on the fab's own quote page.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.strtree import STRtree

from ..export.assembly import is_assembled
from ..model.board import Project
from ..model.connectivity import get_connectivity
from ..model.copper import copper_by_layer, holes
from ..model.drc import pad_annular

PRICING_NOTE = ("Estimates based on each fab's published pricing structure (reviewed 2026). "
                "Prices, promotions, shipping and exchange rates change - confirm on the fab's quote page.")
EUR_USD = 1.08
QUANTITIES = [2, 3, 5, 10, 15, 20, 25, 30, 50, 75, 100, 150, 200, 250, 500, 1000]
THICKNESSES = [0.6, 0.8, 1.0, 1.2, 1.6, 2.0]


@dataclass
class BoardSpec:
    width: float = 0.0
    height: float = 0.0
    layers: int = 2
    min_track: float = 0.0
    min_space: float = 0.0
    min_drill: float = 0.0
    min_annular: float = 0.0
    holes: int = 0
    smd_joints: int = 0
    tht_joints: int = 0
    parts: int = 0
    unique_parts: int = 0
    bottom_parts: int = 0
    unrouted: int = 0

    @property
    def area_cm2(self) -> float:
        return self.width * self.height / 100.0

    @property
    def area_in2(self) -> float:
        return self.width * self.height / 645.16


@dataclass
class OrderOptions:
    quantity: int = 5
    thickness: float = 1.6
    mask_color: str = "Green"
    silk_color: str = "White"
    finish: str = "HASL (lead-free)"
    copper_oz: float = 1.0
    assembly: bool = False
    stencil: bool = False
    express: bool = False

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "OrderOptions":
        o = cls()
        for k, v in (d or {}).items():
            if hasattr(o, k):
                setattr(o, k, v)
        return o


@dataclass
class Capabilities:
    min_track: float
    min_space: float
    min_drill: float
    min_annular: float
    max_w: float
    max_h: float
    min_w: float
    layers: tuple
    mask_colors: tuple
    finishes: tuple
    thicknesses: tuple
    copper_oz: tuple = (1.0, 2.0)
    assembly: bool = False


@dataclass
class Quote:
    fab: "Fab"
    boards: int
    board_cost: float
    assembly_cost: float
    stencil_cost: float
    shipping: float
    build_days: tuple
    ship_days: tuple
    issues: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def total(self) -> float:
        return self.board_cost + self.assembly_cost + self.stencil_cost + self.shipping

    @property
    def unit(self) -> float:
        return self.total / max(1, self.boards)

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def lead_text(self) -> str:
        lo = self.build_days[0] + self.ship_days[0]
        hi = self.build_days[1] + self.ship_days[1]
        return f"{lo}-{hi} days"


class Fab:
    key = ""
    name = ""
    location = ""
    url = ""
    blurb = ""
    caps: Capabilities

    def check(self, spec: BoardSpec, opts: OrderOptions) -> list[str]:
        c = self.caps
        issues = []
        if spec.layers not in c.layers:
            issues.append(f"{spec.layers}-layer boards not offered")
        if spec.min_track and spec.min_track < c.min_track - 1e-6:
            issues.append(f"Track {spec.min_track:.3f} mm < fab minimum {c.min_track:.3f} mm")
        if spec.min_space and spec.min_space < c.min_space - 1e-6:
            issues.append(f"Clearance {spec.min_space:.3f} mm < fab minimum {c.min_space:.3f} mm")
        if spec.min_drill and spec.min_drill < c.min_drill - 1e-6:
            issues.append(f"Drill {spec.min_drill:.2f} mm < fab minimum {c.min_drill:.2f} mm")
        if spec.min_annular and spec.min_annular < c.min_annular - 1e-6:
            issues.append(f"Annular ring {spec.min_annular:.3f} mm < fab minimum {c.min_annular:.3f} mm")
        big, small = max(spec.width, spec.height), min(spec.width, spec.height)
        if big > max(c.max_w, c.max_h) or small > min(c.max_w, c.max_h):
            issues.append(f"Board larger than {c.max_w:g}x{c.max_h:g} mm")
        if small < c.min_w:
            issues.append(f"Board smaller than {c.min_w:g} mm")
        if opts.mask_color not in c.mask_colors:
            issues.append(f"{opts.mask_color} solder mask not offered")
        if opts.finish not in c.finishes:
            issues.append(f"{opts.finish} finish not offered")
        if opts.thickness not in c.thicknesses:
            issues.append(f"{opts.thickness} mm thickness not offered")
        if opts.copper_oz not in c.copper_oz:
            issues.append(f"{opts.copper_oz:g} oz copper not offered")
        if opts.assembly and not c.assembly:
            issues.append("Assembly service not offered")
        return issues

    def quote(self, spec: BoardSpec, opts: OrderOptions) -> Quote:  # pragma: no cover - abstract
        raise NotImplementedError


# --------------------------------------------------------------------------- fabs

class JLCPCB(Fab):
    key = "jlcpcb"
    name = "JLCPCB"
    location = "Shenzhen, China"
    url = "https://cart.jlcpcb.com/quote"
    blurb = "Very low prototype prices, in-house SMT assembly with a large parts library."
    caps = Capabilities(0.127, 0.127, 0.3, 0.13, 500, 400, 5, (1, 2, 4, 6),
                        ("Green", "Red", "Blue", "Black", "White", "Purple", "Yellow"),
                        ("HASL (lead-free)", "HASL", "ENIG", "OSP"), (0.6, 0.8, 1.0, 1.2, 1.6, 2.0), (1.0, 2.0), True)

    def quote(self, spec, opts):
        q = opts.quantity
        area_total = spec.area_cm2 * q
        small = spec.width <= 100 and spec.height <= 100
        if spec.layers <= 2:
            cost = 2.0 if (small and q <= 10) else 5.0 + area_total * 0.032
        elif spec.layers == 4:
            cost = 7.0 if (small and q <= 10) else 18.0 + area_total * 0.09
        else:
            cost = 45.0 + area_total * 0.2
        notes = []
        if opts.finish == "ENIG":
            cost += 12.0 + area_total * 0.03
            notes.append("ENIG surcharge")
        if opts.mask_color == "Purple":
            cost += 4.0
        if opts.copper_oz >= 2:
            cost += 10.0 + area_total * 0.03
        if opts.thickness not in (1.6,):
            cost += 1.5 if opts.thickness >= 1.0 else 4.0
        asm = stencil = 0.0
        if opts.assembly:
            joints = spec.smd_joints + spec.tht_joints * 3
            asm = 8.0 + 1.5 + joints * q * 0.0017 + spec.unique_parts * 3.0 * 0.5
            if spec.tht_joints:
                asm += 3.5 + spec.tht_joints * q * 0.0173
            notes.append("Assembly: setup + per-joint + est. extended-part fees; parts cost not included")
        if opts.stencil:
            stencil = 7.0
        ship = 16.0 if opts.express else 6.5
        build = (1, 2) if spec.layers <= 2 else (3, 4)
        if opts.assembly:
            build = (build[0] + 2, build[1] + 3)
        return Quote(self, q, cost, asm, stencil, ship, build, (3, 5) if opts.express else (7, 15), notes=notes)


class PCBWay(Fab):
    key = "pcbway"
    name = "PCBWay"
    location = "Shenzhen, China"
    url = "https://www.pcbway.com/orderonline.aspx"
    blurb = "Broad capabilities (flex, rigid-flex, advanced materials) and turnkey assembly."
    caps = Capabilities(0.1, 0.1, 0.2, 0.15, 1200, 500, 5, (1, 2, 4, 6, 8),
                        ("Green", "Red", "Blue", "Black", "White", "Purple", "Yellow"),
                        ("HASL (lead-free)", "HASL", "ENIG", "OSP"), THICKNESSES, (1.0, 2.0), True)

    def quote(self, spec, opts):
        q = opts.quantity
        area_total = spec.area_cm2 * q
        small = spec.width <= 100 and spec.height <= 100
        if spec.layers <= 2:
            cost = 5.0 if (small and q <= 10) else 12.0 + area_total * 0.035
        elif spec.layers == 4:
            cost = 30.0 + area_total * 0.10
        else:
            cost = 80.0 + area_total * 0.22
        notes = []
        if opts.finish == "ENIG":
            cost += 15.0 + area_total * 0.03
        if opts.mask_color not in ("Green",):
            cost += 0.0 if opts.mask_color in ("Red", "Blue", "Black", "White", "Yellow") else 8.0
        if opts.copper_oz >= 2:
            cost += 15.0 + area_total * 0.04
        if opts.thickness not in (1.6,):
            cost += 2.0
        asm = stencil = 0.0
        if opts.assembly:
            joints = spec.smd_joints + spec.tht_joints
            asm = 30.0 + joints * q * 0.01
            notes.append("Assembly: turnkey estimate, parts cost not included")
        if opts.stencil:
            stencil = 15.0
        ship = 24.0 if opts.express else 12.0
        build = (1, 3) if spec.layers <= 2 else (4, 5)
        if opts.assembly:
            build = (build[0] + 3, build[1] + 5)
        return Quote(self, q, cost, asm, stencil, ship, build, (3, 6) if opts.express else (8, 15), notes=notes)


class OSHPark(Fab):
    key = "oshpark"
    name = "OSH Park"
    location = "Oregon, USA"
    url = "https://oshpark.com/"
    blurb = "US-made, purple ENIG boards priced per square inch in sets of three; free US shipping."
    caps = Capabilities(0.152, 0.152, 0.254, 0.102, 406, 406, 6, (2, 4),
                        ("Purple", "Black"), ("ENIG",), (0.8, 1.6), (1.0, 2.0), False)

    def quote(self, spec, opts):
        sets = max(1, math.ceil(opts.quantity / 3))
        boards = sets * 3
        rate = 5.0 if spec.layers <= 2 else 10.0
        cost = rate * spec.area_in2 * sets
        notes = [f"Priced as {sets} set(s) of 3 boards"]
        if opts.copper_oz >= 2 or opts.thickness == 0.8:
            notes.append("2 oz / 0.8 mm ordered as 'After Dark'/'Thin' options (2-layer)")
        if opts.express:
            cost += 89.0
            notes.append("Super Swift service")
        build = (5, 9) if spec.layers <= 2 else (8, 12)
        if opts.express:
            build = (2, 4)
        return Quote(self, boards, cost, 0.0, 0.0, 0.0, build, (3, 7), notes=notes)


class Aisler(Fab):
    key = "aisler"
    name = "AISLER"
    location = "Aachen, Germany"
    url = "https://aisler.net/"
    blurb = "Made in Europe, ENIG green boards in sets of three, stencils and assembly available."
    caps = Capabilities(0.125, 0.125, 0.25, 0.125, 350, 250, 7, (2, 4),
                        ("Green",), ("ENIG",), (1.6,), (1.0,), True)

    def quote(self, spec, opts):
        sets = max(1, math.ceil(opts.quantity / 3))
        boards = sets * 3
        per_set_eur = (6.0 + spec.area_cm2 * 0.36) if spec.layers <= 2 else (10.0 + spec.area_cm2 * 0.9)
        cost = per_set_eur * sets * EUR_USD
        asm = 0.0
        notes = [f"Priced as {sets} set(s) of 3 boards (EUR converted at {EUR_USD})"]
        if opts.assembly:
            asm = (45.0 + (spec.smd_joints + spec.tht_joints) * boards * 0.05) * EUR_USD
            notes.append("Assembly estimate excludes parts")
        stencil = 18.0 * EUR_USD if opts.stencil else 0.0
        ship = 18.0 if opts.express else 8.0
        build = (5, 8) if spec.layers <= 2 else (8, 10)
        return Quote(self, boards, cost, asm, stencil, ship, build, (2, 4) if opts.express else (4, 9), notes=notes)


FABS: list[Fab] = [JLCPCB(), PCBWay(), OSHPark(), Aisler()]


def fab_by_key(key: str) -> Fab | None:
    return next((f for f in FABS if f.key == key), None)


# --------------------------------------------------------------------------- spec extraction

def measure_min_space(project: Project) -> float:
    conn = get_connectivity(project)
    best = math.inf
    for layer, items in copper_by_layer(project).items():
        if len(items) < 2:
            continue
        geoms = [s.geom for s in items]
        tree = STRtree(geoms)
        left, right = tree.query(geoms, predicate="dwithin", distance=0.5)
        for i, j in zip(left.tolist(), right.tolist()):
            if i >= j:
                continue
            a, b = items[i], items[j]
            if a.node == b.node or (a.kind == "pad" and b.kind == "pad" and a.obj is b.obj):
                continue
            na, nb = conn.effective_net(a), conn.effective_net(b)
            if na is not None and na == nb:
                continue
            d = a.geom.distance(b.geom)
            if 0 < d < best:
                best = d
    return 0.0 if best is math.inf else round(best, 4)


def board_spec(project: Project) -> BoardSpec:
    s = BoardSpec()
    s.width = round(project.board.width, 2)
    s.height = round(project.board.height, 2)
    s.layers = project.board.layers
    s.min_track = min((t.width for t in project.tracks), default=0.0)
    s.min_space = measure_min_space(project)
    hl = holes(project)
    s.holes = len(hl)
    s.min_drill = min((h.diameter for h in hl), default=0.0)
    ann = [(v.diameter - v.drill) / 2 for v in project.vias]
    for c in project.components:
        for p in c.footprint.pads:
            if p.kind == "tht":
                ann.append(pad_annular(p))
    s.min_annular = min(ann, default=0.0)
    uniq = set()
    for c in project.components:
        if not is_assembled(c):
            continue
        s.parts += 1
        uniq.add((c.value, c.footprint.name))
        if c.side == "bottom":
            s.bottom_parts += 1
        for p in c.footprint.pads:
            if p.kind == "smd":
                s.smd_joints += 1
            elif p.kind == "tht":
                s.tht_joints += 1
    s.unique_parts = len(uniq)
    s.unrouted = get_connectivity(project).unrouted_count()
    return s


def quote_all(spec: BoardSpec, opts: OrderOptions) -> list[Quote]:
    quotes = []
    for fab in FABS:
        q = fab.quote(spec, opts)
        q.issues = fab.check(spec, opts)
        quotes.append(q)
    quotes.sort(key=lambda q: (not q.ok, q.total))
    return quotes
