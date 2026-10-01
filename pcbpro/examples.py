"""Built-in example designs."""
from __future__ import annotations

import json
from pathlib import Path

from .model import footprints as fp
from .model.board import Board, Component, Project, Text, Zone
from .model.geometry import rounded_rect_points

EXAMPLE_DIR = Path(__file__).parent / "resources" / "examples"


def _add(p: Project, ref, value, footprint, x, y, rot=0.0, nets=None, side="top"):
    c = Component(ref, value, footprint, x, y, rot, side, dict(nets or {}))
    p.components.append(c)
    return c


def flasher_555() -> Project:
    """NE555 astable LED flasher with reset button - unrouted."""
    p = Project("555 LED Flasher")
    p.author = "PCBPro"
    p.board = Board(outline=rounded_rect_points(0, 0, 50, 35, 3.0))
    _add(p, "U1", "NE555", fp.soic(8), 25, 17.5, 0,
         {"1": "GND", "2": "THR", "3": "OUT", "4": "RESET", "5": "CTRL", "6": "THR", "7": "DISCH", "8": "VCC"})
    _add(p, "C3", "100nF", fp.chip("C", "0805"), 25, 12.2, 0, {"1": "VCC", "2": "GND"})
    _add(p, "R1", "1k", fp.chip("R", "0805"), 32.5, 14.0, 90, {"1": "DISCH", "2": "VCC"})
    _add(p, "R2", "47k", fp.chip("R", "0805"), 32.5, 19.5, 90, {"1": "THR", "2": "DISCH"})
    _add(p, "C1", "10uF", fp.chip("C", "0805"), 36.0, 19.5, 90, {"1": "GND", "2": "THR"})
    _add(p, "C2", "10nF", fp.chip("C", "0805"), 31.5, 24.5, 0, {"1": "CTRL", "2": "GND"})
    _add(p, "R4", "10k", fp.chip("R", "0805"), 18.0, 13.0, 90, {"1": "RESET", "2": "VCC"})
    _add(p, "R3", "330", fp.chip("R", "0805"), 18.0, 21.5, 90, {"2": "OUT", "1": "LED_A"})
    _add(p, "D1", "Red", fp.led_tht(5), 12.0, 25.5, 0, {"1": "GND", "2": "LED_A"})
    _add(p, "C4", "100uF", fp.cap_radial(5, 2.0, 11), 11.0, 11.0, 0, {"1": "VCC", "2": "GND"})
    _add(p, "J1", "PWR 5V", fp.pin_header(2, 1), 4.5, 17.5, 90, {"1": "VCC", "2": "GND"})
    _add(p, "SW1", "RESET", fp.tactile_switch(), 41.5, 23.5, 0, {"1": "RESET", "2": "GND"})
    for i, (x, y) in enumerate(((4.5, 4.5), (45.5, 4.5), (4.5, 30.5), (45.5, 30.5)), start=1):
        _add(p, f"H{i}", "M3", fp.mounting_hole("M3", False), x, y).show_ref = False
    p.texts.append(Text("555 LED FLASHER", 25, 31.5, 1.5, "F.SilkS"))
    p.texts.append(Text("PCBPro demo  rev A", 25, 31.5, 1.2, "B.SilkS"))
    p.texts.append(Text("+5V", 4.5, 22.2, 1.0, "F.SilkS"))
    p.texts.append(Text("GND", 4.5, 12.8, 1.0, "F.SilkS"))
    outline = rounded_rect_points(0, 0, 50, 35, 3.0)
    p.zones.append(Zone("B.Cu", "GND", outline, clearance=0.3))
    return p


def list_examples() -> list[Path]:
    if not EXAMPLE_DIR.exists():
        return []
    return sorted(EXAMPLE_DIR.glob("*.pcbpro"))


def load_example(path: Path) -> Project:
    return Project.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
