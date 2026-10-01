"""Interactive editing tools for the 2D canvas."""
from __future__ import annotations

import copy
import math
import re

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QInputDialog, QMessageBox
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from ..model.board import Component, Footprint, Text, Track, Via, Zone
from ..model.connectivity import get_connectivity
from ..model.copper import copper_by_layer
from ..model.geometry import point_segment_distance, rotate_point, snap
from .canvas import LAYER_COLORS, THT_COLOR, _inverse, comp_transform, pad_in_local, pad_qpath

HINT_COLOR = QColor(120, 200, 255)


# --------------------------------------------------------------------------- selection operations

def item_anchor(it) -> tuple[float, float]:
    if isinstance(it, (Component, Via, Text)):
        return it.x, it.y
    if isinstance(it, Track):
        return it.x1, it.y1
    if isinstance(it, Zone):
        return it.outline[0]
    return 0.0, 0.0


def _pivot(items) -> tuple[float, float]:
    if len(items) == 1 and isinstance(items[0], (Component, Via, Text)):
        return items[0].x, items[0].y
    xs, ys = [], []
    for it in items:
        if isinstance(it, Track):
            xs += [it.x1, it.x2]
            ys += [it.y1, it.y2]
        elif isinstance(it, Zone):
            xs += [p[0] for p in it.outline]
            ys += [p[1] for p in it.outline]
        else:
            x, y = item_anchor(it)
            xs.append(x)
            ys.append(y)
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2


def _movable(items):
    return [i for i in items if not (isinstance(i, Component) and i.locked)]


def rotate_items(doc, items, angle: float = 90.0) -> None:
    items = _movable(items)
    if not items:
        return
    px, py = _pivot(items)

    def rot(x, y):
        dx, dy = rotate_point(x - px, y - py, angle)
        return round(px + dx, 6), round(py + dy, 6)

    with doc.edit("Rotate"):
        for it in items:
            if isinstance(it, Component):
                it.x, it.y = rot(it.x, it.y)
                it.rotation = (it.rotation + angle) % 360
            elif isinstance(it, Text):
                it.x, it.y = rot(it.x, it.y)
                it.rotation = (it.rotation + angle) % 360
            elif isinstance(it, Via):
                it.x, it.y = rot(it.x, it.y)
            elif isinstance(it, Track):
                it.x1, it.y1 = rot(it.x1, it.y1)
                it.x2, it.y2 = rot(it.x2, it.y2)
            elif isinstance(it, Zone):
                it.outline = [rot(x, y) for x, y in it.outline]


def _other_layer(layer: str) -> str:
    swap = {"F.Cu": "B.Cu", "B.Cu": "F.Cu", "In1.Cu": "In2.Cu", "In2.Cu": "In1.Cu",
            "F.SilkS": "B.SilkS", "B.SilkS": "F.SilkS"}
    return swap.get(layer, layer)


def flip_items(doc, items) -> None:
    items = _movable(items)
    if not items:
        return
    px, _ = _pivot(items)
    single = len(items) == 1

    def mx(x):
        return x if single else round(2 * px - x, 6)

    with doc.edit("Flip"):
        for it in items:
            if isinstance(it, Component):
                it.side = "bottom" if it.side == "top" else "top"
                it.x = mx(it.x)
                it.rotation = (-it.rotation) % 360 if not single else it.rotation
            elif isinstance(it, Text):
                it.layer = _other_layer(it.layer)
                it.x = mx(it.x)
            elif isinstance(it, Via):
                it.x = mx(it.x)
            elif isinstance(it, Track):
                it.layer = _other_layer(it.layer)
                it.x1, it.x2 = mx(it.x1), mx(it.x2)
            elif isinstance(it, Zone):
                it.layer = _other_layer(it.layer)
                it.outline = [(mx(x), y) for x, y in it.outline]


def delete_items(doc, items) -> None:
    items = [i for i in items if not (isinstance(i, Component) and i.locked)]
    if not items:
        return
    with doc.edit("Delete"):
        doc.project.remove_items(items)
    doc.clear_selection()


def duplicate_items(doc, items, offset: float = 2.54):
    new = []
    p = doc.project
    with doc.edit("Duplicate"):
        for it in items:
            if isinstance(it, Component):
                d = it.to_dict()
                d.pop("uid")
                c = Component.from_dict(d)
                prefix = re.match(r"[A-Za-z_]+", it.ref)
                c.ref = p.next_ref(prefix.group(0) if prefix else "U")
                c.x += offset
                c.y += offset
                p.components.append(c)
                new.append(c)
            elif isinstance(it, Text):
                t = Text(it.text, it.x + offset, it.y + offset, it.size, it.layer, it.rotation)
                p.texts.append(t)
                new.append(t)
            elif isinstance(it, Via):
                v = Via(it.x + offset, it.y + offset, it.diameter, it.drill, it.net)
                p.vias.append(v)
                new.append(v)
            elif isinstance(it, Track):
                t = Track(it.x1 + offset, it.y1 + offset, it.x2 + offset, it.y2 + offset, it.width, it.layer, it.net)
                p.tracks.append(t)
                new.append(t)
    doc.set_selection(new)
    return new


