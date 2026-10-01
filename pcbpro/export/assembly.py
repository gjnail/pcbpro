"""Bill of materials and pick-and-place (CPL) generation."""
from __future__ import annotations

import csv
import io
from collections import OrderedDict

from ..model.board import Component, Project, natural_key
from .gerber import Origin


def is_assembled(c: Component) -> bool:
    return c.footprint.model.get("type", "") != "none"


def bom_rows(project: Project) -> list[dict]:
    groups: "OrderedDict[tuple, list[Component]]" = OrderedDict()
    for c in sorted(project.components, key=lambda c: natural_key(c.ref)):
        if not is_assembled(c):
            continue
        key = (c.value, c.footprint.name, c.mpn, c.lcsc)
        groups.setdefault(key, []).append(c)
    rows = []
    for (value, fp, mpn, lcsc), comps in groups.items():
        rows.append({
            "Comment": value,
            "Designator": ",".join(c.ref for c in comps),
            "Footprint": fp,
            "Quantity": len(comps),
            "MPN": mpn,
            "LCSC Part #": lcsc,
        })
    return rows


def bom_csv(project: Project) -> str:
    buf = io.StringIO()
    wr = csv.DictWriter(buf, fieldnames=["Comment", "Designator", "Footprint", "Quantity", "MPN", "LCSC Part #"],
                        lineterminator="\n")
    wr.writeheader()
    for r in bom_rows(project):
        wr.writerow(r)
    return buf.getvalue()


def cpl_csv(project: Project) -> str:
    origin = Origin.for_project(project)
    buf = io.StringIO()
    wr = csv.writer(buf, lineterminator="\n")
    wr.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
    for c in sorted(project.components, key=lambda c: natural_key(c.ref)):
        if not is_assembled(c):
            continue
        x, y = origin(c.x, c.y)
        wr.writerow([c.ref, f"{x:.3f}mm", f"{y:.3f}mm", "Top" if c.side == "top" else "Bottom",
                     f"{c.rotation % 360:g}"])
    return buf.getvalue()
