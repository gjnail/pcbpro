"""KiCad footprint import (.kicad_mod files and .pretty library folders).

Supports KiCad 5-9 footprint syntax: pads (smd / thru_hole / np_thru_hole / connect; rect, roundrect,
circle, oval, trapezoid and custom polygon shapes; round and oval drills), silkscreen / fab /
courtyard lines, rectangles, circles, arcs and polygons. A 3D body is inferred from the footprint
name and fab outline.
"""
from __future__ import annotations

import glob
import math
import os
import re
from pathlib import Path

from shapely.geometry import Polygon
from shapely.ops import unary_union

from ..model.board import Footprint, Graphic, Pad
from ..model.footprints import LibPart
from ..model.geometry import iter_polygons, shape_polygon

_TOKEN = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+')


def parse_sexpr(text: str):
    stack: list[list] = [[]]
    for tok in _TOKEN.findall(text):
        if tok == "(":
            stack.append([])
        elif tok == ")":
            node = stack.pop()
            stack[-1].append(node)
        elif tok.startswith('"'):
            stack[-1].append(tok[1:-1].replace('\\"', '"').replace("\\\\", "\\"))
        else:
            stack[-1].append(tok)
    if len(stack) != 1 or not stack[0]:
        raise ValueError("Unbalanced S-expression")
    return stack[0][0]


def _find(node, key):
    for c in node[1:] if isinstance(node, list) else []:
        if isinstance(c, list) and c and c[0] == key:
            return c
    return None


def _findall(node, key):
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == key]


def _xy(node, key, default=(0.0, 0.0)):
    n = _find(node, key)
    if n is None or len(n) < 3:
        return default
    return float(n[1]), float(n[2])


def _width(node, default=0.12):
    st = _find(node, "stroke")
    if st is not None:
        w = _find(st, "width")
        if w is not None:
            return float(w[1])
    w = _find(node, "width")
    return float(w[1]) if w is not None else default


def _layer(node) -> str | None:
    L = _find(node, "layer")
    name = L[1] if L is not None else ""
    return {"F.SilkS": "silk", "F.Silkscreen": "silk", "F.Fab": "fab", "F.CrtYd": "crtyd",
            "F.Courtyard": "crtyd"}.get(name)


def _arc_from_3pts(s, m, e):
    (x1, y1), (x2, y2), (x3, y3) = s, m, e
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-12:
        return None
    ux = ((x1 * x1 + y1 * y1) * (y2 - y3) + (x2 * x2 + y2 * y2) * (y3 - y1) + (x3 * x3 + y3 * y3) * (y1 - y2)) / d
    uy = ((x1 * x1 + y1 * y1) * (x3 - x2) + (x2 * x2 + y2 * y2) * (x1 - x3) + (x3 * x3 + y3 * y3) * (x2 - x1)) / d
    r = math.hypot(x1 - ux, y1 - uy)

    def ang(x, y):  # CCW on screen (Y down)
        return math.degrees(math.atan2(-(y - uy), x - ux)) % 360

    a1, a2, a3 = ang(x1, y1), ang(x2, y2), ang(x3, y3)
    ccw = (a3 - a1) % 360
    if (a2 - a1) % 360 <= ccw:
        sweep = ccw
    else:
        sweep = ccw - 360
    return ux, uy, r, a1, sweep


