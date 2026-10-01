"""Procedural 3D meshes for the board and component bodies.

Local component coordinates are (x, y_down, z_up) in mm with z = 0 on the board surface.
World coordinates: X right, Y up (= -model y), Z up; board bottom at z = 0, top at z = thickness.
Vertex layout: position(3) normal(3) uv(2), float32.
"""
from __future__ import annotations

import math

import mapbox_earcut as earcut
import numpy as np
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from ..model.board import Component, Project
from ..model.copper import holes
from ..model.geometry import circle_points, iter_polygons, rotate_point

# --------------------------------------------------------------------------- materials


def hex_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def mat(color, spec=0.3, shine=32.0, metal=0.0, alpha=1.0, emit=0.0) -> tuple:
    """(r, g, b, spec, shine, metal[, alpha, emit]): the last two only for see-through (glass) or glowing parts."""
    c = hex_rgb(color) if isinstance(color, str) else tuple(color)
    m = (round(c[0], 3), round(c[1], 3), round(c[2], 3), spec, shine, metal)
    return m if alpha >= 1.0 and not emit else m + (float(alpha), float(emit))


TIN = mat("#d2d4d8", 0.9, 70, 1.0)
GOLD = mat("#e2b04a", 0.9, 70, 1.0)
STEEL = mat("#b9bcc2", 0.8, 50, 1.0)
BLACK_PLASTIC = mat("#141416", 0.25, 20)
DARK = mat("#0b0b0c", 0.1, 10)

LED_COLORS = {"red": "#ff2a1a", "green": "#27e05a", "blue": "#2a6bff", "yellow": "#ffd21f", "white": "#f4f6ff",
              "orange": "#ff7a12", "amber": "#ffb300", "pink": "#ff4fa8", "uv": "#8a3cff", "rgb": "#f4f6ff"}


def led_color(value: str) -> str:
    v = (value or "").lower()
    for k, c in LED_COLORS.items():
        if k in v:
            return c
    return LED_COLORS["red"]


# --------------------------------------------------------------------------- primitives (local coords)

def box(x0, y0, z0, x1, y1, z1) -> np.ndarray:
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    z0, z1 = min(z0, z1), max(z0, z1)
    faces = [
        ((0, 0, 1), [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]),
        ((0, 0, -1), [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)]),
        ((1, 0, 0), [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]),
        ((-1, 0, 0), [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)]),
        ((0, 1, 0), [(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)]),
        ((0, -1, 0), [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)]),
    ]
    out = []
    for n, (a, b, c, d) in faces:
        for v in (a, b, c, a, c, d):
            out.append((*v, *n, 0.0, 0.0))
    return np.array(out, dtype=np.float32)


def cylinder(cx, cy, z0, z1, r, seg=24, top=True, bottom=False, inward=False) -> np.ndarray:
    out = []
    for i in range(seg):
        a0 = 2 * math.pi * i / seg
        a1 = 2 * math.pi * (i + 1) / seg
        p0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
        p1 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
        s = -1.0 if inward else 1.0
        n0 = (s * math.cos(a0), s * math.sin(a0), 0.0)
        n1 = (s * math.cos(a1), s * math.sin(a1), 0.0)
        quad = [((*p0, z0), n0), ((*p1, z0), n1), ((*p1, z1), n1), ((*p0, z0), n0), ((*p1, z1), n1), ((*p0, z1), n0)]
        out += [(*v, *n, 0.0, 0.0) for v, n in quad]
        if top:
            out += [(cx, cy, z1, 0, 0, 1, 0, 0), (*p0, z1, 0, 0, 1, 0, 0), (*p1, z1, 0, 0, 1, 0, 0)]
        if bottom:
            out += [(cx, cy, z0, 0, 0, -1, 0, 0), (*p1, z0, 0, 0, -1, 0, 0), (*p0, z0, 0, 0, -1, 0, 0)]
    return np.array(out, dtype=np.float32)


def cylinder_x(x0, x1, cy, cz, r, seg=20, caps=True) -> np.ndarray:
    """Cylinder along the local X axis."""
    out = []
    for i in range(seg):
        a0 = 2 * math.pi * i / seg
        a1 = 2 * math.pi * (i + 1) / seg
        y0, z0 = cy + r * math.cos(a0), cz + r * math.sin(a0)
        y1, z1 = cy + r * math.cos(a1), cz + r * math.sin(a1)
        n0 = (0.0, math.cos(a0), math.sin(a0))
        n1 = (0.0, math.cos(a1), math.sin(a1))
        quad = [((x0, y0, z0), n0), ((x1, y0, z0), n0), ((x1, y1, z1), n1), ((x0, y0, z0), n0), ((x1, y1, z1), n1),
                ((x0, y1, z1), n1)]
        out += [(*v, *n, 0.0, 0.0) for v, n in quad]
        if caps:
            out += [(x1, cy, cz, 1, 0, 0, 0, 0), (x1, y0, z0, 1, 0, 0, 0, 0), (x1, y1, z1, 1, 0, 0, 0, 0)]
            out += [(x0, cy, cz, -1, 0, 0, 0, 0), (x0, y1, z1, -1, 0, 0, 0, 0), (x0, y0, z0, -1, 0, 0, 0, 0)]
    return np.array(out, dtype=np.float32)


