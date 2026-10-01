"""Import any LCSC part (by its C-number) using the EasyEDA component library.

LCSC stocks well over a million parts and every one has an EasyEDA footprint. This module fetches
the component record, converts the footprint (pads, slots, holes, polygons, silkscreen, outline)
into a PCBPro Footprint and extracts the part metadata (MPN, manufacturer, package, description).

The EasyEDA component endpoint is publicly reachable but not formally documented. To keep imports
working even if it changes or is unreachable:

* several endpoint variants are tried, with retries and back-off for transient errors;
* every successful response is cached on disk, so a part imports offline once it has been fetched;
* the same data can be imported from a file (saved from the browser, or an EasyEDA footprint source
  export), so there is always a manual path that does not depend on the network API;
* the parser is defensive: unknown shapes are skipped and format changes produce a clear error.
"""
from __future__ import annotations

import json
import math
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import Polygon

from ..model.board import Footprint, Graphic, Pad
from .kicad import _courtyard, guess_model

API = "https://easyeda.com/api/products/{lcsc}/components?version=6.4.19.5"
# Tried in order; the versionless form is what the EasyEDA web editor falls back to.
ENDPOINTS = [API, "https://easyeda.com/api/products/{lcsc}/components"]
RETRIES = 2
UNIT = 0.254  # EasyEDA canvas unit = 10 mil
USER_AGENT = "PCBPro/1.0 (+desktop PCB design tool)"

LAYER_MAP = {"3": "silk", "13": "fab", "99": "fab", "12": "fab"}


@dataclass
class LcscPart:
    lcsc: str
    mpn: str = ""
    manufacturer: str = ""
    package: str = ""
    description: str = ""
    value: str = ""
    prefix: str = "U"
    datasheet: str = ""
    footprint: Footprint | None = None
    warnings: list = field(default_factory=list)
    from_cache: bool = False


class LcscError(Exception):
    """Import failure with a user-facing explanation and suggested alternatives."""

    def __init__(self, message: str, lcsc: str = ""):
        hint = ("\n\nAlternatives:\n"
                "  1. Click 'Open part data in browser', save the page as a .json file, then click "
                "'Import from file'.\n"
                "  2. Use the matching footprint from the KiCad library (Library > KiCad footprint libraries).\n"
                "  3. Build the land pattern from the datasheet with the Footprint wizard.")
        super().__init__(message + hint)
        self.short = message
        self.lcsc = lcsc


def normalise_lcsc(code: str) -> str:
    code = code.strip().upper()
    if re.fullmatch(r"\d+", code):
        code = "C" + code
    if not re.fullmatch(r"C\d+", code):
        raise ValueError(f"'{code}' is not an LCSC part number (expected something like C25804)")
    return code


def cache_dir() -> Path:
    d = Path.home() / "Documents" / "PCBPro" / "library" / ".cache" / "lcsc"
    d.mkdir(parents=True, exist_ok=True)
    return d


def api_url(lcsc: str) -> str:
    return API.format(lcsc=normalise_lcsc(lcsc))


def _http_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https endpoints
        return json.loads(resp.read().decode("utf-8"))


def _result_of(data, lcsc: str) -> dict:
    """Accept the documented-by-usage envelope {"success": true, "result": {...}} or a bare result."""
    if isinstance(data, dict) and "result" in data:
        if data.get("success") is False or not data.get("result"):
            raise LookupError(f"LCSC part {lcsc} was not found in the EasyEDA library")
        data = data["result"]
    if not isinstance(data, dict) or "packageDetail" not in data:
        raise LcscError("The EasyEDA response has an unexpected format (no 'packageDetail'). The service may have "
                        "changed.", lcsc)
    return data


