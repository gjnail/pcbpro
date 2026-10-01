"""Excellon drill file writer (separate plated / non-plated files)."""
from __future__ import annotations

import datetime as _dt

from .. import __version__
from ..model.board import Project
from ..model.copper import holes
from .gerber import Origin


def drill_file(project: Project, plated: bool) -> str:
    origin = Origin.for_project(project)
    hl = [h for h in holes(project) if h.plated == plated]
    tools: dict[float, int] = {}
    for h in sorted(hl, key=lambda h: h.diameter):
        d = round(h.diameter, 3)
        if d not in tools:
            tools[d] = len(tools) + 1
    n = len(project.copper_layers)
    kind = "PTH" if plated else "NPTH"
    lines = [
        "M48",
        f"; DRILL file PCBPro {__version__} date {_dt.datetime.now().replace(microsecond=0).isoformat()}",
        "; FORMAT={-:-/ absolute / metric / decimal}",
        f"; #@! TF.FileFunction,{'Plated' if plated else 'NonPlated'},1,{n},{kind}",
        "FMAT,2",
        "METRIC",
    ]
    for d, t in tools.items():
        lines.append(f"T{t}C{d:.3f}")
    lines += ["%", "G90", "G05"]
    for d, t in tools.items():
        lines.append(f"T{t}")
        for h in hl:
            if round(h.diameter, 3) != d:
                continue
            if h.is_slot:
                (ax, ay), (bx, by) = h.endpoints()
                ax, ay = origin(ax, ay)
                bx, by = origin(bx, by)
                lines.append(f"X{ax:.3f}Y{ay:.3f}G85X{bx:.3f}Y{by:.3f}")
            else:
                x, y = origin(h.x, h.y)
                lines.append(f"X{x:.3f}Y{y:.3f}")
    lines.append("M30")
    return "\n".join(lines) + "\n"


def drill_summary(project: Project) -> dict:
    hl = holes(project)
    return {
        "plated": sum(1 for h in hl if h.plated),
        "non_plated": sum(1 for h in hl if not h.plated),
        "min_drill": min((h.diameter for h in hl), default=0.0),
        "tools": len({round(h.diameter, 3) for h in hl}),
    }
