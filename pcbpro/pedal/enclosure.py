"""Pedal enclosures: the Hammond catalogue, board placement and panel (drill) holes.

Coordinate systems
------------------
Board coordinates are the layout editor's: mm, X right, Y down, seen from the top (F.Cu) side.

Panel coordinates follow Tayda's drill-service convention. Every side is measured in mm from its own
centre in the *unfolded* drawing, +X right and +Y up:

    A  the face with the knobs, seen from outside with the pedal upright (knobs up, footswitch down)
    B  top side (north wall) - drawn above A
    C  left side (west wall) - drawn left of A
    D  bottom side (south wall) - drawn below A
    E  right side (east wall) - drawn right of A

On B-E the fold line (the edge shared with A) is the edge nearest to A in the unfolded drawing.

Depth ``z`` is measured from the outside of face A into the box: 0 is the outer surface of the face and
``spec.depth`` is the rim where the lid (the pedal's base plate) sits.

Most pedal PCBs hang from their pots: the pots are soldered to the *back* of the board, so the face of the
enclosure sees the board's bottom side and everything is mirrored left/right relative to the layout view.
``Enclosure.face_side`` records which PCB side faces panel A and every conversion here honours it, so the
drill template is never accidentally mirrored.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, fields, replace

from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from ..model.board import Component, Project, new_uid
from ..model.geometry import rounded_rect_points

FACES = ("A", "B", "C", "D", "E")
FACE_NAMES = {"A": "Face", "B": "Top side", "C": "Left side", "D": "Bottom side", "E": "Right side"}
SIDE_WALLS = ("B", "C", "D", "E")


# --------------------------------------------------------------------------- catalogue

@dataclass(frozen=True)
class EnclosureSpec:
    """Die-cast enclosure dimensions (mm). Pairs are (short side, long side)."""

    key: str
    ext: tuple  # external size at the rim
    face: tuple  # the drilled face
    cavity: tuple  # internal cavity at the face
    depth: float  # body height without the lid
    wall: float
    draft: float  # casting draft per side, face -> rim
    corner_r: float  # external corner radius
    boss: float  # how far each lid-screw boss reaches in from both walls
    screws: int = 4  # 6 = extra bosses in the middle of the long walls
    orientation: str = "portrait"  # usual orientation for pedals
    blurb: str = ""

    @property
    def name(self) -> str:
        return f"Hammond {self.key}"

    @property
    def face_t(self) -> float:
        """Thickness of the drilled face (approximate: walls plus half a millimetre)."""
        return round(self.wall + 0.5, 2)

    @property
    def usable(self) -> tuple:
        return (round(self.cavity[0] - 2 * self.boss, 2), round(self.cavity[1] - 2 * self.boss, 2))

    def describe(self) -> str:
        return (f"{self.name}: {self.ext[0]:g} × {self.ext[1]:g} × {self.depth:g} mm outside, cavity "
                f"{self.cavity[0]:g} × {self.cavity[1]:g} mm, flat area inside the screw bosses "
                f"{self.usable[0]:g} × {self.usable[1]:g} mm.")


# Hammond dimensions derived from Hammond's CAD data (as tabulated by stompboxlayout.com). The face thickness
# and the lid are approximations; always check critical fits against the enclosure you actually buy.
CATALOG: dict[str, EnclosureSpec] = {s.key: s for s in (
    EnclosureSpec("1590LB", (50.6, 50.6), (49.3, 49.3), (45.4, 45.4), 27.0, 2.0, 0.7, 5.0, 4.2,
                  blurb="Tiny square box: one knob and a footswitch."),
    EnclosureSpec("1590A", (38.5, 92.6), (37.1, 91.2), (33.6, 87.7), 27.0, 1.8, 0.7, 5.3, 4.0,
                  blurb="Mini pedal: boosts, simple fuzzes, utilities."),
    EnclosureSpec("1590B", (60.5, 112.4), (59.3, 111.2), (55.3, 107.2), 27.0, 2.0, 0.6, 5.5, 4.0,
                  blurb="The classic small pedal box (2-3 knobs)."),
    EnclosureSpec("1590BS", (60.5, 112.0), (58.6, 110.1), (54.6, 106.1), 38.0, 2.0, 1.0, 5.1, 4.0,
                  blurb="1590B footprint with extra depth."),
    EnclosureSpec("125B", (65.5, 121.2), (63.6, 119.3), (60.1, 115.8), 35.8, 1.8, 1.0, 4.5, 4.0,
                  blurb="Most popular DIY size; deep enough for top-mounted jacks."),
    EnclosureSpec("1590BB", (94.0, 119.5), (91.4, 116.9), (86.9, 112.4), 30.0, 2.3, 1.3, 4.3, 4.0,
                  blurb="Wide box for 4-6 knobs or dual circuits."),
    EnclosureSpec("1590BB2", (94.0, 119.5), (92.6, 118.1), (88.1, 113.6), 33.8, 2.3, 0.7, 4.9, 4.0,
                  blurb="1590BB with more depth."),
    EnclosureSpec("1590XX", (121.2, 145.2), (119.4, 143.4), (114.9, 138.9), 35.2, 2.3, 0.9, 5.0, 4.8,
                  blurb="Large box for complex builds and two footswitches."),
    EnclosureSpec("1590DD", (120.0, 188.0), (117.7, 185.7), (112.7, 180.7), 33.0, 2.5, 1.2, 5.0, 4.4, 6,
                  "landscape", "Very wide box for multi-footswitch pedals."),
)}
CATALOG["1590N1"] = replace(CATALOG["125B"], key="1590N1", blurb="Older name for the 125B size.")


def spec_for(key: str) -> EnclosureSpec | None:
    return CATALOG.get(key)


# --------------------------------------------------------------------------- panel hardware

@dataclass(frozen=True)
class Hardware:
    """Typical panel hardware. Diameters are finished holes in bare aluminium (add paint allowance for powder
    coat). ``body_r``/``body_len`` describe the part body inside the box; ``outer_d`` the knob, cap or nut."""

    kind: str
    label: str
    d: float
    body_r: float
    body_len: float
    outer_d: float
    faces: str = "A"


HARDWARE: dict[str, Hardware] = {h.kind: h for h in (
    Hardware("pot", "Pot, 16 mm (M7 bushing)", 7.5, 8.5, 10.7, 20.0),
    Hardware("pot9", "Pot, 9 mm", 7.2, 5.5, 7.0, 15.0),
    Hardware("footswitch", "3PDT footswitch", 12.2, 11.0, 28.0, 14.0),
    Hardware("jack", '1/4" jack', 9.7, 9.0, 22.0, 14.0, "BCDE"),
    Hardware("dc", "DC jack 2.1 mm", 12.0, 7.0, 18.0, 15.0, "BCDE"),
    Hardware("led3", "3 mm LED", 3.2, 2.0, 6.0, 3.0),
    Hardware("led5", "5 mm LED", 5.2, 3.0, 9.0, 5.0),
    Hardware("bezel3", "3 mm LED bezel", 6.2, 4.0, 10.0, 8.0),
    Hardware("bezel5", "5 mm LED bezel", 8.0, 5.0, 12.0, 10.0),
    Hardware("toggle", "Mini toggle", 6.2, 7.0, 18.0, 11.0),
    Hardware("submini", "Sub-mini toggle", 5.2, 4.5, 13.0, 8.0),
    Hardware("rotary", "Rotary switch", 10.0, 13.0, 20.0, 20.0),
    Hardware("custom", "Custom hole", 5.0, 0.0, 0.0, 0.0, "ABCDE"),
)}

POWDER_COATS = {
    "Raw aluminium": ("#c9ccd1", True), "Black": ("#1d1d20", False), "White": ("#ecebe6", False),
    "Cream": ("#eee2c2", False), "Red": ("#b3261f", False), "Orange": ("#e3671c", False),
    "Yellow": ("#eec21f", False), "Green": ("#2d7a4c", False), "Teal": ("#1c8585", False),
    "Blue": ("#1f53a6", False), "Purple": ("#5b2c8a", False), "Pink": ("#df669e", False),
    "Gold sparkle": ("#c9a13b", True), "Silver sparkle": ("#b7bac0", True),
}
KNOB_COLORS = {"Black": "#151517", "Cream": "#ebe0c3", "White": "#f2f2ee", "Chrome": "#d7d9dd", "Red": "#b8241c",
               "Gold": "#d4ad4c"}

PAINT_ALLOWANCE = 0.4  # powder coat is ~0.2 mm per side


# --------------------------------------------------------------------------- holes

@dataclass(eq=False)
class PanelHole:
    face: str
    x: float  # mm from the centre of the side, +right (Tayda convention)
    y: float  # mm from the centre of the side, +up
    d: float
    label: str = ""
    kind: str = "custom"
    uid: str = field(default_factory=new_uid)
    # runtime only: holes derived from a board component
    comp_uid: str = ""
    ref: str = ""
    body_r: float = 0.0
    body_len: float = 0.0
    outer_d: float = 0.0
    wrong_side: bool = False

    PERSIST = ("face", "x", "y", "d", "label", "kind", "uid")

    @property
    def derived(self) -> bool:
        return bool(self.comp_uid)

    @property
    def hardware(self) -> Hardware:
        return HARDWARE.get(self.kind, HARDWARE["custom"])

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.PERSIST}

    @classmethod
    def from_dict(cls, d: dict) -> "PanelHole":
        return cls(**{k: d[k] for k in cls.PERSIST if k in d})

    @classmethod
    def of(cls, kind: str, face: str, x: float, y: float, label: str = "") -> "PanelHole":
        hw = HARDWARE.get(kind, HARDWARE["custom"])
        return cls(face, round(x, 2), round(y, 2), hw.d, label or hw.label, kind)

    def effective_body(self) -> tuple[float, float, float]:
        """(body radius, body length, outer diameter) - explicit values win over the hardware preset."""
        hw = self.hardware
        return (self.body_r or hw.body_r, self.body_len or hw.body_len, self.outer_d or hw.outer_d)


# --------------------------------------------------------------------------- placement

@dataclass
class Enclosure:
    """Where the board sits inside an enclosure, plus the manually placed panel holes."""

    model: str = "125B"
    orientation: str = ""  # portrait | landscape; "" = the enclosure's usual orientation
    cx: float = 0.0  # board coordinates of the centre of face A
    cy: float = 0.0
    face_side: str = "bottom"  # PCB side facing panel A (the side the pots are soldered to)
    standoff: float = 0.0  # face inner surface -> near PCB surface; 0 = automatic from the pots
    color: str = "Raw aluminium"
    knob_color: str = "Black"
    knob_d: float = 20.0
    led_hole: str = "bezel"  # bezel | bare
    paint_allowance: float = 0.0
    lid_clearance: float = 1.0  # keep parts this far away from the base plate
    holes: list = field(default_factory=list)

    # ------------------------------------------------------------------ persistence
    def to_dict(self) -> dict:
        d = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "holes"}
        d["holes"] = [h.to_dict() for h in self.holes]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Enclosure":
        known = {f.name for f in fields(cls)}
        e = cls(**{k: v for k, v in d.items() if k in known and k != "holes"})
        e.holes = [PanelHole.from_dict(h) for h in d.get("holes", [])]
        return e

    # ------------------------------------------------------------------ geometry
    @property
    def spec(self) -> EnclosureSpec:
        return CATALOG.get(self.model) or CATALOG["125B"]

    @property
    def landscape(self) -> bool:
        return (self.orientation or self.spec.orientation) == "landscape"

    def _wh(self, pair) -> tuple[float, float]:
        s, l = pair
        return (l, s) if self.landscape else (s, l)

    @property
    def face_size(self) -> tuple[float, float]:
        return self._wh(self.spec.face)

    @property
    def cavity_size(self) -> tuple[float, float]:
        return self._wh(self.spec.cavity)

    @property
    def ext_size(self) -> tuple[float, float]:
        return self._wh(self.spec.ext)

    @property
    def mirror(self) -> float:
        """-1 when panel A sees the board's bottom side (left/right swapped relative to the layout)."""
        return 1.0 if self.face_side == "top" else -1.0

    def board_to_face(self, x: float, y: float) -> tuple[float, float]:
        return self.mirror * (x - self.cx), -(y - self.cy)

    def face_to_board(self, u: float, v: float) -> tuple[float, float]:
        return self.cx + self.mirror * u, self.cy - v

    def geom_to_face(self, g: BaseGeometry) -> BaseGeometry:
        s = self.mirror
        return affinity.affine_transform(g, [s, 0.0, 0.0, -1.0, -s * self.cx, self.cy])

    def geom_to_board(self, g: BaseGeometry) -> BaseGeometry:
        s = self.mirror
        return affinity.affine_transform(g, [s, 0.0, 0.0, -1.0, self.cx, self.cy])

    def side_size(self, face: str) -> tuple[float, float]:
        """Unfolded drawing size of a side (width, height) using the drilled-face edge lengths."""
        W, H = self.face_size
        d = self.spec.depth
        return {"A": (W, H), "B": (W, d), "D": (W, d), "C": (d, H), "E": (d, H)}[face]

    # ------------------------------------------------------------------ depth
    def resolved_standoff(self, project: Project | None) -> float:
        if self.standoff > 0:
            return self.standoff
        best = 0.0
        if project is not None:
            for c in project.components:
                meta = c.footprint.model.get("panel") or {}
                if meta.get("face") == "A" and c.side == self.face_side and meta.get("standoff"):
                    best = max(best, float(meta["standoff"]))
        return best or HARDWARE["pot"].body_len

    def z_levels(self, project: Project) -> tuple[float, float]:
        """Depth of the PCB surface nearest to panel A and of the far surface."""
        near = self.spec.face_t + self.resolved_standoff(project)
        return near, near + project.board.thickness

    def part_z(self, project: Project, side: str, h: float) -> float:
        """Depth of a point ``h`` mm above the surface of PCB side ``side``."""
        near, far = self.z_levels(project)
        return near - h if side == self.face_side else far + h

    def free_depth(self, project: Project) -> float:
        """Height available for parts on the far side of the board (towards the base plate)."""
        return self.spec.depth - self.z_levels(project)[1] - self.lid_clearance

    # ------------------------------------------------------------------ keep-outs (panel A coordinates)
    def cavity_polygon(self) -> Polygon:
        W, H = self.cavity_size
        r = max(0.5, self.spec.corner_r - self.spec.wall)
        return Polygon(rounded_rect_points(-W / 2, -H / 2, W, H, r))

    def face_polygon(self) -> Polygon:
        W, H = self.face_size
        return Polygon(rounded_rect_points(-W / 2, -H / 2, W, H, self.spec.corner_r))

    def boss_polygons(self) -> list[Polygon]:
        """Lid screw bosses, modelled as squares in the cavity corners (plus mid-wall bosses on 6-screw boxes)."""
        W, H = self.cavity_size
        b = self.spec.boss
        out = []
        for sx in (-1, 1):
            for sy in (-1, 1):
                x0, x1 = sorted((sx * W / 2, sx * (W / 2 - b)))
                y0, y1 = sorted((sy * H / 2, sy * (H / 2 - b)))
                out.append(box(x0, y0, x1, y1).buffer(-0.8).buffer(0.8))
        if self.spec.screws == 6:
            long_is_x = W > H
            for s in (-1, 1):
                if long_is_x:
                    y0, y1 = sorted((s * H / 2, s * (H / 2 - b)))
                    out.append(box(-b, y0, b, y1).buffer(-0.8).buffer(0.8))
                else:
                    x0, x1 = sorted((s * W / 2, s * (W / 2 - b)))
                    out.append(box(x0, -b, x1, b).buffer(-0.8).buffer(0.8))
        return out

    def usable_polygon(self, clearance: float = 0.0) -> BaseGeometry:
        cav = self.cavity_polygon().buffer(-clearance, join_style="mitre") if clearance else self.cavity_polygon()
        bosses = unary_union(self.boss_polygons())
        if clearance:
            bosses = bosses.buffer(clearance)
        return cav.difference(bosses)


