"""Core PCB data model: board, components, tracks, vias, zones, text, rules."""
from __future__ import annotations

import copy
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable

from shapely.geometry import Polygon

from .geometry import rounded_rect_points, transform_geom, transform_point

FILE_VERSION = 1

COPPER_LAYERS = {2: ["F.Cu", "B.Cu"], 4: ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]}
SILK_LAYERS = ["F.SilkS", "B.SilkS"]

MASK_COLORS = ["Green", "Red", "Blue", "Black", "White", "Purple", "Yellow"]
SILK_COLORS = ["White", "Black"]
FINISHES = ["HASL (lead-free)", "HASL", "ENIG", "OSP"]


def new_uid() -> str:
    return uuid.uuid4().hex[:12]


# --------------------------------------------------------------------------- footprints

@dataclass
class Pad:
    number: str
    x: float
    y: float
    w: float
    h: float
    shape: str = "rect"  # rect | roundrect | circle | oval
    kind: str = "smd"  # smd | tht | npth
    drill: float = 0.0
    rotation: float = 0.0
    roundness: float = 0.25
    paste: bool = True
    mask_margin: float | None = None  # overrides the global solder mask expansion
    drill_h: float = 0.0  # slot: drill is the X size, drill_h the Y size (0 = round hole)
    points: list | None = None  # custom polygon pad outline, relative to the pad centre

    @property
    def plated(self) -> bool:
        return self.kind == "tht"

    @property
    def has_hole(self) -> bool:
        return self.kind in ("tht", "npth") and self.drill > 0

    @property
    def is_slot(self) -> bool:
        return self.drill_h > 0 and abs(self.drill_h - self.drill) > 1e-6

    @property
    def min_drill(self) -> float:
        return min(self.drill, self.drill_h) if self.is_slot else self.drill

    @classmethod
    def from_dict(cls, d: dict) -> "Pad":
        d = dict(d)
        if d.get("points"):
            d["points"] = [tuple(p) for p in d["points"]]
        return cls(**d)


@dataclass
class Graphic:
    """Footprint artwork in local coordinates.

    kind: line (pts=[a, b]) | circle (pts=[c], r) | arc (pts=[c], r, start, sweep) | poly (pts)
    layer: silk | fab | crtyd
    """

    kind: str
    pts: list
    width: float = 0.12
    layer: str = "silk"
    r: float = 0.0
    start: float = 0.0
    sweep: float = 0.0
    fill: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "Graphic":
        d = dict(d)
        d["pts"] = [tuple(p) for p in d.get("pts", [])]
        return cls(**d)


@dataclass
class Footprint:
    name: str
    description: str = ""
    pads: list[Pad] = field(default_factory=list)
    graphics: list[Graphic] = field(default_factory=list)
    courtyard: tuple = (-1.0, -1.0, 1.0, 1.0)  # local bbox x0, y0, x1, y1
    model: dict = field(default_factory=dict)  # procedural 3D body description
    ref_pos: tuple = (0.0, -1.5)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "pads": [asdict(p) for p in self.pads],
            "graphics": [asdict(g) for g in self.graphics],
            "courtyard": list(self.courtyard),
            "model": copy.deepcopy(self.model),
            "ref_pos": list(self.ref_pos),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Footprint":
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            pads=[Pad.from_dict(p) for p in d.get("pads", [])],
            graphics=[Graphic.from_dict(g) for g in d.get("graphics", [])],
            courtyard=tuple(d.get("courtyard", (-1, -1, 1, 1))),
            model=d.get("model", {}),
            ref_pos=tuple(d.get("ref_pos", (0, -1.5))),
        )

    def pad_numbers(self) -> list[str]:
        seen, out = set(), []
        for p in self.pads:
            if p.number and p.number not in seen:
                seen.add(p.number)
                out.append(p.number)
        return out


# --------------------------------------------------------------------------- board items