def dome(cx, cy, z0, r, seg=24, rings=8) -> np.ndarray:
    out = []
    for j in range(rings):
        t0 = (math.pi / 2) * j / rings
        t1 = (math.pi / 2) * (j + 1) / rings
        for i in range(seg):
            a0 = 2 * math.pi * i / seg
            a1 = 2 * math.pi * (i + 1) / seg
            pts = []
            for t, a in ((t0, a0), (t0, a1), (t1, a1), (t1, a0)):
                n = (math.cos(t) * math.cos(a), math.cos(t) * math.sin(a), math.sin(t))
                pts.append(((cx + r * n[0], cy + r * n[1], z0 + r * n[2]), n))
            for k in (0, 1, 2, 0, 2, 3):
                v, n = pts[k]
                out.append((*v, *n, 0.0, 0.0))
    return np.array(out, dtype=np.float32)


def prism(poly_pts, z0, z1, top=True, bottom=False) -> np.ndarray:
    """Vertical extrusion of a simple polygon (local x, y)."""
    poly = orient(Polygon(poly_pts), 1.0)
    ring = list(poly.exterior.coords)[:-1]
    out = []
    n = len(ring)
    for i in range(n):
        (ax, ay), (bx, by) = ring[i], ring[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy) or 1.0
        nx, ny = dy / L, -dx / L
        quad = [(ax, ay, z0), (bx, by, z0), (bx, by, z1), (ax, ay, z0), (bx, by, z1), (ax, ay, z1)]
        out += [(*v, nx, ny, 0.0, 0.0, 0.0) for v in quad]
    verts = np.array(ring, dtype=np.float64)
    tri = earcut.triangulate_float64(verts, np.array([len(ring)], dtype=np.uint32))
    for k in tri:
        x, y = ring[k]
        if top:
            out.append((x, y, z1, 0, 0, 1, 0, 0))
    if bottom:
        for k in tri[::-1]:
            x, y = ring[k]
            out.append((x, y, z0, 0, 0, -1, 0, 0))
    return np.array(out, dtype=np.float32)


def extrude_xz(profile, y0, y1) -> np.ndarray:
    """Extrude a closed profile drawn in the local x/z plane along y (used for gull-wing leads)."""
    poly = orient(Polygon(profile), 1.0)
    ring = list(poly.exterior.coords)[:-1]
    out = []
    n = len(ring)
    for i in range(n):
        (ax, az), (bx, bz) = ring[i], ring[(i + 1) % n]
        dx, dz = bx - ax, bz - az
        L = math.hypot(dx, dz) or 1.0
        nx, nz = dz / L, -dx / L
        quad = [(ax, y0, az), (bx, y0, bz), (bx, y1, bz), (ax, y0, az), (bx, y1, bz), (ax, y1, az)]
        out += [(*v, nx, 0.0, nz, 0.0, 0.0) for v in quad]
    verts = np.array(ring, dtype=np.float64)
    tri = earcut.triangulate_float64(verts, np.array([len(ring)], dtype=np.uint32))
    for k in tri:
        x, z = ring[k]
        out.append((x, y0, z, 0, -1, 0, 0, 0))
    for k in tri[::-1]:
        x, z = ring[k]
        out.append((x, y1, z, 0, 1, 0, 0, 0))
    return np.array(out, dtype=np.float32)


def rotz(arr: np.ndarray, deg: float, ox=0.0, oy=0.0) -> np.ndarray:
    """Rotate local geometry about z (CCW as displayed, Y down) then translate by (ox, oy)."""
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    out = arr.copy()
    x, y = arr[:, 0], arr[:, 1]
    out[:, 0] = x * c + y * s + ox
    out[:, 1] = -x * s + y * c + oy
    nx, ny = arr[:, 3], arr[:, 4]
    out[:, 3] = nx * c + ny * s
    out[:, 4] = -nx * s + ny * c
    return out


# --------------------------------------------------------------------------- component bodies

class Parts:
    def __init__(self):
        self.items: list[tuple[tuple, np.ndarray]] = []
        self.glow: list[tuple[tuple, np.ndarray]] = []  # LED lenses (also in items): lit by the simulation

    def add(self, material: tuple, arr: np.ndarray) -> None:
        if arr is not None and len(arr):
            self.items.append((material, arr))

    def add_glow(self, material: tuple, arr: np.ndarray) -> None:
        if arr is not None and len(arr):
            entry = (material, arr)
            self.items.append(entry)
            self.glow.append(entry)


def _pad_side(pad, bw, bh):
    """Direction (deg) a lead leaves the body towards this pad: 0=+x, 90=-y (up on screen), ..."""
    ex = abs(pad.x) - bw / 2
    ey = abs(pad.y) - bh / 2
    if ex >= ey:
        return 0.0 if pad.x > 0 else 180.0
    return 90.0 if pad.y < 0 else 270.0


