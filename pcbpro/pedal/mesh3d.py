"""3D meshes of the pedal enclosure and its hardware (knobs, footswitch, jack nuts, LED bezels).

Geometry is built in enclosure coordinates (u, v, w): u/v as on panel A (outside view, +v up), w the depth from
the outer surface of the face (outside of the box is negative w). ``to_world`` maps it into the 3D viewer's board
space (X = board x, Y = -board y, Z up with the board's bottom at 0).
"""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import Point, Polygon
from shapely.geometry.polygon import orient

from ..model.board import Project
from ..model.geometry import iter_polygons, rounded_rect_points
from ..ui.mesh import DARK, _earcut_polygon, box, cylinder, cylinder_x, cylinder_y, led_color, mat
from .enclosure import (KNOB_COLORS, POWDER_COATS, Enclosure, PanelHole, all_holes, export_diameter,
                        get_enclosure, hole_face_point)

CHROME = mat("#dcdfe4", 0.95, 90, 1.0)
NICKEL = mat("#c3c6cb", 0.85, 60, 1.0)
BLACK_BODY = mat("#18181a", 0.25, 18)


class Parts:
    def __init__(self):
        self.items: list[tuple[tuple, np.ndarray]] = []

    def add(self, material, arr) -> None:
        if arr is not None and len(arr):
            self.items.append((material, np.asarray(arr, dtype=np.float32)))


# --------------------------------------------------------------------------- primitives in (u, v, w)

def slab(poly: Polygon, w0: float, w1: float) -> np.ndarray:
    """Solid between w0 and w1 with the outline (and holes) of ``poly``."""
    out = []
    poly = orient(poly, 1.0)
    verts, tri = _earcut_polygon(poly)
    for k in tri:
        x, y = verts[k]
        out.append((x, y, w0, 0, 0, -1, 0, 0))
    for k in tri[::-1]:
        x, y = verts[k]
        out.append((x, y, w1, 0, 0, 1, 0, 0))
    rings = [list(poly.exterior.coords)] + [list(r.coords) for r in poly.interiors]
    for ring in rings:
        for (ax, ay), (bx, by) in zip(ring, ring[1:]):
            dx, dy = bx - ax, by - ay
            L = math.hypot(dx, dy)
            if L < 1e-9:
                continue
            nx, ny = dy / L, -dx / L
            for x, y, z in ((ax, ay, w0), (bx, by, w0), (bx, by, w1), (ax, ay, w0), (bx, by, w1), (ax, ay, w1)):
                out.append((x, y, z, nx, ny, 0, 0, 0))
    return np.array(out, dtype=np.float32).reshape(-1, 8)