def connected_tracks(project, track: Track) -> list[Track]:
    """All tracks electrically chained to `track` through shared end points (and vias)."""
    result = {track.uid: track}
    frontier = [track]
    via_pts = {(round(v.x, 4), round(v.y, 4)) for v in project.vias}
    while frontier:
        t = frontier.pop()
        ends = [(round(t.x1, 4), round(t.y1, 4)), (round(t.x2, 4), round(t.y2, 4))]
        for o in project.tracks:
            if o.uid in result:
                continue
            oe = [(round(o.x1, 4), round(o.y1, 4)), (round(o.x2, 4), round(o.y2, 4))]
            shared = set(ends) & set(oe)
            if shared and (o.layer == t.layer or shared & via_pts):
                result[o.uid] = o
                frontier.append(o)
    return list(result.values())


# --------------------------------------------------------------------------- tool base

class Tool:
    name = ""
    label = ""
    cursor = Qt.CrossCursor

    def __init__(self, canvas):
        self.c = canvas

    @property
    def doc(self):
        return self.c.doc

    @property
    def project(self):
        return self.c.doc.project

    def activate(self, **kwargs):
        self.reset()

    def deactivate(self):
        self.reset()

    def reset(self):
        pass

    def press(self, ev, x, y):
        pass

    def move(self, ev, x, y):
        pass

    def release(self, ev, x, y):
        pass

    def double_click(self, ev, x, y):
        pass

    def key(self, ev) -> bool:
        return False

    def paint(self, p: QPainter):
        pass

    def paint_screen(self, p: QPainter):
        pass

    def hint(self) -> str:
        return ""

    def status(self, text: str):
        self.c.status.emit(text)

    # helpers ---------------------------------------------------------------
    def paint_component_ghost(self, p: QPainter, comp: Component, alpha: int = 170):
        proj = self.project
        p.save()
        p.setTransform(comp_transform(comp), True)
        side_col = QColor(LAYER_COLORS["F.Cu" if comp.side == "top" else "B.Cu"])
        side_col.setAlpha(alpha)
        tht = QColor(THT_COLOR)
        tht.setAlpha(alpha)
        p.setPen(Qt.NoPen)
        for pad in comp.footprint.pads:
            p.save()
            p.translate(pad.x, pad.y)
            if pad.rotation:
                p.rotate(-pad.rotation)
            p.setBrush(tht if pad.kind == "tht" else (QColor(30, 30, 30, alpha) if pad.kind == "npth" else side_col))
            p.drawPath(pad_qpath(pad))
            p.restore()
        silk = QColor(LAYER_COLORS["F.SilkS" if comp.side == "top" else "B.SilkS"])
        silk.setAlpha(alpha)
        self.c._paint_graphics(p, comp.footprint.graphics, "silk", silk)
        pen = QPen(QColor(255, 255, 255, 120), 1.0, Qt.DashLine)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        x0, y0, x1, y1 = comp.footprint.courtyard
        p.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))
        p.restore()
        if comp.show_ref:
            rx, ry = comp.to_board(*comp.footprint.ref_pos)
            self.c._paint_text_item(p, comp.ref, rx, ry, 0.9, comp.rotation % 180, comp.mirror, silk)


def _cosmetic(color, width=1.0, style=Qt.SolidLine) -> QPen:
    pen = QPen(color, width, style)
    pen.setCosmetic(True)
    return pen


# --------------------------------------------------------------------------- select / move

