"""Physical connectivity analysis: clusters, ratsnest (unrouted connections) and shorts."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from shapely.strtree import STRtree

from .board import Project
from .copper import CopperShape, collect_copper


class UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, a: str) -> str:
        p = self.parent
        p.setdefault(a, a)
        root = a
        while p[root] != root:
            root = p[root]
        while p[a] != root:
            p[a], a = root, p[a]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


@dataclass
class Cluster:
    root: str
    nodes: set = field(default_factory=set)
    anchors: list = field(default_factory=list)  # (x, y, layer-set-key)
    shapes: list = field(default_factory=list)


@dataclass
class RatLine:
    net: str
    x1: float
    y1: float
    x2: float
    y2: float
    length: float


@dataclass
class Short:
    nets: tuple
    x: float
    y: float


class Connectivity:
    def __init__(self, project: Project):
        self.project = project
        shapes = collect_copper(project, include_zones=True)
        self.shapes = shapes
        uf = UnionFind()
        by_layer: dict[str, list[CopperShape]] = defaultdict(list)
        for s in shapes:
            uf.find(s.node)
            by_layer[s.layer].append(s)
        # Pads that share a number in one footprint are internally connected (e.g. switch legs).
        for c in project.components:
            first: dict[str, str] = {}
            for i, pad in enumerate(c.footprint.pads):
                if not pad.number or pad.kind == "npth":
                    continue
                node = f"{c.uid}:{i}"
                if pad.number in first:
                    uf.union(first[pad.number], node)
                else:
                    first[pad.number] = node
        self.touch_pairs: list[tuple[CopperShape, CopperShape]] = []
        for layer, items in by_layer.items():
            if len(items) < 2:
                continue
            tree = STRtree([s.geom for s in items])
            left, right = tree.query([s.geom for s in items], predicate="intersects")
            for i, j in zip(left.tolist(), right.tolist()):
                if i < j:
                    a, b = items[i], items[j]
                    if a.node != b.node:
                        uf.union(a.node, b.node)
                        self.touch_pairs.append((a, b))
        self.uf = uf

        # group nodes into clusters and determine net membership
        clusters: dict[str, Cluster] = {}
        node_seen: set = set()
        for s in shapes:
            r = uf.find(s.node)
            cl = clusters.get(r)
            if cl is None:
                cl = clusters[r] = Cluster(r)
            cl.shapes.append(s)
            if s.node in node_seen:
                continue
            node_seen.add(s.node)
            cl.nodes.add(s.node)
            if s.kind == "pad":
                x, y = s.obj.pad_pos(s.pad)
                cl.anchors.append((x, y))
            elif s.kind == "via":
                cl.anchors.append((s.obj.x, s.obj.y))
            elif s.kind == "track":
                t = s.obj
                cl.anchors.append((t.x1, t.y1))
                cl.anchors.append((t.x2, t.y2))
            elif s.kind == "zone":
                p = s.geom.representative_point()
                cl.anchors.append((p.x, p.y))
        self.clusters = clusters

        self.cluster_nets: dict[str, set] = {}
        for r, cl in clusters.items():
            nets = {s.net for s in cl.shapes if s.net}
            self.cluster_nets[r] = nets

        self.shorts: list[Short] = []
        for r, nets in self.cluster_nets.items():
            if len(nets) > 1:
                # locate the touching pair responsible
                loc = None
                for a, b in self.touch_pairs:
                    if uf.find(a.node) == r and a.net and b.net and a.net != b.net:
                        p = a.geom.intersection(b.geom).representative_point()
                        loc = (p.x, p.y)
                        break
                if loc is None:
                    loc = clusters[r].anchors[0] if clusters[r].anchors else (0, 0)
                self.shorts.append(Short(tuple(sorted(nets)), loc[0], loc[1]))

        self.net_clusters: dict[str, list[Cluster]] = defaultdict(list)
        for r, nets in self.cluster_nets.items():
            for n in nets:
                self.net_clusters[n].append(clusters[r])

        self.ratsnest: list[RatLine] = []
        for net, cls in self.net_clusters.items():
            if len(cls) > 1:
                self.ratsnest.extend(_mst(net, cls))

    # ------------------------------------------------------------------ queries
    def node_net(self, node: str) -> str | None:
        r = self.uf.find(node)
        nets = self.cluster_nets.get(r, set())
        return next(iter(nets)) if len(nets) == 1 else None

    def effective_net(self, s: CopperShape) -> str | None:
        return s.net or self.node_net(s.node)

    def unrouted_count(self) -> int:
        return len(self.ratsnest)

    def net_status(self) -> dict[str, tuple[int, int]]:
        """net -> (clusters, unrouted connections)."""
        out = {}
        for net, cls in self.net_clusters.items():
            out[net] = (len(cls), len(cls) - 1)
        return out


def _mst(net: str, clusters: list[Cluster]) -> list[RatLine]:
    anchors = [np.array(c.anchors if c.anchors else [(0.0, 0.0)], dtype=float) for c in clusters]
    n = len(clusters)
    in_tree = [False] * n
    in_tree[0] = True
    best = [math.inf] * n
    best_pair: list = [None] * n

    def closest(a: np.ndarray, b: np.ndarray):
        d = ((a[:, None, :] - b[None, :, :]) ** 2).sum(-1)
        idx = np.unravel_index(np.argmin(d), d.shape)
        return float(np.sqrt(d[idx])), tuple(a[idx[0]]), tuple(b[idx[1]])

    def relax(k: int):
        for j in range(n):
            if not in_tree[j]:
                d, pa, pb = closest(anchors[k], anchors[j])
                if d < best[j]:
                    best[j] = d
                    best_pair[j] = (pa, pb)

    relax(0)
    lines = []
    for _ in range(n - 1):
        j = min((i for i in range(n) if not in_tree[i]), key=lambda i: best[i])
        in_tree[j] = True
        (x1, y1), (x2, y2) = best_pair[j]
        lines.append(RatLine(net, x1, y1, x2, y2, best[j]))
        relax(j)
    return lines


def get_connectivity(project: Project) -> Connectivity:
    return project.cached("connectivity", lambda: Connectivity(project))
