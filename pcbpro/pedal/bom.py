"""Pedal build sheet: a bill of materials grouped the way pedal builders shop for parts, including the
off-board hardware implied by the enclosure (box, knobs, footswitch, jacks, DC socket, bezels)."""
from __future__ import annotations

import csv
import io
import re
from collections import OrderedDict

from ..model.board import Component, Project, natural_key
from .enclosure import HARDWARE, get_enclosure, all_holes

SECTIONS = ["Resistors", "Film capacitors", "Ceramic capacitors", "Electrolytic capacitors", "Capacitors", "Diodes",
            "LEDs", "Transistors", "ICs", "Potentiometers", "Switches", "Jacks & connectors", "Other parts",
            "Hardware"]

_MULT = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6, "R": 1.0, "r": 1.0}


def value_number(value: str) -> float:
    """Numeric value of pedal-style notation (4k7, 2n2, 100uF, 1M, 47R) for sorting; inf when unknown."""
    v = value.strip().replace("Ω", "").replace("ohm", "")
    m = re.match(r"^([0-9]*\.?[0-9]*)([pnuµmkKMRr]?)([0-9]*)", v)
    if not m or not (m.group(1) or m.group(3)):
        return float("inf")
    whole, mult, frac = m.groups()
    try:
        num = float(f"{whole or 0}.{frac}" if frac else (whole or 0))
    except ValueError:
        return float("inf")
    return num * _MULT.get(mult, 1.0)


def section_of(c: Component) -> str:
    name = c.footprint.name
    ref = re.match(r"[A-Za-z]+", c.ref or "")
    prefix = ref.group(0).upper() if ref else ""
    if prefix in ("R",) and not name.startswith("Pot"):
        return "Resistors"
    if prefix == "C":
        if name.startswith("CP_") or "Elec" in name or c.footprint.model.get("type") == "radial_cap":
            return "Electrolytic capacitors"
        if name.startswith("C_Rect_L") or "Film" in name:
            return "Film capacitors"
        if name.startswith(("C_Disc", "C_Rect_Ceramic")):
            return "Ceramic capacitors"
        return "Capacitors"
    if prefix == "D":
        return "LEDs" if name.startswith("LED") else "Diodes"
    if prefix == "Q":
        return "Transistors"
    if prefix in ("U", "IC"):
        return "ICs"
    if prefix in ("RV", "VR", "P", "POT") or name.startswith("Pot"):
        return "Potentiometers"
    if prefix == "SW" or name.startswith(("Footswitch", "Toggle")):
        return "Switches"
    if prefix in ("J", "CN"):
        return "Jacks & connectors"
    return "Other parts"


def _counts_as_part(c: Component) -> bool:
    return c.footprint.model.get("type", "auto") != "none" and not c.ref.upper().startswith(("H", "FID", "TP", "W"))


def build_rows(project: Project) -> list[dict]:
    groups: "OrderedDict[tuple, list[Component]]" = OrderedDict()
    for c in sorted(project.components, key=lambda c: natural_key(c.ref)):
        if not _counts_as_part(c):
            continue
        groups.setdefault((section_of(c), c.value, c.footprint.name), []).append(c)
    rows = []
    for (section, value, fp), comps in groups.items():
        note = ""
        if section == "ICs" and fp.startswith("DIP"):
            note = f"+ {fp.split('_')[0]} socket recommended"
        elif section == "Potentiometers":
            note = "16 mm, right-angle PCB pins" if "16mm" in fp else ("9 mm, PCB mount" if "9mm" in fp else "")
        elif section == "Electrolytic capacitors":
            note = "25 V or higher"
        elif section == "Film capacitors":
            note = "5 mm lead spacing" if "P5" in fp else ""
        elif section == "Resistors":
            note = "1/4 W metal film"
        rows.append({"Section": section, "Qty": len(comps), "Value": value,
                     "Designators": ", ".join(c.ref for c in comps), "Part": fp, "Notes": note,
                     "MPN": ", ".join(sorted({c.mpn for c in comps if c.mpn}))})
    rows += hardware_rows(project)
    order = {s: i for i, s in enumerate(SECTIONS)}
    rows.sort(key=lambda r: (order.get(r["Section"], 99), value_number(r["Value"]) if r["Section"] != "Hardware"
                             else 0, natural_key(r["Designators"])))
    return rows


def hardware_rows(project: Project) -> list[dict]:
    enc = get_enclosure(project)
    rows = []

    def add(qty, value, part, note=""):
        if qty:
            rows.append({"Section": "Hardware", "Qty": qty, "Value": value, "Designators": "", "Part": part,
                         "Notes": note, "MPN": ""})

    pots16 = sum(1 for c in project.components if c.footprint.name.startswith("Pot_Alpha_16mm"))
    if enc is None:
        add(pots16, "Knob", "Knob for 6 mm shaft")
        return rows
    holes = all_holes(project, enc)
    kinds: dict[str, list] = {}
    for h in holes:
        kinds.setdefault(h.kind, []).append(h)
    add(1, enc.spec.name, "Die-cast aluminium enclosure", f"{enc.color}; drill per the template")
    add(len(kinds.get("pot", [])) + len(kinds.get("pot9", [])), f"Knob {enc.knob_d:g} mm ({enc.knob_color})",
        "Knob for 6 mm shaft")
    add(pots16, "Dust cover", "16 mm pot dust cover", "insulates pots mounted under the board")
    add(sum(1 for h in kinds.get("footswitch", []) if not h.derived), "3PDT", "Latching footswitch (3PDT)",
        "12 mm bushing")
    add(sum(1 for h in kinds.get("jack", []) if not h.derived), '1/4" mono jack', "Open-frame 6.35 mm jack",
        "stereo for the input if it switches the battery")
    add(sum(1 for h in kinds.get("dc", []) if not h.derived), "DC 2.1 mm", "Panel DC socket, centre negative",
        "12 mm hole type")
    for k in ("bezel3", "bezel5"):
        add(len(kinds.get(k, [])), HARDWARE[k].label, "LED bezel")
    add(sum(1 for h in kinds.get("toggle", []) if not h.derived), "Mini toggle", "Toggle switch (panel)")
    add(1, "Hook-up wire", "22-24 AWG stranded", "several colours")
    return rows


def pedal_bom_csv(project: Project) -> str:
    buf = io.StringIO()
    wr = csv.DictWriter(buf, fieldnames=["Section", "Qty", "Value", "Designators", "Part", "Notes", "MPN"],
                        lineterminator="\n")
    wr.writeheader()
    for r in build_rows(project):
        wr.writerow(r)
    return buf.getvalue()


def pedal_bom_text(project: Project) -> str:
    lines = [f"{project.name} - build sheet", ""]
    section = None
    for r in build_rows(project):
        if r["Section"] != section:
            section = r["Section"]
            lines += ["", section.upper()]
        des = f"  [{r['Designators']}]" if r["Designators"] else ""
        note = f"  - {r['Notes']}" if r["Notes"] else ""
        lines.append(f"  {r['Qty']:>3} x {r['Value']:<14} {r['Part']}{des}{note}")
    return "\n".join(lines).strip() + "\n"