# --------------------------------------------------------------------------- project access

def get_enclosure(project: Project) -> Enclosure | None:
    data = getattr(project, "pedal", {}) or {}
    enc = data.get("enclosure")
    if not enc or not enc.get("model"):
        return None
    try:
        return Enclosure.from_dict(enc)
    except TypeError:
        return None


def set_enclosure(project: Project, enc: Enclosure | None) -> None:
    if not hasattr(project, "pedal") or project.pedal is None:
        project.pedal = {}
    if enc is None:
        project.pedal.pop("enclosure", None)
    else:
        project.pedal["enclosure"] = enc.to_dict()


def centre_on_board(project: Project, enc: Enclosure) -> None:
    """Centre the enclosure on the board outline."""
    x0, y0, x1, y1 = project.board.bounds()
    enc.cx, enc.cy = round((x0 + x1) / 2, 3), round((y0 + y1) / 2, 3)


# --------------------------------------------------------------------------- holes derived from the board

def _local_dir(c: Component, deg: float) -> tuple[float, float]:
    """Board-space unit vector of a direction given in footprint coordinates (degrees, CCW on screen)."""
    a = math.radians(deg)
    ox, oy = c.to_board(0.0, 0.0)
    px, py = c.to_board(math.cos(a), -math.sin(a))
    dx, dy = px - ox, py - oy
    n = math.hypot(dx, dy) or 1.0
    return dx / n, dy / n


