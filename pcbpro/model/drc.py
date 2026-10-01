"""Design rule check."""
from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import Point
from shapely.ops import nearest_points
from shapely.strtree import STRtree

from .board import Project
from .connectivity import get_connectivity
from .copper import copper_by_layer, holes


@dataclass
class Violation:
    kind: str
    message: str
    x: float
    y: float
    severity: str = "error"  # error | warning
    uids: list = field(default_factory=list)
    nets: tuple = ()


def pad_annular(pad) -> float:
    if pad.shape == "poly":
        return 1.0  # custom pads: the annular ring is defined by the footprint author
    if pad.is_slot:
        return min((pad.w - pad.drill) / 2, (pad.h - pad.drill_h) / 2)
    return (min(pad.w, pad.h) - pad.drill) / 2


def _label(s) -> str:
    return s.describe() + (f" [{s.net}]" if s.net else "")


def _uid(s) -> str:
    return s.obj.uid


def run_drc(project: Project) -> list[Violation]:
    out: list[Violation] = []
    r = project.rules
    board = project.board.polygon()

    if board.is_empty or not board.is_valid:
        out.append(Violation("outline", "Board outline is missing or invalid", 0, 0))
        return out

    conn = get_connectivity(project)

    # --- clearance & shorts --------------------------------------------------
    reported: set = set()
    for layer, items in copper_by_layer(project).items():
        if len(items) < 2:
            continue
        geoms = [s.geom for s in items]
        tree = STRtree(geoms)
        maxcl = max([nc.clearance for nc in project.netclasses.values()] + [r.clearance]
                    + [z.clearance for z in project.zones])
        left, right = tree.query(geoms, predicate="dwithin", distance=maxcl)
        for i, j in zip(left.tolist(), right.tolist()):
            if i >= j:
                continue
            a, b = items[i], items[j]
            if a.node == b.node:
                continue
            na, nb = conn.effective_net(a), conn.effective_net(b)
            if na is not None and na == nb:
                continue
            if na is None and nb is None and conn.uf.find(a.node) == conn.uf.find(b.node):
                continue
            if a.kind == "pad" and b.kind == "pad" and a.obj is b.obj:
                continue  # pads within one footprint: footprint-level concern
            if a.kind == "zone" and b.kind == "zone" and a.obj is b.obj:
                continue
            cl = max(project.netclass_for(na).clearance, project.netclass_for(nb).clearance, r.clearance)
            if a.kind == "zone" or b.kind == "zone":
                z = a.obj if a.kind == "zone" else b.obj
                cl = max(cl, z.clearance)
            d = a.geom.distance(b.geom)
            if d >= cl - 1e-4:
                continue
            key = (min(a.node, b.node), max(a.node, b.node), layer)
            if key in reported:
                continue
            reported.add(key)
            pa, pb = nearest_points(a.geom, b.geom)
            x, y = (pa.x + pb.x) / 2, (pa.y + pb.y) / 2
            if d <= 1e-6 and na and nb and na != nb:
                out.append(Violation("short", f"Short circuit between {na} and {nb} on {layer} "
                                              f"({_label(a)} / {_label(b)})", x, y, "error", [_uid(a), _uid(b)],
                                     tuple(sorted((na, nb)))))
            else:
                out.append(Violation("clearance", f"Clearance {d:.3f} mm < {cl:.3f} mm on {layer}: "
                                                  f"{_label(a)} to {_label(b)}", x, y, "error", [_uid(a), _uid(b)]))

    # --- widths, drills, annular rings ----------------------------------------
    for t in project.tracks:
        if t.width < r.min_track - 1e-6:
            out.append(Violation("width", f"Track width {t.width:.3f} mm < minimum {r.min_track:.3f} mm",
                                 (t.x1 + t.x2) / 2, (t.y1 + t.y2) / 2, "error", [t.uid]))
    for v in project.vias:
        if v.drill < r.min_drill - 1e-6:
            out.append(Violation("drill", f"Via drill {v.drill:.3f} mm < minimum {r.min_drill:.3f} mm", v.x, v.y,
                                 "error", [v.uid]))
        ann = (v.diameter - v.drill) / 2
        if ann < r.min_annular - 1e-6:
            out.append(Violation("annular", f"Via annular ring {ann:.3f} mm < minimum {r.min_annular:.3f} mm", v.x,
                                 v.y, "error", [v.uid]))
    for c in project.components:
        for pad in c.footprint.pads:
            if pad.kind == "tht":
                x, y = c.pad_pos(pad)
                ann = pad_annular(pad)
                if ann < r.min_annular - 1e-6:
                    out.append(Violation("annular", f"Pad {c.ref}.{pad.number} annular ring {ann:.3f} mm < "
                                                    f"{r.min_annular:.3f} mm", x, y, "warning", [c.uid]))
            if pad.has_hole and pad.min_drill < r.min_drill - 1e-6 and pad.kind == "tht":
                x, y = c.pad_pos(pad)
                out.append(Violation("drill", f"Pad {c.ref}.{pad.number} drill {pad.min_drill:.3f} mm < "
                                              f"{r.min_drill:.3f} mm", x, y, "warning", [c.uid]))

    # --- board edge -----------------------------------------------------------
    edge = board.boundary
    for layer, items in copper_by_layer(project, include_zones=False).items():
        for s in items:
            if s.kind == "pad" and s.pad is not None and s.pad.kind == "npth":
                continue
            d = s.geom.distance(edge)
            inside = board.contains(s.geom)
            if not inside or d < r.edge_clearance - 1e-4:
                p, _ = nearest_points(s.geom, edge)
                msg = "outside the board" if not inside else f"{d:.3f} mm from board edge (min {r.edge_clearance:.2f})"
                key = ("edge", s.node)
                if key in reported:
                    continue
                reported.add(key)
                out.append(Violation("edge", f"{_label(s)} {msg}", p.x, p.y, "error", [_uid(s)]))

    # --- holes ------------------------------------------------------------------
    hl = holes(project)
    if len(hl) > 1:
        pts = [h.geom(quad_segs=4) for h in hl]
        tree = STRtree(pts)
        left, right = tree.query(pts, predicate="dwithin", distance=r.hole_to_hole)
        for i, j in zip(left.tolist(), right.tolist()):
            if i >= j:
                continue
            a, b = hl[i], hl[j]
            if a.owner is b.owner and a.pad is not None and b.pad is not None and a.owner is not None \
                    and getattr(a.owner, "footprint", None) is not None:
                continue
            d = pts[i].distance(pts[j])
            out.append(Violation("hole", f"Hole-to-hole spacing {d:.3f} mm < {r.hole_to_hole:.3f} mm",
                                 (a.x + b.x) / 2, (a.y + b.y) / 2, "error", [a.owner.uid, b.owner.uid]))

    # --- courtyards / placement -----------------------------------------------------
    comps = project.components
    cys = [c.courtyard_polygon() for c in comps]
    for i in range(len(comps)):
        overhang_ok = bool(comps[i].footprint.model.get("panel")) and all(  # e.g. pot bodies past the edge
            board.contains(Point(*comps[i].pad_pos(pad))) for pad in comps[i].footprint.pads)
        if not overhang_ok and not board.buffer(0.01).contains(cys[i]):
            out.append(Violation("placement", f"{comps[i].ref} extends beyond the board outline", comps[i].x,
                                 comps[i].y, "warning", [comps[i].uid]))
        for j in range(i + 1, len(comps)):
            if comps[i].side != comps[j].side:
                continue
            inter = cys[i].intersection(cys[j])
            if inter.area > 0.01:
                p = inter.representative_point()
                out.append(Violation("courtyard", f"Courtyards of {comps[i].ref} and {comps[j].ref} overlap", p.x, p.y,
                                     "warning", [comps[i].uid, comps[j].uid]))

    # --- connectivity ---------------------------------------------------------------
    short_pairs = {v.nets for v in out if v.kind == "short"}
    for s in conn.shorts:
        if len(s.nets) == 2 and tuple(sorted(s.nets)) in short_pairs:
            continue
        out.append(Violation("short", "Nets shorted together: " + ", ".join(s.nets), s.x, s.y, "error", [], s.nets))
    for rl in conn.ratsnest:
        out.append(Violation("unrouted", f"Unrouted connection on net {rl.net} ({rl.length:.1f} mm)",
                             (rl.x1 + rl.x2) / 2, (rl.y1 + rl.y2) / 2, "error"))

    if project.fills_stale:
        out.append(Violation("zones", "Copper zones are out of date - refill before manufacturing", 0, 0, "warning"))

    if getattr(project, "pedal", None):  # enclosure fit, part heights, knob / jack clearances
        from ..pedal.checks import run_pedal_checks
        out.extend(run_pedal_checks(project))

    if getattr(project, "amp", None):  # HV spacing, track current, part ratings, bleeders, tube wiring
        from ..amp.checks import run_amp_checks
        out.extend(run_amp_checks(project))

    sev = {"error": 0, "warning": 1}
    out.sort(key=lambda v: (sev.get(v.severity, 2), v.kind))
    return out