def _gullwing(parts: Parts, c: Component, m: dict):
    bw, bh, H = m["bw"], m["bh"], m["H"]
    so = m.get("standoff", 0.1)
    body = mat(m.get("body", "#1e1e1e"), 0.3, 28)
    parts.add(body, box(-bw / 2, -bh / 2, so, bw / 2, bh / 2, H))
    if m.get("pin1"):
        r = min(bw, bh) * 0.08
        p1 = c.footprint.pads[0]
        dx = -bw / 2 + r * 2.2 if p1.x < 0 else bw / 2 - r * 2.2
        dy = -bh / 2 + r * 2.2 if p1.y < 0 else bh / 2 - r * 2.2
        parts.add(mat("#2c2c2e", 0.1, 8), cylinder(dx, dy, H, H + 0.01, r, 16))
    th = 0.13
    for pad in c.footprint.pads:
        side = _pad_side(pad, bw, bh)
        # rotate pad into the +x frame
        px, py = rotate_point(pad.x, pad.y, -side)
        pw, ph = (pad.w, pad.h) if side in (0.0, 180.0) else (pad.h, pad.w)
        edge = bw / 2 if side in (0.0, 180.0) else bh / 2
        u1 = px + pw / 2 - 0.2 - edge
        if u1 <= 0.15:
            continue  # pad under the body (e.g. exposed pad)
        zh = min(H * 0.45, 0.55)
        a = u1 * 0.28
        b = u1 * 0.55
        prof = [(-0.2, zh), (a, zh), (b, th), (u1, th), (u1, 0.0), (b - th * 0.8, 0.0), (a - th * 0.5, zh - th),
                (-0.2, zh - th)]
        prof = [(edge + u, z) for u, z in prof]
        lw = max(0.12, min(ph * 0.7, 3.0))
        lead = extrude_xz(prof, py - lw / 2, py + lw / 2)
        parts.add(TIN, rotz(lead, side))


def _chip(parts: Parts, c: Component, m: dict):
    L, W, H = m["L"], m["W"], m["H"]
    t = min(0.28 * L, 0.5)
    cls = m.get("cls", "R")
    if cls == "LED":
        parts.add(mat("#f0f0ea", 0.3, 30), box(-L / 2 + t, -W / 2, 0.02, L / 2 - t, W / 2, H * 0.55))
        col = led_color(c.value)
        parts.add_glow(mat(col, 0.9, 80), box(-L / 2 + t, -W / 2 + 0.05, H * 0.55, L / 2 - t, W / 2 - 0.05, H))
        parts.add(mat("#1a8a3a", 0.3, 20), box(-L / 2 + t, -W / 2 - 0.01, H * 0.9, -L / 2 + t + 0.2, W / 2 + 0.01, H + 0.005))
    else:
        parts.add(mat(m.get("body", "#141414"), 0.35 if cls != "C" else 0.2, 30),
                  box(-L / 2 + t * 0.9, -W / 2, 0.02, L / 2 - t * 0.9, W / 2, H))
    parts.add(TIN, box(-L / 2, -W / 2, 0.0, -L / 2 + t, W / 2, H + 0.01))
    parts.add(TIN, box(L / 2 - t, -W / 2, 0.0, L / 2, W / 2, H + 0.01))


def _qfn(parts: Parts, c: Component, m: dict):
    bw, bh, H = m["bw"], m["bh"], m["H"]
    parts.add(mat(m.get("body", "#262626"), 0.3, 28), box(-bw / 2, -bh / 2, 0.02, bw / 2, bh / 2, H))
    parts.add(mat("#3a3a3c", 0.1, 8), cylinder(-bw / 2 + 0.45, -bh / 2 + 0.45, H, H + 0.01, 0.15, 16))
    for pad in c.footprint.pads:
        if abs(pad.x) < bw / 2 - 0.5 and abs(pad.y) < bh / 2 - 0.5:
            continue
        side = _pad_side(pad, bw, bh)
        px, py = rotate_point(pad.x, pad.y, -side)
        ph = pad.h if side in (0.0, 180.0) else pad.w
        edge = bw / 2 if side in (0.0, 180.0) else bh / 2
        term = box(edge - 0.35, py - ph * 0.4, 0.0, edge + 0.005, py + ph * 0.4, 0.2)
        parts.add(TIN, rotz(term, side))