def fetch_component(lcsc: str, timeout: float = 20.0, endpoints: list[str] | None = None) -> dict:
    """Fetch the component record, trying every endpoint with retries and back-off."""
    errors = []
    for url_t in endpoints or ENDPOINTS:
        url = url_t.format(lcsc=lcsc)
        for attempt in range(RETRIES + 1):
            try:
                return _result_of(_http_json(url, timeout), lcsc)
            except LookupError:
                raise
            except urllib.error.HTTPError as e:
                errors.append(f"{url}: HTTP {e.code}")
                if e.code in (429, 500, 502, 503, 504) and attempt < RETRIES:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                break
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                errors.append(f"{url}: {getattr(e, 'reason', e)}")
                if attempt < RETRIES:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                break
            except (ValueError, LcscError) as e:
                errors.append(f"{url}: {e if isinstance(e, ValueError) else e.short}")
                break
    unique = list(dict.fromkeys(errors))
    raise LcscError("Could not download the part from the EasyEDA / LCSC library:\n  " + "\n  ".join(unique[-4:]),
                    lcsc)


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _points(s: str) -> list[tuple[float, float]]:
    vals = [_f(v) for v in re.split(r"[\s,]+", (s or "").strip()) if v]
    return [(vals[i], vals[i + 1]) for i in range(0, len(vals) - 1, 2)]


