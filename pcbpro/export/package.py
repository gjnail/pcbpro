"""Manufacturing package: Gerbers + drills zipped for upload, plus assembly files."""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from ..model.board import Project
from ..model.copper import fill_all_zones
from .assembly import bom_csv, cpl_csv
from .excellon import drill_file
from .gerber import LAYER_FILES, generate_gerbers


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "board"


@dataclass
class PackageResult:
    folder: Path
    zip_path: Path
    files: list[Path] = field(default_factory=list)
    bom_path: Path | None = None
    cpl_path: Path | None = None
    pedal_files: list = field(default_factory=list)  # drill template, Tayda coordinates, build sheet


def export_package(project: Project, folder: str | Path, include_assembly: bool = True) -> PackageResult:
    if project.fills_stale:
        fill_all_zones(project)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    base = safe_name(project.name)
    files: list[Path] = []
    for layer, text in generate_gerbers(project).items():
        p = folder / f"{base}.{LAYER_FILES[layer]}"
        p.write_text(text, encoding="ascii")
        files.append(p)
    for plated in (True, False):
        p = folder / f"{base}-{'PTH' if plated else 'NPTH'}.drl"
        p.write_text(drill_file(project, plated), encoding="ascii")
        files.append(p)
    zip_path = folder / f"{base}_gerbers.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, p.name)
    res = PackageResult(folder, zip_path, files)
    if include_assembly and project.components:
        res.bom_path = folder / f"{base}_BOM.csv"
        res.bom_path.write_text(bom_csv(project), encoding="utf-8")
        res.cpl_path = folder / f"{base}_CPL.csv"
        res.cpl_path.write_text(cpl_csv(project), encoding="utf-8")
    res.pedal_files = export_pedal_docs(project, folder, base)
    return res


def export_pedal_docs(project: Project, folder: Path, base: str) -> list[Path]:
    """Drill template, Tayda coordinates and build sheet for designs with a pedal enclosure."""
    from ..pedal.enclosure import get_enclosure
    out: list[Path] = []
    if get_enclosure(project) is None:
        return out
    from ..pedal.bom import pedal_bom_csv
    from ..pedal.drill import export_pdf, tayda_text
    p = folder / f"{base}_Tayda_drill.txt"
    p.write_text(tayda_text(project), encoding="utf-8")
    out.append(p)
    p = folder / f"{base}_build_sheet.csv"
    p.write_text(pedal_bom_csv(project), encoding="utf-8")
    out.append(p)
    try:  # needs Qt's PDF writer (a running GUI application)
        out.append(export_pdf(project, folder / f"{base}_drill_template.pdf"))
    except Exception as e:  # pragma: no cover - headless use without a QGuiApplication
        import sys
        print(f"PCBPro: drill template not written: {e}", file=sys.stderr)
    return out