def _led_meta(c: Component, enc: Enclosure) -> dict | None:
    m = c.footprint.model
    name = c.footprint.name
    size = None
    if m.get("type") == "led_tht":
        size = m.get("D", 5)
    elif name.startswith(("LED_D3", "LED_D5")) and any(p.kind == "tht" for p in c.footprint.pads):
        size = 3 if name.startswith("LED_D3") else 5
    if size is None:
        return None
    small = float(size) < 4
    kind = ("bezel3" if small else "bezel5") if enc.led_hole == "bezel" else ("led3" if small else "led5")
    return {"face": "A", "kind": kind}


def side_position(enc: Enclosure, wall: str, u: float, v: float, z: float) -> tuple[float, float]:
    """Unfolded Tayda coordinates on a side wall for a point on that wall at face position (u, v), depth z."""
    d = enc.spec.depth
    if wall == "B":
        return u, z - d / 2
    if wall == "D":
        return u, d / 2 - z
    if wall == "C":
        return d / 2 - z, v
    if wall == "E":
        return z - d / 2, v
    return u, v


def side_to_face(enc: Enclosure, wall: str, x: float, y: float) -> tuple[float, float, float]:
    """Inverse of :func:`side_position`: (u, v, z) of a side-wall hole centre (u/v on the wall plane)."""
    d = enc.spec.depth
    W, H = enc.cavity_size
    if wall == "B":
        return x, H / 2, y + d / 2
    if wall == "D":
        return x, -H / 2, d / 2 - y
    if wall == "C":
        return -W / 2, y, d / 2 - x
    if wall == "E":
        return W / 2, y, x + d / 2
    return x, y, 0.0