class SelectTool(Tool):
    name = "select"
    label = "Select / Move"
    cursor = Qt.ArrowCursor

    def reset(self):
        self.drag = None
        self.band = None

    def hint(self):
        return ("Click to select, drag to move, drag on empty space to box-select.  "
                "R rotate · F flip side · Del delete · U select trace · E properties")

    def press(self, ev, x, y):
        if ev.button() != Qt.LeftButton:
            return
        item = self.c.item_at(x, y)
        mods = ev.modifiers()
        sel = list(self.doc.selection)
        if item is None:
            if not (mods & (Qt.ShiftModifier | Qt.ControlModifier)):
                self.doc.clear_selection()
            self.band = [x, y, x, y]
            return
        if mods & (Qt.ShiftModifier | Qt.ControlModifier):
            if item in sel:
                sel.remove(item)
            else:
                sel.append(item)
            self.doc.set_selection(sel)
            return
        if item not in sel:
            self.doc.set_selection([item])
        self._start_drag(x, y)

    def _start_drag(self, x, y):
        items = _movable(self.doc.selection)
        if not items:
            return
        orig = {}
        for it in items:
            if isinstance(it, Track):
                orig[it.uid] = (it.x1, it.y1, it.x2, it.y2)
            elif isinstance(it, Zone):
                orig[it.uid] = list(it.outline)
            else:
                orig[it.uid] = (it.x, it.y)
        # track ends attached to moving pads / vias stretch with them
        attached = []
        sel_ids = {i.uid for i in items}
        comps = [i for i in items if isinstance(i, Component)]
        vias = [i for i in items if isinstance(i, Via)]
        for t in self.project.tracks:
            if t.uid in sel_ids:
                continue
            for end in (1, 2):
                ex, ey = (t.x1, t.y1) if end == 1 else (t.x2, t.y2)
                hit = False
                for c in comps:
                    lx, ly = _inverse(c, ex, ey)
                    if any(pad.kind != "npth" and pad_in_local(pad, lx, ly, 1e-3) for pad in c.footprint.pads):
                        hit = True
                        break
                if not hit:
                    hit = any(math.hypot(v.x - ex, v.y - ey) < v.diameter / 2 for v in vias)
                if hit:
                    attached.append((t, end, ex, ey))
        ax, ay = item_anchor(items[0])
        self.drag = {"x": x, "y": y, "items": items, "orig": orig, "attached": attached, "anchor": (ax, ay),
                     "moved": False}

    def move(self, ev, x, y):
        if self.band is not None:
            self.band[2], self.band[3] = x, y
            self.c.update()
            return
        if self.drag is not None and ev.buttons() & Qt.LeftButton:
            d = self.drag
            ax, ay = d["anchor"]
            nx, ny = self.c.snap(ax + x - d["x"], ay + y - d["y"])
            dx, dy = nx - ax, ny - ay
            if not d["moved"]:
                if math.hypot(x - d["x"], y - d["y"]) * self.c.scale < 4:
                    return
                self.doc.begin("Move")
                d["moved"] = True
            for it in d["items"]:
                o = d["orig"][it.uid]
                if isinstance(it, Track):
                    it.x1, it.y1, it.x2, it.y2 = o[0] + dx, o[1] + dy, o[2] + dx, o[3] + dy
                elif isinstance(it, Zone):
                    it.outline = [(px + dx, py + dy) for px, py in o]
                else:
                    it.x, it.y = round(o[0] + dx, 6), round(o[1] + dy, 6)
            for t, end, ex, ey in d["attached"]:
                if end == 1:
                    t.x1, t.y1 = ex + dx, ey + dy
                else:
                    t.x2, t.y2 = ex + dx, ey + dy
            self.doc.live_update()
            self.status(f"Move  dx {dx:+.3f}  dy {dy:+.3f} mm")
            return
        hov = self.c.item_at(x, y)
        if hov is not self.c.hover:
            self.c.hover = hov
            self.c.update()

    def release(self, ev, x, y):
        if self.band is not None:
            x0, y0, x1, y1 = self.band
            self.band = None
            if abs(x1 - x0) * self.c.scale > 3 or abs(y1 - y0) * self.c.scale > 3:
                items = self.c.items_in_rect(x0, y0, x1, y1, crossing=x1 < x0)
                if ev.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier):
                    items = list(self.doc.selection) + [i for i in items if i not in self.doc.selection]
                self.doc.set_selection(items)
            self.c.update()
            return
        if self.drag is not None:
            if self.drag["moved"]:
                self.doc.commit()
            self.drag = None
            self.status(self.hint())

    def double_click(self, ev, x, y):
        item = self.c.item_at(x, y)
        if isinstance(item, Track):
            self.doc.set_selection(connected_tracks(self.project, item))
        elif item is not None:
            self.doc.set_selection([item])
            self.c.open_properties.emit()

    def key(self, ev):
        k = ev.key()
        sel = self.doc.selection
        if k == Qt.Key_Escape:
            if self.drag and self.drag["moved"]:
                self.doc.cancel()
                self.drag = None
            else:
                self.doc.clear_selection()
            return True
        if k == Qt.Key_U and sel and isinstance(sel[0], Track):
            self.doc.set_selection(connected_tracks(self.project, sel[0]))
            return True
        if k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) and sel:
            step = self.c.grid if not (ev.modifiers() & Qt.ShiftModifier) else self.c.grid * 10
            dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(k, 0)
            dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(k, 0)
            with self.doc.edit("Nudge"):
                for it in _movable(sel):
                    if isinstance(it, Track):
                        it.x1 += dx; it.x2 += dx; it.y1 += dy; it.y2 += dy
                    elif isinstance(it, Zone):
                        it.outline = [(px + dx, py + dy) for px, py in it.outline]
                    else:
                        it.x = round(it.x + dx, 6)
                        it.y = round(it.y + dy, 6)
            return True
        return False

    def paint(self, p):
        if self.band is not None:
            x0, y0, x1, y1 = self.band
            crossing = x1 < x0
            col = QColor(90, 200, 120) if crossing else QColor(80, 150, 255)
            p.setPen(_cosmetic(col, 1.0, Qt.DashLine if crossing else Qt.SolidLine))
            fill = QColor(col)
            fill.setAlpha(35)
            p.setBrush(fill)
            p.drawRect(QRectF(QPointF(x0, y0), QPointF(x1, y1)).normalized())

    def context_menu(self, menu, item, x, y):
        mw = self.c.window()
        if item is not None:
            for name in ("act_props", "act_rotate", "act_flip", "act_duplicate", "act_delete"):
                act = getattr(mw, name, None)
                if act is not None:
                    menu.addAction(act)
            if isinstance(item, Track):
                menu.addAction("Select whole trace", lambda: self.doc.set_selection(connected_tracks(self.project, item)))
            net = getattr(item, "net", None)
            if net:
                menu.addAction(f"Highlight net {net}", lambda: mw.highlight_net(net))
            menu.addSeparator()
        menu.addAction("Route track here", lambda: self.c.set_tool("route"))
        menu.addAction("Place via here", lambda: add_via(self.c, *self.c.snap(x, y)))
        menu.addSeparator()
        menu.addAction("Fit board\tHome", self.c.fit_board)