def _graphics(root) -> list[Graphic]:
    out: list[Graphic] = []
    for kind in ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly"):
        for n in _findall(root, kind):
            layer = _layer(n)
            if layer is None:
                continue
            w = _width(n)
            if kind == "fp_line":
                out.append(Graphic("line", [_xy(n, "start"), _xy(n, "end")], w, layer))
            elif kind == "fp_rect":
                (x0, y0), (x1, y1) = _xy(n, "start"), _xy(n, "end")
                out.append(Graphic("poly", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], w, layer))
            elif kind == "fp_circle":
                (cx, cy), (ex, ey) = _xy(n, "center"), _xy(n, "end")
                fill = _find(n, "fill")
                out.append(Graphic("circle", [(cx, cy)], w, layer, r=math.hypot(ex - cx, ey - cy),
                                   fill=bool(fill and len(fill) > 1 and fill[1] in ("solid", "yes"))))
            elif kind == "fp_arc":
                if _find(n, "mid") is not None:
                    arc = _arc_from_3pts(_xy(n, "start"), _xy(n, "mid"), _xy(n, "end"))
                    if arc:
                        cx, cy, r, a0, sw = arc
                        out.append(Graphic("arc", [(cx, cy)], w, layer, r=r, start=a0, sweep=sw))
                else:  # KiCad 5: start = centre, end = arc start, angle = clockwise sweep
                    (cx, cy), (sx, sy) = _xy(n, "start"), _xy(n, "end")
                    a = _find(n, "angle")
                    sweep = -float(a[1]) if a else 90.0
                    r = math.hypot(sx - cx, sy - cy)
                    a0 = math.degrees(math.atan2(-(sy - cy), sx - cx))
                    out.append(Graphic("arc", [(cx, cy)], w, layer, r=r, start=a0, sweep=sweep))
            elif kind == "fp_poly":
                pts = _find(n, "pts")
                if pts is None:
                    continue
                coords = [(float(p[1]), float(p[2])) for p in _findall(pts, "xy")]
                if len(coords) >= 3:
                    fill = _find(n, "fill")
                    filled = fill is None or (len(fill) > 1 and fill[1] in ("solid", "yes"))
                    out.append(Graphic("poly", coords, w, layer, fill=filled and layer != "crtyd"))
    return out


def _custom_pad_points(p, anchor_w, anchor_h, anchor_shape) -> list | None:
    prims = _find(p, "primitives")
    geoms = [shape_polygon(anchor_shape, anchor_w, anchor_h)]
    if prims is not None:
        for g in prims[1:]:
            if not isinstance(g, list):
                continue
            w = _width(g, 0.0)
            if g[0] == "gr_poly":
                pts = _find(g, "pts")
                coords = [(float(q[1]), float(q[2])) for q in _findall(pts, "xy")] if pts else []
                if len(coords) >= 3:
                    geoms.append(Polygon(coords).buffer(w / 2 if w else 0))
            elif g[0] == "gr_rect":
                (x0, y0), (x1, y1) = _xy(g, "start"), _xy(g, "end")
                geoms.append(Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)]).buffer(w / 2 if w else 0))
            elif g[0] == "gr_circle":
                (cx, cy), (ex, ey) = _xy(g, "center"), _xy(g, "end")
                from shapely.geometry import Point
                geoms.append(Point(cx, cy).buffer(math.hypot(ex - cx, ey - cy) + w / 2))
            elif g[0] == "gr_line":
                from shapely.geometry import LineString
                geoms.append(LineString([_xy(g, "start"), _xy(g, "end")]).buffer(max(w, 0.05) / 2))
    u = unary_union(geoms)
    polys = list(iter_polygons(u))
    if not polys:
        return None
    big = max(polys, key=lambda q: q.area)
    return [(round(x, 4), round(y, 4)) for x, y in list(big.exterior.coords)[:-1]]


def _pads(root) -> list[Pad]:
    pads = []
    for p in _findall(root, "pad"):
        if len(p) < 4:
            continue
        number, ptype, shape = str(p[1]), p[2], p[3]
        at = _find(p, "at")
        x, y = float(at[1]), float(at[2])
        rot = float(at[3]) if len(at) > 3 else 0.0
        size = _find(p, "size")
        w, h = (float(size[1]), float(size[2])) if size else (1.0, 1.0)
        layers_node = _find(p, "layers")
        layers = [str(v) for v in layers_node[1:]] if layers_node else []
        if ptype in ("smd", "connect"):
            if not any(l in ("F.Cu", "*.Cu") for l in layers):
                continue  # bottom-only pad of a double-sided footprint: not supported
            kind = "smd"
        elif ptype == "thru_hole":
            kind = "tht"
        else:
            kind = "npth"
        drill = drill_h = 0.0
        d = _find(p, "drill")
        if d is not None:
            vals = [v for v in d[1:] if not isinstance(v, list)]
            if vals and vals[0] == "oval":
                drill = float(vals[1])
                drill_h = float(vals[2]) if len(vals) > 2 else drill
            elif vals:
                drill = float(vals[0])
        pad_shape = {"rect": "rect", "roundrect": "roundrect", "circle": "circle", "oval": "oval",
                     "trapezoid": "rect"}.get(shape, "custom")
        rr = _find(p, "roundrect_rratio")
        roundness = float(rr[1]) if rr else 0.25
        points = None
        if pad_shape == "custom":
            opts = _find(p, "options")
            anchor = _find(opts, "anchor")[1] if opts is not None and _find(opts, "anchor") is not None else "circle"
            points = _custom_pad_points(p, w, h, "circle" if anchor == "circle" else "rect")
            pad_shape = "poly" if points else "rect"
        paste = any("Paste" in l for l in layers)
        mm = _find(p, "solder_mask_margin")
        if kind == "npth" and w < drill:
            w = h = drill
        pad = Pad(number if kind != "npth" else "", round(x, 4), round(y, 4), round(w, 4), round(h, 4), pad_shape, kind,
                  round(drill, 4), rot % 360, roundness, paste, float(mm[1]) if mm else None,
                  round(drill_h, 4) if drill_h and abs(drill_h - drill) > 1e-6 else 0.0, points)
        pads.append(pad)
    return pads


