import json

import pytest
from shapely.geometry import Point, box

from pcbpro.model.board import Component, Project, Track, Via
from pcbpro.model.connectivity import get_connectivity
from pcbpro.model.copper import collect_copper, pad_geom
from pcbpro.model.drc import run_drc
from pcbpro.model.footprints import LIBRARY, chip
from pcbpro.model.geometry import inverse_transform_point, rotate_point, split_holes, transform_point


def test_rotation_is_counter_clockwise_on_screen():
    x, y = rotate_point(1, 0, 90)
    assert abs(x) < 1e-9 and abs(y + 1) < 1e-9  # +X rotates to screen "up" (-Y)


def test_transform_round_trip():
    for mirror in (False, True):
        x, y = transform_point(1.5, -0.7, 10, 20, 33, mirror)
        lx, ly = inverse_transform_point(x, y, 10, 20, 33, mirror)
        assert abs(lx - 1.5) < 1e-9 and abs(ly + 0.7) < 1e-9


def test_serialisation_round_trip(example):
    d = example.to_dict()
    p2 = Project.from_dict(json.loads(json.dumps(d)))
    assert json.loads(json.dumps(p2.to_dict())) == json.loads(json.dumps(d))


def test_ratsnest_and_routing_connectivity(qapp):
    p = Project("t")
    a = Component("R1", "1k", chip("R", "0805"), 10, 10, pad_nets={"2": "N1"})
    b = Component("R2", "1k", chip("R", "0805"), 20, 10, pad_nets={"1": "N1"})
    p.components += [a, b]
    assert get_connectivity(p).unrouted_count() == 1
    ax, ay = a.pad_pos(a.footprint.pads[1])
    bx, by = b.pad_pos(b.footprint.pads[0])
    p.tracks.append(Track(ax, ay, bx, by, 0.25, "F.Cu", "N1"))
    p.touch()
    assert get_connectivity(p).unrouted_count() == 0


def test_drc_detects_clearance_and_short(qapp):
    p = Project("t")
    p.tracks.append(Track(10, 10, 20, 10, 0.25, "F.Cu", "A"))
    p.tracks.append(Track(10, 10.35, 20, 10.35, 0.25, "F.Cu", "B"))  # 0.1 mm gap
    assert "clearance" in {v.kind for v in run_drc(p)}
    p.tracks.append(Track(15, 5, 15, 15, 0.25, "F.Cu", "C"))  # crosses both
    p.touch()
    assert any(v.kind == "short" for v in run_drc(p))


def test_drc_via_rules(qapp):
    p = Project("t")
    p.vias.append(Via(10, 10, 0.4, 0.3, "A"))
    assert "annular" in [v.kind for v in run_drc(p)]


def test_split_holes_preserves_area():
    poly = box(0, 0, 10, 10).difference(Point(3, 3).buffer(1)).difference(Point(7, 6).buffer(1.5))
    pieces = split_holes(poly)
    assert all(not p.interiors for p in pieces)
    assert abs(sum(p.area for p in pieces) - poly.area) < 1e-6


def test_zone_fill_respects_other_nets(example):
    z = example.zones[0]
    fill = example.zone_fills[z.uid]
    assert fill.area > 1000  # most of the 50x35 board
    for s in collect_copper(example, include_zones=False):
        if s.layer == z.layer and s.net != z.net:
            assert fill.distance(s.geom) >= z.clearance - 1e-3
