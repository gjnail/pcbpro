"""Project file load/save (.pcbpro JSON)."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .board import Project
from .copper import fill_all_zones


def save_project(project: Project, path: str | Path) -> None:
    path = Path(path)
    data = json.dumps(project.to_dict(), indent=1)
    # atomic write so a crash never leaves a truncated design behind
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".pcbpro-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_project(path: str | Path) -> Project:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    p = Project.from_dict(data)
    if p.zones:
        fill_all_zones(p)
    return p
