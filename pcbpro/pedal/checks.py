"""Enclosure-aware checks for pedal builds (run as part of DRC when the design has an enclosure)."""
from __future__ import annotations

import math

from shapely.geometry import Point, box

from ..model.board import Component, Project
from ..model.drc import Violation
from .enclosure import Enclosure, PanelHole, all_holes, get_enclosure, hole_face_point

HEIGHT_MARGIN = 0.3


def component_height(c: Component) -> float:
    """Tallest point of the part's 3D body above its PCB surface (0 when it has no body)."""
    def build():
        from ..ui.mesh import component_parts
        top = 0.0
        for _mat, arr in component_parts(c).items:
            if len(arr):
                top = max(top, float(arr[:, 2].max()))
        return round(top, 2)
    key = ("h", c.footprint.name, c.value, repr(sorted(c.footprint.model.items(), key=lambda kv: kv[0]))[:4000])
    cached = _HEIGHTS.get(key)
    if cached is None:
        cached = _HEIGHTS[key] = build()
    return cached


_HEIGHTS: dict = {}


def _goes_through_face(c: Component) -> bool:
    meta = c.footprint.model.get("panel") or {}
    if meta.get("face") == "A":
        return True
    name = c.footprint.name
    return c.footprint.model.get("type") == "led_tht" or name.startswith(("LED_D3", "LED_D5"))


def _side_body(enc: Enclosure, h: PanelHole):
    """(footprint in panel-A coordinates, z range) of a side-wall part's body."""
    u, v, z = hole_face_point(enc, h)
    r, length, _ = h.effective_body()
    r = max(r, h.d / 2)
    W, H = enc.cavity_size
    if h.face == "E":
        rect = box(W / 2 - length, v - r, W / 2, v + r)
    elif h.face == "C":
        rect = box(-W / 2, v - r, -W / 2 + length, v + r)
    elif h.face == "B":
        rect = box(u - r, H / 2 - length, u + r, H / 2)
    else:
        rect = box(u - r, -H / 2, u + r, -H / 2 + length)
    return rect, (z - r, z + r)


def _overlap(a: tuple, b: tuple, margin: float = 0.0) -> bool:
    return a[0] < b[1] - margin and b[0] < a[1] - margin


def _label(h: PanelHole) -> str:
    return h.ref or h.label or h.hardware.label