def _dip(parts: Parts, c: Component, m: dict):
    bw, bh, H = m["bw"], m["bh"], m["H"]
    z0 = 0.6
    parts.add(mat(m.get("body", "#1c1c1c"), 0.3, 24), box(-bw / 2, -bh / 2, z0, bw / 2, bh / 2, H + z0))
    parts.add(DARK, cylinder(0, -bh / 2 + 0.01, H + z0 - 0.01, H + z0 + 0.005, 0.7, 16))
    for pad in c.footprint.pads:
        sx = 1 if pad.x > 0 else -1
        parts.add(TIN, box(pad.x - 0.25, pad.y - 0.13, -1.2, pad.x + 0.25, pad.y + 0.13, z0 + 0.8))
        parts.add(TIN, box(sx * bw / 2, pad.y - 0.75, z0 + 0.6, pad.x + sx * 0.25, pad.y + 0.75, z0 + 0.85))
        parts.add(TIN, box(pad.x - 0.25, pad.y - 0.75, z0 + 0.3, pad.x + 0.25, pad.y + 0.75, z0 + 0.85))


def _header(parts: Parts, c: Component, m: dict):
    pitch = m.get("pitch", 2.54)
    base = mat(m.get("body", "#161616"), 0.2, 20)
    pin = mat(m.get("pin", "#d9b44a"), 0.9, 70, 1.0)
    for pad in c.footprint.pads:
        h = pitch / 2 - 0.02
        parts.add(base, box(pad.x - h, pad.y - h, 0.0, pad.x + h, pad.y + h, 2.5))
        parts.add(pin, box(pad.x - 0.32, pad.y - 0.32, -3.0, pad.x + 0.32, pad.y + 0.32, 8.5))


def _jst(parts: Parts, c: Component, m: dict):
    w, y0, y1, H = m["w"], m["y0"], m["y1"], m["H"]
    body = mat(m.get("body", "#efe7d4"), 0.25, 20)
    wall = 0.6
    parts.add(body, box(-w / 2, y0, 0, w / 2, y1, 1.0))
    parts.add(body, box(-w / 2, y0, 0, -w / 2 + wall, y1, H))
    parts.add(body, box(w / 2 - wall, y0, 0, w / 2, y1, H))
    parts.add(body, box(-w / 2, y1 - wall, 0, w / 2, y1, H))
    parts.add(body, box(-w / 2, y0, 0, w / 2, y0 + wall, H * 0.75))
    for pad in c.footprint.pads:
        parts.add(GOLD, box(pad.x - 0.32, pad.y - 0.32, -2.5, pad.x + 0.32, pad.y + 0.32, H - 1.0))


def _terminal(parts: Parts, c: Component, m: dict):
    w, y0, y1, H = m["w"], m["y0"], m["y1"], m["H"]
    body = mat(m.get("body", "#2f7d4a"), 0.25, 20)
    parts.add(body, box(-w / 2, y0, 0, w / 2, y1, H * 0.6))
    parts.add(body, box(-w / 2, y0 + (y1 - y0) * 0.35, H * 0.6, w / 2, y1, H))
    for pad in c.footprint.pads:
        cy = y0 + (y1 - y0) * 0.68
        parts.add(STEEL, cylinder(pad.x, cy, H - 1.0, H + 0.01, 1.4, 20))
        parts.add(DARK, box(pad.x - 1.3, cy - 0.25, H + 0.011, pad.x + 1.3, cy + 0.25, H + 0.02))
        parts.add(DARK, box(pad.x - 1.6, y0 - 0.01, 1.2, pad.x + 1.6, y0 + 1.0, 4.2))


def _tact(parts: Parts, c: Component, m: dict):
    w, h, H = m["w"], m["h"], m["H"]
    parts.add(BLACK_PLASTIC, box(-w / 2, -h / 2, 0, w / 2, h / 2, H - 0.3))
    parts.add(STEEL, box(-w / 2, -h / 2, H - 0.3, w / 2, h / 2, H))
    parts.add(mat("#1a1a1a", 0.3, 20), cylinder(0, 0, H, H + m.get("act_h", 1.5), m.get("actuator", 3.5) / 2, 28))
    for pad in c.footprint.pads:
        parts.add(STEEL, box(pad.x - 0.35, pad.y - 0.15, -1.5, pad.x + 0.35, pad.y + 0.15, 1.0))


def _radial_cap(parts: Parts, c: Component, m: dict):
    D, H = m["D"], m["H"]
    r = D / 2
    z0 = 0.4
    parts.add(mat(m.get("body", "#23336b"), 0.45, 40), cylinder(0, 0, z0, z0 + H - 0.4, r, 36, top=False))
    parts.add(mat("#c9ccd2", 0.8, 50, 1.0), cylinder(0, 0, z0 + H - 0.4, z0 + H, r * 0.97, 36))
    parts.add(mat("#8f9399", 0.5, 30, 1.0), box(-r * 0.6, -0.1, z0 + H + 0.001, r * 0.6, 0.1, z0 + H + 0.02))
    parts.add(mat("#8f9399", 0.5, 30, 1.0), box(-0.1, -r * 0.6, z0 + H + 0.001, 0.1, r * 0.6, z0 + H + 0.02))
    # negative stripe (pin 2 side)
    stripe = cylinder(0, 0, z0 + 0.3, z0 + H - 0.5, r + 0.02, 36, top=False)
    ang = np.degrees(np.arctan2(stripe[:, 1], stripe[:, 0]))
    tri_mask = (np.abs(ang.reshape(-1, 3)).max(axis=1) < 32)
    parts.add(mat(m.get("stripe", "#d0d0d0"), 0.4, 40), stripe.reshape(-1, 3, 8)[tri_mask].reshape(-1, 8))
    parts.add(DARK, cylinder(0, 0, 0, z0, r * 0.9, 24))


