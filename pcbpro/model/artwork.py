"""Non-copper fabrication layers: solder mask, paste and silkscreen geometry."""
from __future__ import annotations

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .board import Component, Graphic, Project
from .copper import pad_geom, via_geom
from .geometry import arc_points
from .textgeom import text_geometry


def side_of(layer: str) -> str:
    return "top" if layer.startswith("F.") else "bottom"


def _pad_on_side(c: Component, pad, side: str) -> bool:
    if pad.kind in ("tht", "npth"):
        return True
    return c.side == side


def mask_openings(project: Project, side: str) -> BaseGeometry:
    def build():
        exp = project.rules.mask_expansion
        geoms = []
        for c in project.components:
            for pad in c.footprint.pads:
                if not _pad_on_side(c, pad, side):
                    continue
                m = pad.mask_margin if pad.mask_margin is not None else exp
                geoms.append(pad_geom(c, pad, m))
        if not project.rules.tent_vias:
            for v in project.vias:
                geoms.append(via_geom(v, exp))
        return unary_union(geoms) if geoms else Polygon()

    return project.cached(f"mask_{side}", build)


def paste_shapes(project: Project, side: str) -> BaseGeometry:
    def build():
        geoms = []
        for c in project.components:
            if c.side != side:
                continue
            for pad in c.footprint.pads:
                if pad.kind == "smd" and pad.paste:
                    geoms.append(pad_geom(c, pad))
        return unary_union(geoms) if geoms else Polygon()

    return project.cached(f"paste_{side}", build)


def graphic_geometry(gr: Graphic) -> BaseGeometry:
    w = max(gr.width, 0.01) / 2
    if gr.kind == "line":
        return LineString(gr.pts).buffer(w, quad_segs=4)
    if gr.kind == "circle":
        (cx, cy), = gr.pts
        if gr.fill:
            return Point(cx, cy).buffer(gr.r + w, quad_segs=8)
        return Point(cx, cy).buffer(gr.r + w, quad_segs=8).difference(Point(cx, cy).buffer(max(gr.r - w, 0), quad_segs=8))
    if gr.kind == "arc":
        (cx, cy), = gr.pts
        return LineString(arc_points(cx, cy, gr.r, gr.start, gr.sweep, 0.15)).buffer(w, quad_segs=4)
    if gr.kind == "poly":
        if gr.fill:
            return Polygon(gr.pts).buffer(w)
        return LineString(list(gr.pts) + [gr.pts[0]]).buffer(w, quad_segs=4)
    return Polygon()


def value_anchor(c: Component) -> tuple[float, float]:
    """Board position of the silkscreen value: below the part, or in place of a hidden reference."""
    if not (c.show_ref and c.ref):
        return c.to_board(*c.footprint.ref_pos)
    return c.to_board(0.0, c.footprint.courtyard[3] + 0.9)


def component_silk(c: Component, include_ref: bool = True) -> BaseGeometry:
    geoms = [c.geom_to_board(graphic_geometry(g)) for g in c.footprint.graphics if g.layer == "silk"]
    rot = c.rotation % 180  # keep designators readable
    if include_ref and c.show_ref and c.ref:
        rx, ry = c.to_board(*c.footprint.ref_pos)
        geoms.append(text_geometry(c.ref, rx, ry, 0.9, rot, c.mirror))
    if include_ref and c.show_value and c.value:
        vx, vy = value_anchor(c)
        geoms.append(text_geometry(c.value, vx, vy, 0.9, rot, c.mirror))
    return unary_union(geoms) if geoms else Polygon()


def silkscreen(project: Project, side: str, clip: bool = True) -> BaseGeometry:
    def build():
        layer = "F.SilkS" if side == "top" else "B.SilkS"
        geoms = []
        for c in project.components:
            if c.side == side:
                geoms.append(component_silk(c))
        for t in project.texts:
            if t.layer == layer:
                geoms.append(text_geometry(t.text, t.x, t.y, t.size, t.rotation, t.mirrored))
        g = unary_union(geoms) if geoms else Polygon()
        if clip and not g.is_empty:
            g = g.difference(mask_openings(project, side).buffer(0.05))
            board = project.board.polygon()
            if not board.is_empty:
                g = g.intersection(board)
        return g

    return project.cached(f"silk_{side}_{clip}", build)


def copper_text(project: Project, layer: str) -> BaseGeometry:
    geoms = [text_geometry(t.text, t.x, t.y, t.size, t.rotation, t.mirrored) for t in project.texts if t.layer == layer]
    return unary_union(geoms) if geoms else Polygon()
