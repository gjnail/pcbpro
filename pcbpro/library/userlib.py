"""The user's own part library: imported LCSC parts, KiCad imports and wizard-generated footprints.

Stored as one JSON file per part in Documents/PCBPro/library so it survives updates and can be shared.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..model.board import Footprint
from ..model.footprints import LibPart


def library_dir() -> Path:
    d = Path.home() / "Documents" / "PCBPro" / "library"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")[:120] or "part"


def save_part(name: str, footprint: Footprint, category: str = "My library", prefix: str = "U", value: str = "",
              mpn: str = "", manufacturer: str = "", lcsc: str = "", description: str = "",
              source: str = "user", folder: Path | None = None) -> Path:
    folder = folder or library_dir()
    data = {"format": "pcbpro-part", "version": 1, "name": name, "category": category, "prefix": prefix,
            "value": value or name, "mpn": mpn, "manufacturer": manufacturer, "lcsc": lcsc,
            "description": description or footprint.description, "source": source,
            "footprint": footprint.to_dict()}
    path = folder / f"{_slug(name)}.json"
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return path


def _part_from_file(path: Path) -> LibPart | None:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if d.get("format") != "pcbpro-part":
        return None
    fp_dict = d["footprint"]

    def factory(fp_dict=fp_dict):
        return Footprint.from_dict(fp_dict)

    source = d.get("source", "user")
    cat = d.get("category") or "My library"
    if not cat.startswith("My library"):
        cat = f"My library/{cat}"
    part = LibPart(cat, d["name"], d.get("prefix", "U"), d.get("value", d["name"]), factory,
                   f"{d.get('description', '')} {fp_dict.get('name', '')}".lower(), mpn=d.get("mpn", ""),
                   manufacturer=d.get("manufacturer", ""), description=d.get("description", ""),
                   lcsc=d.get("lcsc", ""), source=source)
    part.path = str(path)  # type: ignore[attr-defined]
    return part


def load_user_parts(folder: Path | None = None) -> list[LibPart]:
    folder = folder or library_dir()
    parts = []
    for path in sorted(folder.glob("*.json")):
        p = _part_from_file(path)
        if p is not None:
            parts.append(p)
    return parts


def delete_part(part: LibPart) -> bool:
    path = getattr(part, "path", None)
    if path and Path(path).exists():
        Path(path).unlink()
        return True
    return False