def derived_holes(project: Project, enc: Enclosure) -> list[PanelHole]:
    """Panel holes implied by board-mounted pots, switches, LEDs and jacks."""
    out: list[PanelHole] = []
    for c in project.components:
        meta = c.footprint.model.get("panel")
        if not meta:
            meta = _led_meta(c, enc)
            if not meta:
                continue
        kind = meta.get("kind", "custom")
        hw = HARDWARE.get(kind, HARDWARE["custom"])
        d = float(meta.get("d", hw.d))
        lx, ly = meta.get("at", (0.0, 0.0))
        bx, by = c.to_board(lx, ly)
        u, v = enc.board_to_face(bx, by)
        label = f"{c.ref} {c.value}".strip()
        common = dict(label=label, kind=kind, comp_uid=c.uid, ref=c.ref, body_r=float(meta.get("body_r", 0.0)),
                      body_len=float(meta.get("body_len", 0.0)), outer_d=float(meta.get("outer_d", 0.0)),
                      uid=f"{c.uid}:{kind}")
        if meta.get("face", "A") == "A":
            h = PanelHole("A", round(u, 3), round(v, 3), d, **common)
            h.wrong_side = c.side != enc.face_side
            if kind == "pot" and not h.outer_d:
                h.outer_d = enc.knob_d
            out.append(h)
            continue
        # side-wall part: follow its axis to the wall it points at
        dx, dy = _local_dir(c, float(meta.get("dir", 0.0)))
        du, dv = enc.mirror * dx, -dy
        if abs(du) >= abs(dv):
            wall = "E" if du > 0 else "C"
        else:
            wall = "B" if dv > 0 else "D"
        z = enc.part_z(project, c.side, float(meta.get("axis_h", 5.0)))
        sx, sy = side_position(enc, wall, u, v, z)
        out.append(PanelHole(wall, round(sx, 3), round(sy, 3), d, **common))
    return out