def run_pedal_checks(project: Project) -> list[Violation]:
    enc = get_enclosure(project)
    if enc is None:
        return []
    out: list[Violation] = []
    spec = enc.spec
    near, far = enc.z_levels(project)

    def at_face(u, v):
        return enc.face_to_board(u, v)

    # --- board inside the cavity -------------------------------------------------------------
    board = project.board.polygon()
    if not board.is_empty:
        board_f = enc.geom_to_face(board)
        cavity = enc.cavity_polygon().buffer(spec.draft * min(1.0, far / spec.depth))
        from shapely.ops import unary_union
        room = cavity.difference(unary_union(enc.boss_polygons()))
        outside = board_f.difference(room)
        if outside.area > 0.05:
            p = outside.representative_point()
            bx, by = at_face(p.x, p.y)
            what = "the lid-screw bosses" if board_f.intersection(unary_union(enc.boss_polygons())).area > 0.05 \
                else "the enclosure walls"
            out.append(Violation("enclosure", f"Board outline collides with {what} of the {spec.name} "
                                              f"({outside.area:.1f} mm² outside the usable area)", bx, by, "error"))
        if far > spec.depth - enc.lid_clearance:
            out.append(Violation("enclosure", f"The {spec.name} is only {spec.depth:g} mm deep; the board would sit "
                                              f"at {far:.1f} mm", *at_face(0, 0), "error"))

    # --- part heights ----------------------------------------------------------------------------
    free = enc.free_depth(project)
    stand = enc.resolved_standoff(project)
    for c in project.components:
        if c.footprint.model.get("type", "auto") == "none":
            continue
        h = component_height(c)
        if h <= 0:
            continue
        if c.side == enc.face_side:
            if _goes_through_face(c):
                continue
            limit = stand - HEIGHT_MARGIN
            if h > limit:
                out.append(Violation("height", f"{c.ref} ({c.value}) is {h:.1f} mm tall but only {stand:.1f} mm fit "
                                               f"between the board and the enclosure face - move it to the other "
                                               f"side or lay it down", c.x, c.y, "error", [c.uid]))
        elif h > free:
            out.append(Violation("height", f"{c.ref} ({c.value}) is {h:.1f} mm tall; only {max(free, 0):.1f} mm is free "
                                           f"towards the base plate of the {spec.name} - lay it down, use a smaller "
                                           f"part or a deeper enclosure", c.x, c.y, "error", [c.uid]))

    # --- panel holes -------------------------------------------------------------------------------
    holes = all_holes(project, enc)
    usable = enc.usable_polygon(0.3)
    face_poly = enc.face_polygon()
    for h in holes:
        u, v, z = hole_face_point(enc, h)
        bx, by = at_face(u, v)
        uids = [h.comp_uid] if h.comp_uid else []
        r_body, body_len, outer = h.effective_body()
        if h.wrong_side:
            out.append(Violation("panel", f"{_label(h)} is on the {'bottom' if enc.face_side == 'top' else 'top'} side "
                                          f"of the board, so it would point away from the enclosure face. Flip it (F) "
                                          f"or change which side faces the panel", bx, by, "error", uids))
        if h.face == "A":
            if r_body > 0:
                body = Point(u, v).buffer(r_body, quad_segs=12)
                spill = body.difference(usable).area
                if spill > 0.5:
                    out.append(Violation("panel", f"{_label(h)}: its body (dia {2 * r_body:.0f} mm) hits the enclosure "
                                                  f"wall or a lid-screw boss", bx, by, "error", uids))
            elif not face_poly.buffer(-(h.d / 2 + 1.0)).contains(Point(u, v)):
                out.append(Violation("panel", f"{_label(h)} hole is too close to the edge of the face", bx, by, "error",
                                     uids))
            if outer > 0 and not face_poly.contains(Point(u, v).buffer(outer / 2 - 0.5)):
                out.append(Violation("knobs", f"{_label(h)}: the {outer:.0f} mm knob/cap overhangs the edge of the face",
                                     bx, by, "warning", uids))
        else:
            along = abs(h.x) if h.face in ("B", "D") else abs(h.y)
            half = (enc.face_size[0] if h.face in ("B", "D") else enc.face_size[1]) / 2
            lo, hi = spec.face_t + h.d / 2 + 0.5, spec.depth - h.d / 2 - 0.5
            if not lo <= z <= hi:
                out.append(Violation("jack", f"{_label(h)} on the {h.face} side sits {z:.1f} mm deep; a {h.d:g} mm hole "
                                             f"needs {lo:.1f}-{hi:.1f} mm on the {spec.name}", bx, by, "error", uids))
            if along + max(h.d, outer) / 2 > half - spec.corner_r * 0.6:
                out.append(Violation("jack", f"{_label(h)} is too close to the corner of the {h.face} side", bx, by,
                                     "error", uids))
            rect, zr = _side_body(enc, h)
            if not h.derived and not board.is_empty and _overlap(zr, (near, far)) and \
                    rect.intersects(enc.geom_to_face(board)):
                out.append(Violation("jack", f"The body of {_label(h)} ({h.face} side, {z:.1f} mm deep) collides with "
                                             f"the PCB - move the hole, shorten the board or use a deeper enclosure",
                                     bx, by, "error", uids))
            for c in project.components:
                if h.comp_uid == c.uid or c.footprint.model.get("type", "auto") == "none":
                    continue
                ch = component_height(c)
                if ch <= 0:
                    continue
                cz = (near - ch, near) if c.side == enc.face_side else (far, far + ch)
                if _overlap(zr, cz, 0.2) and rect.intersects(enc.geom_to_face(c.courtyard_polygon())):
                    out.append(Violation("jack", f"The body of {_label(h)} ({h.face} side) collides with {c.ref}",
                                         c.x, c.y, "warning", uids + [c.uid]))

    # --- pairwise ---------------------------------------------------------------------------------------
    for i, a in enumerate(holes):
        ua, va, za = hole_face_point(enc, a)
        ra, la, oa = a.effective_body()
        for b in holes[i + 1:]:
            ub, vb, zb = hole_face_point(enc, b)
            rb, lb, ob = b.effective_body()
            uids = [x for x in (a.comp_uid, b.comp_uid) if x]
            if a.face == b.face:
                d = math.hypot(a.x - b.x, a.y - b.y)
                x, y = at_face((ua + ub) / 2, (va + vb) / 2)
                if d < (a.d + b.d) / 2 + 1.0:
                    out.append(Violation("panel", f"Holes for {_label(a)} and {_label(b)} overlap or are too close "
                                                  f"({d:.1f} mm apart)", x, y, "error", uids))
                    continue
                if a.face == "A" and ra > 0 and rb > 0 and d < ra + rb - 0.2:
                    out.append(Violation("panel", f"{_label(a)} and {_label(b)} collide behind the panel ({d:.1f} mm "
                                                  f"apart, bodies need {ra + rb:.1f} mm)", x, y, "error", uids))
                    continue
                if oa > 0 and ob > 0 and d < (oa + ob) / 2:
                    what = "Knobs" if a.face == "A" else "Nuts"
                    out.append(Violation("knobs", f"{what} of {_label(a)} and {_label(b)} overlap ({d:.1f} mm apart, "
                                                  f"need {(oa + ob) / 2:.1f} mm)", x, y,
                                         "warning" if a.face == "A" else "error", uids))
            # bodies of side-wall parts against face parts and other side-wall parts
            if a.face != "A" or b.face != "A":
                sa = _side_body(enc, a) if a.face != "A" else None
                sb = _side_body(enc, b) if b.face != "A" else None
                hit = False
                if sa and sb:
                    hit = sa[0].intersects(sb[0]) and _overlap(sa[1], sb[1], 0.2)
                else:
                    side, face_h = (sa, b) if sa else (sb, a)
                    uf, vf, _ = hole_face_point(enc, face_h)
                    rf, lf, _ = face_h.effective_body()
                    if rf > 0:
                        hit = side[0].intersects(Point(uf, vf).buffer(rf)) and _overlap(side[1], (spec.face_t,
                                                                                            spec.face_t + lf), 0.2)
                if hit:
                    x, y = at_face((ua + ub) / 2, (va + vb) / 2)
                    out.append(Violation("jack", f"{_label(a)} and {_label(b)} collide inside the enclosure", x, y,
                                         "error", uids))
    return out
