"""2D PCB editing canvas: rendering, view navigation and hit-testing."""
from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QCursor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen,
                           QPolygonF, QTransform)
from PySide6.QtWidgets import QMenu, QWidget

from ..model.board import Component, Pad, Text, Track, Via, Zone
from ..model.connectivity import get_connectivity
from ..model.copper import holes
from ..model.geometry import iter_polygons, point_segment_distance, rotate_point, snap
from ..model.textgeom import text_path_local
from .document import Document

LAYER_COLORS = {
    "F.Cu": QColor(206, 58, 58),
    "In1.Cu": QColor(196, 176, 58),
    "In2.Cu": QColor(170, 96, 210),
    "B.Cu": QColor(66, 122, 232),
    "F.SilkS": QColor(236, 236, 214),
    "B.SilkS": QColor(186, 160, 238),
    "Edge.Cuts": QColor(236, 204, 72),
}
THT_COLOR = QColor(205, 163, 64)
VIA_COLOR = QColor(172, 174, 182)
HOLE_COLOR = QColor(14, 16, 19)
BOARD_FILL = QColor(20, 36, 27)
BG_COLOR = QColor(13, 15, 19)
GRID_COLOR = QColor(64, 70, 82)
RATS_COLOR = QColor(250, 250, 250, 170)
SEL_COLOR = QColor(255, 255, 255)
COURTYARD_COLOR = QColor(255, 70, 200)
FAB_COLOR = QColor(150, 150, 170)
DRC_COLOR = QColor(255, 70, 60)


@lru_cache(maxsize=2048)
def pad_path(shape: str, w: float, h: float, roundness: float) -> QPainterPath:
    p = QPainterPath()
    if shape == "circle":
        p.addEllipse(QPointF(0, 0), w / 2, w / 2)
    elif shape == "oval":
        r = min(w, h) / 2
        p.addRoundedRect(QRectF(-w / 2, -h / 2, w, h), r, r)
    elif shape == "roundrect":
        r = roundness * min(w, h)
        p.addRoundedRect(QRectF(-w / 2, -h / 2, w, h), r, r)
    else:
        p.addRect(QRectF(-w / 2, -h / 2, w, h))
    return p


@lru_cache(maxsize=4096)
def _poly_path(points: tuple) -> QPainterPath:
    p = QPainterPath()
    p.addPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
    p.closeSubpath()
    return p


def pad_qpath(pad: Pad) -> QPainterPath:
    """Pad outline centred on the pad origin (before the pad's own rotation)."""
    if pad.shape == "poly" and pad.points:
        return _poly_path(tuple(tuple(pt) for pt in pad.points))
    return pad_path(pad.shape, pad.w, pad.h, pad.roundness)


def geom_to_path(g) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.OddEvenFill)
    for poly in iter_polygons(g):
        path.addPolygon(QPolygonF([QPointF(x, y) for x, y in poly.exterior.coords]))
        for ring in poly.interiors:
            path.addPolygon(QPolygonF([QPointF(x, y) for x, y in ring.coords]))
    return path


def comp_transform(c: Component) -> QTransform:
    t = QTransform()
    t.translate(c.x, c.y)
    t.rotate(-c.rotation)
    if c.mirror:
        t.scale(-1, 1)
    return t


def pad_in_local(pad: Pad, lx: float, ly: float, tol: float = 0.0) -> bool:
    dx, dy = rotate_point(lx - pad.x, ly - pad.y, -pad.rotation)
    if pad.shape == "poly" and pad.points:
        return _poly_path(tuple(tuple(pt) for pt in pad.points)).contains(QPointF(dx, dy))
    if pad.shape == "circle":
        return math.hypot(dx, dy) <= pad.w / 2 + tol
    if pad.shape == "oval":
        r = min(pad.w, pad.h) / 2
        ex = max(0.0, abs(dx) - (pad.w / 2 - r))
        ey = max(0.0, abs(dy) - (pad.h / 2 - r))
        return math.hypot(ex, ey) <= r + tol
    return abs(dx) <= pad.w / 2 + tol and abs(dy) <= pad.h / 2 + tol


