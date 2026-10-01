"""Gerber RS-274X (X2) writer and full manufacturing layer set generation."""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from shapely.geometry.base import BaseGeometry

from .. import __version__
from ..model.artwork import copper_text, mask_openings, paste_shapes, silkscreen
from ..model.board import Component, Pad, Project
from ..model.copper import pad_geom
from ..model.geometry import iter_polygons, split_holes


@dataclass
class Origin:
    """Maps model coordinates (Y down) to Gerber coordinates (Y up, board lower-left at 0,0)."""

    x0: float
    y1: float

    def __call__(self, x: float, y: float) -> tuple[float, float]:
        return x - self.x0, self.y1 - y

    @classmethod
    def for_project(cls, project: Project) -> "Origin":
        bx0, _, _, by1 = project.board.bounds()
        return cls(bx0, by1)


def _c(v: float) -> str:
    return str(int(round(v * 1_000_000)))


class GerberWriter:
    def __init__(self, file_function: str, polarity: str = "Positive", origin: Origin | None = None):
        self.file_function = file_function
        self.polarity = polarity
        self.origin = origin or Origin(0, 0)
        self.apertures: dict[tuple, int] = {}
        self.aperture_defs: list[str] = []
        self.body: list[str] = []
        self.current_ap: int | None = None

    # ------------------------------------------------------------------ apertures
    def aperture(self, shape: str, params: tuple, function: str | None = None) -> int:
        key = (shape, tuple(round(p, 6) for p in params), function)
        code = self.apertures.get(key)
        if code is None:
            code = 10 + len(self.apertures)
            self.apertures[key] = code
            ps = "X".join(f"{p:.6f}" for p in params)
            if function:
                self.aperture_defs.append(f"%TA.AperFunction,{function}*%")
            self.aperture_defs.append(f"%ADD{code}{shape},{ps}*%")
            if function:
                self.aperture_defs.append("%TD*%")
        return code

    def _select(self, code: int) -> None:
        if self.current_ap != code:
            self.body.append(f"D{code}*")
            self.current_ap = code

    # ------------------------------------------------------------------ primitives
    def flash(self, code: int, x: float, y: float) -> None:
        self._select(code)
        gx, gy = self.origin(x, y)
        self.body.append(f"X{_c(gx)}Y{_c(gy)}D03*")

    def stroke(self, code: int, pts: list[tuple[float, float]]) -> None:
        if len(pts) < 2:
            return
        self._select(code)
        gx, gy = self.origin(*pts[0])
        self.body.append(f"X{_c(gx)}Y{_c(gy)}D02*")
        for p in pts[1:]:
            gx, gy = self.origin(*p)
            self.body.append(f"X{_c(gx)}Y{_c(gy)}D01*")

    def region(self, coords) -> None:
        pts = list(coords)
        if len(pts) < 3:
            return
        self.body.append("G36*")
        gx, gy = self.origin(*pts[0])
        self.body.append(f"X{_c(gx)}Y{_c(gy)}D02*")
        for p in pts[1:]:
            gx, gy = self.origin(*p)
            self.body.append(f"X{_c(gx)}Y{_c(gy)}D01*")
        if pts[0] != pts[-1]:
            gx, gy = self.origin(*pts[0])
            self.body.append(f"X{_c(gx)}Y{_c(gy)}D01*")
        self.body.append("G37*")

    def geometry(self, g: BaseGeometry) -> None:
        """Fill arbitrary polygon geometry using hole-free regions."""
        for poly in iter_polygons(g):
            for piece in split_holes(poly):
                self.region(piece.exterior.coords)

    def comment(self, text: str) -> None:
        self.body.append(f"G04 {text}*")

    # ------------------------------------------------------------------ output
    def render(self) -> str:
        now = _dt.datetime.now().replace(microsecond=0).isoformat()
        head = [
            f"%TF.GenerationSoftware,PCBPro,PCBPro,{__version__}*%",
            f"%TF.CreationDate,{now}*%",
            "%TF.SameCoordinates,Original*%",
            f"%TF.FileFunction,{self.file_function}*%",
            f"%TF.FilePolarity,{self.polarity}*%",
            "%FSLAX46Y46*%",
            "G04 Gerber Fmt 4.6, Leading zero omitted, Abs format (unit mm)*",
            "%MOMM*%",
            "%LPD*%",
            "G01*",
        ]
        return "\n".join(head + self.aperture_defs + self.body + ["M02*"]) + "\n"


# --------------------------------------------------------------------------- pad emission