def _led_tht(parts: Parts, c: Component, m: dict):
    D, H = m["D"], m["H"]
    r = D / 2
    col = mat(led_color(c.value), 0.9, 90)
    parts.add_glow(col, cylinder(0, 0, 1.0, H - r, r, 36, top=False))
    parts.add_glow(col, dome(0, 0, H - r, r, 36, 10))
    parts.add_glow(col, cylinder(0, 0, 0.6, 1.6, r + 0.4, 36))
    for pad in c.footprint.pads:
        parts.add(STEEL, box(pad.x - 0.25, pad.y - 0.25, -1.5, pad.x + 0.25, pad.y + 0.25, 0.8))


def _to220(parts: Parts, c: Component, m: dict):
    parts.add(mat(m.get("body", "#1c1c1c"), 0.3, 24), box(-5.0, -1.9, 3.0, 5.0, 0.6, 12.0))
    tab = mat(m.get("tab", "#c9c9c9"), 0.8, 60, 1.0)
    parts.add(tab, box(-5.0, -3.2, 3.0, 5.0, -1.9, 18.5))
    parts.add(DARK, cylinder(0, -2.55, 14.5, 15.5, 1.8, 24))
    for pad in c.footprint.pads:
        parts.add(TIN, box(pad.x - 0.4, pad.y - 0.25, -1.5, pad.x + 0.4, pad.y + 0.25, 3.0))


def _to92(parts: Parts, c: Component, m: dict):
    pts = [(2.4 * math.cos(math.radians(a)), -0.3 - 2.4 * math.sin(math.radians(a))) for a in range(-20, 201, 10)]
    parts.add(mat(m.get("body", "#1a1a1a"), 0.3, 24), prism(pts, 2.5, 7.0))
    for pad in c.footprint.pads:
        parts.add(TIN, box(pad.x - 0.22, pad.y - 0.22, -1.5, pad.x + 0.22, pad.y + 0.22, 2.6))


def _hc49(parts: Parts, c: Component, m: dict):
    L, W, H = m["L"], m["W"], m["H"]
    r = W / 2
    pts = [(-(L / 2 - r) + r * math.cos(math.radians(a)), r * math.sin(math.radians(a))) for a in range(90, 271, 15)]
    pts += [((L / 2 - r) + r * math.cos(math.radians(a)), r * math.sin(math.radians(a))) for a in range(-90, 91, 15)]
    parts.add(mat("#c6c9cf", 0.85, 60, 1.0), prism(pts, 0.4, H))
    parts.add(mat("#2a2a2a", 0.2, 10), box(-L / 2 + 0.3, -W / 2 + 0.3, 0.0, L / 2 - 0.3, W / 2 - 0.3, 0.4))


def _xtal_smd(parts: Parts, c: Component, m: dict):
    L, W, H = m["L"], m["W"], m["H"]
    parts.add(mat("#d9cfb4", 0.2, 16), box(-L / 2, -W / 2, 0.0, L / 2, W / 2, H * 0.55))
    parts.add(mat("#c6c9cf", 0.85, 60, 1.0), box(-L / 2 + 0.15, -W / 2 + 0.15, H * 0.55, L / 2 - 0.15, W / 2 - 0.15, H))


def _diode_smd(parts: Parts, c: Component, m: dict):
    L, W, H = m["L"], m["W"], m["H"]
    parts.add(mat(m.get("body", "#1d1d1d"), 0.3, 24), box(-L / 2 * 0.72, -W / 2, 0.05, L / 2 * 0.72, W / 2, H))
    parts.add(mat(m.get("band", "#bfbfbf"), 0.3, 20), box(-L / 2 * 0.62, -W / 2 + 0.05, H, -L / 2 * 0.42, W / 2 - 0.05, H + 0.01))
    for sx in (-1, 1):
        parts.add(TIN, box(sx * L / 2 * 0.7, -W * 0.3, 0.0, sx * L / 2, W * 0.3, 0.2))


RES_BANDS = ["#000000", "#7a3b12", "#d11f1f", "#ff8c00", "#ffe000", "#1e9e3a", "#1e4fd1", "#8a3cc8", "#8c8c8c", "#ffffff"]