def _svg_arc_points(path: str, ox: float, oy: float) -> list[tuple[float, float]]:
    """Polyline approximation of an SVG 'M x y A rx ry rot large sweep x y' path (EasyEDA arcs)."""
    nums = [_f(v) for v in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", path)]
    if len(nums) < 9:
        return []
    x1, y1, rx, ry, _rot, large, sweep, x2, y2 = nums[:9]
    rx, ry = abs(rx), abs(ry)
    if rx < 1e-9:
        return [(x1, y1), (x2, y2)]
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    lam = (dx * dx) / (rx * rx) + (dy * dy) / (ry * ry)
    if lam > 1:
        rx *= math.sqrt(lam)
        ry *= math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * dy * dy - ry * ry * dx * dx
    den = rx * rx * dy * dy + ry * ry * dx * dx
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if int(large) == int(sweep):
        coef = -coef
    cxp = coef * rx * dy / ry
    cyp = -coef * ry * dx / rx
    cx, cy = cxp + (x1 + x2) / 2, cyp + (y1 + y2) / 2
    a1 = math.atan2((y1 - cy) / ry, (x1 - cx) / rx)
    a2 = math.atan2((y2 - cy) / ry, (x2 - cx) / rx)
    da = a2 - a1
    if int(sweep) and da < 0:
        da += 2 * math.pi
    elif not int(sweep) and da > 0:
        da -= 2 * math.pi
    n = max(4, int(abs(da) / (math.pi / 18)))
    return [(cx + rx * math.cos(a1 + da * i / n), cy + ry * math.sin(a1 + da * i / n)) for i in range(n + 1)]


def convert_footprint(pkg: dict, name: str, prefix_hint: str = "") -> tuple[Footprint, list[str]]:
    ds = pkg.get("dataStr") or {}
    if isinstance(ds, str):
        ds = json.loads(ds)
    head = ds.get("head", {})
    ox, oy = _f(head.get("x")), _f(head.get("y"))

    def mm(x, y):
        return round((x - ox) * UNIT, 4), round((y - oy) * UNIT, 4)

    pads: list[Pad] = []
    graphics: list[Graphic] = []
    warnings: list[str] = []
    for raw in ds.get("shape", []):
        f = raw.split("~")
        kind = f[0]
        try:
            if kind == "PAD":
                shape, cx, cy, w, h, layer = f[1], _f(f[2]), _f(f[3]), _f(f[4]), _f(f[5]), f[6]
                number = f[8]
                hole_r = _f(f[9])
                pts = _points(f[10]) if len(f) > 10 else []
                rot = _f(f[11]) if len(f) > 11 else 0.0
                hole_len = _f(f[13]) if len(f) > 13 else 0.0
                plated = (f[15] if len(f) > 15 else "Y") != "N"
                x, y = mm(cx, cy)
                pw, ph = round(w * UNIT, 4), round(h * UNIT, 4)
                if layer == "11" or hole_r > 0:
                    pkind = "tht" if plated else "npth"
                elif layer in ("1",):
                    pkind = "smd"
                else:
                    warnings.append(f"Skipped pad {number} on unsupported layer {layer}")
                    continue
                drill = round(hole_r * 2 * UNIT, 4)
                drill_h = 0.0
                if hole_len > 0:
                    L = round(hole_len * UNIT, 4)
                    if L > drill:
                        # slot runs along the pad's longer local axis
                        if ph >= pw:
                            drill_h = L
                        else:
                            drill, drill_h = L, drill
                pshape = {"ELLIPSE": "circle", "RECT": "rect", "OVAL": "oval"}.get(shape, "poly")
                points = None
                prot = rot % 360
                if pshape == "poly":
                    if len(pts) < 3:
                        pshape = "rect"
                    else:
                        points = [(round((px - cx) * UNIT, 4), round((py - cy) * UNIT, 4)) for px, py in pts]
                        prot = 0.0
                        poly = Polygon(points)
                        if poly.area <= 0:
                            pshape, points = "rect", None
                        else:
                            minx, miny, maxx, maxy = poly.bounds
                            pw, ph = round(maxx - minx, 4), round(maxy - miny, 4)
                if pshape == "circle" and abs(pw - ph) > 1e-3:
                    pshape = "oval"
                if pkind == "npth" and pw < drill:
                    pw = ph = drill
                pads.append(Pad(number if pkind != "npth" else "", x, y, pw, ph, pshape, pkind, drill, prot,
                                paste=(pkind == "smd"), drill_h=drill_h, points=points))
            elif kind == "HOLE":
                x, y = mm(_f(f[1]), _f(f[2]))
                d = round(_f(f[3]) * 2 * UNIT, 4)
                pads.append(Pad("", x, y, d, d, "circle", "npth", d))
            elif kind == "TRACK":
                width, layer, pts = _f(f[1]) * UNIT, f[2], _points(f[4])
                gl = LAYER_MAP.get(layer)
                if gl and len(pts) >= 2:
                    mp = [mm(px, py) for px, py in pts]
                    for a, b in zip(mp, mp[1:]):
                        graphics.append(Graphic("line", [a, b], max(width, 0.05), gl))
            elif kind == "CIRCLE":
                cx, cy, r, width, layer = _f(f[1]), _f(f[2]), _f(f[3]), _f(f[4]), f[5]
                gl = LAYER_MAP.get(layer)
                if gl:
                    graphics.append(Graphic("circle", [mm(cx, cy)], max(width * UNIT, 0.05), gl, r=round(r * UNIT, 4)))
            elif kind == "ARC":
                width, layer, path = _f(f[1]) * UNIT, f[2], f[4]
                gl = LAYER_MAP.get(layer)
                if gl:
                    mp = [mm(px, py) for px, py in _svg_arc_points(path, ox, oy)]
                    for a, b in zip(mp, mp[1:]):
                        graphics.append(Graphic("line", [a, b], max(width, 0.05), gl))
            elif kind == "RECT":
                x, y, w, h, width, layer = _f(f[1]), _f(f[2]), _f(f[3]), _f(f[4]), _f(f[5]), f[7] if len(f) > 7 else ""
                gl = LAYER_MAP.get(layer)
                if gl:
                    (x0, y0), (x1, y1) = mm(x, y), mm(x + w, y + h)
                    graphics.append(Graphic("poly", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], max(width * UNIT, 0.05), gl))
        except (IndexError, ValueError) as e:
            warnings.append(f"Skipped malformed {kind}: {e}")
    if not pads:
        raise ValueError("The EasyEDA footprint contains no pads")
    court = _courtyard(pads, graphics)
    x0, y0, x1, y1 = court
    graphics.append(Graphic("poly", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], 0.05, "crtyd"))
    title = head.get("c_para", {}).get("package") or pkg.get("title") or name
    model = guess_model(str(title), pads, graphics, court, prefix_hint)
    fp = Footprint(name=str(title), description=f"Imported from LCSC/EasyEDA ({name})", pads=pads, graphics=graphics,
                   courtyard=court, model=model, ref_pos=(0.0, round(y0 - 0.9, 3)))
    return fp, warnings


STANDARD_PREFIXES = {"R", "C", "L", "D", "Q", "U", "J", "SW", "Y", "X", "F", "K", "BZ", "BT", "FB", "H", "TP", "RV",
                     "T", "JP", "LS", "MK", "RN"}
PREFIX_ALIASES = {"LED": "D", "USB": "J", "USBC": "J", "CN": "J", "P": "J", "S": "SW", "KEY": "SW", "B": "BT",
                  "IC": "U", "VR": "RV", "Z": "D", "ZD": "D", "TVS": "D", "SPK": "LS", "MIC": "MK"}