def add_via(canvas, x, y):
    doc = canvas.doc
    net = None
    t = canvas.track_at(x, y)
    if t:
        net = t.net
    else:
        c, pad = canvas.pad_at(x, y)
        if c is not None:
            net = c.pad_net(pad)
        else:
            z = canvas.zone_at(x, y)
            net = z.net if z else None
    nc = doc.project.netclass_for(net)
    with doc.edit("Add via"):
        doc.project.vias.append(Via(x, y, nc.via_diameter, nc.via_drill, net))


# --------------------------------------------------------------------------- routing

class RouteTool(Tool):
    name = "route"
    label = "Route Tracks"
    WIDTHS = [0.1, 0.127, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0]

    def reset(self):
        self.active = False
        self.segments: list[Track] = []
        self.vias: list[Via] = []
        self.last = None
        self.net = None
        self.layer = None
        self.end = None
        self.preview: list[tuple[float, float]] = []
        self.collide = False
        self.diagonal_first = True
        self.width_override: float | None = getattr(self, "width_override", None)
        self._trees = {}

    def hint(self):
        if not self.active:
            return "Click on a pad, via or track to start routing (45 degree).  W/Shift+W width · Esc exit"
        return (f"Routing {self.net or '(no net)'} on {self.layer}, width {self.width:.3f} mm.  Click to add corner · "
                "click a pad to finish · V via + layer change · / posture · Backspace undo corner · Esc cancel")

    @property
    def width(self) -> float:
        return self.width_override or self.project.netclass_for(self.net).track_width

    def _anchor(self, x, y, layer):
        """Existing copper under the cursor: (x, y, net) snapped to its natural centre."""
        c = self.c
        v = c.via_at(x, y)
        if v:
            return v.x, v.y, v.net, v
        comp, pad = c.pad_at(x, y, layer)
        if comp is not None:
            px, py = comp.pad_pos(pad)
            return px, py, comp.pad_net(pad), (comp, pad)
        t = c.track_at(x, y, layer)
        if t:
            for ex, ey in ((t.x1, t.y1), (t.x2, t.y2)):
                if math.hypot(ex - x, ey - y) <= max(t.width, c.px(8)):
                    return ex, ey, t.net, t
            # project onto the segment, snapped to grid
            sx, sy = c.snap(x, y)
            return sx, sy, t.net, t
        return None

    def _legs(self, a, b):
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        if abs(dx) < 1e-9 or abs(dy) < 1e-9 or abs(abs(dx) - abs(dy)) < 1e-9:
            return [a, b]
        d = min(abs(dx), abs(dy))
        sx = math.copysign(1, dx)
        sy = math.copysign(1, dy)
        if self.diagonal_first:
            mid = (ax + sx * d, ay + sy * d)
        else:
            mid = (bx - sx * d, by - sy * d)
        return [a, mid, b]

    def _build_trees(self):
        conn = get_connectivity(self.project)
        self._trees = {}
        for layer, shapes in copper_by_layer(self.project).items():
            others = [s for s in shapes if conn.effective_net(s) != self.net or self.net is None]
            self._trees[layer] = (STRtree([s.geom for s in others]) if others else None, others)

    def _collides(self, pts, layer) -> bool:
        if self.net is None or len(pts) < 2:
            return False
        tree, shapes = self._trees.get(layer, (None, []))
        if tree is None:
            return False
        line = LineString(pts) if len(pts) > 1 and pts[0] != pts[-1] else Point(pts[0])
        g = line.buffer(self.width / 2, quad_segs=4)
        clr = self.project.netclass_for(self.net).clearance
        hits = tree.query(g, predicate="dwithin", distance=clr - 1e-4)
        return len(hits) > 0

    def press(self, ev, x, y):
        if ev.button() != Qt.LeftButton:
            return
        layer = self.c.active_layer
        if not self.active:
            a = self._anchor(x, y, layer)
            if a:
                sx, sy, net, _ = a
            else:
                sx, sy = self.c.snap(x, y)
                net = None
            self.active = True
            self.net = net
            self.layer = layer
            self.last = (sx, sy)
            self.end = (sx, sy)
            self.preview = []
            self._build_trees()
            self.c.highlight_net = net
            self.status(self.hint())
            self.c.update()
            return
        end, target = self._resolve_end(x, y)
        if target is not None:
            tnet = target[2]
            if tnet and self.net and tnet != self.net:
                self.status(f"Cannot connect net {self.net} to {tnet}")
                return
        self._commit_legs(end)
        if target is not None and (len(self.segments) > 0):
            if target[2] and not self.net:
                self.net = target[2]
                for s in self.segments:
                    s.net = self.net
                for v in self.vias:
                    v.net = self.net
            self.finish()

    def _resolve_end(self, x, y):
        """End point for the current leg, snapping onto copper that the route could connect to."""
        a = self._anchor(x, y, self.layer)
        if a and (self.last is None or math.hypot(a[0] - self.last[0], a[1] - self.last[1]) > 1e-6):
            return (a[0], a[1]), a
        return self.c.snap(x, y), None

    def _commit_legs(self, end):
        pts = self._legs(self.last, end)
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            if math.hypot(x2 - x1, y2 - y1) < 1e-6:
                continue
            self.segments.append(Track(x1, y1, x2, y2, self.width, self.layer, self.net))
        self.last = end

    def move(self, ev, x, y):
        if not self.active:
            a = self._anchor(x, y, self.c.active_layer)
            self.c.hover = a[3] if a and not isinstance(a[3], tuple) else (a[3][0] if a else None)
            self.c.update()
            return
        end, target = self._resolve_end(x, y)
        self.end = end
        self.preview = self._legs(self.last, end)
        self.collide = self._collides(self.preview, self.layer)
        self.c.update()

    def double_click(self, ev, x, y):
        if self.active:
            self.finish()

    def finish(self):
        if self.segments:
            with self.doc.edit("Route track"):
                self.project.tracks.extend(self.segments)
                self.project.vias.extend(self.vias)
        keep = self.width_override
        self.reset()
        self.width_override = keep
        self.c.highlight_net = None
        self.status(self.hint())
        self.c.update()

    def key(self, ev):
        k = ev.key()
        if k == Qt.Key_Escape:
            if self.active:
                self.reset()
                self.c.highlight_net = None
                self.status(self.hint())
                self.c.update()
                return True
            return False
        if k == Qt.Key_W:
            cur = self.width
            if ev.modifiers() & Qt.ShiftModifier:
                smaller = [w for w in self.WIDTHS if w < cur - 1e-9]
                self.width_override = smaller[-1] if smaller else self.WIDTHS[0]
            else:
                bigger = [w for w in self.WIDTHS if w > cur + 1e-9]
                self.width_override = bigger[0] if bigger else self.WIDTHS[-1]
            self.status(f"Track width {self.width:.3f} mm")
            self.c.update()
            return True
        if not self.active:
            return False
        if k == Qt.Key_Slash:
            self.diagonal_first = not self.diagonal_first
            self.preview = self._legs(self.last, self.end)
            self.c.update()
            return True
        if k == Qt.Key_Backspace:
            v = self.vias[-1] if self.vias else None
            at_via = v is not None and math.hypot(v.x - self.last[0], v.y - self.last[1]) < 1e-6 and (
                not self.segments or self.segments[-1].layer != self.layer)
            if at_via:
                # step back through the via onto the previous layer
                self.vias.pop()
                self.layer = self.segments[-1].layer if self.segments else self.layer
                self.c.set_active_layer(self.layer)
            elif self.segments:
                s = self.segments.pop()
                self.last = (s.x1, s.y1)
            self.preview = self._legs(self.last, self.end or self.last)
            self.status(self.hint())
            self.c.update()
            return True
        if k == Qt.Key_V:
            end = self.end or self.last
            self._commit_legs(end)
            nc = self.project.netclass_for(self.net)
            self.vias.append(Via(end[0], end[1], nc.via_diameter, nc.via_drill, self.net))
            layers = self.project.copper_layers
            self.layer = layers[-1] if self.layer == layers[0] else layers[0]
            self.c.set_active_layer(self.layer)
            self.preview = []
            self.status(self.hint())
            self.c.update()
            return True
        if k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_End):
            self.finish()
            return True
        return False

    def paint(self, p):
        if not self.active:
            return
        col = QColor(LAYER_COLORS.get(self.layer, QColor(220, 220, 220)))
        pen = QPen(col.lighter(125), self.width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        for s in self.segments:
            pen.setColor(QColor(LAYER_COLORS.get(s.layer)).lighter(125))
            p.setPen(pen)
            p.drawLine(QPointF(s.x1, s.y1), QPointF(s.x2, s.y2))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(200, 200, 210))
        for v in self.vias:
            p.drawEllipse(QPointF(v.x, v.y), v.diameter / 2, v.diameter / 2)
        if len(self.preview) >= 2:
            pc = QColor(255, 80, 70) if self.collide else col.lighter(150)
            pc.setAlpha(210)
            pen = QPen(pc, self.width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(QPolygonF([QPointF(*pt) for pt in self.preview]))
            # clearance halo around the end
            ex, ey = self.preview[-1]
            clr = self.project.netclass_for(self.net).clearance
            p.setPen(_cosmetic(QColor(255, 255, 255, 110), 1.0, Qt.DotLine))
            r = self.width / 2 + clr
            p.drawEllipse(QPointF(ex, ey), r, r)


# --------------------------------------------------------------------------- vias

class ViaTool(Tool):
    name = "via"
    label = "Place Via"

    def hint(self):
        return "Click to place a via (it inherits the net of the copper underneath). Esc to exit"

    def press(self, ev, x, y):
        if ev.button() == Qt.LeftButton:
            add_via(self.c, *self.c.snap(x, y))

    def move(self, ev, x, y):
        self.pos = self.c.snap(x, y)
        self.c.update()

    def paint(self, p):
        pos = getattr(self, "pos", None)
        if pos:
            nc = self.project.netclass_for(None)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(200, 200, 210, 150))
            p.drawEllipse(QPointF(*pos), nc.via_diameter / 2, nc.via_diameter / 2)
            p.setBrush(QColor(20, 20, 20, 200))
            p.drawEllipse(QPointF(*pos), nc.via_drill / 2, nc.via_drill / 2)