def _resistor_bands(value: str) -> list[str]:
    v = (value or "").strip().lower().replace("ohm", "").replace("r", ".") if value else "10k"
    mult = 1.0
    for suffix, m in (("k", 1e3), ("m", 1e6)):
        if suffix in v:
            v = v.replace(suffix, ".")
            mult = m
    try:
        ohms = float(v.strip(".") or 0) * mult
    except ValueError:
        return ["#7a3b12", "#000000", "#ff8c00", "#c9a13b"]
    if ohms <= 0:
        return ["#000000", "#000000", "#000000", "#c9a13b"]
    exp = int(math.floor(math.log10(ohms))) - 1
    digits = int(round(ohms / 10 ** exp))
    if digits >= 100:
        digits //= 10
        exp += 1
    d1, d2 = digits // 10, digits % 10
    mcol = RES_BANDS[exp] if 0 <= exp <= 9 else ("#c9a13b" if exp == -1 else "#c0c0c0")
    return [RES_BANDS[d1], RES_BANDS[d2], mcol, "#c9a13b"]


def _axial(parts: Parts, c: Component, m: dict):
    L, D, pitch = m["L"], m["D"], m["pitch"]
    r = D / 2
    zc = r + 0.3
    parts.add(mat(m.get("body", "#1a1a1a"), 0.35, 30), cylinder_x(-L / 2, L / 2, 0, zc, r, 24))
    if m.get("bands"):
        xs = [-L * 0.3, -L * 0.15, 0.0, L * 0.3]
        for x, col in zip(xs, _resistor_bands(c.value)):
            parts.add(mat(col, 0.3, 24), cylinder_x(x - 0.25, x + 0.25, 0, zc, r + 0.02, 24, caps=False))
    elif m.get("band"):
        parts.add(mat(m["band"], 0.3, 24), cylinder_x(-L / 2 + 0.4, -L / 2 + 1.0, 0, zc, r + 0.02, 24, caps=False))
    for sx in (-1, 1):
        parts.add(TIN, cylinder_x(min(sx * L / 2, sx * pitch / 2), max(sx * L / 2, sx * pitch / 2), 0, zc, 0.3, 12))
        parts.add(TIN, box(sx * pitch / 2 - 0.3, -0.3, -1.5, sx * pitch / 2 + 0.3, 0.3, zc))


def _usb_c(parts: Parts, c: Component, m: dict):
    w, y0, y1, H = m["w"], m["y0"], m["y1"], m["H"]
    shell = mat("#c3c6cc", 0.85, 60, 1.0)
    r = H / 2
    pts = [(-(w / 2 - r) + r * math.cos(math.radians(a)), r * math.sin(math.radians(a))) for a in range(90, 271, 15)]
    pts += [((w / 2 - r) + r * math.cos(math.radians(a)), r * math.sin(math.radians(a))) for a in range(-90, 91, 15)]
    prof = [(x, z + r) for x, z in pts]
    # extrude the stadium profile along y
    shell_mesh = extrude_xz(prof, y0, y1)
    parts.add(shell, shell_mesh)
    inner = [(x * 0.82, (z - r) * 0.6 + r) for x, z in prof]
    parts.add(DARK, extrude_xz(inner, y1 - 0.3, y1 + 0.01))
    parts.add(mat("#1d1d1d", 0.3, 20), box(-w * 0.3, y1 - 0.2, r - 0.35, w * 0.3, y1 + 0.02, r + 0.35))


def cylinder_y(y0, y1, cx, cz, r, seg=20, caps=True) -> np.ndarray:
    """Cylinder along the local Y axis."""
    return rotz(cylinder_x(y0, y1, 0.0, cz, r, seg, caps), -90.0, cx, 0.0)


def _material(e: dict) -> tuple:
    metal = bool(e.get("m"))
    return mat(e.get("c", "#c8cad0" if metal else "#1e1e20"), e.get("sp", 0.85 if metal else 0.3),
               e.get("sh", 60.0 if metal else 24.0), 1.0 if metal else 0.0, e.get("a", 1.0), e.get("e", 0.0))


def _tht_pins(parts: Parts, c: Component, top: float = 1.0, color: str = "#cfd2d6") -> None:
    pin = mat(color, 0.85, 60, 1.0)
    for pad in c.footprint.pads:
        if pad.kind != "tht":
            continue
        dx = max(0.2, min(pad.drill, pad.drill_h or pad.drill) * 0.35)
        dy = max(0.2, (pad.drill_h or pad.drill) * 0.35)
        parts.add(pin, box(pad.x - dx, pad.y - dy, -1.6, pad.x + dx, pad.y + dy, top))


def _composite(parts: Parts, c: Component, m: dict):
    """Declarative body description: a list of primitives (boxes, cylinders, domes, prisms)."""
    for e in m.get("parts", []):
        s, p = e.get("s"), e.get("p", [])
        if s == "box":
            arr = box(*p)
        elif s == "cyl":
            arr = cylinder(p[0], p[1], p[2], p[3], p[4], e.get("seg", 28))
        elif s == "cylx":
            arr = cylinder_x(*p[:5])
        elif s == "cyly":
            arr = cylinder_y(*p[:5])
        elif s == "dome":
            arr = dome(*p[:4])
        elif s == "prism":
            arr = prism(e["pts"], p[0], p[1])
        elif s == "xz":
            arr = extrude_xz(e["pts"], p[0], p[1])
        else:
            continue
        parts.add(_material(e), arr)
    if m.get("pins") == "tht":
        _tht_pins(parts, c, m.get("pin_top", 1.0), m.get("pin_color", "#cfd2d6"))
    if m.get("leads"):
        bw, bh = m["leads"]
        _gullwing_leads(parts, c, bw, bh, m.get("lead_z", 0.5))


