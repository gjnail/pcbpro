"""3D tube sockets with the tube in them: a transparent glass envelope over the plate structure, the silver
getter flash, mica spacers and glowing heaters. Called by ``ui.mesh`` for footprints whose model type is "tube";
the component value picks the tube ("12AX7", "EL84", "6L6GC" ...)."""
from __future__ import annotations

import math

import numpy as np

from ..ui.mesh import Parts, _tht_pins, box, cylinder, dome, mat, prism
from .tubes import Tube, find_tube

GLASS = mat("#e8f0f4", 1.0, 140, 0.0, alpha=0.14)
GLASS_TIP = mat("#e8f0f4", 1.0, 140, 0.0, alpha=0.35)
GETTER = mat("#d4d8de", 0.95, 110, 1.0)
PLATE = mat("#45484d", 0.55, 34, 0.55)
PLATE_DARK = mat("#2a2c30", 0.4, 24, 0.4)
MICA = mat("#8f8573", 0.1, 10, 0.0)
WIRE = mat("#b7bbc1", 0.8, 50, 1.0)
GLOW = mat("#ff7d26", 0.0, 1.0, 0.0, emit=1.0)
HALO = mat("#ff8a30", 0.0, 1.0, 0.0, alpha=0.22, emit=1.0)
BAKELITE = mat("#2b1f18", 0.35, 30)
SADDLE = mat("#c4c7cc", 0.85, 60, 1.0)
HOLE = mat("#0b0b0c", 0.1, 10)

# radius of the tube's own pin circle (contacts on top of the socket)
_TUBE_PIN_R = {"noval": 11.89 / 2, "b7g": 9.53 / 2, "octal": 17.45 / 2}
_DEFAULT = {"noval": "12AX7", "b7g": "6AQ5", "octal": "6V6GT"}


def _squash(arr: np.ndarray, z0: float, k: float) -> np.ndarray:
    """Scale a dome vertically about z0 (keeps the normals right); a negative k turns it upside down."""
    out = arr.copy()
    out[:, 2] = z0 + (out[:, 2] - z0) * k
    out[:, 5] = out[:, 5] / (k if abs(k) > 1e-3 else 1e-3)
    n = np.linalg.norm(out[:, 3:6], axis=1, keepdims=True)
    out[:, 3:6] = out[:, 3:6] / np.maximum(n, 1e-6)
    return out


def _socket(parts: Parts, m: dict, base: str) -> float:
    r = m.get("socket_d", 22.0) / 2
    h = m.get("socket_h", 9.0)
    body = mat(m.get("socket_c", "#2a2523"), 0.35 if not m.get("ceramic") else 0.55, 30 if not m.get("ceramic") else 60)
    parts.add(body, cylinder(0, 0, 0.3, h - 1.2, r, 40))
    parts.add(body, cylinder(0, 0, h - 1.2, h, r * 0.88, 40))
    parts.add(body, cylinder(0, 0, h - 1.2, h - 1.19, r, 40))  # top face of the lower part
    pr = _TUBE_PIN_R[base]
    positions, pins, a1 = {"noval": (10, 9, -54.0), "b7g": (8, 7, -45.0), "octal": (8, 8, -67.5)}[base]
    for n in range(pins):
        a = math.radians(a1 + 360.0 / positions * n)
        parts.add(HOLE, cylinder(pr * math.cos(a), -pr * math.sin(a), h, h + 0.02, 0.75 if base != "octal" else 1.2, 10))
    parts.add(HOLE, cylinder(0, 0, h, h + 0.02, 2.0 if base != "octal" else 4.2, 16))
    if m.get("saddle"):
        L, W, hole = m["saddle"]
        pts = []
        for i in range(25):  # stadium-shaped mounting plate
            a = math.pi / 2 + math.pi * i / 24
            pts.append((-(L / 2 - W / 2) + W / 2 * math.cos(a), -W / 2 * math.sin(a)))
        pts += [(-x, -y) for x, y in pts]
        z = h - 3.0
        parts.add(SADDLE, prism(pts, z, z + 0.8, top=True, bottom=True))
        for sx in (-1, 1):
            parts.add(HOLE, cylinder(sx * hole / 2, 0, z - 0.01, z + 0.82, 1.75, 16))
    return h