# --------------------------------------------------------------------------- polygon based tools

class PolygonTool(Tool):
    rect_mode = False

    def reset(self):
        self.pts: list[tuple[float, float]] = []
        self.cur = None

    def press(self, ev, x, y):
        if ev.button() != Qt.LeftButton:
            return
        pt = self.c.snap(x, y)
        if self.rect_mode:
            if not self.pts:
                self.pts = [pt]
            else:
                (x0, y0), (x1, y1) = self.pts[0], pt
                if abs(x1 - x0) > 1e-6 and abs(y1 - y0) > 1e-6:
                    self.pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
                    self._finish()
            self.c.update()
            return
        if self.pts and len(self.pts) >= 3 and math.hypot(pt[0] - self.pts[0][0], pt[1] - self.pts[0][1]) < self.c.px(8):
            self._finish()
            return
        if not self.pts or pt != self.pts[-1]:
            self.pts.append(pt)
        self.c.update()

    def move(self, ev, x, y):
        self.cur = self.c.snap(x, y)
        self.c.update()

    def double_click(self, ev, x, y):
        if not self.rect_mode and len(self.pts) >= 3:
            self._finish()

    def key(self, ev):
        k = ev.key()
        if k == Qt.Key_Escape:
            if self.pts:
                self.reset()
                self.c.update()
                return True
            return False
        if k == Qt.Key_Backspace and self.pts:
            self.pts.pop()
            self.c.update()
            return True
        if k in (Qt.Key_Return, Qt.Key_Enter) and len(self.pts) >= 3:
            self._finish()
            return True
        if k == Qt.Key_R and not ev.modifiers():
            self.rect_mode = not self.rect_mode
            self.pts = []
            self.status(self.hint())
            self.c.update()
            return True
        return False

    def _finish(self):
        pts = list(self.pts)
        self.reset()
        self.c.update()
        if len(pts) >= 3:
            self.finish_polygon(pts)

    def finish_polygon(self, pts):
        raise NotImplementedError

    def color(self) -> QColor:
        return QColor(230, 200, 80)

    def paint(self, p):
        col = self.color()
        pts = list(self.pts)
        if self.rect_mode and len(pts) == 1 and self.cur:
            (x0, y0), (x1, y1) = pts[0], self.cur
            pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        elif self.cur and pts:
            pts = pts + [self.cur]
        if len(pts) >= 2:
            fill = QColor(col)
            fill.setAlpha(40)
            p.setBrush(fill)
            p.setPen(_cosmetic(col, 1.6))
            p.drawPolygon(QPolygonF([QPointF(*q) for q in pts]))
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        s = self.c.px(3)
        for q in self.pts:
            p.drawRect(QRectF(q[0] - s, q[1] - s, 2 * s, 2 * s))