def all_holes(project: Project, enc: Enclosure) -> list[PanelHole]:
    return derived_holes(project, enc) + list(enc.holes)


def export_diameter(h: PanelHole, enc: Enclosure) -> float:
    return round(h.d + enc.paint_allowance, 2)


def hole_face_point(enc: Enclosure, h: PanelHole) -> tuple[float, float, float]:
    """(u, v, z) of a hole centre in panel-A coordinates (z = 0 for holes in the face)."""
    if h.face == "A":
        return h.x, h.y, 0.0
    return side_to_face(enc, h.face, h.x, h.y)


# --------------------------------------------------------------------------- layout helpers

def fit_outline(enc: Enclosure, v_top: float | None = None, v_bottom: float | None = None,
                clearance: float = 0.8) -> list[tuple[float, float]]:
    """Largest board outline (board coordinates) that fits the cavity, notched around the screw bosses and
    optionally limited to the band v_bottom <= v <= v_top of panel A."""
    region = enc.usable_polygon(clearance)
    W, H = enc.cavity_size
    top = H / 2 if v_top is None else v_top
    bot = -H / 2 if v_bottom is None else v_bottom
    region = region.intersection(box(-W, bot, W, top))
    polys = [p for p in getattr(region, "geoms", [region]) if isinstance(p, Polygon) and not p.is_empty]
    if not polys:
        return []
    poly = max(polys, key=lambda p: p.area).simplify(0.05)
    board = enc.geom_to_board(poly)
    return [(round(x, 3), round(y, 3)) for x, y in list(board.exterior.coords)[:-1]]


