"""Grid-based multi-layer autorouter.

Obstacles are rasterised with Qt (fast polygon scan conversion) into a per-net
occupancy grid, then connections are routed with A* over 8-connected moves
(45 degree routing) plus via transitions between layers.
"""
from __future__ import annotations

import heapq
import math
from array import array
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF, QTransform

from ..model.board import Project, Track, Via
from ..model.connectivity import Cluster, Connectivity
from ..model.copper import CopperShape, collect_copper, fill_all_zones, holes
from ..model.geometry import iter_polygons

SQ2 = math.sqrt(2.0)
DIRS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, SQ2), (1, -1, SQ2), (-1, 1, SQ2), (-1, -1, SQ2)]


@dataclass
class RouteResult:
    tracks: list = field(default_factory=list)
    vias: list = field(default_factory=list)
    routed: int = 0
    failed: int = 0
    failed_nets: list = field(default_factory=list)
    cancelled: bool = False


def _geom_path(g) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.OddEvenFill)
    for poly in iter_polygons(g):
        path.addPolygon(QPolygonF([QPointF(x, y) for x, y in poly.exterior.coords]))
        for ring in poly.interiors:
            path.addPolygon(QPolygonF([QPointF(x, y) for x, y in ring.coords]))
    return path


class Autorouter:
    def __init__(self, project: Project, grid: float | None = None, via_cost: float = 10.0,
                 progress: Callable[[int, int, str], None] | None = None,
                 cancelled: Callable[[], bool] | None = None, max_expansions: int = 400_000,
                 route_pour_nets: bool = True, nets: set | None = None):
        self.p = project
        self.via_cost = via_cost
        self.progress = progress or (lambda a, b, m: None)
        self.cancelled = cancelled or (lambda: False)
        self.max_expansions = max_expansions
        self.route_pour_nets = route_pour_nets
        self.only_nets = nets
        board = project.board.polygon()
        self.board = board
        minx, miny, maxx, maxy = board.bounds
        if grid is None:
            nc = project.netclass_for(None)
            grid = max(0.1, min(0.25, (nc.track_width + nc.clearance) / 2))
        # Keep the grid tractable for big boards.
        while ((maxx - minx) / grid) * ((maxy - miny) / grid) > 300_000:
            grid *= 1.25
        self.g = grid
        self.x0, self.y0 = minx, miny
        self.W = int(math.ceil((maxx - minx) / grid)) + 1
        self.H = int(math.ceil((maxy - miny) / grid)) + 1
        self.layers = project.copper_layers
        self.NL = len(self.layers)
        self.xf = QTransform()
        self.xf.translate(0.5, 0.5)
        self.xf.scale(1 / grid, 1 / grid)
        self.xf.translate(-minx, -miny)
        self._path_cache: dict[int, QPainterPath] = {}
        self.result = RouteResult()
        self.soft_zones = False  # True: other nets' pours are not obstacles (they get refilled afterwards)
        # amp boards: live nets need IPC spacing from each other (B+ next to a heater, both ends of an HV winding)
        self._pair = None
        self._rank = None  # optional routing priority per net (lower routes first)
        if getattr(project, "amp", None):
            from ..amp.hv import net_info, pair_clearance_fn
            self._pair = pair_clearance_fn(project)
            if self._pair is not None:  # the widest-spaced (highest-voltage) nets need the free board most
                self._rank = lambda net: -round(net_info(project, net).peak, -2)

    # ------------------------------------------------------------------ rasterisation
    def _new_image(self, fill: int) -> QImage:
        img = QImage(self.W, self.H, QImage.Format_Grayscale8)
        img.fill(fill)
        return img

    @staticmethod
    def _to_array(img: QImage) -> np.ndarray:
        bpl = img.bytesPerLine()
        arr = np.frombuffer(img.constBits(), dtype=np.uint8, count=bpl * img.height()).reshape(img.height(), bpl)
        return arr[:, : img.width()].copy()

    def _shape_path(self, s: CopperShape) -> QPainterPath:
        key = id(s.geom)
        p = self._path_cache.get(key)
        if p is None:
            p = _geom_path(s.geom)
            self._path_cache[key] = p
        return p

    def _paint_inflated(self, painter: QPainter, s: CopperShape, r: float) -> None:
        if s.kind == "track":
            t = s.obj
            pen = QPen(QColor(255, 255, 255), t.width + 2 * r, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawLine(QPointF(t.x1, t.y1), QPointF(t.x2, t.y2))
            return
        if s.kind == "via":
            v = s.obj
            rr = v.diameter / 2 + r
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255))
            painter.drawEllipse(QPointF(v.x, v.y), rr, rr)
            return
        path = self._shape_path(s)
        painter.setBrush(QColor(255, 255, 255))
        if r > 0:
            painter.setPen(QPen(QColor(255, 255, 255), 2 * r, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        else:
            painter.setPen(Qt.NoPen)
        painter.drawPath(path)

    def _begin(self, img: QImage) -> QPainter:
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setTransform(self.xf)
        return painter

    def _blocked_grid(self, net: str, conn: Connectivity, inflate: float, clearance: float,
                      edge_inset: float, same_net_pad_r: float | None) -> list[np.ndarray]:
        """Per-layer uint8 grids: 255 = blocked for the centre line of copper of `net`."""
        shapes = collect_copper(self.p, include_zones=True)
        out = []
        board_in = self.board.buffer(-edge_inset, join_style="mitre")
        board_path = _geom_path(board_in)
        hole_list = holes(self.p)
        for layer in self.layers:
            img = self._new_image(255)
            painter = self._begin(img)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0))
            painter.drawPath(board_path)
            for s in shapes:
                if s.layer != layer:
                    continue
                en = conn.effective_net(s)
                if en == net:
                    if same_net_pad_r is not None and s.kind == "pad":
                        self._paint_inflated(painter, s, same_net_pad_r)
                    continue
                if s.kind == "zone" and self.soft_zones:
                    continue  # retry pass: route through other nets' pours; they are refilled afterwards
                cl = max(clearance, self.p.netclass_for(en).clearance)
                if self._pair is not None:  # + rasterisation slack: round caps at these large spacings
                    cl = max(cl, self._pair(net, en, s.kind == "pad")) + 0.03 + 0.4 * self.g
                if s.kind == "zone":
                    cl = min(cl, s.obj.clearance)
                self._paint_inflated(painter, s, cl + inflate)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255))
            for h in hole_list:
                if not h.plated:
                    painter.drawPath(_geom_path(h.geom(clearance + inflate, quad_segs=4)))
            painter.end()
            out.append(self._to_array(img))
        return out

    def _cluster_cells(self, clusters: list[Cluster], inset: float = 0.0
                       ) -> tuple[list[np.ndarray], list[tuple[float, float, int]]]:
        """Per-layer masks of cells covered by the clusters' copper, and pad anchors. With ``inset`` (half the new
        track's width) only cells that far inside the copper count, so a track never starts at a pad's edge and
        sticks out towards a neighbouring pin; pad and via centres always count."""
        masks = []
        anchors = []
        for li, layer in enumerate(self.layers):
            img = self._new_image(0)
            painter = self._begin(img)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255))
            for cl in clusters:
                for s in cl.shapes:
                    if s.layer != layer:
                        continue
                    if s.kind == "track":
                        t = s.obj
                        width = max(t.width - 2 * inset, 0.01)
                        painter.setPen(QPen(QColor(255, 255, 255), width, Qt.SolidLine, Qt.RoundCap))
                        painter.drawLine(QPointF(t.x1, t.y1), QPointF(t.x2, t.y2))
                        painter.setPen(Qt.NoPen)
                    elif inset > 0:
                        inner = s.geom.buffer(-inset)
                        if not inner.is_empty:
                            painter.drawPath(_geom_path(inner))
                    else:
                        painter.drawPath(self._shape_path(s))
                    if s.kind in ("pad", "via"):
                        if s.kind == "pad":
                            x, y = s.obj.pad_pos(s.pad)
                        else:
                            x, y = s.obj.x, s.obj.y
                        anchors.append((x, y, li))
                        if inset > 0:
                            painter.drawEllipse(QPointF(x, y), self.g * 0.6, self.g * 0.6)
            painter.end()
            masks.append(self._to_array(img) > 0)
        return masks, anchors

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        ix = int(round((x - self.x0) / self.g))
        iy = int(round((y - self.y0) / self.g))
        return min(max(ix, 0), self.W - 1), min(max(iy, 0), self.H - 1)

    # ------------------------------------------------------------------ search
    def _astar(self, passable: list[bytes], via_ok: bytes, sources: dict, targets: set, tbox) -> list[int] | None:
        W, H, NL = self.W, self.H, self.NL
        WH = W * H
        INF = 1e30
        gs = array("d", [INF]) * (NL * WH)
        par = array("l", [-1]) * (NL * WH)
        tx0, ty0, tx1, ty1 = tbox
        vcost = self.via_cost
        heap = []
        hw = 1.25  # weighted A*: much faster, slightly longer routes

        def hfun(ix, iy):
            dx = tx0 - ix if ix < tx0 else (ix - tx1 if ix > tx1 else 0)
            dy = ty0 - iy if iy < ty0 else (iy - ty1 if iy > ty1 else 0)
            return (dx + dy + (SQ2 - 2) * (dx if dx < dy else dy)) * hw

        for s, g0 in sources.items():
            gs[s] = g0
            rem = s % WH
            heapq.heappush(heap, (g0 + hfun(rem % W, rem // W), g0, s))
        # direction penalties: layer 0 prefers horizontal, last layer vertical
        pen_h = [1.0] * NL
        pen_v = [1.0] * NL
        if NL >= 2:
            pen_v[0] = 1.3
            pen_h[NL - 1] = 1.3
        expansions = 0
        maxexp = self.max_expansions
        while heap:
            f, gc, cur = heapq.heappop(heap)
            if gc > gs[cur]:
                continue
            if cur in targets:
                path = [cur]
                while par[cur] != -1:
                    cur = par[cur]
                    path.append(cur)
                path.reverse()
                return path
            expansions += 1
            if expansions > maxexp:
                return None
            l, rem = divmod(cur, WH)
            iy, ix = divmod(rem, W)
            pl = passable[l]
            base = l * WH
            p = par[cur]
            if p != -1 and p // WH == l:
                prem = p % WH
                pdx = ix - prem % W
                pdy = iy - prem // W
            else:
                pdx = pdy = 0
            ph, pv = pen_h[l], pen_v[l]
            for dx, dy, c in DIRS:
                nx = ix + dx
                ny = iy + dy
                if nx < 0 or ny < 0 or nx >= W or ny >= H:
                    continue
                nrem = ny * W + nx
                if not pl[nrem]:
                    continue
                if dy == 0:
                    c *= ph
                elif dx == 0:
                    c *= pv
                if (pdx or pdy) and (dx != pdx or dy != pdy):
                    c += 0.35
                ng = gc + c
                n = base + nrem
                if ng < gs[n]:
                    gs[n] = ng
                    par[n] = cur
                    heapq.heappush(heap, (ng + hfun(nx, ny), ng, n))
            if via_ok[rem]:
                for l2 in range(NL):
                    if l2 == l or not passable[l2][rem]:
                        continue
                    n = l2 * WH + rem
                    ng = gc + vcost
                    if ng < gs[n]:
                        gs[n] = ng
                        par[n] = cur
                        heapq.heappush(heap, (ng + hfun(ix, iy), ng, n))
        return None

    # ------------------------------------------------------------------ one connection
    def _route_connection(self, net: str, conn: Connectivity, src: Cluster, dst: list[Cluster]) -> bool:
        nc = self.p.netclass_for(net)
        w = nc.track_width
        clr = max(nc.clearance, self.p.rules.clearance)
        margin = 0.02 + self.g * self.g / (4 * (clr + w / 2))
        edge = self.p.rules.edge_clearance
        track_block = self._blocked_grid(net, conn, w / 2 + margin, clr, edge + w / 2, None)
        via_d = nc.via_diameter
        via_block_layers = self._blocked_grid(net, conn, via_d / 2 + margin, clr, edge + via_d / 2, via_d / 2)
        via_block = np.zeros((self.H, self.W), dtype=bool)
        for vb in via_block_layers:
            via_block |= vb > 0
        # hole-to-hole spacing for new vias
        img = self._new_image(0)
        painter = self._begin(img)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        for h in holes(self.p):
            painter.drawPath(_geom_path(h.geom(nc.via_drill / 2 + self.p.rules.hole_to_hole + margin, quad_segs=4)))
        painter.end()
        via_block |= self._to_array(img) > 0

        inset = w / 2 + 0.02 if self._pair is not None else 0.0  # amp boards: keep track ends inside the pads
        src_masks, src_anchors = self._cluster_cells([src], inset)
        dst_masks, dst_anchors = self._cluster_cells(dst, inset)
        WH = self.W * self.H
        sources: dict[int, float] = {}
        targets: set[int] = set()
        passable = []
        for li in range(self.NL):
            free = track_block[li] == 0
            sm = src_masks[li]
            dm = dst_masks[li]
            free = free | sm | dm
            passable.append(free.astype(np.uint8).tobytes())
            ys, xs = np.nonzero(sm)
            for iy, ix in zip(ys.tolist(), xs.tolist()):
                sources[li * WH + iy * self.W + ix] = 0.0
            ys, xs = np.nonzero(dm)
            for iy, ix in zip(ys.tolist(), xs.tolist()):
                targets.add(li * WH + iy * self.W + ix)
        for x, y, li in src_anchors:
            ix, iy = self._cell(x, y)
            sources.setdefault(li * WH + iy * self.W + ix, 0.0)
        for x, y, li in dst_anchors:
            ix, iy = self._cell(x, y)
            targets.add(li * WH + iy * self.W + ix)
        if not sources or not targets:
            return False
        # Make anchor cells passable even when they are off-grid
        passable = [bytearray(pl) for pl in passable]
        for s in list(sources) + list(targets):
            l, rem = divmod(s, WH)
            passable[l][rem] = 1
        # Prefer starting close to pad centres
        if src_anchors:
            ax = np.array([(x - self.x0) / self.g for x, y, _ in src_anchors])
            ay = np.array([(y - self.y0) / self.g for x, y, _ in src_anchors])
            for s in sources:
                rem = s % WH
                iy, ix = divmod(rem, self.W)
                sources[s] = 0.3 * float(np.min(np.hypot(ax - ix, ay - iy)))
        trem = [t % WH for t in targets]
        txs = [r % self.W for r in trem]
        tys = [r // self.W for r in trem]
        tbox = (min(txs), min(tys), max(txs), max(tys))
        via_ok = (~via_block).astype(np.uint8).tobytes()
        path = self._astar([bytes(pl) for pl in passable], via_ok, sources, targets, tbox)
        if path is None:
            return False
        self._commit_path(net, path, w, nc, src_anchors, dst_anchors)
        return True

    def _commit_path(self, net, path, width, nc, src_anchors, dst_anchors) -> None:
        WH = self.W * self.H
        cells = []
        for n in path:
            l, rem = divmod(n, WH)
            iy, ix = divmod(rem, self.W)
            cells.append((l, ix, iy))
        # split into per-layer runs, placing vias at layer changes
        runs: list[tuple[int, list[tuple[float, float]]]] = []
        cur_l = cells[0][0]
        pts = []
        for l, ix, iy in cells:
            x, y = self.x0 + ix * self.g, self.y0 + iy * self.g
            if l != cur_l:
                runs.append((cur_l, pts))
                self.result.vias.append(Via(x, y, nc.via_diameter, nc.via_drill, net))
                self.p.vias.append(self.result.vias[-1])
                pts = [(x, y)]
                cur_l = l
            else:
                pts.append((x, y))
        runs.append((cur_l, pts))

        def snap_end(pt, anchors, li):
            best = None
            for ax, ay, al in anchors:
                if al != li:
                    continue
                d = math.hypot(ax - pt[0], ay - pt[1])
                if d <= self.g * 1.5 and (best is None or d < best[0]):
                    best = (d, (ax, ay))
            return best[1] if best else None

        # extend the ends to pad centres when the end cell lies next to the pad centre
        first_l, first_pts = runs[0]
        a = snap_end(first_pts[0], src_anchors, first_l)
        if a and a != first_pts[0]:
            first_pts.insert(0, a)
        last_l, last_pts = runs[-1]
        b = snap_end(last_pts[-1], dst_anchors, last_l)
        if b and b != last_pts[-1]:
            last_pts.append(b)

        for li, pts in runs:
            simp = _simplify(pts)
            layer = self.layers[li]
            for (x1, y1), (x2, y2) in zip(simp, simp[1:]):
                t = Track(round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4), width, layer, net)
                self.result.tracks.append(t)
                self.p.tracks.append(t)
        self.p.touch()
        self._path_cache.clear()

    # ------------------------------------------------------------------ driver
    def _pending(self, conn: Connectivity, allowed: Callable[[str], bool], failed: set):
        cands = [rl for rl in conn.ratsnest if allowed(rl.net) and _key(rl) not in failed]
        if self._rank is not None:
            return sorted(cands, key=lambda rl: (self._rank(rl.net), rl.length))
        return sorted(cands, key=lambda rl: rl.length)

    def _route_phase(self, allowed: Callable[[str], bool], failed: set, total_hint: int) -> None:
        while not self.cancelled():
            conn = Connectivity(self.p)
            pending = self._pending(conn, allowed, failed)
            if not pending:
                return
            rl = pending[0]
            clusters = conn.net_clusters[rl.net]
            src = next((c for c in clusters if (rl.x1, rl.y1) in c.anchors), clusters[0])
            dst = [c for c in clusters if c is not src]
            done = self.result.routed + self.result.failed
            self.progress(done, max(total_hint, done + len(pending)), f"Routing {rl.net}")
            if self._route_connection(rl.net, conn, src, dst):
                self.result.routed += 1
            else:
                failed.add(_key(rl))
                self.result.failed += 1
                if rl.net not in self.result.failed_nets:
                    self.result.failed_nets.append(rl.net)

    def run(self) -> RouteResult:
        pour_nets = {z.net for z in self.p.zones if z.net}
        conn = Connectivity(self.p)
        total = conn.unrouted_count()
        failed: set = set()

        def normal(net):
            return (self.only_nets is None or net in self.only_nets) and net not in pour_nets

        self._route_phase(normal, failed, total)
        if failed and self.p.zones and not self.cancelled():
            # pours on every layer (a GND plane top and bottom is common) leave no room: retry the failures
            # routing straight through other nets' pours, which then flow around the new tracks
            self.soft_zones = True
            self._route_phase(normal, set(), total)
            self.soft_zones = False
        if self.route_pour_nets and pour_nets and not self.cancelled():
            fill_all_zones(self.p)
            self._path_cache.clear()

            def pour(net):
                return (self.only_nets is None or net in self.only_nets) and net in pour_nets

            self._route_phase(pour, failed, total)
        if pour_nets:
            fill_all_zones(self.p)
        # report what is still unrouted rather than the number of failed attempts
        remaining = [rl for rl in Connectivity(self.p).ratsnest
                     if self.only_nets is None or rl.net in self.only_nets]
        self.result.failed = len(remaining)
        self.result.failed_nets = sorted({rl.net for rl in remaining})
        self.result.cancelled = self.cancelled()
        self.progress(total, total, "Done")
        return self.result


def _key(rl) -> tuple:
    return (rl.net, round(rl.x1, 3), round(rl.y1, 3), round(rl.x2, 3), round(rl.y2, 3))


def _simplify(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for p in pts:
        if out and abs(out[-1][0] - p[0]) < 1e-9 and abs(out[-1][1] - p[1]) < 1e-9:
            continue
        out.append(p)
    if len(out) < 3:
        return out
    res = [out[0]]
    for i in range(1, len(out) - 1):
        ax, ay = res[-1]
        bx, by = out[i]
        cx, cy = out[i + 1]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if abs(cross) > 1e-9:
            res.append(out[i])
    res.append(out[-1])
    return res