class OutlineTool(PolygonTool):
    name = "outline"
    label = "Board Outline"
    cutout = False

    def hint(self):
        mode = "RECTANGLE" if self.rect_mode else "POLYGON"
        what = "cut-out" if self.cutout else "board outline"
        return (f"Draw {what} ({mode}): click points, double-click / Enter to close.  "
                "R toggle rectangle · C toggle cut-out · Backspace undo point")

    def key(self, ev):
        if ev.key() == Qt.Key_C and not ev.modifiers():
            self.cutout = not self.cutout
            self.status(self.hint())
            return True
        return super().key(ev)

    def finish_polygon(self, pts):
        with self.doc.edit("Board cut-out" if self.cutout else "Board outline"):
            if self.cutout:
                self.project.board.cutouts.append(pts)
            else:
                self.project.board.outline = pts
        self.status("Board outline updated" if not self.cutout else "Cut-out added")


class ZoneTool(PolygonTool):
    name = "zone"
    label = "Copper Zone"

    def hint(self):
        mode = "RECTANGLE" if self.rect_mode else "POLYGON"
        return f"Draw a copper pour ({mode}) on {self.c.active_layer}: click points, double-click to close.  R toggle rectangle"

    def color(self):
        return QColor(LAYER_COLORS.get(self.c.active_layer, QColor(220, 220, 80)))

    def finish_polygon(self, pts):
        from .dialogs import ZoneDialog
        dlg = ZoneDialog(self.project, None, self.c.active_layer, self.c.window())
        if dlg.exec():
            z = dlg.make_zone(pts)
            with self.doc.edit("Add zone"):
                self.project.zones.append(z)
            self.doc.refill_zones()