def _ref_pos(root, courtyard):
    for t in _findall(root, "fp_text") + _findall(root, "property"):
        if len(t) > 2 and t[1] in ("reference", "Reference"):
            at = _find(t, "at")
            if at is not None:
                return float(at[1]), float(at[2])
    return 0.0, round(courtyard[1] - 0.9, 3)


def _bbox_of(graphics, layer):
    xs, ys = [], []
    for g in graphics:
        if g.layer != layer:
            continue
        if g.kind in ("circle", "arc"):
            (cx, cy), = g.pts
            xs += [cx - g.r, cx + g.r]
            ys += [cy - g.r, cy + g.r]
        else:
            xs += [p[0] for p in g.pts]
            ys += [p[1] for p in g.pts]
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _courtyard(pads, graphics):
    bb = _bbox_of(graphics, "crtyd")
    if bb:
        return tuple(round(v, 3) for v in bb)
    xs, ys = [], []
    for p in pads:
        r = max(p.w, p.h) / 2
        xs += [p.x - r, p.x + r]
        ys += [p.y - r, p.y + r]
    for L in ("fab", "silk"):
        b = _bbox_of(graphics, L)
        if b:
            xs += [b[0], b[2]]
            ys += [b[1], b[3]]
    if not xs:
        return (-1.0, -1.0, 1.0, 1.0)
    return (round(min(xs) - 0.25, 3), round(min(ys) - 0.25, 3), round(max(xs) + 0.25, 3), round(max(ys) + 0.25, 3))


# --------------------------------------------------------------------------- 3D model inference

IMPERIAL_TO_LW = {"0201": (0.6, 0.3), "0402": (1.0, 0.5), "0603": (1.6, 0.8), "0805": (2.0, 1.25), "1206": (3.2, 1.6),
                  "1210": (3.2, 2.5), "1812": (4.5, 3.2), "2010": (5.0, 2.5), "2512": (6.3, 3.2)}
CHIP_BODY = {"R": "#141414", "C": "#b78a5a", "L": "#2b2b2b", "LED": "#f4f4f0", "D": "#1a1a1a", "F": "#e8e2cf",
             "FB": "#3a3a3c"}


def _chip_model(cls: str, L: float, W: float) -> dict:
    return {"type": "chip", "L": L, "W": W, "H": max(0.2, min(W * 0.6, 1.2)), "body": CHIP_BODY.get(cls, "#b78a5a"),
            "term": "#c9c9c9", "cls": cls if cls in CHIP_BODY else "C"}


