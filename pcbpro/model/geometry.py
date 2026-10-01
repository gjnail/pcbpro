"""2D geometry helpers.

Model units are millimetres. The Y axis points *down* (screen convention, same as
KiCad). Rotations are in degrees and are counter-clockwise *as displayed*.
"""
from __future__ import annotations

import math

from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.geometry.base import BaseGeometry


def rotate_point(x: float, y: float, deg: float) -> tuple[float, float]:
    """Rotate (x, y) about the origin, counter-clockwise on screen (Y down)."""
    if deg % 360 == 0:
        return x, y
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return x * c + y * s, -x * s + y * c


def transform_point(x, y, ox, oy, rot, mirror=False) -> tuple[float, float]:
    """Local footprint coordinates -> board coordinates."""
    if mirror:
        x = -x
    rx, ry = rotate_point(x, y, rot)
    return ox + rx, oy + ry


def inverse_transform_point(x, y, ox, oy, rot, mirror=False) -> tuple[float, float]:
    lx, ly = rotate_point(x - ox, y - oy, -rot)
    if mirror:
        lx = -lx
    return lx, ly


def transform_geom(g: BaseGeometry, ox, oy, rot, mirror=False) -> BaseGeometry:
    if mirror:
        g = affinity.scale(g, -1.0, 1.0, origin=(0, 0))
    if rot % 360:
        # shapely rotates CCW in a Y-up frame, which is CW on screen.
        g = affinity.rotate(g, -rot, origin=(0, 0))
    if ox or oy:
        g = affinity.translate(g, ox, oy)
    return g


def snap(v: float, grid: float) -> float:
    if grid <= 0:
        return v
    return round(round(v / grid) * grid, 6)


def dist(ax, ay, bx, by) -> float:
    return math.hypot(bx - ax, by - ay)


def point_segment_distance(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 <= 1e-18:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def arc_points(cx, cy, r, start_deg, sweep_deg, max_seg=0.25) -> list[tuple[float, float]]:
    """Points along an arc. Angles are CCW on screen, 0 deg = +X."""
    n = max(4, int(abs(math.radians(sweep_deg)) * r / max_seg) + 1)
    pts = []
    for i in range(n + 1):
        a = math.radians(start_deg + sweep_deg * i / n)
        pts.append((cx + r * math.cos(a), cy - r * math.sin(a)))
    return pts


def circle_points(cx, cy, r, segments=32) -> list[tuple[float, float]]:
    return [
        (cx + r * math.cos(2 * math.pi * i / segments), cy + r * math.sin(2 * math.pi * i / segments))
        for i in range(segments)
    ]


def rounded_rect_points(x0, y0, w, h, r, seg=6) -> list[tuple[float, float]]:
    r = max(0.0, min(r, w / 2, h / 2))
    if r <= 1e-9:
        return [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]
    pts = []
    corners = [
        (x0 + w - r, y0 + r, 270),  # top-right  (screen)
        (x0 + w - r, y0 + h - r, 0),  # bottom-right
        (x0 + r, y0 + h - r, 90),  # bottom-left
        (x0 + r, y0 + r, 180),  # top-left
    ]
    for cx, cy, a0 in corners:
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def shape_polygon(shape: str, w: float, h: float, roundness: float = 0.25) -> Polygon:
    """A pad-like shape centred on the origin."""
    if shape == "circle":
        return Point(0, 0).buffer(w / 2, quad_segs=8)
    if shape == "oval":
        if abs(w - h) < 1e-9:
            return Point(0, 0).buffer(w / 2, quad_segs=8)
        if w > h:
            d = (w - h) / 2
            return LineString([(-d, 0), (d, 0)]).buffer(h / 2, quad_segs=8)
        d = (h - w) / 2
        return LineString([(0, -d), (0, d)]).buffer(w / 2, quad_segs=8)
    if shape == "roundrect":
        r = max(0.0, min(roundness * min(w, h), min(w, h) / 2 - 1e-6))
        if r <= 1e-6:
            return box(-w / 2, -h / 2, w / 2, h / 2)
        return box(-w / 2 + r, -h / 2 + r, w / 2 - r, h / 2 - r).buffer(r, quad_segs=4)
    return box(-w / 2, -h / 2, w / 2, h / 2)


def iter_polygons(g: BaseGeometry):
    """Yield the Polygon parts of any geometry."""
    if g is None or g.is_empty:
        return
    if isinstance(g, Polygon):
        yield g
    elif isinstance(g, MultiPolygon):
        yield from g.geoms
    elif hasattr(g, "geoms"):
        for sub in g.geoms:
            yield from iter_polygons(sub)


def split_holes(poly: Polygon, _depth: int = 0) -> list[Polygon]:
    """Split a polygon with holes into hole-free pieces (for Gerber regions etc.)."""
    if not poly.interiors:
        return [poly]
    minx, miny, maxx, maxy = poly.bounds
    # Cut through the middle of every hole (nudged on retries for degenerate cases).
    nudge = 0.0137 * _depth
    xs = sorted({hole_rep_x(h) + nudge for h in poly.interiors})
    cuts = [minx - 1] + xs + [maxx + 1]
    out: list[Polygon] = []
    for a, b in zip(cuts, cuts[1:]):
        piece = poly.intersection(box(a, miny - 1, b, maxy + 1))
        for p in iter_polygons(piece):
            if p.area < 1e-9:
                continue
            if p.interiors and _depth < 3:
                out.extend(split_holes(p, _depth + 1))
            elif not p.interiors:
                out.append(p)
    return out


def hole_rep_x(ring) -> float:
    minx, _, maxx, _ = ring.bounds
    return (minx + maxx) / 2


def fmt_mm(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".") if abs(v) < 1e6 else f"{v:.1f}"
