"""Copper geometry: pads, tracks, vias, drill holes and zone (pour) filling."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .board import Component, Pad, Project, Track, Via, Zone
from .geometry import iter_polygons, shape_polygon


# Buffered arcs are polygon chords that sit slightly inside the true offset curve;
# pad zone clearances by this much so fills never undercut the requested clearance.
ARC_MARGIN = 0.01


def _clear(d: float, quad_segs: int) -> float:
    """Buffer distance whose polygon chords stay at least ``d`` away (chords of an n-gon sit cos(pi/4n) inside the
    arc: 0.02 mm at a 1 mm clearance, but 0.07 mm at the 3.5 mm a 700 V amp net needs)."""
    return (d + ARC_MARGIN) / math.cos(math.pi / (4 * quad_segs))


@dataclass(eq=False)
class CopperShape:
    kind: str  # pad | track | via | zone
    obj: Any  # Component, Track, Via or Zone
    pad: Pad | None
    layer: str
    net: str | None
    geom: BaseGeometry
    node: str  # connectivity node id (pads/vias share one node across layers)

    def describe(self) -> str:
        if self.kind == "pad":
            return f"Pad {self.obj.ref}.{self.pad.number or '?'}"
        if self.kind == "track":
            return "Track"
        if self.kind == "via":
            return "Via"
        return "Zone"


@dataclass
class Hole:
    x: float
    y: float
    diameter: float  # round hole diameter, or the smaller slot dimension
    plated: bool
    owner: Any
    pad: Pad | None = None
    length: float = 0.0  # slot length (0 for round holes)
    angle: float = 0.0  # slot direction, degrees CCW on screen (0 = along X)

    @property
    def is_slot(self) -> bool:
        return self.length > self.diameter + 1e-6

    def endpoints(self) -> tuple[tuple[float, float], tuple[float, float]]:
        """Centre line end points of a slot (both equal the centre for round holes)."""
        import math
        half = max(0.0, (self.length - self.diameter) / 2)
        a = math.radians(self.angle)
        dx, dy = half * math.cos(a), -half * math.sin(a)
        return (self.x - dx, self.y - dy), (self.x + dx, self.y + dy)

    def geom(self, extra: float = 0.0, quad_segs: int = 8) -> BaseGeometry:
        r = self.diameter / 2 + extra
        if not self.is_slot:
            return Point(self.x, self.y).buffer(r, quad_segs=quad_segs)
        a, b = self.endpoints()
        return LineString([a, b]).buffer(r, quad_segs=quad_segs)


# --------------------------------------------------------------------------- primitive geometry

def pad_local_polygon(pad: Pad) -> Polygon:
    if pad.shape == "poly" and pad.points and len(pad.points) >= 3:
        g = Polygon(pad.points).buffer(0)
    else:
        g = shape_polygon(pad.shape, pad.w, pad.h, pad.roundness)
    if pad.rotation % 360:
        g = affinity.rotate(g, -pad.rotation, origin=(0, 0))
    return affinity.translate(g, pad.x, pad.y)


def pad_geom(comp: Component, pad: Pad, expand: float = 0.0) -> BaseGeometry:
    g = pad_local_polygon(pad)
    if expand:
        g = g.buffer(expand, quad_segs=4, join_style="round" if pad.shape in ("circle", "oval") else "mitre")
    return comp.geom_to_board(g)


def track_geom(t: Track, extra: float = 0.0) -> BaseGeometry:
    r = t.width / 2 + extra
    if abs(t.x1 - t.x2) < 1e-9 and abs(t.y1 - t.y2) < 1e-9:
        return Point(t.x1, t.y1).buffer(r, quad_segs=6)
    return LineString([(t.x1, t.y1), (t.x2, t.y2)]).buffer(r, quad_segs=6)


def via_geom(v: Via, extra: float = 0.0) -> BaseGeometry:
    return Point(v.x, v.y).buffer(v.diameter / 2 + extra, quad_segs=8)


def holes(project: Project) -> list[Hole]:
    def build():
        out = []
        for c in project.components:
            for pad in c.footprint.pads:
                if pad.has_hole:
                    x, y = c.pad_pos(pad)
                    if pad.is_slot:
                        # slot direction in footprint space, then into board space
                        ang = pad.rotation + (0.0 if pad.drill >= pad.drill_h else 90.0)
                        ang = (c.rotation + (180 - ang if c.mirror else ang)) % 180
                        out.append(Hole(x, y, min(pad.drill, pad.drill_h), pad.plated, c, pad,
                                        max(pad.drill, pad.drill_h), ang))
                    else:
                        out.append(Hole(x, y, pad.drill, pad.plated, c, pad))
        for v in project.vias:
            out.append(Hole(v.x, v.y, v.drill, True, v))
        return out

    return project.cached("holes", build)


# --------------------------------------------------------------------------- collection

def collect_copper(project: Project, include_zones: bool = True) -> list[CopperShape]:
    key = "copper_z" if include_zones else "copper"

    def build():
        layers = project.copper_layers
        shapes: list[CopperShape] = []
        for c in project.components:
            for i, pad in enumerate(c.footprint.pads):
                lays = c.pad_copper_layers(pad, layers)
                if not lays:
                    continue
                g = pad_geom(c, pad)
                net = c.pad_net(pad)
                node = f"{c.uid}:{i}"
                for L in lays:
                    shapes.append(CopperShape("pad", c, pad, L, net, g, node))
        for t in project.tracks:
            if t.layer in layers:
                shapes.append(CopperShape("track", t, None, t.layer, t.net, track_geom(t), t.uid))
        for v in project.vias:
            g = via_geom(v)
            for L in layers:
                shapes.append(CopperShape("via", v, None, L, v.net, g, v.uid))
        if include_zones:
            for z in project.zones:
                fill = project.zone_fills.get(z.uid)
                if fill is None or fill.is_empty or z.layer not in layers:
                    continue
                for k, part in enumerate(iter_polygons(fill)):
                    shapes.append(CopperShape("zone", z, None, z.layer, z.net, part, f"{z.uid}:{k}"))
        return shapes

    return project.cached(key, build)


def copper_by_layer(project: Project, include_zones: bool = True) -> dict[str, list[CopperShape]]:
    def build():
        out: dict[str, list[CopperShape]] = {L: [] for L in project.copper_layers}
        for s in collect_copper(project, include_zones):
            out.setdefault(s.layer, []).append(s)
        return out

    return project.cached(f"bylayer_{include_zones}", build)


# --------------------------------------------------------------------------- zone filling

def _thermal_relief(pad_g: BaseGeometry, gap: float, spoke: float) -> BaseGeometry:
    ring = pad_g.buffer(gap, quad_segs=4).difference(pad_g)
    minx, miny, maxx, maxy = pad_g.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    ext = max(maxx - minx, maxy - miny) / 2 + gap + 0.5
    spokes = unary_union([
        box(cx - ext, cy - spoke / 2, cx + ext, cy + spoke / 2),
        box(cx - spoke / 2, cy - ext, cx + spoke / 2, cy + ext),
    ])
    return ring.difference(spokes)


def fill_zone(project: Project, zone: Zone, base: list[CopperShape], done: dict[str, BaseGeometry]) -> BaseGeometry:
    rules = project.rules
    board = project.board.polygon()
    if board.is_empty or len(zone.outline) < 3:
        return Polygon()
    area = Polygon(zone.outline).buffer(0).intersection(board.buffer(-rules.edge_clearance, join_style="mitre"))
    if area.is_empty:
        return Polygon()
    clearance = max(zone.clearance, rules.clearance)
    pair = None
    if getattr(project, "amp", None):  # amp boards: a pour keeps conductor spacing from live tracks
        from ..amp.hv import pair_clearance_fn
        pair = pair_clearance_fn(project)
    obstacles = []
    same = []
    for s in base:
        if s.layer != zone.layer:
            continue
        if zone.net and s.net == zone.net:
            same.append(s)
            continue
        cl = max(clearance, project.netclass_for(s.net).clearance)
        if pair is not None:
            cl = max(cl, pair(zone.net, s.net, s.kind == "pad"))
        obstacles.append(s.geom.buffer(_clear(cl, 4), quad_segs=4))
    for h in holes(project):
        if not h.plated:
            obstacles.append(h.geom(_clear(clearance, 6), quad_segs=6))
    for other in project.zones:
        if other is zone or other.layer != zone.layer or other.uid not in done:
            continue
        if zone.net and other.net == zone.net:
            continue
        obstacles.append(done[other.uid].buffer(_clear(clearance, 4), quad_segs=4))
    fill = area.difference(unary_union(obstacles)) if obstacles else area
    if zone.thermal:
        reliefs = [_thermal_relief(s.geom, zone.thermal_gap, zone.spoke_width)
                   for s in same if s.kind == "pad" and s.pad is not None and s.pad.kind == "tht"]
        if reliefs:
            fill = fill.difference(unary_union(reliefs))
    mw = max(zone.min_width, 0.05)
    fill = fill.buffer(-mw / 2, quad_segs=3).buffer(mw / 2, quad_segs=3)
    if zone.net and not zone.keep_islands:
        anchor = unary_union([s.geom for s in same]) if same else None
        parts = [p for p in iter_polygons(fill) if anchor is not None and p.intersects(anchor)]
        fill = unary_union(parts) if parts else Polygon()
    return fill


def fill_all_zones(project: Project) -> None:
    base = collect_copper(project, include_zones=False)
    done: dict[str, BaseGeometry] = {}
    for z in sorted(project.zones, key=lambda z: -z.priority):
        done[z.uid] = fill_zone(project, z, base, done)
    project.zone_fills = done
    project.touch()
    project.fills_rev = project.rev