class TextTool(Tool):
    name = "text"
    label = "Text"

    def hint(self):
        return "Click to place silkscreen text (placed on the bottom silkscreen when B.Cu is the active layer)"

    def press(self, ev, x, y):
        if ev.button() != Qt.LeftButton:
            return
        text, ok = QInputDialog.getText(self.c.window(), "Add text", "Text:")
        if ok and text.strip():
            layer = "B.SilkS" if self.c.active_layer == "B.Cu" else "F.SilkS"
            sx, sy = self.c.snap(x, y)
            t = Text(text.strip(), sx, sy, 1.2, layer)
            with self.doc.edit("Add text"):
                self.project.texts.append(t)
            self.doc.set_selection([t])


class MeasureTool(Tool):
    name = "measure"
    label = "Measure"

    def reset(self):
        self.a = None
        self.b = None
        self.fixed = False

    def hint(self):
        return "Click two points to measure distance. Esc to exit"

    def press(self, ev, x, y):
        if ev.button() != Qt.LeftButton:
            return
        pt = self._pt(x, y)
        if self.a is None or self.fixed:
            self.a, self.b, self.fixed = pt, pt, False
        else:
            self.b = pt
            self.fixed = True
        self.c.update()

    def _pt(self, x, y):
        comp, pad = self.c.pad_at(x, y)
        if comp is not None:
            return comp.pad_pos(pad)
        v = self.c.via_at(x, y)
        if v:
            return v.x, v.y
        return self.c.snap(x, y)

    def move(self, ev, x, y):
        if self.a is not None and not self.fixed:
            self.b = self._pt(x, y)
            self.c.update()

    def paint(self, p):
        if self.a and self.b:
            p.setPen(_cosmetic(QColor(255, 230, 90), 1.4))
            p.drawLine(QPointF(*self.a), QPointF(*self.b))

    def paint_screen(self, p):
        if self.a and self.b:
            dx, dy = self.b[0] - self.a[0], self.b[1] - self.a[1]
            d = math.hypot(dx, dy)
            sp = self.c.to_screen(*self.b)
            txt = f"{d:.3f} mm   dx {dx:+.3f}   dy {dy:+.3f}   ({d / 0.0254:.1f} mil)"
            f = QFont("Segoe UI")
            f.setPixelSize(12)
            p.setFont(f)
            r = QRectF(sp.x() + 12, sp.y() + 10, 12 + len(txt) * 6.4, 22)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(20, 22, 27, 230))
            p.drawRoundedRect(r, 5, 5)
            p.setPen(QColor(255, 230, 90))
            p.drawText(r, Qt.AlignCenter, txt)