def _plate_unit(parts: Parts, cx: float, cy: float, z0: float, w: float, d: float, h: float, glow: float,
                fins: bool = False, dark: bool = False) -> None:
    """Two plate halves with the glowing cathode between them, heater glow peeking out top and bottom."""
    gap = 0.45
    mat_p = PLATE_DARK if dark else PLATE
    parts.add(mat_p, box(cx - w / 2, cy - d / 2, z0, cx + w / 2, cy - gap, z0 + h))
    parts.add(mat_p, box(cx - w / 2, cy + gap, z0, cx + w / 2, cy + d / 2, z0 + h))
    if fins:  # beam-tetrode / pentode cooling wings
        for sx in (-1, 1):
            parts.add(mat_p, box(cx + sx * w / 2, cy - 0.15, z0 + h * 0.05, cx + sx * (w / 2 + d * 0.55), cy + 0.15,
                                 z0 + h * 0.95))
    parts.add(GLOW, box(cx - w * 0.3, cy - gap * 0.6, z0 + 0.4, cx + w * 0.3, cy + gap * 0.6, z0 + h - 0.4))
    for zz in (z0 - glow, z0 + h):  # the heater glowing where the cathode sleeve leaves the plates
        parts.add(GLOW, cylinder(cx, cy, zz, zz + glow, 0.75, 12, top=True, bottom=True))
        hz = zz + glow / 2
        parts.add(HALO, _squash(dome(cx, cy, hz, 2.2, 12, 4), hz, 0.7))
        parts.add(HALO, _squash(dome(cx, cy, hz, 2.2, 12, 4), hz, -0.7))


def _tube(parts: Parts, t: Tube, base: str, z0: float) -> None:
    d, H, base_h = t.shape
    R = d / 2
    zg = z0  # bottom of the glass
    if base == "octal":
        rb = min(15.0, R * 0.98)
        parts.add(BAKELITE, cylinder(0, 0, z0, z0 + base_h, rb, 40))
        parts.add(BAKELITE, cylinder(0, 0, z0 + base_h - 1.5, z0 + base_h, min(R * 0.98, rb + 1.0), 40))
        zg = z0 + base_h
    straight = max(4.0, H - R * 0.75)
    ztop = zg + straight
    # internals first (opaque), the glass is drawn transparent over them
    pr = _TUBE_PIN_R[base] * (0.8 if base != "octal" else 0.55)
    struct_z0 = zg + max(5.0, H * 0.14)
    struct_h = straight * (0.55 if t.kind in ("triode2",) else 0.7) - (struct_z0 - zg) * 0.3
    struct_h = max(8.0, min(struct_h, ztop - struct_z0 - 4.0))
    for i in range(8 if base != "b7g" else 7):
        a = math.radians(-54.0 + 40.0 * i)
        parts.add(WIRE, cylinder(pr * math.cos(a), -pr * math.sin(a), zg, struct_z0, 0.22, 6, top=False))
    if t.kind == "triode2":
        w, dd = min(7.5, R * 0.62), min(3.6, R * 0.32)
        for sx in (-1, 1):
            _plate_unit(parts, sx * R * 0.42, 0.0, struct_z0, w, dd, struct_h, 1.0)
    elif t.kind == "rectifier":
        w, dd = min(10.0, R * 0.6), min(5.0, R * 0.35)
        for sx in (-1, 1):
            _plate_unit(parts, sx * R * 0.4, 0.0, struct_z0, w, dd, struct_h, 1.4, dark=True)
    else:
        w, dd = min(R * 0.95, 22.0), min(R * 0.5, 12.0)
        _plate_unit(parts, 0.0, 0.0, struct_z0, w, dd, struct_h, 1.2, fins=t.kind == "power")
    for zz in (struct_z0 - 0.9, struct_z0 + struct_h + 0.6):  # mica spacers
        parts.add(MICA, cylinder(0, 0, zz, zz + 0.3, R * 0.86, 32, top=True, bottom=True))
    # getter: a ring above the structure and the silver flash on the inside of the top
    zr = min(ztop - 1.0, struct_z0 + struct_h + 3.0)
    parts.add(GETTER, cylinder(0, 0, zr, zr + 1.2, min(3.0, R * 0.3), 16, top=True, bottom=True))
    parts.add(GETTER, _squash(dome(0, 0, ztop, R * 0.97, 32, 8), ztop, 0.72))
    # glass: straight wall, domed top, the sealed exhaust tip and the pressed base
    parts.add(GLASS, cylinder(0, 0, zg, ztop, R, 40, top=False, bottom=base != "octal"))
    parts.add(GLASS, _squash(dome(0, 0, ztop, R, 32, 8), ztop, 0.75))
    tip = ztop + R * 0.75
    parts.add(GLASS_TIP, cylinder(0, 0, tip - 0.6, tip + 2.6, 1.4, 12, top=False))
    parts.add(GLASS_TIP, dome(0, 0, tip + 2.6, 1.4, 12, 4))


def tube_parts(parts: Parts, c, m: dict) -> None:
    base = m.get("base", "noval")
    h = _socket(parts, m, base)
    _tht_pins(parts, c, 1.0)
    value = (c.value or "").strip()
    t = find_tube(value)
    if t is None and not value:
        t = find_tube(_DEFAULT[base])
    if t is not None and t.base == base:
        _tube(parts, t, base, h + 0.4)