def guess_model(name: str, pads: list[Pad], graphics: list[Graphic], courtyard, prefix: str = "") -> dict:
    """Infer a procedural 3D body from a footprint / package name (KiCad or EasyEDA naming)."""
    n = name.upper()
    fab = _bbox_of(graphics, "fab")
    if fab is None:
        x0, y0, x1, y1 = courtyard
        fab = (x0 + 0.3, y0 + 0.3, x1 - 0.3, y1 - 0.3)
    fw, fh = max(fab[2] - fab[0], 0.2), max(fab[3] - fab[1], 0.2)
    tht = any(p.kind == "tht" for p in pads)
    if re.match(r"^(MOUNTINGHOLE|TESTPOINT|FIDUCIAL|SOLDERJUMPER|NETTIE|SOLDERWIREPAD)", n):
        return {"type": "none"}
    m = re.match(r"^(R|C|L|LED|D|FUSE|CP_TANTALUM)_(\d{4})_(\d{4})METRIC", n)
    if m:
        cls = {"FUSE": "F", "CP_TANTALUM": "C"}.get(m.group(1), m.group(1))
        metric = m.group(3)
        return _chip_model(cls, int(metric[:2]) / 10, int(metric[2:]) / 10)
    smd_two = len([p for p in pads if p.kind == "smd"]) == 2 and not tht
    m = re.search(r"(?:^|[^0-9])(0201|0402|0603|0805|1206|1210|1812|2010|2512)(?:[^0-9]|$)", n)
    if m and smd_two:
        head = re.match(r"^(LED|FB|R|C|L|D|F)", n)
        cls = head.group(1) if head else (prefix if prefix in CHIP_BODY else "C")
        L, W = IMPERIAL_TO_LW[m.group(1)]
        return _chip_model(cls, L, W)
    if re.search(r"BGA|WLCSP|(^|[^A-Z])CSP", n):
        return {"type": "composite", "parts": [{"s": "box", "p": [fab[0], fab[1], 0.3, fab[2], fab[3], 1.3],
                                                 "c": "#1b1b1d", "m": 0}]}
    if re.search(r"QFN|DFN|(^|[^A-Z])SON|LGA|MLF|TDSON|PQFN", n):
        return {"type": "qfn", "bw": fw, "bh": fh, "H": 0.85, "body": "#262626"}
    if re.search(r"SOIC|(^|[^A-Z])SOP|SSOP|TSSOP|MSOP|QSOP|VSSOP|(^|[^A-Z])SO-|SOT-?23|SOT-?223|SOT-?89|"
                 r"SOT-?[35][0-9]{2}|TSOT|SC-?70|SC-?88|QFP", n) and not tht:
        small = bool(re.search(r"SOT|SC-?\d", n))
        H = 1.0 if small else (1.4 if "QFP" in n else 1.5)
        return {"type": "gullwing", "bw": fw, "bh": fh, "H": H, "body": "#1e1e1e", "standoff": 0.1, "pin1": not small}
    if re.search(r"(^|[^A-Z])P?DIP", n) and tht:
        return {"type": "dip", "bw": fw, "bh": fh, "H": 3.3, "body": "#1c1c1c"}
    if n.startswith("PINHEADER") and tht:
        xs = sorted({round(p.x, 3) for p in pads})
        ys = sorted({round(p.y, 3) for p in pads})
        pitch = min([b - a for a, b in zip(xs, xs[1:])] + [b - a for a, b in zip(ys, ys[1:])] or [2.54])
        return {"type": "header", "cols": len(xs), "rows": len(ys), "pitch": pitch, "body": "#161616", "pin": "#d9b44a"}
    m = re.search(r"CP_RADIAL_D(\d+(?:\.\d+)?)MM", n)
    if m:
        D = float(m.group(1))
        return {"type": "radial_cap", "D": D, "H": max(5.0, D * 1.6), "body": "#23336b", "stripe": "#d0d0d0"}
    m = re.search(r"^LED_D(\d+(?:\.\d+)?)MM", n)
    if m and tht:
        D = float(m.group(1))
        return {"type": "led_tht", "D": D, "H": D + 3.6, "color": "#e03030"}
    if re.search(r"TO-?92", n):
        return {"type": "to92", "body": "#1a1a1a"}
    if re.search(r"TO-?220", n) and "VERTICAL" in n:
        return {"type": "to220", "body": "#1c1c1c", "tab": "#c9c9c9"}
    if n.startswith("CRYSTAL_HC49") or "HC-49" in n or "HC49" in n:
        return {"type": "hc49", "L": 10.9, "W": 4.65, "H": 3.6 if ("4H" in n or "SMD" in n) else 13.5}
    if re.match(r"^(CRYSTAL|OSCILLATOR)_SMD", n) or (re.search(r"CRYSTAL|OSC", n) and not tht):
        return {"type": "xtal_smd", "L": fw, "W": fh, "H": 0.9}
    if n.startswith(("SW_PUSH", "SW_TACTILE")) or re.search(r"(^|_)KEY|TACT", n):
        return {"type": "tact", "w": fw, "h": fh, "H": 3.5, "actuator": min(fw, fh) * 0.55, "act_h": 1.2}
    return {"type": "auto"}


# --------------------------------------------------------------------------- public API