class PlaceTool(Tool):
    name = "place"
    label = "Place Component"

    def reset(self):
        self.ghost: Component | None = None

    def activate(self, footprint: Footprint | None = None, prefix: str = "U", value: str = "", mpn: str = "",
                 lcsc: str = "", **kw):
        self.reset()
        self.prefix = prefix
        self.value = value
        self.mpn = mpn
        self.lcsc = lcsc
        self.footprint = footprint
        self.rotation = getattr(self, "rotation", 0.0)
        self.side = "top"
        if footprint is not None:
            self._new_ghost(*self.c.mouse_world)

    def _new_ghost(self, x, y):
        fp = copy.deepcopy(self.footprint)
        sx, sy = self.c.snap(x, y)
        g = Component(self.project.next_ref(self.prefix), self.value, fp, sx, sy, self.rotation, self.side,
                      mpn=getattr(self, "mpn", ""), lcsc=getattr(self, "lcsc", ""))
        if fp.model.get("type") == "none" and self.prefix in ("H", "FID", "TP"):
            g.show_ref = False
        self.ghost = g

    def hint(self):
        name = self.footprint.name if getattr(self, "footprint", None) else ""
        return f"Placing {name}: click to place · R rotate · F flip to bottom · Esc done"

    def move(self, ev, x, y):
        if self.ghost is not None:
            self.ghost.x, self.ghost.y = self.c.snap(x, y)
            self.c.update()

    def press(self, ev, x, y):
        if ev.button() != Qt.LeftButton or self.ghost is None:
            return
        g = self.ghost
        g.ref = self.project.next_ref(self.prefix)
        with self.doc.edit(f"Place {g.ref}"):
            self.project.components.append(g)
        self.doc.set_selection([g])
        self._new_ghost(x, y)
        self.status(f"Placed {g.ref}. " + self.hint())

    def key(self, ev):
        k = ev.key()
        if self.ghost is None:
            return False
        if k == Qt.Key_R:
            self.rotation = (self.rotation + (-90 if ev.modifiers() & Qt.ShiftModifier else 90)) % 360
            self.ghost.rotation = self.rotation
            self.c.update()
            return True
        if k == Qt.Key_F:
            self.side = "bottom" if self.side == "top" else "top"
            self.ghost.side = self.side
            self.c.update()
            return True
        if k == Qt.Key_Escape:
            self.c.set_tool("select")
            return True
        return False

    def paint(self, p):
        if self.ghost is not None:
            self.paint_component_ghost(p, self.ghost)


class ConnectTool(Tool):
    name = "connect"
    label = "Connect Pads (netlist)"

    def reset(self):
        self.first = None
        self.cur = None

    def hint(self):
        if self.first is None:
            return "Netlist editing: click a pad, then click another pad to put both on the same net. Esc to exit"
        c, pad = self.first
        return f"From {c.ref}.{pad.number} ({c.pad_net(pad) or 'no net'}) - click the pad to connect to"

    def press(self, ev, x, y):
        if ev.button() != Qt.LeftButton:
            return
        comp, pad = self.c.pad_at(x, y)
        if comp is None or not pad.number:
            return
        if self.first is None:
            self.first = (comp, pad)
            self.c.highlight_net = comp.pad_net(pad)
            self.status(self.hint())
            self.c.update()
            return
        c1, p1 = self.first
        if c1 is comp and p1.number == pad.number:
            return
        n1, n2 = c1.pad_net(p1), comp.pad_net(pad)
        proj = self.project
        if n1 and n2 and n1 != n2:
            r = QMessageBox.question(self.c.window(), "Merge nets",
                                     f"{c1.ref}.{p1.number} is on net '{n1}' and {comp.ref}.{pad.number} is on '{n2}'.\n\n"
                                     f"Merge '{n2}' into '{n1}'?")
            if r != QMessageBox.Yes:
                self.reset()
                self.c.highlight_net = None
                self.c.update()
                return
            with self.doc.edit(f"Merge net {n2} into {n1}"):
                proj.rename_net(n2, n1)
            net = n1
        else:
            net = n1 or n2 or proj.next_net_name()
            with self.doc.edit(f"Connect {c1.ref}.{p1.number} - {comp.ref}.{pad.number}"):
                c1.pad_nets[p1.number] = net
                comp.pad_nets[pad.number] = net
        self.status(f"Connected {c1.ref}.{p1.number} and {comp.ref}.{pad.number} on net {net}")
        # chain: continue from the second pad
        self.first = (comp, pad)
        self.c.highlight_net = net
        self.c.update()

    def move(self, ev, x, y):
        self.cur = (x, y)
        if self.first is not None:
            self.c.update()

    def key(self, ev):
        if ev.key() == Qt.Key_Escape and self.first is not None:
            self.reset()
            self.c.highlight_net = None
            self.status(self.hint())
            self.c.update()
            return True
        return False

    def paint(self, p):
        if self.first is not None and self.cur is not None:
            c, pad = self.first
            x, y = c.pad_pos(pad)
            p.setPen(_cosmetic(QColor(255, 220, 90), 1.6, Qt.DashLine))
            p.drawLine(QPointF(x, y), QPointF(*self.cur))


def make_tools(canvas) -> dict:
    tools = [SelectTool, RouteTool, ViaTool, OutlineTool, ZoneTool, TextTool, MeasureTool, PlaceTool, ConnectTool]
    return {cls.name: cls(canvas) for cls in tools}