def _gullwing_leads(parts: Parts, c: Component, bw: float, bh: float, zh: float) -> None:
    th = 0.13
    for pad in c.footprint.pads:
        if pad.kind != "smd":
            continue
        side = _pad_side(pad, bw, bh)
        px, py = rotate_point(pad.x, pad.y, -side)
        pw, ph = (pad.w, pad.h) if side in (0.0, 180.0) else (pad.h, pad.w)
        edge = bw / 2 if side in (0.0, 180.0) else bh / 2
        u1 = px + pw / 2 - 0.2 - edge
        if u1 <= 0.15:
            continue
        a, b = u1 * 0.28, u1 * 0.55
        prof = [(-0.2, zh), (a, zh), (b, th), (u1, th), (u1, 0.0), (b - th * 0.8, 0.0), (a - th * 0.5, zh - th),
                (-0.2, zh - th)]
        prof = [(edge + u, z) for u, z in prof]
        lw = max(0.12, min(ph * 0.7, 3.0))
        parts.add(TIN, rotz(extrude_xz(prof, py - lw / 2, py + lw / 2), side))


def _auto(parts: Parts, c: Component, m: dict):
    """Fallback body for footprints without a dedicated model (e.g. imported ones)."""
    fp = c.footprint
    xs, ys = [], []
    for g in fp.graphics:
        if g.layer == "fab":
            if g.kind == "circle":
                (cx, cy), = g.pts
                xs += [cx - g.r, cx + g.r]
                ys += [cy - g.r, cy + g.r]
            else:
                xs += [p[0] for p in g.pts]
                ys += [p[1] for p in g.pts]
    if xs and (max(xs) - min(xs)) > 0.2 and (max(ys) - min(ys)) > 0.2:
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    else:
        cx0, cy0, cx1, cy1 = fp.courtyard
        x0, y0, x1, y1 = cx0 + 0.3, cy0 + 0.3, cx1 - 0.3, cy1 - 0.3
        if x1 - x0 < 0.2 or y1 - y0 < 0.2:
            return
    area = (x1 - x0) * (y1 - y0)
    H = m.get("H") or max(0.5, min(4.0, 0.35 * math.sqrt(area)))
    has_tht = any(p.kind == "tht" for p in fp.pads)
    z0 = 0.0 if not has_tht else 0.2
    parts.add(mat(m.get("body", "#232326"), 0.3, 24), box(x0, y0, z0, x1, y1, z0 + H))
    if m.get("leads", True):
        for pad in fp.pads:
            if pad.kind != "smd":
                continue
            inside = x0 + 0.05 < pad.x < x1 - 0.05 and y0 + 0.05 < pad.y < y1 - 0.05
            if inside and (pad.w * pad.h) > 0.25 * area:
                continue  # exposed pad under the body
            hw, hh = pad.w * 0.42, pad.h * 0.42
            parts.add(TIN, rotz(box(-hw, -hh, 0.0, hw, hh, 0.14), pad.rotation, pad.x, pad.y))
    if has_tht:
        _tht_pins(parts, c, z0 + 0.4)


def _tube(parts: Parts, c: Component, m: dict):
    """Tube socket with the tube named by the component value (see pcbpro.amp.mesh3d)."""
    from ..amp.mesh3d import tube_parts
    tube_parts(parts, c, m)


BUILDERS = {
    "chip": _chip, "gullwing": _gullwing, "qfn": _qfn, "dip": _dip, "header": _header, "jst": _jst,
    "terminal": _terminal, "tact": _tact, "radial_cap": _radial_cap, "led_tht": _led_tht, "to220": _to220,
    "to92": _to92, "hc49": _hc49, "xtal_smd": _xtal_smd, "diode_smd": _diode_smd, "axial": _axial, "usb_c": _usb_c,
    "composite": _composite, "auto": _auto, "tube": _tube,
}


def component_parts(c: Component) -> Parts:
    parts = Parts()
    kind = c.footprint.model.get("type", "auto")
    fn = BUILDERS.get(kind, _auto if kind != "none" else None)
    if fn is not None:
        try:
            fn(parts, c, c.footprint.model)
        except Exception:  # a broken model description must never break the viewer
            parts = Parts()
    return parts


def place_component(arr: np.ndarray, c: Component, thickness: float) -> np.ndarray:
    """Local component mesh -> world coordinates."""
    out = arr.copy()
    if c.mirror:
        out[:, 0] *= -1
        out[:, 3] *= -1
    out = rotz(out, c.rotation, c.x, c.y)
    if c.side == "top":
        out[:, 2] += thickness
    else:
        out[:, 2] *= -1
        out[:, 5] *= -1
    out[:, 1] *= -1
    out[:, 4] *= -1
    return out