@dataclass(eq=False)
class Component:
    ref: str
    value: str
    footprint: Footprint
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    side: str = "top"  # top | bottom
    pad_nets: dict = field(default_factory=dict)  # pad number -> net name
    locked: bool = False
    mpn: str = ""
    lcsc: str = ""
    show_ref: bool = True
    uid: str = field(default_factory=new_uid)
    show_value: bool = False  # print the value on the silkscreen (kit-style boards)

    @property
    def mirror(self) -> bool:
        return self.side == "bottom"

    def to_board(self, lx: float, ly: float) -> tuple[float, float]:
        return transform_point(lx, ly, self.x, self.y, self.rotation, self.mirror)

    def geom_to_board(self, g):
        return transform_geom(g, self.x, self.y, self.rotation, self.mirror)

    def pad_pos(self, pad: Pad) -> tuple[float, float]:
        return self.to_board(pad.x, pad.y)

    def pad_net(self, pad: Pad) -> str | None:
        return self.pad_nets.get(pad.number) or None

    def pad_copper_layers(self, pad: Pad, copper_layers: list[str]) -> list[str]:
        if pad.kind == "smd":
            return ["F.Cu" if self.side == "top" else "B.Cu"]
        if pad.kind == "tht":
            return list(copper_layers)
        return []

    def pad_rotation(self, pad: Pad) -> float:
        """Absolute rotation of a pad on the board (as displayed)."""
        return (self.rotation + (-pad.rotation if self.mirror else pad.rotation)) % 360

    def courtyard_polygon(self) -> Polygon:
        x0, y0, x1, y1 = self.footprint.courtyard
        return self.geom_to_board(Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)]))

    @property
    def silk_layer(self) -> str:
        return "F.SilkS" if self.side == "top" else "B.SilkS"

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "ref": self.ref,
            "value": self.value,
            "footprint": self.footprint.to_dict(),
            "x": self.x,
            "y": self.y,
            "rotation": self.rotation,
            "side": self.side,
            "pad_nets": dict(self.pad_nets),
            "locked": self.locked,
            "mpn": self.mpn,
            "lcsc": self.lcsc,
            "show_ref": self.show_ref,
            "show_value": self.show_value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Component":
        d = dict(d)
        d["footprint"] = Footprint.from_dict(d["footprint"])
        return cls(**d)


@dataclass(eq=False)
class Track:
    x1: float
    y1: float
    x2: float
    y2: float
    width: float = 0.25
    layer: str = "F.Cu"
    net: str | None = None
    uid: str = field(default_factory=new_uid)

    def length(self) -> float:
        return ((self.x2 - self.x1) ** 2 + (self.y2 - self.y1) ** 2) ** 0.5


@dataclass(eq=False)
class Via:
    x: float
    y: float
    diameter: float = 0.6
    drill: float = 0.3
    net: str | None = None
    uid: str = field(default_factory=new_uid)


@dataclass(eq=False)
class Zone:
    layer: str
    net: str | None
    outline: list
    clearance: float = 0.3
    min_width: float = 0.25
    priority: int = 0
    thermal: bool = True
    thermal_gap: float = 0.4
    spoke_width: float = 0.45
    keep_islands: bool = False
    uid: str = field(default_factory=new_uid)

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        d["outline"] = [tuple(p) for p in d["outline"]]
        return cls(**d)


@dataclass(eq=False)
class Text:
    text: str
    x: float
    y: float
    size: float = 1.2  # cap height in mm
    layer: str = "F.SilkS"
    rotation: float = 0.0
    uid: str = field(default_factory=new_uid)

    @property
    def mirrored(self) -> bool:
        return self.layer.startswith("B.")


@dataclass
class NetClass:
    name: str
    clearance: float = 0.2
    track_width: float = 0.25
    via_diameter: float = 0.6
    via_drill: float = 0.3


@dataclass
class DesignRules:
    clearance: float = 0.2
    track_width: float = 0.25
    via_diameter: float = 0.6
    via_drill: float = 0.3
    min_track: float = 0.15
    min_drill: float = 0.3
    min_annular: float = 0.13
    edge_clearance: float = 0.3
    hole_to_hole: float = 0.25
    mask_expansion: float = 0.05
    tent_vias: bool = True