class Canvas(QWidget):
    cursor_moved = Signal(float, float)
    tool_changed = Signal(str)
    layer_changed = Signal(str)
    status = Signal(str)
    view_changed = Signal()
    open_properties = Signal()

    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.scale = 12.0
        self.cx, self.cy = 30.0, 20.0
        self.grid = 0.5
        self.active_layer = "F.Cu"
        self.visible: dict[str, bool] = {
            "F.Cu": True, "In1.Cu": True, "In2.Cu": True, "B.Cu": True,
            "F.SilkS": True, "B.SilkS": True, "Edge.Cuts": True,
            "Ratsnest": True, "Zones": True, "PadNumbers": True, "NetNames": True,
            "Courtyard": False, "Fab": False, "DRC": True, "Grid": True, "Enclosure": True,
        }
        self.highlight_net: str | None = None
        self.hover = None
        self.drc_markers: list = []
        self.focus_marker = None
        self.mouse_world = (0.0, 0.0)
        self._pan_last = None
        self._space = False
        self._zone_paths: dict[str, tuple[int, QPainterPath]] = {}
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setMinimumSize(400, 300)
        self.tool = None
        self.tools: dict = {}
        self.key_fallback = None
        self.world_overlays: list = []  # extra painters called in board coordinates (e.g. the pedal enclosure)
        doc.changed.connect(self.update)
        doc.selection_changed.connect(self.update)
        doc.replaced.connect(self._on_replaced)

    # ------------------------------------------------------------------ tools
    def register_tools(self, tools: dict) -> None:
        self.tools = tools

    def set_tool(self, name: str, **kwargs) -> None:
        if self.tool is not None:
            self.tool.deactivate()
        self.tool = self.tools[name]
        self.tool.activate(**kwargs)
        self.setCursor(self.tool.cursor)
        self.tool_changed.emit(name)
        self.status.emit(self.tool.hint())
        self.update()

    def set_active_layer(self, layer: str) -> None:
        if layer in self.doc.project.copper_layers and layer != self.active_layer:
            self.active_layer = layer
            self.layer_changed.emit(layer)
            self.update()

    def flip_active_layer(self) -> None:
        layers = self.doc.project.copper_layers
        self.set_active_layer(layers[-1] if self.active_layer == layers[0] else layers[0])

    def _on_replaced(self) -> None:
        self._zone_paths.clear()
        if self.active_layer not in self.doc.project.copper_layers:
            self.set_active_layer("F.Cu")
        if self.tool is not None:
            self.tool.reset()
        self.update()

    # ------------------------------------------------------------------ view transform
    def world_transform(self) -> QTransform:
        t = QTransform()
        t.translate(self.width() / 2, self.height() / 2)
        t.scale(self.scale, self.scale)
        t.translate(-self.cx, -self.cy)
        return t

    def to_world(self, sx: float, sy: float) -> tuple[float, float]:
        return (sx - self.width() / 2) / self.scale + self.cx, (sy - self.height() / 2) / self.scale + self.cy

    def to_screen(self, x: float, y: float) -> QPointF:
        return QPointF((x - self.cx) * self.scale + self.width() / 2, (y - self.cy) * self.scale + self.height() / 2)

    def snap(self, x: float, y: float) -> tuple[float, float]:
        return snap(x, self.grid), snap(y, self.grid)

    def zoom_at(self, factor: float, sx: float, sy: float) -> None:
        wx, wy = self.to_world(sx, sy)
        self.scale = max(0.5, min(2000.0, self.scale * factor))
        self.cx = wx - (sx - self.width() / 2) / self.scale
        self.cy = wy - (sy - self.height() / 2) / self.scale
        self.view_changed.emit()
        self.update()

    def fit_board(self) -> None:
        x0, y0, x1, y1 = self.doc.project.board.bounds()
        for c in self.doc.project.components:
            cx0, cy0, cx1, cy1 = c.courtyard_polygon().bounds
            x0, y0, x1, y1 = min(x0, cx0), min(y0, cy0), max(x1, cx1), max(y1, cy1)
        w, h = max(x1 - x0, 1), max(y1 - y0, 1)
        self.cx, self.cy = (x0 + x1) / 2, (y0 + y1) / 2
        self.scale = max(0.5, min((self.width() - 60) / w, (self.height() - 60) / h))
        self.view_changed.emit()
        self.update()

    def zoom_to(self, x: float, y: float, scale: float | None = None) -> None:
        self.cx, self.cy = x, y
        if scale:
            self.scale = scale
        self.view_changed.emit()
        self.update()

    def px(self, n: float) -> float:
        """n screen pixels in world units."""
        return n / self.scale

    # ------------------------------------------------------------------ hit testing
    def pad_at(self, x: float, y: float, layer: str | None = None):
        p = self.doc.project
        best = None
        tol = self.px(1)
        for c in reversed(p.components):
            if layer and not any(layer in c.pad_copper_layers(pad, p.copper_layers) for pad in c.footprint.pads):
                continue
            lx, ly = _inverse(c, x, y)
            for pad in c.footprint.pads:
                if pad.kind == "npth":
                    continue
                if layer and layer not in c.pad_copper_layers(pad, p.copper_layers):
                    continue
                if pad_in_local(pad, lx, ly, tol):
                    d = math.hypot(lx - pad.x, ly - pad.y)
                    if best is None or d < best[0]:
                        best = (d, c, pad)
        return (best[1], best[2]) if best else (None, None)

    def via_at(self, x: float, y: float) -> Via | None:
        tol = self.px(3)
        for v in reversed(self.doc.project.vias):
            if math.hypot(v.x - x, v.y - y) <= v.diameter / 2 + tol:
                return v
        return None

    def track_at(self, x: float, y: float, layer: str | None = None) -> Track | None:
        tol = self.px(3)
        best = None
        for t in self.doc.project.tracks:
            if layer and t.layer != layer:
                continue
            if not self.visible.get(t.layer, True):
                continue
            d = point_segment_distance(x, y, t.x1, t.y1, t.x2, t.y2)
            if d <= t.width / 2 + tol:
                score = d - (0.5 if t.layer == self.active_layer else 0)
                if best is None or score < best[0]:
                    best = (score, t)
        return best[1] if best else None

    def text_at(self, x: float, y: float) -> Text | None:
        for t in reversed(self.doc.project.texts):
            if not self.visible.get(t.layer, True):
                continue
            br = text_path_local(t.text, t.size).boundingRect().adjusted(-0.3, -0.3, 0.3, 0.3)
            lx, ly = rotate_point(x - t.x, y - t.y, -t.rotation)
            if t.mirrored:
                lx = -lx
            if br.contains(QPointF(lx, ly)):
                return t
        return None

    def component_at(self, x: float, y: float) -> Component | None:
        best = None
        for c in self.doc.project.components:
            if c.side == "bottom" and not self.visible.get("B.Cu", True):
                continue
            lx, ly = _inverse(c, x, y)
            x0, y0, x1, y1 = c.footprint.courtyard
            if x0 <= lx <= x1 and y0 <= ly <= y1:
                area = (x1 - x0) * (y1 - y0)
                pref = 0 if (c.side == "top") == (self.active_layer != "B.Cu") else 1
                key = (pref, area)
                if best is None or key < best[0]:
                    best = (key, c)
        return best[1] if best else None

    def zone_at(self, x: float, y: float) -> Zone | None:
        from shapely.geometry import Point, Polygon
        pt = Point(x, y)
        tol = self.px(4)
        for z in reversed(self.doc.project.zones):
            if not self.visible.get(z.layer, True) or len(z.outline) < 3:
                continue
            poly = Polygon(z.outline)
            if poly.exterior.distance(pt) <= tol:
                return z
        for z in reversed(self.doc.project.zones):
            if z.layer == self.active_layer and len(z.outline) >= 3 and Polygon(z.outline).contains(pt):
                return z
        return None

    def item_at(self, x: float, y: float):
        v = self.via_at(x, y)
        if v:
            return v
        c, pad = self.pad_at(x, y)
        if c is not None and self.visible.get("F.Cu" if c.side == "top" else "B.Cu", True):
            return c
        t = self.track_at(x, y)
        if t:
            return t
        tx = self.text_at(x, y)
        if tx:
            return tx
        c = self.component_at(x, y)
        if c:
            return c
        return self.zone_at(x, y)

    def items_in_rect(self, x0, y0, x1, y1, crossing: bool):
        from shapely.geometry import LineString, Point, Polygon, box
        r = box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        test = r.intersects if crossing else r.contains
        out = []
        p = self.doc.project
        for c in p.components:
            if test(c.courtyard_polygon()):
                out.append(c)
        for t in p.tracks:
            if self.visible.get(t.layer, True) and test(LineString([(t.x1, t.y1), (t.x2, t.y2)]) if (t.x1, t.y1) != (t.x2, t.y2) else Point(t.x1, t.y1)):
                out.append(t)
        for v in p.vias:
            if test(Point(v.x, v.y)):
                out.append(v)
        for t in p.texts:
            if test(Point(t.x, t.y)):
                out.append(t)
        for z in p.zones:
            if len(z.outline) >= 3 and test(Polygon(z.outline)):
                out.append(z)
        return out

    # ------------------------------------------------------------------ events
    def _world(self, ev) -> tuple[float, float]:
        pos = ev.position()
        return self.to_world(pos.x(), pos.y())

    def mousePressEvent(self, ev):
        self.setFocus()
        if ev.button() == Qt.MiddleButton or (ev.button() == Qt.LeftButton and self._space):
            self._pan_last = ev.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if ev.button() == Qt.RightButton:
            self._pan_last = ev.position()
            self._right_drag = False
            return
        x, y = self._world(ev)
        if self.tool:
            self.tool.press(ev, x, y)

    def mouseMoveEvent(self, ev):
        if self._pan_last is not None:
            d = ev.position() - self._pan_last
            if ev.buttons() & Qt.RightButton and not getattr(self, "_right_drag", False):
                if abs(d.x()) + abs(d.y()) < 4:
                    return
                self._right_drag = True
                self.setCursor(Qt.ClosedHandCursor)
            self._pan_last = ev.position()
            self.cx -= d.x() / self.scale
            self.cy -= d.y() / self.scale
            self.view_changed.emit()
            self.update()
            return
        x, y = self._world(ev)
        self.mouse_world = (x, y)
        sx, sy = self.snap(x, y)
        self.cursor_moved.emit(sx, sy)
        if self.tool:
            self.tool.move(ev, x, y)

    def mouseReleaseEvent(self, ev):
        if self._pan_last is not None and ev.button() in (Qt.MiddleButton, Qt.LeftButton, Qt.RightButton):
            was_right_click = ev.button() == Qt.RightButton and not getattr(self, "_right_drag", False)
            self._pan_last = None
            self._right_drag = False
            self.setCursor(self.tool.cursor if self.tool else Qt.ArrowCursor)
            if was_right_click:
                self._context_menu(ev)
            return
        x, y = self._world(ev)
        if self.tool:
            self.tool.release(ev, x, y)

    def mouseDoubleClickEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        x, y = self._world(ev)
        if self.tool:
            self.tool.double_click(ev, x, y)

    def wheelEvent(self, ev):
        wheel = getattr(self.tool, "wheel", None)
        if wheel is not None and not ev.modifiers() and wheel(ev, *self._world(ev)):
            return  # the tool used it (simulation: turning a pot)
        dy = ev.angleDelta().y()
        if ev.modifiers() & Qt.ShiftModifier:
            self.cx -= dy / self.scale * 0.5
            self.update()
            return
        if ev.modifiers() & Qt.ControlModifier:
            self.cy -= dy / self.scale * 0.5
            self.update()
            return
        factor = 1.0015 ** dy
        pos = ev.position()
        self.zoom_at(factor, pos.x(), pos.y())

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Space and not ev.isAutoRepeat():
            self._space = True
            self.setCursor(Qt.OpenHandCursor)
            return
        if self.tool and self.tool.key(ev):
            return
        if self.key_fallback is not None and self.key_fallback(ev):
            return
        k = ev.key()
        if k in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom_at(1.25, self.width() / 2, self.height() / 2)
        elif k == Qt.Key_Minus:
            self.zoom_at(0.8, self.width() / 2, self.height() / 2)
        elif k == Qt.Key_Home:
            self.fit_board()
        elif k == Qt.Key_PageUp:
            self.set_active_layer("F.Cu")
        elif k == Qt.Key_PageDown:
            self.set_active_layer("B.Cu")
        elif k == Qt.Key_L and not ev.modifiers():
            self.flip_active_layer()
        else:
            super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        if ev.key() == Qt.Key_Space and not ev.isAutoRepeat():
            self._space = False
            self.setCursor(self.tool.cursor if self.tool else Qt.ArrowCursor)
            return
        super().keyReleaseEvent(ev)

    def leaveEvent(self, ev):
        if self.hover is not None:
            self.hover = None
            self.update()

    def _context_menu(self, ev):
        x, y = self._world(ev)
        item = self.item_at(x, y)
        if item is not None and item not in self.doc.selection:
            self.doc.set_selection([item])
        if self.tool and hasattr(self.tool, "context_menu"):
            menu = QMenu(self)
            self.tool.context_menu(menu, item, x, y)
            if not menu.isEmpty():
                menu.exec(QCursor.pos())

    # ------------------------------------------------------------------ painting
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), BG_COLOR)
        proj = self.doc.project
        if self.visible.get("Grid", True):
            self._paint_grid(p)
        p.setTransform(self.world_transform())
        self._paint_board(p)
        layers = list(proj.copper_layers)
        order = [L for L in reversed(layers) if L != self.active_layer] + [self.active_layer]
        if self.active_layer == layers[-1]:
            order = [L for L in layers if L != self.active_layer] + [self.active_layer]
        sel = set(id(i) for i in self.doc.selection)
        for L in order:
            if self.visible.get(L, True):
                self._paint_copper_layer(p, L, L == self.active_layer)
        self._paint_tht_and_vias(p)
        self._paint_holes(p)
        silk_order = ["B.SilkS", "F.SilkS"] if self.active_layer != "B.Cu" else ["F.SilkS", "B.SilkS"]
        for L in silk_order:
            if self.visible.get(L, True):
                self._paint_silk(p, L)
        if self.visible.get("Courtyard") or self.visible.get("Fab"):
            self._paint_courtyards(p)
        self._paint_outline(p)
        for overlay in self.world_overlays:
            p.save()
            overlay(p)
            p.restore()
        if self.highlight_net:
            self._paint_net_highlight(p, self.highlight_net)
        if self.visible.get("Ratsnest", True):
            self._paint_ratsnest(p)
        self._paint_selection(p, sel)
        if self.tool:
            self.tool.paint(p)
        p.resetTransform()
        if self.visible.get("PadNumbers", True):
            self._paint_pad_labels(p)
        if self.visible.get("DRC", True):
            self._paint_drc(p)
        if self.tool:
            self.tool.paint_screen(p)
        self._paint_hud(p)
        p.end()

    def _paint_grid(self, p: QPainter) -> None:
        step = self.grid
        while step * self.scale < 8:
            step *= 5 if str(step).startswith(("1", "0.1")) else 2
        x0, y0 = self.to_world(0, 0)
        x1, y1 = self.to_world(self.width(), self.height())
        gx0 = math.floor(x0 / step) * step
        gy0 = math.floor(y0 / step) * step
        nx = int((x1 - gx0) / step) + 2
        ny = int((y1 - gy0) / step) + 2
        if nx * ny > 60000:
            return
        pts = []
        for i in range(nx):
            sx = (gx0 + i * step - self.cx) * self.scale + self.width() / 2
            for j in range(ny):
                sy = (gy0 + j * step - self.cy) * self.scale + self.height() / 2
                pts.append(QPointF(sx, sy))
        p.setPen(QPen(GRID_COLOR, 1.2 if step * self.scale > 18 else 1.0))
        p.drawPoints(pts)
        # origin cross
        o = self.to_screen(0, 0)
        p.setPen(QPen(QColor(90, 98, 112), 1))
        p.drawLine(QPointF(o.x() - 8, o.y()), QPointF(o.x() + 8, o.y()))
        p.drawLine(QPointF(o.x(), o.y() - 8), QPointF(o.x(), o.y() + 8))

    def _board_path(self) -> QPainterPath:
        b = self.doc.project.board
        path = QPainterPath()
        path.setFillRule(Qt.OddEvenFill)
        if len(b.outline) >= 3:
            path.addPolygon(QPolygonF([QPointF(x, y) for x, y in b.outline]))
            path.closeSubpath()
        for c in b.cutouts:
            if len(c) >= 3:
                path.addPolygon(QPolygonF([QPointF(x, y) for x, y in c]))
                path.closeSubpath()
        return path

    def _paint_board(self, p: QPainter) -> None:
        p.setPen(Qt.NoPen)
        p.setBrush(BOARD_FILL)
        p.drawPath(self._board_path())

    def _paint_outline(self, p: QPainter) -> None:
        if not self.visible.get("Edge.Cuts", True):
            return
        p.setBrush(Qt.NoBrush)
        pen = QPen(LAYER_COLORS["Edge.Cuts"], 1.6)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.drawPath(self._board_path())

    def _layer_color(self, layer: str, active: bool) -> QColor:
        c = QColor(LAYER_COLORS.get(layer, QColor(200, 200, 200)))
        if not active:
            c = c.darker(165)
            c.setAlpha(200)
        return c

    def _zone_path(self, z: Zone) -> QPainterPath | None:
        fill = self.doc.project.zone_fills.get(z.uid)
        if fill is None:
            return None
        cached = self._zone_paths.get(z.uid)
        if cached and cached[0] == id(fill):
            return cached[1]
        path = geom_to_path(fill)
        self._zone_paths[z.uid] = (id(fill), path)
        return path

    def _paint_copper_layer(self, p: QPainter, layer: str, active: bool) -> None:
        proj = self.doc.project
        col = self._layer_color(layer, active)
        if self.visible.get("Zones", True):
            zc = QColor(col)
            zc.setAlpha(120 if active else 70)
            for z in proj.zones:
                if z.layer != layer:
                    continue
                path = self._zone_path(z)
                if path is not None:
                    p.setPen(Qt.NoPen)
                    p.setBrush(zc)
                    p.drawPath(path)
                if proj.fills_stale or path is None or z in self.doc.selection:
                    pen = QPen(col, 1.2, Qt.DashLine)
                    pen.setCosmetic(True)
                    p.setPen(pen)
                    p.setBrush(Qt.NoBrush)
                    p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in z.outline]))
        pen = QPen(col, 0.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        for t in proj.tracks:
            if t.layer == layer:
                pen.setWidthF(t.width)
                p.setPen(pen)
                p.drawLine(QPointF(t.x1, t.y1), QPointF(t.x2, t.y2))
        # SMD pads on this layer
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        want_side = "top" if layer == "F.Cu" else ("bottom" if layer == "B.Cu" else None)
        if want_side is None:
            return
        for c in proj.components:
            if c.side != want_side:
                continue
            p.save()
            p.setTransform(comp_transform(c), True)
            for pad in c.footprint.pads:
                if pad.kind != "smd":
                    continue
                p.save()
                p.translate(pad.x, pad.y)
                if pad.rotation:
                    p.rotate(-pad.rotation)
                p.drawPath(pad_qpath(pad))
                p.restore()
            p.restore()

    def _paint_tht_and_vias(self, p: QPainter) -> None:
        proj = self.doc.project
        p.setPen(Qt.NoPen)
        p.setBrush(THT_COLOR)
        for c in proj.components:
            p.save()
            p.setTransform(comp_transform(c), True)
            for pad in c.footprint.pads:
                if pad.kind != "tht":
                    continue
                p.save()
                p.translate(pad.x, pad.y)
                if pad.rotation:
                    p.rotate(-pad.rotation)
                p.drawPath(pad_qpath(pad))
                p.restore()
            p.restore()
        p.setBrush(VIA_COLOR)
        for v in proj.vias:
            p.drawEllipse(QPointF(v.x, v.y), v.diameter / 2, v.diameter / 2)

    def _paint_holes(self, p: QPainter) -> None:
        proj = self.doc.project
        p.setPen(Qt.NoPen)
        p.setBrush(HOLE_COLOR)
        for h in holes(proj):
            path = geom_to_path(h.geom(quad_segs=6)) if h.is_slot else None
            if path is not None:
                p.drawPath(path)
            else:
                p.drawEllipse(QPointF(h.x, h.y), h.diameter / 2, h.diameter / 2)
            if not h.plated:
                pen = QPen(QColor(120, 126, 138), 1.0)
                pen.setCosmetic(True)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                if path is not None:
                    p.drawPath(path)
                else:
                    p.drawEllipse(QPointF(h.x, h.y), h.diameter / 2, h.diameter / 2)
                p.setPen(Qt.NoPen)
                p.setBrush(HOLE_COLOR)

    def _paint_graphics(self, p: QPainter, graphics, layer: str, color: QColor) -> None:
        pen = QPen(color, 0.12, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        for g in graphics:
            if g.layer != layer:
                continue
            pen.setWidthF(max(g.width, 0.01))
            p.setPen(pen)
            if g.kind == "line":
                (x1, y1), (x2, y2) = g.pts
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            elif g.kind == "circle":
                (cx, cy), = g.pts
                p.setBrush(color if g.fill else Qt.NoBrush)
                p.drawEllipse(QPointF(cx, cy), g.r, g.r)
                p.setBrush(Qt.NoBrush)
            elif g.kind == "arc":
                (cx, cy), = g.pts
                p.drawArc(QRectF(cx - g.r, cy - g.r, 2 * g.r, 2 * g.r), int(g.start * 16), int(g.sweep * 16))
            elif g.kind == "poly":
                p.setBrush(color if g.fill else Qt.NoBrush)
                p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in g.pts]))
                p.setBrush(Qt.NoBrush)

    def _paint_text_item(self, p: QPainter, text: str, x: float, y: float, size: float, rot: float, mirror: bool,
                         color: QColor) -> None:
        path = text_path_local(text, round(size, 4))
        p.save()
        p.translate(x, y)
        p.rotate(-rot)
        if mirror:
            p.scale(-1, 1)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawPath(path)
        p.restore()

    def _paint_silk(self, p: QPainter, layer: str) -> None:
        proj = self.doc.project
        active_side = "bottom" if self.active_layer == "B.Cu" else "top"
        col = QColor(LAYER_COLORS[layer])
        if (layer == "B.SilkS") != (active_side == "bottom"):
            col = col.darker(170)
        side = "top" if layer == "F.SilkS" else "bottom"
        for c in proj.components:
            if c.side != side:
                continue
            p.save()
            p.setTransform(comp_transform(c), True)
            self._paint_graphics(p, c.footprint.graphics, "silk", col)
            p.restore()
            if c.show_ref and c.ref:
                rx, ry = c.to_board(*c.footprint.ref_pos)
                self._paint_text_item(p, c.ref, rx, ry, 0.9, c.rotation % 180, c.mirror, col)
            if c.show_value and c.value:
                from ..model.artwork import value_anchor
                vx, vy = value_anchor(c)
                self._paint_text_item(p, c.value, vx, vy, 0.9, c.rotation % 180, c.mirror, col)
        for t in proj.texts:
            if t.layer == layer:
                self._paint_text_item(p, t.text, t.x, t.y, t.size, t.rotation, t.mirrored, col)

    def _paint_courtyards(self, p: QPainter) -> None:
        for c in self.doc.project.components:
            p.save()
            p.setTransform(comp_transform(c), True)
            if self.visible.get("Fab"):
                self._paint_graphics(p, c.footprint.graphics, "fab", FAB_COLOR)
            if self.visible.get("Courtyard"):
                pen = QPen(COURTYARD_COLOR, 1.0)
                pen.setCosmetic(True)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                x0, y0, x1, y1 = c.footprint.courtyard
                p.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))
            p.restore()

    def _paint_ratsnest(self, p: QPainter) -> None:
        conn = get_connectivity(self.doc.project)
        pen = QPen(RATS_COLOR, 1.0)
        pen.setCosmetic(True)
        p.setPen(pen)
        for rl in conn.ratsnest:
            if self.highlight_net and rl.net == self.highlight_net:
                hp = QPen(QColor(255, 220, 90), 1.6)
                hp.setCosmetic(True)
                p.setPen(hp)
                p.drawLine(QPointF(rl.x1, rl.y1), QPointF(rl.x2, rl.y2))
                p.setPen(pen)
            else:
                p.drawLine(QPointF(rl.x1, rl.y1), QPointF(rl.x2, rl.y2))

    def _paint_net_highlight(self, p: QPainter, net: str) -> None:
        proj = self.doc.project
        hl = QColor(255, 255, 255, 90)
        pen = QPen(hl, 0.2, Qt.SolidLine, Qt.RoundCap)
        for t in proj.tracks:
            if t.net == net and self.visible.get(t.layer, True):
                pen.setWidthF(t.width)
                p.setPen(pen)
                p.drawLine(QPointF(t.x1, t.y1), QPointF(t.x2, t.y2))
        p.setPen(Qt.NoPen)
        p.setBrush(hl)
        for v in proj.vias:
            if v.net == net:
                p.drawEllipse(QPointF(v.x, v.y), v.diameter / 2, v.diameter / 2)
        for c in proj.components:
            p.save()
            p.setTransform(comp_transform(c), True)
            for pad in c.footprint.pads:
                if c.pad_nets.get(pad.number) == net:
                    p.save()
                    p.translate(pad.x, pad.y)
                    if pad.rotation:
                        p.rotate(-pad.rotation)
                    p.drawPath(pad_qpath(pad))
                    p.restore()
            p.restore()

    def _paint_item_outline(self, p: QPainter, item, color: QColor, width_px: float = 1.6) -> None:
        pen = QPen(color, width_px)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if isinstance(item, Component):
            p.save()
            p.setTransform(comp_transform(item), True)
            x0, y0, x1, y1 = item.footprint.courtyard
            p.setBrush(QColor(color.red(), color.green(), color.blue(), 28))
            p.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))
            for pad in item.footprint.pads:
                p.save()
                p.translate(pad.x, pad.y)
                if pad.rotation:
                    p.rotate(-pad.rotation)
                p.setBrush(Qt.NoBrush)
                p.drawPath(pad_qpath(pad))
                p.restore()
            p.restore()
        elif isinstance(item, Track):
            path = QPainterPath()
            path.moveTo(item.x1, item.y1)
            path.lineTo(item.x2, item.y2)
            from PySide6.QtGui import QPainterPathStroker
            st = QPainterPathStroker()
            st.setWidth(item.width)
            st.setCapStyle(Qt.RoundCap)
            p.drawPath(st.createStroke(path))
        elif isinstance(item, Via):
            p.drawEllipse(QPointF(item.x, item.y), item.diameter / 2 + self.px(2), item.diameter / 2 + self.px(2))
        elif isinstance(item, Zone):
            pen = QPen(color, 2.0, Qt.DashLine)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in item.outline]))
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            for x, y in item.outline:
                s = self.px(3)
                p.drawRect(QRectF(x - s, y - s, 2 * s, 2 * s))
        elif isinstance(item, Text):
            br = text_path_local(item.text, item.size).boundingRect().adjusted(-0.2, -0.2, 0.2, 0.2)
            p.save()
            p.translate(item.x, item.y)
            p.rotate(-item.rotation)
            if item.mirrored:
                p.scale(-1, 1)
            p.drawRect(br)
            p.restore()

    def _paint_selection(self, p: QPainter, sel_ids: set) -> None:
        for it in self.doc.selection:
            self._paint_item_outline(p, it, SEL_COLOR, 1.8)
        if self.hover is not None and id(self.hover) not in sel_ids:
            self._paint_item_outline(p, self.hover, QColor(140, 200, 255, 200), 1.2)

    def _paint_pad_labels(self, p: QPainter) -> None:
        proj = self.doc.project
        if self.scale < 9:
            return
        font = QFont("Segoe UI")
        show_nets = self.visible.get("NetNames", True)
        rect_all = QRectF(self.rect())
        for c in proj.components:
            if c.side == "bottom" and not self.visible.get("B.Cu", True):
                continue
            for pad in c.footprint.pads:
                if pad.kind == "npth" or (not pad.number and not c.pad_nets.get(pad.number)):
                    continue
                x, y = c.pad_pos(pad)
                sp = self.to_screen(x, y)
                if not rect_all.contains(sp):
                    continue
                rot = c.pad_rotation(pad) % 180
                pw, ph = (pad.w, pad.h) if abs(rot - 90) > 45 else (pad.h, pad.w)
                sw, sh = pw * self.scale, ph * self.scale
                m = min(sw, sh)
                if m < 11:
                    continue
                net = c.pad_nets.get(pad.number) if show_nets else None
                vertical = sh > sw * 1.3
                fs = max(6.0, min(m * 0.42, 13.0))
                font.setPixelSize(int(fs))
                p.setFont(font)
                p.save()
                p.translate(sp)
                if vertical:
                    p.rotate(-90)
                    sw, sh = sh, sw
                p.setPen(QColor(255, 255, 255, 230))
                if net and max(sw, sh) > 36:
                    p.drawText(QRectF(-sw / 2, -sh / 2, sw, sh / 2 + 2), Qt.AlignHCenter | Qt.AlignBottom, pad.number)
                    font.setPixelSize(int(max(6.0, fs * 0.8)))
                    p.setFont(font)
                    p.setPen(QColor(255, 255, 210, 220))
                    fm = QFontMetricsF(font)
                    label = fm.elidedText(net, Qt.ElideRight, sw - 2)
                    p.drawText(QRectF(-sw / 2, 0, sw, sh / 2), Qt.AlignHCenter | Qt.AlignTop, label)
                else:
                    p.drawText(QRectF(-sw / 2, -sh / 2, sw, sh), Qt.AlignCenter, pad.number or "")
                p.restore()

    def _paint_drc(self, p: QPainter) -> None:
        for v in self.drc_markers:
            if v.kind == "zones":
                continue
            sp = self.to_screen(v.x, v.y)
            col = DRC_COLOR if v.severity == "error" else QColor(245, 184, 61)
            p.setPen(QPen(col, 2))
            p.setBrush(QColor(col.red(), col.green(), col.blue(), 50))
            p.drawEllipse(sp, 7, 7)
            p.drawLine(sp + QPointF(-4, -4), sp + QPointF(4, 4))
            p.drawLine(sp + QPointF(-4, 4), sp + QPointF(4, -4))
        if self.focus_marker is not None:
            sp = self.to_screen(*self.focus_marker)
            p.setPen(QPen(QColor(255, 255, 255), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(sp, 14, 14)

    def _paint_hud(self, p: QPainter) -> None:
        # scale bar
        target = 120 / self.scale
        mag = 10 ** math.floor(math.log10(target))
        for m in (1, 2, 5, 10):
            if m * mag >= target * 0.5:
                length = m * mag
                break
        px = length * self.scale
        x0, y0 = 16, self.height() - 18
        p.setPen(QPen(QColor(150, 158, 172), 1.5))
        p.drawLine(QPointF(x0, y0), QPointF(x0 + px, y0))
        p.drawLine(QPointF(x0, y0 - 4), QPointF(x0, y0 + 4))
        p.drawLine(QPointF(x0 + px, y0 - 4), QPointF(x0 + px, y0 + 4))
        f = QFont("Segoe UI")
        f.setPixelSize(11)
        p.setFont(f)
        p.drawText(QPointF(x0 + px + 6, y0 + 4), f"{length:g} mm")
        # active layer chip
        col = LAYER_COLORS.get(self.active_layer, QColor(200, 200, 200))
        text = f"  {self.active_layer}  "
        fm = QFontMetricsF(f)
        w = fm.horizontalAdvance(text) + 14
        r = QRectF(self.width() - w - 12, 10, w, 22)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(30, 34, 41, 230))
        p.drawRoundedRect(r, 6, 6)
        p.setBrush(col)
        p.drawEllipse(QPointF(r.left() + 11, r.center().y()), 4.5, 4.5)
        p.setPen(QColor(220, 224, 232))
        p.drawText(r.adjusted(14, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, text)


def _inverse(c: Component, x: float, y: float) -> tuple[float, float]:
    lx, ly = rotate_point(x - c.x, y - c.y, -c.rotation)
    if c.mirror:
        lx = -lx
    return lx, ly