# --------------------------------------------------------------------------- board

def _earcut_polygon(poly: Polygon):
    rings = [list(poly.exterior.coords)[:-1]] + [list(r.coords)[:-1] for r in poly.interiors]
    verts = []
    ends = []
    for r in rings:
        verts.extend(r)
        ends.append(len(verts))
    arr = np.array(verts, dtype=np.float64)
    tri = earcut.triangulate_float64(arr, np.array(ends, dtype=np.uint32))
    return arr, tri


def _closest_on_segment(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return x1 + t * dx, y1 + t * dy


def board_meshes(project: Project):
    """Returns dict with 'top', 'bottom' (textured), 'edge' and 'plated'/'bare' hole walls, world coords."""
    t = project.board.thickness
    board = project.board.polygon()
    x0, y0, x1, y1 = project.board.bounds()
    bw, bh = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    hl = holes(project)
    circles = []
    for h in hl:
        if h.is_slot:
            ring = list(h.geom(quad_segs=6).exterior.coords)[:-1]
        else:
            seg = 16 if h.diameter < 1.0 else (24 if h.diameter < 2.5 else 36)
            ring = circle_points(h.x, h.y, h.diameter / 2, seg)
        circles.append((h, ring))
    shape = board
    if circles:
        shape = board.difference(unary_union([Polygon(pts) for _, pts in circles]))
    top, bottom = [], []
    for poly in iter_polygons(shape):
        if poly.area < 1e-6:
            continue
        verts, tri = _earcut_polygon(poly)
        for k in tri:
            x, y = verts[k]
            u, v = (x - x0) / bw, (y - y0) / bh
            top.append((x, -y, t, 0, 0, 1, u, v))
        for k in tri[::-1]:
            x, y = verts[k]
            u, v = (x - x0) / bw, (y - y0) / bh
            bottom.append((x, -y, 0.0, 0, 0, -1, u, v))
    edge = []
    oriented = orient(board, 1.0) if not board.is_empty else board
    rings = []
    for poly in iter_polygons(oriented):
        rings.append(list(poly.exterior.coords))
        rings.extend(list(r.coords) for r in poly.interiors)
    for ring in rings:
        for (ax, ay), (bx, by) in zip(ring, ring[1:]):
            dx, dy = bx - ax, by - ay
            L = math.hypot(dx, dy)
            if L < 1e-9:
                continue
            nx, ny = dy / L, -dx / L
            for (x, y, z) in ((ax, ay, 0), (bx, by, 0), (bx, by, t), (ax, ay, 0), (bx, by, t), (ax, ay, t)):
                edge.append((x, -y, z, nx, -ny, 0, 0, 0))
    plated, bare = [], []
    for h, pts in circles:
        n = len(pts)
        target = plated if h.plated else bare
        (sx0, sy0), (sx1, sy1) = h.endpoints()
        for i in range(n):
            (ax, ay), (bx, by) = pts[i], pts[(i + 1) % n]
            ca = _closest_on_segment(ax, ay, sx0, sy0, sx1, sy1)
            cb = _closest_on_segment(bx, by, sx0, sy0, sx1, sy1)
            na = ((ca[0] - ax), (ca[1] - ay))
            nb = ((cb[0] - bx), (cb[1] - by))
            la = math.hypot(*na) or 1
            lb = math.hypot(*nb) or 1
            na = (na[0] / la, na[1] / la)
            nb = (nb[0] / lb, nb[1] / lb)
            for (x, y, z), (nx, ny) in (((ax, ay, -0.035), na), ((bx, by, -0.035), nb), ((bx, by, t + 0.035), nb),
                                        ((ax, ay, -0.035), na), ((bx, by, t + 0.035), nb), ((ax, ay, t + 0.035), na)):
                target.append((x, -y, z, nx, -ny, 0, 0, 0))
    f = lambda L: np.array(L, dtype=np.float32).reshape(-1, 8)
    return {"top": f(top), "bottom": f(bottom), "edge": f(edge), "plated": f(plated), "bare": f(bare)}


def scene_parts(project: Project, with_components: bool = True, glow: dict | None = None) -> dict:
    """All component geometry merged per material, in world coordinates. LED lenses go to ``glow`` (component
    uid -> [(material, array)]) when given, otherwise they are merged like everything else."""
    merged: dict[tuple, list[np.ndarray]] = {}
    if with_components:
        t = project.board.thickness
        for c in project.components:
            parts = component_parts(c)
            lenses = {id(e) for e in parts.glow} if glow is not None else set()
            for entry in parts.items:
                material, arr = entry
                world = place_component(arr, c, t)
                if id(entry) in lenses:
                    glow.setdefault(c.uid, []).append((material, world.astype(np.float32)))
                else:
                    merged.setdefault(material, []).append(world)
    return {m: np.concatenate(v).astype(np.float32) for m, v in merged.items()}