# where a pot's terminals run, relative to its shaft: (distance of the pin row below the shaft, half the row width)
POT_PINS = {"pot": (16.0, 6.1), "pot9": (7.5, 3.4)}
# footprint courtyards around the shaft: (half width, extent above, extent below)
POT_COURTYARD = {"pot": (8.75, 8.75, 17.35), "pot9": (6.75, 5.85, 8.65)}


def knob_layout(n: int, enc: Enclosure, kind: str = "pot", v_top: float | None = None) -> list[tuple[float, float]]:
    """Pleasant default knob positions (panel A coordinates) for ``n`` pots, top row first.

    Lower rows are pushed down until their bodies clear both the pots above and those pots' terminals, which run
    from the body down to the pin row (16 mm below the shaft on Alpha 16 mm right-angle pots)."""
    if n <= 0:
        return []
    hw = HARDWARE.get(kind, HARDWARE["pot"])
    pin_dy, pin_half = POT_PINS.get(kind, POT_PINS["pot"])
    cw, ca, cb = POT_COURTYARD.get(kind, POT_COURTYARD["pot"])
    W, H = enc.cavity_size
    half = W / 2 - hw.body_r - 1.5
    min_pitch = 2 * hw.body_r + 2.0
    pref_pitch = max(min_pitch, enc.knob_d + 3.0)
    per_row = max(1, int(2 * half // min_pitch) + 1)
    rows = [per_row] * (n // per_row) + ([n % per_row] if n % per_row else [])
    if len(rows) == 3 and rows[-1] < rows[0]:
        rows = [rows[0], rows[2], rows[1]]  # e.g. 2-1-2: the odd knob in the middle row
    top = v_top if v_top is not None else H / 2 - hw.body_r - 2.5
    out: list[tuple[float, float]] = []
    keep = []  # bodies and terminal strips of the pots placed so far
    courts = []  # their courtyards (kept apart too, so DRC stays quiet)
    for r, k in enumerate(rows):
        pitch = min(pref_pitch, 2 * half / (k - 1)) if k > 1 else 0.0
        us = [round((i - (k - 1) / 2) * pitch, 2) for i in range(k)]
        v = top if r == 0 else out[-1][1] - min_pitch
        for _ in range(200):
            bodies = [Point(u, v).buffer(hw.body_r + 0.5, quad_segs=8) for u in us]
            new_courts = [box(u - cw, v - cb, u + cw, v + ca) for u in us]
            if not any(b.intersects(g) for b in bodies for g in keep) and                     not any(c.intersection(o).area > 0.01 for c in new_courts for o in courts):
                break
            v -= 0.5
        for u in us:
            out.append((u, round(v, 2)))
            keep.append(Point(u, v).buffer(hw.body_r + 0.5, quad_segs=8))
            keep.append(box(u - pin_half, v - pin_dy - 1.1, u + pin_half, v - hw.body_r + 1.0))
            courts.append(box(u - cw, v - cb, u + cw, v + ca))
    return out