@dataclass
class Board:
    outline: list = field(default_factory=lambda: rounded_rect_points(0, 0, 50, 40, 1.0))
    cutouts: list = field(default_factory=list)
    thickness: float = 1.6
    layers: int = 2
    mask_color: str = "Green"
    silk_color: str = "White"
    finish: str = "HASL (lead-free)"
    copper_oz: float = 1.0

    def polygon(self) -> Polygon:
        if len(self.outline) < 3:
            return Polygon()
        poly = Polygon(self.outline).buffer(0)
        for c in self.cutouts:
            if len(c) >= 3:
                poly = poly.difference(Polygon(c).buffer(0))
        return poly

    def bounds(self) -> tuple[float, float, float, float]:
        if not self.outline:
            return (0, 0, 0, 0)
        xs = [p[0] for p in self.outline]
        ys = [p[1] for p in self.outline]
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def width(self) -> float:
        b = self.bounds()
        return b[2] - b[0]

    @property
    def height(self) -> float:
        b = self.bounds()
        return b[3] - b[1]

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        d["outline"] = [tuple(p) for p in d.get("outline", [])]
        d["cutouts"] = [[tuple(p) for p in c] for c in d.get("cutouts", [])]
        return cls(**d)


# --------------------------------------------------------------------------- project

class Project:
    """A complete PCB design."""

    def __init__(self, name: str = "Untitled"):
        self.name = name
        self.author = ""
        self.revision = "A"
        self.notes = ""
        self.board = Board()
        self.components: list[Component] = []
        self.tracks: list[Track] = []
        self.vias: list[Via] = []
        self.zones: list[Zone] = []
        self.texts: list[Text] = []
        self.extra_nets: list[str] = []
        self.netclasses: dict[str, NetClass] = {"Default": NetClass("Default")}
        self.net_class_map: dict[str, str] = {}
        self.rules = DesignRules()
        self.order: dict = {}
        self.pedal: dict = {}  # guitar-pedal data: enclosure, panel holes (see pcbpro.pedal)
        self.sim: dict = {}  # simulation settings: sources, part model overrides, MCU firmware (see pcbpro.sim)
        self.amp: dict = {}  # amplifier data: net voltages / currents, HV rule settings (see pcbpro.amp)
        # runtime state (not serialised)
        self.rev = 0
        self._cache: dict[str, Any] = {}
        self._cache_rev = -1
        self.zone_fills: dict[str, Any] = {}
        self.fills_rev = -1

    # ------------------------------------------------------------------ caching
    def touch(self) -> None:
        self.rev += 1

    def cached(self, key: str, fn: Callable[[], Any]) -> Any:
        if self._cache_rev != self.rev:
            self._cache.clear()
            self._cache_rev = self.rev
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    @property
    def fills_stale(self) -> bool:
        return bool(self.zones) and self.fills_rev != self.rev

    # ------------------------------------------------------------------ queries
    @property
    def copper_layers(self) -> list[str]:
        return COPPER_LAYERS.get(self.board.layers, COPPER_LAYERS[2])

    def all_items(self) -> Iterable[Any]:
        yield from self.components
        yield from self.tracks
        yield from self.vias
        yield from self.zones
        yield from self.texts

    def find(self, uid: str):
        for it in self.all_items():
            if it.uid == uid:
                return it
        return None

    def component(self, ref: str) -> Component | None:
        for c in self.components:
            if c.ref == ref:
                return c
        return None

    def nets(self) -> list[str]:
        names: set[str] = set(self.extra_nets)
        for c in self.components:
            names.update(n for n in c.pad_nets.values() if n)
        for it in (*self.tracks, *self.vias, *self.zones):
            if it.net:
                names.add(it.net)
        return sorted(names, key=natural_key)

    def netclass_for(self, net: str | None) -> NetClass:
        if net and net in self.net_class_map:
            nc = self.netclasses.get(self.net_class_map[net])
            if nc:
                return nc
        nc = self.netclasses.get("Default")
        if nc is None:
            r = self.rules
            nc = NetClass("Default", r.clearance, r.track_width, r.via_diameter, r.via_drill)
        return nc

    def next_ref(self, prefix: str) -> str:
        used = set()
        for c in self.components:
            m = re.fullmatch(re.escape(prefix) + r"(\d+)", c.ref)
            if m:
                used.add(int(m.group(1)))
        n = 1
        while n in used:
            n += 1
        return f"{prefix}{n}"

    def next_net_name(self, prefix: str = "N$") -> str:
        existing = set(self.nets())
        n = 1
        while f"{prefix}{n}" in existing:
            n += 1
        return f"{prefix}{n}"

    def rename_net(self, old: str, new: str | None) -> None:
        for c in self.components:
            for k, v in list(c.pad_nets.items()):
                if v == old:
                    if new:
                        c.pad_nets[k] = new
                    else:
                        del c.pad_nets[k]
        for it in (*self.tracks, *self.vias, *self.zones):
            if it.net == old:
                it.net = new
        if old in self.extra_nets:
            self.extra_nets.remove(old)
            if new and new not in self.extra_nets:
                self.extra_nets.append(new)
        if old in self.net_class_map:
            cls = self.net_class_map.pop(old)
            if new:
                self.net_class_map[new] = cls

    def remove_items(self, items: Iterable[Any]) -> None:
        ids = {it.uid for it in items}
        self.components = [c for c in self.components if c.uid not in ids]
        self.tracks = [t for t in self.tracks if t.uid not in ids]
        self.vias = [v for v in self.vias if v.uid not in ids]
        self.zones = [z for z in self.zones if z.uid not in ids]
        self.texts = [t for t in self.texts if t.uid not in ids]
        for uid in ids:
            self.zone_fills.pop(uid, None)

    # ------------------------------------------------------------------ serialisation
    def to_dict(self) -> dict:
        return {
            "format": "pcbpro",
            "version": FILE_VERSION,
            "name": self.name,
            "author": self.author,
            "revision": self.revision,
            "notes": self.notes,
            "board": asdict(self.board),
            "rules": asdict(self.rules),
            "netclasses": {k: asdict(v) for k, v in self.netclasses.items()},
            "net_class_map": dict(self.net_class_map),
            "extra_nets": list(self.extra_nets),
            "components": [c.to_dict() for c in self.components],
            "tracks": [asdict(t) for t in self.tracks],
            "vias": [asdict(v) for v in self.vias],
            "zones": [asdict(z) for z in self.zones],
            "texts": [asdict(t) for t in self.texts],
            "order": copy.deepcopy(self.order),
            "pedal": copy.deepcopy(self.pedal),
            "sim": copy.deepcopy(self.sim),
            "amp": copy.deepcopy(self.amp),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        if d.get("format") != "pcbpro":
            raise ValueError("Not a PCBPro project file")
        p = cls(d.get("name", "Untitled"))
        p.author = d.get("author", "")
        p.revision = d.get("revision", "A")
        p.notes = d.get("notes", "")
        p.board = Board.from_dict(d.get("board", {}))
        p.rules = DesignRules(**d.get("rules", {}))
        p.netclasses = {k: NetClass(**v) for k, v in d.get("netclasses", {}).items()} or {
            "Default": NetClass("Default")
        }
        p.net_class_map = dict(d.get("net_class_map", {}))
        p.extra_nets = list(d.get("extra_nets", []))
        p.components = [Component.from_dict(c) for c in d.get("components", [])]
        p.tracks = [Track(**t) for t in d.get("tracks", [])]
        p.vias = [Via(**v) for v in d.get("vias", [])]
        p.zones = [Zone.from_dict(z) for z in d.get("zones", [])]
        p.texts = [Text(**t) for t in d.get("texts", [])]
        p.order = d.get("order", {})
        p.pedal = d.get("pedal", {}) or {}
        p.sim = d.get("sim", {}) or {}
        p.amp = d.get("amp", {}) or {}
        return p

    def clone(self) -> "Project":
        p = Project.from_dict(self.to_dict())
        p.zone_fills = dict(self.zone_fills)
        p.fills_rev = p.rev if not self.fills_stale else -1
        return p


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s or "")]