def footprint_from_kicad(text: str, name_hint: str | None = None) -> Footprint:
    root = parse_sexpr(text)
    if not isinstance(root, list) or root[0] not in ("footprint", "module"):
        raise ValueError("Not a KiCad footprint (expected (footprint ...) or (module ...))")
    name = str(root[1]) if len(root) > 1 and not isinstance(root[1], list) else (name_hint or "Imported")
    if ":" in name:
        name = name.split(":", 1)[1]
    descr = _find(root, "descr")
    pads = _pads(root)
    graphics = _graphics(root)
    court = _courtyard(pads, graphics)
    if not any(g.layer == "crtyd" for g in graphics):
        x0, y0, x1, y1 = court
        graphics.append(Graphic("poly", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], 0.05, "crtyd"))
    fp = Footprint(name=name, description=(str(descr[1]) if descr else "Imported from KiCad"), pads=pads,
                   graphics=graphics, courtyard=court, model=guess_model(name, pads, graphics, court),
                   ref_pos=_ref_pos(root, court))
    return fp


def load_kicad_mod(path: str | Path) -> Footprint:
    path = Path(path)
    return footprint_from_kicad(path.read_text(encoding="utf-8", errors="replace"), path.stem)


PREFIX_BY_LIB = [("Resistor", "R", "10k"), ("Capacitor", "C", "100nF"), ("Inductor", "L", "10uH"),
                 ("LED", "D", "LED"), ("Diode", "D", "Diode"), ("Crystal", "Y", "Crystal"), ("Oscillator", "X", "OSC"),
                 ("Button_Switch", "SW", "Switch"), ("Relay", "K", "Relay"), ("Fuse", "F", "Fuse"),
                 ("MountingHole", "H", "MountingHole"), ("TestPoint", "TP", "TP"), ("Potentiometer", "RV", "10k"),
                 ("Buzzer", "BZ", "Buzzer"), ("Battery", "BT", "Battery"), ("Transformer", "T", "Transformer"),
                 ("Jumper", "JP", "Jumper"), ("Connector", "J", "Conn"), ("Fiducial", "FID", "Fiducial"),
                 ("Display", "U", "Display"), ("Varistor", "RV", "Varistor"), ("Heatsink", "HS", "Heatsink"),
                 ("Package", "U", "IC"), ("Module", "U", "Module"), ("Sensor", "U", "Sensor"), ("RF", "U", "RF")]


def _prefix_for(lib: str):
    for key, prefix, value in PREFIX_BY_LIB:
        if lib.startswith(key) or key in lib:
            return prefix, value
    return "U", "IC"


def scan_kicad_dir(root: str | Path) -> list[LibPart]:
    """Index every footprint in a folder of .pretty libraries (or a single .pretty folder)."""
    root = Path(root)
    libs = [root] if root.suffix == ".pretty" else sorted(p for p in root.glob("*.pretty") if p.is_dir())
    out: list[LibPart] = []
    for lib in libs:
        libname = lib.stem
        prefix, value = _prefix_for(libname)
        try:
            entries = sorted(os.scandir(lib), key=lambda e: e.name.lower())
        except OSError:
            continue
        for e in entries:
            if not e.name.endswith(".kicad_mod"):
                continue
            stem = e.name[:-10]
            out.append(LibPart(f"KiCad/{libname.replace('_', ' ')}", f"{libname}:{stem}", prefix, value,
                               (lambda p=e.path: load_kicad_mod(p)), f"{libname} {stem} kicad".lower().replace("_", " "),
                               description=f"KiCad footprint {libname}:{stem}", source="kicad"))
    return out


def default_kicad_dirs() -> list[Path]:
    """Well-known footprint library locations (KiCad installs and PCBPro's download folder)."""
    cands = []
    for pattern in (r"C:\Program Files\KiCad\*\share\kicad\footprints", r"C:\Program Files (x86)\KiCad\*\share\kicad\footprints",
                    "/usr/share/kicad/footprints", "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"):
        cands += [Path(p) for p in glob.glob(pattern)]
    cands.append(Path.home() / "Documents" / "PCBPro" / "kicad-footprints")
    return [c for c in cands if c.is_dir() and any(c.glob("*.pretty"))]


OFFICIAL_ZIP = "https://gitlab.com/kicad/libraries/kicad-footprints/-/archive/master/kicad-footprints-master.zip"