PREFIX_HINTS = [("usb", "J"), ("resistor", "R"), ("capacitor", "C"), ("inductor", "L"), ("ferrite", "FB"), ("led", "D"),
                ("diode", "D"), ("mosfet", "Q"), ("transistor", "Q"), ("crystal", "Y"), ("oscillator", "X"),
                ("connector", "J"), ("header", "J"), ("switch", "SW"), ("button", "SW"), ("relay", "K"),
                ("fuse", "F"), ("buzzer", "BZ"), ("battery", "BT")]


def parse_component(result: dict, lcsc: str) -> LcscPart:
    part = LcscPart(lcsc)
    sym = result.get("dataStr") or {}
    if isinstance(sym, str):
        sym = json.loads(sym)
    cpara = (sym.get("head") or {}).get("c_para", {}) if isinstance(sym, dict) else {}
    part.mpn = cpara.get("Manufacturer Part") or result.get("title") or lcsc
    part.manufacturer = cpara.get("Manufacturer", "")
    part.package = cpara.get("package", "")
    part.value = cpara.get("Value") or cpara.get("name") or part.mpn
    pre = (cpara.get("pre") or "U?").rstrip("?").strip() or "U"
    part.prefix = re.sub(r"[^A-Za-z]", "", pre) or "U"
    part.description = result.get("description") or cpara.get("name", "")
    ds = result.get("lcsc", {}) if isinstance(result.get("lcsc"), dict) else {}
    part.datasheet = ds.get("url", "") if isinstance(ds, dict) else ""
    low = f"{part.description} {part.package} {part.mpn}".lower()
    part.prefix = PREFIX_ALIASES.get(part.prefix.upper(), part.prefix.upper())
    if part.prefix not in STANDARD_PREFIXES:
        part.prefix = "U"
    if part.prefix == "U":
        for key, pfx in PREFIX_HINTS:
            if key in low:
                part.prefix = pfx
                break
    pkg = result.get("packageDetail") or {}
    fp, warnings = convert_footprint(pkg, lcsc, part.prefix)
    fp.description = f"{part.mpn} ({part.manufacturer}) - {part.package}. Imported from LCSC {lcsc} via EasyEDA."
    part.footprint = fp
    part.warnings = warnings
    return part


def import_lcsc(code: str, use_cache: bool = True, refresh: bool = False) -> LcscPart:
    """Import an LCSC part. Uses the on-disk cache when offline (or always, unless refresh=True)."""
    lcsc = normalise_lcsc(code)
    cached = cache_dir() / f"{lcsc}.json"
    if use_cache and cached.exists() and not refresh:
        part = parse_component(_result_of(json.loads(cached.read_text(encoding="utf-8")), lcsc), lcsc)
        part.from_cache = True
        return part
    try:
        result = fetch_component(lcsc)
    except LcscError:
        if use_cache and cached.exists():  # offline or service down: fall back to the last good copy
            part = parse_component(_result_of(json.loads(cached.read_text(encoding="utf-8")), lcsc), lcsc)
            part.from_cache = True
            part.warnings.insert(0, "EasyEDA could not be reached - using the cached copy of this part")
            return part
        raise
    part = parse_component(result, lcsc)  # parse before caching so a broken response is never stored
    cached.write_text(json.dumps(result), encoding="utf-8")
    return part


def import_easyeda_file(path: str | Path, lcsc: str = "") -> LcscPart:
    """Import a saved EasyEDA record: the API response (as saved from a browser), a bare component
    record, or an EasyEDA Standard footprint source export ({"head": ..., "shape": [...]})."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "shape" in data and "head" in data:  # footprint source export
        code = lcsc or (data.get("head", {}).get("c_para", {}).get("Supplier Part") or Path(path).stem)
        data = {"packageDetail": {"dataStr": data, "title": data.get("head", {}).get("c_para", {}).get("package", "")},
                "dataStr": {"head": {"c_para": data.get("head", {}).get("c_para", {})}}, "title": Path(path).stem}
    else:
        code = lcsc
    if not code:
        m = re.search(r"C\d{3,}", Path(path).stem.upper())
        code = m.group(0) if m else Path(path).stem
    return parse_component(_result_of(data, code), code)


def search_url(query: str) -> str:
    from urllib.parse import quote
    return f"https://www.lcsc.com/search?q={quote(query)}"