def _emit_pad(w: GerberWriter, c: Component, pad: Pad, expand: float, function: str | None) -> None:
    x, y = c.pad_pos(pad)
    pw, ph = pad.w + 2 * expand, pad.h + 2 * expand
    if pw <= 0 or ph <= 0:
        return
    rot = c.pad_rotation(pad) % 180
    if pad.shape == "circle" or (pad.shape == "oval" and abs(pad.w - pad.h) < 1e-9):
        w.flash(w.aperture("C", (pw,), function), x, y)
        return
    if pad.shape in ("rect", "oval") and (abs(rot) < 1e-6 or abs(rot - 90) < 1e-6):
        if abs(rot - 90) < 1e-6:
            pw, ph = ph, pw
        w.flash(w.aperture("R" if pad.shape == "rect" else "O", (pw, ph), function), x, y)
        return
    w.geometry(pad_geom(c, pad, expand))


def _pad_function(pad: Pad) -> str:
    if pad.kind == "smd":
        return "SMDPad,CuDef"
    return "ComponentPad"


# --------------------------------------------------------------------------- layer generators

def copper_layer(project: Project, layer: str, index: int, origin: Origin) -> str:
    n = len(project.copper_layers)
    pos = "Top" if index == 1 else ("Bot" if index == n else "Inr")
    w = GerberWriter(f"Copper,L{index},{pos}", origin=origin)
    for z in project.zones:
        if z.layer == layer and z.uid in project.zone_fills:
            w.comment(f"Zone {z.net or ''}")
            w.geometry(project.zone_fills[z.uid])
    for t in project.tracks:
        if t.layer == layer:
            w.stroke(w.aperture("C", (t.width,), "Conductor"), [(t.x1, t.y1), (t.x2, t.y2)])
    for c in project.components:
        for pad in c.footprint.pads:
            if layer in c.pad_copper_layers(pad, project.copper_layers):
                _emit_pad(w, c, pad, 0.0, _pad_function(pad))
    for v in project.vias:
        w.flash(w.aperture("C", (v.diameter,), "ViaPad"), v.x, v.y)
    txt = copper_text(project, layer)
    if not txt.is_empty:
        w.geometry(txt)
    return w.render()


def mask_layer(project: Project, side: str, origin: Origin) -> str:
    w = GerberWriter(f"Soldermask,{'Top' if side == 'top' else 'Bot'}", "Negative", origin)
    exp = project.rules.mask_expansion
    for c in project.components:
        for pad in c.footprint.pads:
            if pad.kind == "smd" and c.side != side:
                continue
            m = pad.mask_margin if pad.mask_margin is not None else exp
            _emit_pad(w, c, pad, m, None)
    if not project.rules.tent_vias:
        for v in project.vias:
            w.flash(w.aperture("C", (v.diameter + 2 * exp,)), v.x, v.y)
    return w.render()


def paste_layer(project: Project, side: str, origin: Origin) -> str:
    w = GerberWriter(f"Paste,{'Top' if side == 'top' else 'Bot'}", origin=origin)
    for c in project.components:
        if c.side != side:
            continue
        for pad in c.footprint.pads:
            if pad.kind == "smd" and pad.paste:
                _emit_pad(w, c, pad, 0.0, None)
    return w.render()


def silk_layer(project: Project, side: str, origin: Origin) -> str:
    w = GerberWriter(f"Legend,{'Top' if side == 'top' else 'Bot'}", origin=origin)
    w.geometry(silkscreen(project, side))
    return w.render()


def edge_layer(project: Project, origin: Origin) -> str:
    w = GerberWriter("Profile,NP", origin=origin)
    ap = w.aperture("C", (0.1,), "Profile")
    rings = [project.board.outline] + list(project.board.cutouts)
    for ring in rings:
        if len(ring) >= 3:
            pts = list(ring) + [ring[0]]
            w.stroke(ap, pts)
    return w.render()


# Protel-style extensions are recognised by every major fab.
LAYER_FILES = {
    "F.Cu": "GTL", "B.Cu": "GBL", "In1.Cu": "G2", "In2.Cu": "G3",
    "F.Mask": "GTS", "B.Mask": "GBS", "F.SilkS": "GTO", "B.SilkS": "GBO",
    "F.Paste": "GTP", "B.Paste": "GBP", "Edge.Cuts": "GKO",
}


def generate_gerbers(project: Project) -> dict[str, str]:
    """Returns {layer name: gerber text} for the full layer stack."""
    origin = Origin.for_project(project)
    out: dict[str, str] = {}
    for i, layer in enumerate(project.copper_layers, start=1):
        out[layer] = copper_layer(project, layer, i, origin)
    out["F.Mask"] = mask_layer(project, "top", origin)
    out["B.Mask"] = mask_layer(project, "bottom", origin)
    out["F.SilkS"] = silk_layer(project, "top", origin)
    out["B.SilkS"] = silk_layer(project, "bottom", origin)
    out["F.Paste"] = paste_layer(project, "top", origin)
    out["B.Paste"] = paste_layer(project, "bottom", origin)
    out["Edge.Cuts"] = edge_layer(project, origin)
    return out
