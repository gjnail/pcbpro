"""Where to buy: links to PCB fabs and component suppliers, plus a shopping list with search terms per line.

Nothing here talks to a supplier. It builds URLs that open in the user's browser and a CSV that the
suppliers' BOM tools import. Search terms use short, catalogue-style words, because the hobby shops
(Tayda, Small Bear...) only return products that contain *every* word ("B25K 16mm" finds nothing on Tayda,
"B25K" finds the Alpha pots). URL formats were checked against each site in September 2026.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass, replace
from urllib.parse import quote

from ..model.board import Project, natural_key
from ..pedal.bom import SECTIONS, _counts_as_part, hardware_rows, section_of, value_number
from .fabs import FABS


@dataclass(frozen=True)
class Supplier:
    key: str
    name: str
    region: str
    url: str  # home page
    search: str  # search page, "{q}" is replaced by the URL-encoded query
    blurb: str
    kind: str = "distributor"  # distributor | pedal
    bom_url: str = ""  # BOM upload tool
    part_url: str = ""  # product page by LCSC number, "{code}" is replaced

    def search_url(self, query: str) -> str:
        return self.search.format(q=quote(query.strip(), safe=""))

    def line_url(self, line: "Line") -> str:
        """Best page for one line: the exact product when the supplier knows its part number, else a search."""
        if self.part_url and line.lcsc:
            return self.part_url.format(code=quote(line.lcsc.strip(), safe=""))
        return self.search_url(line.query or search_terms(line))


SUPPLIERS: list[Supplier] = [
    Supplier("digikey", "Digi-Key", "USA, ships worldwide", "https://www.digikey.com/",
             "https://www.digikey.com/en/products/result?keywords={q}",
             "Huge in-stock catalogue, fast shipping and no minimum order. Upload a BOM to myLists as a guest.",
             bom_url="https://www.digikey.com/en/mylists/"),
    Supplier("mouser", "Mouser", "USA, ships worldwide", "https://www.mouser.com/",
             "https://www.mouser.com/c/?q={q}",
             "Huge in-stock catalogue and fast shipping. The BOM tool needs a free My Mouser account.",
             bom_url="https://www.mouser.com/bom/"),
    Supplier("lcsc", "LCSC", "China, ships worldwide", "https://www.lcsc.com/",
             "https://www.lcsc.com/search?q={q}",
             "Very low prices. Same C-numbers as JLCPCB assembly, so parts with an LCSC # open directly.",
             bom_url="https://www.lcsc.com/bom", part_url="https://www.lcsc.com/product-detail/{code}.html"),
    Supplier("farnell", "Farnell / element14", "UK and Europe (Newark in the US)", "https://uk.farnell.com/",
             "https://uk.farnell.com/search?st={q}",
             "Broad catalogue with next-day delivery in the UK and Europe."),
    Supplier("tayda", "Tayda Electronics", "Thailand, with a US warehouse", "https://www.taydaelectronics.com/",
             "https://www.taydaelectronics.com/catalogsearch/result/?q={q}",
             "The pedal builder's staple: cheap passives, Alpha pots, enclosures, plus custom drilling and UV printing.",
             kind="pedal"),
    Supplier("smallbear", "Small Bear Electronics", "USA", "https://smallbear-electronics.mybigcommerce.com/",
             "https://smallbear-electronics.mybigcommerce.com/search.php?search_query={q}",
             "Pedal specialist: footswitches, jacks, enclosures, vintage and germanium transistors.", kind="pedal"),
    Supplier("lovemyswitches", "Love My Switches", "USA", "https://lovemyswitches.com/",
             "https://lovemyswitches.com/search.php?search_query={q}",
             "Pedal hardware: footswitches, toggles, pots, knobs, LEDs and enclosures.", kind="pedal"),
    Supplier("musikding", "Das Musikding", "Germany, ships across the EU", "https://www.musikding.de/",
             "https://www.musikding.de/navi.php?qs={q}",
             "EU pedal-parts shop: enclosures, pots, switches, knobs and kits.", kind="pedal"),
]

TAYDA_DRILL_URL = "https://drill.taydakits.com/"


def supplier_by_key(key: str) -> Supplier | None:
    return next((s for s in SUPPLIERS if s.key == key), None)


@dataclass(frozen=True)
class FabLink:
    name: str
    region: str
    url: str
    blurb: str
    quoted: bool = True  # included in the Order tab's price comparison


MORE_FABS = [
    FabLink("Seeed Fusion", "Shenzhen, China", "https://www.seeedstudio.com/fusion_pcb.html",
            "Low-cost prototypes and assembly from the makers of Grove and XIAO.", False),
    FabLink("NextPCB", "Shenzhen, China", "https://www.nextpcb.com/pcb-quote",
            "Low-cost prototypes, HDI and assembly.", False),
    FabLink("Eurocircuits", "Belgium / Hungary", "https://www.eurocircuits.com/",
            "European prototypes and small series with assembly.", False),
]


def fab_links() -> list[FabLink]:
    """PCB manufacturers: the fabs PCBPro quotes first, then a few more without estimates."""
    return [FabLink(f.name, f.location, f.url, f.blurb) for f in FABS] + MORE_FABS


# --------------------------------------------------------------------------- shopping list

@dataclass
class Line:
    section: str
    qty: int
    value: str
    package: str = ""  # footprint name, or the kind of part for hardware
    refs: str = ""
    mpn: str = ""
    lcsc: str = ""
    notes: str = ""
    query: str = ""  # search words, user-editable


def shopping_list(project: Project) -> list[Line]:
    """Every part to buy, one line per value and package: board parts, DIP sockets and enclosure hardware."""
    groups: "OrderedDict[tuple, list]" = OrderedDict()
    for c in sorted(project.components, key=lambda c: natural_key(c.ref)):
        if _counts_as_part(c):
            groups.setdefault((section_of(c), c.value, c.footprint.name, c.mpn, c.lcsc), []).append(c)
    lines = []
    sockets: Counter = Counter()
    for (section, value, fp, mpn, lcsc), comps in groups.items():
        lines.append(Line(section, len(comps), value, fp, ", ".join(c.ref for c in comps), mpn, lcsc))
        m = re.match(r"(?:DIP|PDIP)-(\d+)", fp)
        if section == "ICs" and m:
            sockets[int(m.group(1))] += len(comps)
    for pins, n in sorted(sockets.items()):
        lines.append(Line("ICs", n, f"DIP-{pins} socket", "IC socket", notes="recommended for DIP ICs"))
    for r in hardware_rows(project):
        lines.append(Line("Hardware", r["Qty"], r["Value"], r["Part"], notes=r["Notes"]))
    for ln in lines:
        ln.query = search_terms(ln)
    order = {s: i for i, s in enumerate(SECTIONS)}
    lines.sort(key=lambda ln: (order.get(ln.section, 99), 0 if ln.section == "Hardware" else value_number(ln.value),
                               natural_key(ln.refs)))
    return lines


_CHIP = re.compile(r"(?:^|_)(01005|0201|0402|0603|0805|1206|1210|1812|2010|2512)(?:_|$)")
_COLOURS = ("red", "green", "blue", "yellow", "orange", "white", "warm white", "amber", "purple", "pink", "uv")


def _chip_size(fp: str) -> str:
    m = _CHIP.search(fp)
    return m.group(1) if m else ""


def _si(x: float, units: str) -> str:
    """4700 -> '4.7K', 1e-7 -> '100nF' (the way the shops name their parts)."""
    if units == "ohm":
        for div, suffix in ((1e6, "M"), (1e3, "K")):
            if x >= div:
                return f"{x / div:g}{suffix}"
        return f"{x:g} ohm"
    for div, suffix in ((1e-6, "uF"), (1e-9, "nF"), (1e-12, "pF")):
        if x >= div * 0.999:
            return f"{round(x / div, 3):g}{suffix}"
    return f"{x:g}F"


def _value(value: str, units: str) -> str:
    n = value_number(value)
    return value.strip() if n == float("inf") or n <= 0 else _si(n, units)


def _axial_power(fp: str) -> str:
    m = re.search(r"R_Axial_L([\d.]+)mm", fp)
    if not m:
        return "1/4W"
    length = float(m.group(1))
    for limit, power in ((4.0, "1/8W"), (7.0, "1/4W"), (9.5, "1/2W"), (12.0, "1W"), (16.0, "2W")):
        if length <= limit:
            return power
    return "3W"


def _pot_terms(value: str, fp: str) -> str:
    v = value.strip().upper().replace("OHM", "").replace(" ", "")
    m = re.match(r"^([ABCW]?)(\d+(?:\.\d+)?[KM]?)$", v)
    if not m:
        return f"{value} potentiometer"
    taper = {"A": "audio", "B": "linear", "C": "C"}.get(m.group(1), "")
    if taper == "C":  # reverse-log pots are sold as "C100K"
        words = [v, "potentiometer"]
    else:
        words = [m.group(2), taper, "potentiometer"]
    if "Dual" in fp:
        words.insert(0, "dual")
    if "9mm" in fp:
        words.append("9mm")
    return " ".join(w for w in words if w)


def search_terms(line: Line) -> str:
    """Words that find this line at a supplier: the MPN when known, else catalogue-style terms from value and package."""
    if line.mpn:
        return line.mpn
    v, fp, s = line.value.strip(), line.package, line.section
    size = _chip_size(fp)
    if s == "Hardware":
        return _hardware_terms(line)
    if fp == "IC socket":
        return f"{re.sub(r'[^0-9]', '', v)} pin DIP socket"
    if s == "Resistors":
        return f"{_value(v, 'ohm')} resistor {size}" if size else f"{_value(v, 'ohm')} {_axial_power(fp)} metal film"
    if s in ("Film capacitors", "Ceramic capacitors", "Electrolytic capacitors", "Capacitors"):
        val = _value(v, "F")
        if s == "Electrolytic capacitors":
            return f"{val} 25V electrolytic" if fp.startswith("CP_Radial") else f"{val} electrolytic capacitor"
        if s == "Film capacitors":
            return f"{val} film capacitor"
        return f"{val} ceramic capacitor {size}".strip()
    if s == "LEDs":
        m = re.search(r"D(\d+(?:\.\d+)?)mm", fp)
        colour = v.lower() if v.lower() in _COLOURS else ""
        if colour or v.upper() == "LED":
            return " ".join(w for w in (colour, "LED", f"{m.group(1)}mm" if m else size) if w)
        return v  # a part number such as WS2812B
    if s == "Potentiometers":
        return _pot_terms(v, fp)
    if s == "Switches":
        if fp.startswith("Footswitch"):
            return f"{v} footswitch" if "PDT" in v.upper() else "3PDT footswitch"
        if fp.startswith("Toggle"):
            poles = re.search(r"Toggle_Mini_(\w+?)_", fp)
            return f"{poles.group(1) if poles else v} mini toggle"
    if s == "Jacks & connectors" and fp.startswith("DC_Jack"):
        return "DC jack 2.1mm"
    if s == "ICs" and _is_part_number(v):
        m = re.match(r"(SOIC|SSOP|TSSOP|MSOP|SOT|QFN|DFN|LQFP|TQFP)-(\d+)", fp)
        return f"{v} {m.group(1)}-{m.group(2)}" if m else v
    if _is_part_number(v) or not fp:
        return v
    return _package_terms(fp) or v


def _is_part_number(v: str) -> bool:
    """'NE555', '1N4148', 'NMJ6HCD2' - not a label such as 'RESET' or 'PWR 5V'."""
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+/#-]*", v)) and any(c.isdigit() for c in v) and any(
        c.isalpha() for c in v)


def _package_terms(fp: str) -> str:
    """Search words for a part known only by its footprint (a header labelled 'PWR 5V', a switch labelled 'RESET')."""
    m = re.match(r"Pin(Header|Socket)_(\d+)x(\d+)_P([\d.]+)mm", fp)
    if m:
        return f"{m.group(4)}mm pin {m.group(1).lower()} {int(m.group(2))}x{int(m.group(3))}"
    m = re.match(r"SW_PUSH_(\d+(?:\.\d+)?)mm", fp)
    if m:
        return f"{m.group(1)}mm tactile switch"
    return ""


_HARDWARE = [("dust cover", "pot dust cover"), ("knob", "knob 6mm"), ("footswitch", "3PDT footswitch"),
             ("mono jack", "mono jack"), ("dc socket", "DC jack 2.1mm"), ("toggle", "mini toggle"),
             ("wire", "hook-up wire")]


def _hardware_terms(line: Line) -> str:
    text = f"{line.value} {line.package}".lower()
    if "enclosure" in text:
        return f"{line.value.replace('Hammond', '').strip()} enclosure"
    if "bezel" in text:
        m = re.search(r"(\d+)\s*mm", line.value)
        return f"{m.group(1)}mm LED bezel" if m else "LED bezel"
    return next((words for key, words in _HARDWARE if key in text), line.value)


def scaled(lines: list[Line], sets: int) -> list[Line]:
    """The list for building `sets` copies of the board."""
    return [replace(ln, qty=ln.qty * max(1, int(sets))) for ln in lines]


def order_csv(lines: list[Line]) -> str:
    """A parts list that the Digi-Key, Mouser and LCSC BOM tools import (they ask which column is which)."""
    buf = io.StringIO()
    wr = csv.writer(buf, lineterminator="\n")
    wr.writerow(["Quantity", "Manufacturer Part Number", "LCSC Part Number", "Description", "Value", "Package",
                 "Designators", "Notes"])
    for ln in lines:
        wr.writerow([ln.qty, ln.mpn, ln.lcsc, ln.query, ln.value, ln.package, ln.refs, ln.notes])
    return buf.getvalue()


def order_text(lines: list[Line], title: str = "") -> str:
    """Plain-text shopping list for the clipboard or an email."""
    out = [f"{title} - parts to buy"] if title else []
    section = None
    for ln in lines:
        if ln.section != section:
            section = ln.section
            out += ["", section.upper()]
        ref = f"  [{ln.refs}]" if ln.refs else ""
        code = "  ".join(x for x in (ln.mpn, ln.lcsc) if x)
        out.append(f"  {ln.qty:>3} x {ln.value:<16} {ln.query}{ref}{'  ' + code if code else ''}")
    return "\n".join(out).strip() + "\n"