def loft(ring_a, ring_b, wa: float, wb: float, outward: bool = True) -> np.ndarray:
    """Band between two rings with the same vertex count (e.g. a tapered wall)."""
    out = []
    n = len(ring_a)
    for i in range(n):
        (ax, ay), (bx, by) = ring_a[i], ring_a[(i + 1) % n]
        (cx, cy), (dx_, dy_) = ring_b[i], ring_b[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        L = math.hypot(ex, ey) or 1.0
        nx, ny = (ey / L, -ex / L) if outward else (-ey / L, ex / L)
        quad = [(ax, ay, wa), (bx, by, wa), (dx_, dy_, wb), (ax, ay, wa), (dx_, dy_, wb), (cx, cy, wb)]
        out += [(x, y, z, nx, ny, 0, 0, 0) for x, y, z in quad]
    return np.array(out, dtype=np.float32).reshape(-1, 8)


def _ccw(pts):
    poly = orient(Polygon(pts), 1.0)
    return list(poly.exterior.coords)[:-1]


def cyl_w(u, v, w0, w1, r, seg=32) -> np.ndarray:
    """Cylinder along w (perpendicular to the face)."""
    return cylinder(u, v, min(w0, w1), max(w0, w1), r, seg, top=True, bottom=True)


def cyl_axis(face: str, u: float, v: float, w: float, a0: float, a1: float, r: float, seg=28) -> np.ndarray:
    """Cylinder whose axis is the wall normal of a side wall, from a0 to a1 along that axis."""
    if face in ("C", "E"):
        return cylinder_x(min(a0, a1), max(a0, a1), v, w, r, seg)
    return cylinder_y(min(a0, a1), max(a0, a1), u, w, r, seg)


# --------------------------------------------------------------------------- enclosure

def enclosure_color(enc: Enclosure) -> tuple:
    hexcol, metallic = POWDER_COATS.get(enc.color, POWDER_COATS["Raw aluminium"])
    if metallic:
        return mat(hexcol, 0.7, 40, 0.85)
    return mat(hexcol, 0.35, 22)


def _box_parts(parts: Parts, project: Project, enc: Enclosure, holes: list[PanelHole], show_lid: bool) -> None:
    spec = enc.spec
    body = enclosure_color(enc)
    W, H = enc.face_size
    We, He = enc.ext_size
    Wc, Hc = enc.cavity_size
    cr = spec.corner_r
    seg = 8
    outer_face = rounded_rect_points(-W / 2, -H / 2, W, H, cr, seg)
    outer_rim = rounded_rect_points(-We / 2, -He / 2, We, He, cr, seg)
    inner = rounded_rect_points(-Wc / 2, -Hc / 2, Wc, Hc, max(0.5, cr - spec.wall), seg)
    # face plate with real holes
    face = Polygon(outer_face)
    for h in holes:
        if h.face == "A":
            face = face.difference(Point(h.x, h.y).buffer(export_diameter(h, enc) / 2, quad_segs=10))
    for poly in iter_polygons(face):
        parts.add(body, slab(poly, 0.0, spec.face_t))
    # tapered outer skin, vertical inner skin, rim
    parts.add(body, loft(_ccw(outer_face), _ccw(outer_rim), 0.0, spec.depth, True))
    parts.add(body, loft(_ccw(inner), _ccw(inner), spec.face_t, spec.depth, False))
    rim = Polygon(outer_rim, [inner])
    parts.add(body, slab(rim, spec.depth - 0.01, spec.depth))
    # lid-screw bosses
    b = spec.boss
    for sx in (-1, 1):
        for sy in (-1, 1):
            cu, cv = sx * (Wc / 2 - b / 2 - 0.3), sy * (Hc / 2 - b / 2 - 0.3)
            parts.add(body, cyl_w(cu, cv, spec.face_t, spec.depth, b / 2 + 0.6, 24))
            parts.add(DARK, cyl_w(cu, cv, spec.depth, spec.depth + 0.02, 1.4, 16))
    if show_lid:
        lid = Polygon(outer_rim)
        parts.add(mat("#9ea3aa", 0.6, 30, 0.8), slab(lid, spec.depth, spec.depth + 2.0))
    # holes in the side walls: a dark disc just outside the wall
    for h in holes:
        if h.face == "A":
            continue
        u, v, w = hole_face_point(enc, h)
        r = export_diameter(h, enc) / 2
        sign = 1 if h.face in ("E", "B") else -1
        a = (u if h.face in ("C", "E") else v) + sign * 0.35
        parts.add(DARK, cyl_axis(h.face, u, v, w, a - 0.3 * sign, a + 0.3 * sign, r))


def _knob(parts: Parts, u: float, v: float, d: float, color: str, pointer_deg: float) -> None:
    r = d / 2
    body = mat(color, 0.45, 40, 1.0 if color == KNOB_COLORS["Chrome"] else 0.0)
    parts.add(NICKEL, cylinder(u, v, -2.0, 0.0, 5.6, 6, top=True, bottom=True))  # M7 nut
    parts.add(body, cylinder(u, v, -5.0, -3.0, r, 40, top=True, bottom=True))  # skirt
    parts.add(body, cylinder(u, v, -16.0, -5.0, r * 0.82, 40, top=True, bottom=True))
    a = math.radians(pointer_deg)
    du, dv = math.sin(a), math.cos(a)
    line = box(-0.45, 0.0, -16.08, 0.45, r * 0.78, -16.0)
    # rotate the pointer line (built along +v) into direction (du, dv)
    rot = line.copy()
    x, y = line[:, 0], line[:, 1]
    rot[:, 0] = x * dv + y * du + u
    rot[:, 1] = -x * du + y * dv + v
    parts.add(mat("#f2f2ee", 0.2, 10), rot)


def _hardware(parts: Parts, project: Project, enc: Enclosure, holes: list[PanelHole]) -> None:
    spec = enc.spec
    knob_col = KNOB_COLORS.get(enc.knob_color, KNOB_COLORS["Black"])
    for i, h in enumerate(holes):
        d = export_diameter(h, enc)
        if h.face == "A":
            u, v = h.x, h.y
            if h.kind in ("pot", "pot9"):
                _knob(parts, u, v, h.outer_d or enc.knob_d, knob_col, (-135 + 67 * i) % 270 - 135)
                if not h.derived:  # panel-mounted pot: show its body inside
                    parts.add(NICKEL, cyl_w(u, v, spec.face_t, spec.face_t + 9.0, 8.25))
            elif h.kind == "footswitch":
                parts.add(NICKEL, cylinder(u, v, -3.0, 0.0, 7.9, 6, top=True, bottom=True))
                parts.add(NICKEL, cyl_w(u, v, -8.0, -3.0, 6.0))
                parts.add(CHROME, cyl_w(u, v, -15.5, -8.0, 4.6))
                parts.add(CHROME, cyl_w(u, v, -17.0, -15.5, 5.3))
                if not h.derived:
                    parts.add(BLACK_BODY, box(u - 8.8, v - 8.8, spec.face_t, u + 8.8, v + 8.8, spec.face_t + 21.0))
            elif h.kind.startswith("bezel") or h.kind.startswith("led"):
                parts.add(CHROME, cyl_w(u, v, -1.6, 0.0, d / 2 + 1.4))
                parts.add(mat(led_color("red"), 0.9, 90), cyl_w(u, v, -2.2, -1.6, max(0.8, d / 2 - 0.9)))
            elif h.kind in ("toggle", "submini"):
                parts.add(NICKEL, cylinder(u, v, -2.0, 0.0, d / 2 + 2.4, 6, top=True, bottom=True))
                parts.add(NICKEL, cyl_w(u, v, -7.0, -2.0, d / 2 - 0.2))
                parts.add(CHROME, cyl_w(u, v, -17.0, -7.0, 1.3))
                if not h.derived:
                    parts.add(BLACK_BODY, box(u - 6.5, v - 6.4, spec.face_t, u + 6.5, v + 6.4, spec.face_t + 10.0))
            elif h.kind == "rotary":
                _knob(parts, u, v, 24.0, knob_col, 0.0)
            continue
        # side-wall hardware: nut and ferrule outside, body inside (for panel-mounted parts)
        u, v, w = hole_face_point(enc, h)
        sign = 1 if h.face in ("E", "B") else -1
        base = u if h.face in ("C", "E") else v
        if h.kind in ("jack", "dc"):
            nut_r = 7.6 if h.kind == "jack" else 7.9
            parts.add(NICKEL, cyl_axis(h.face, u, v, w, base + sign * 0.5, base + sign * 2.6, nut_r, 6))
            parts.add(NICKEL, cyl_axis(h.face, u, v, w, base + sign * 2.6, base + sign * 3.6, d / 2 + 0.3, 28))
            parts.add(DARK, cyl_axis(h.face, u, v, w, base + sign * 3.6, base + sign * 3.65, d / 2 - 1.8, 24))
            if not h.derived:
                r, length, _ = h.effective_body()
                a0, a1 = base - sign * spec.wall, base - sign * (spec.wall + length)
                lo, hi = sorted((a0, a1))
                if h.face in ("C", "E"):
                    parts.add(BLACK_BODY if h.kind == "dc" else NICKEL,
                              box(lo, v - r * 0.9, w - r * 0.9, hi, v + r * 0.9, w + r * 0.9))
                else:
                    parts.add(BLACK_BODY if h.kind == "dc" else NICKEL,
                              box(u - r * 0.9, lo, w - r * 0.9, u + r * 0.9, hi, w + r * 0.9))
        else:
            parts.add(NICKEL, cyl_axis(h.face, u, v, w, base + sign * 0.5, base + sign * 2.0, d / 2 + 2.0, 6))


# --------------------------------------------------------------------------- world mapping

def to_world(arr: np.ndarray, project: Project, enc: Enclosure) -> np.ndarray:
    out = arr.copy()
    near = enc.z_levels(project)[0]
    s = enc.mirror
    t = project.board.thickness
    out[:, 0] = enc.cx + s * arr[:, 0]
    out[:, 3] = s * arr[:, 3]
    out[:, 1] = arr[:, 1] - enc.cy
    if enc.face_side == "bottom":
        out[:, 2] = arr[:, 2] - near
    else:
        out[:, 2] = t + near - arr[:, 2]
        out[:, 5] = -arr[:, 5]
    return out


def pedal_parts(project: Project, show_lid: bool = False, show_box: bool = True) -> dict:
    """Enclosure + hardware merged per material, in the 3D viewer's world coordinates."""
    enc = get_enclosure(project)
    if enc is None:
        return {}
    holes = all_holes(project, enc)
    parts = Parts()
    if show_box:
        _box_parts(parts, project, enc, holes, show_lid)
    _hardware(parts, project, enc, holes)
    merged: dict[tuple, list] = {}
    for material, arr in parts.items:
        merged.setdefault(material, []).append(to_world(arr, project, enc))
    return {m: np.concatenate(v).astype(np.float32) for m, v in merged.items()}


def flip_for_pedal_view(arr: np.ndarray) -> np.ndarray:
    """Rotate 180 degrees about the world Y axis so a board hanging from its pots shows the knobs on top."""
    out = arr.copy()
    out[:, 0] *= -1
    out[:, 2] *= -1
    out[:, 3] *= -1
    out[:, 5] *= -1
    return out


def pedal_bounds(project: Project) -> tuple | None:
    """World-space bounding box (x0, y0, z0, x1, y1, z1) of the enclosure, before any flip."""
    enc = get_enclosure(project)
    if enc is None:
        return None
    We, He = enc.ext_size
    corners = np.array([[-We / 2, -He / 2, -18.0, 0, 0, 1, 0, 0], [We / 2, He / 2, enc.spec.depth, 0, 0, 1, 0, 0]],
                       dtype=np.float32)
    w = to_world(corners, project, enc)
    lo, hi = w[:, :3].min(axis=0), w[:, :3].max(axis=0)
    return (*lo, *hi)
