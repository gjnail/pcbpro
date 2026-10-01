"""Unified, searchable index over every part source (built-in, catalogue, user library, KiCad folders)."""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from ..model.footprints import LIBRARY, LibPart
from .kicad import default_kicad_dirs, scan_kicad_dir
from .userlib import load_user_parts

SOURCES = OrderedDict([("all", "All sources"), ("builtin", "Built-in footprints"), ("catalog", "Parts catalog (MPNs)"),
                       ("user", "My library (imports)"), ("kicad", "KiCad libraries")])


class LibraryIndex:
    def __init__(self, kicad_dirs: list[str] | None = None):
        self.kicad_dirs: list[str] = list(kicad_dirs or [])
        self.builtin: list[LibPart] = list(LIBRARY)
        self.user: list[LibPart] = []
        self.kicad: list[LibPart] = []
        self.reload_user()
        self.reload_kicad()

    # ------------------------------------------------------------------ loading
    def reload_user(self) -> None:
        self.user = load_user_parts()

    def all_kicad_dirs(self) -> list[Path]:
        dirs = [Path(d) for d in self.kicad_dirs if Path(d).is_dir()]
        for d in default_kicad_dirs():
            if d not in dirs:
                dirs.append(d)
        return dirs

    def reload_kicad(self) -> None:
        parts: list[LibPart] = []
        seen: set[str] = set()
        for d in self.all_kicad_dirs():
            for p in scan_kicad_dir(d):
                if p.name not in seen:
                    seen.add(p.name)
                    parts.append(p)
        self.kicad = parts

    def add_kicad_dir(self, path: str) -> int:
        if path not in self.kicad_dirs:
            self.kicad_dirs.append(path)
        before = len(self.kicad)
        self.reload_kicad()
        return len(self.kicad) - before

    # ------------------------------------------------------------------ queries
    def parts(self, source: str = "all") -> list[LibPart]:
        builtin = [p for p in self.builtin if p.source != "catalog"]
        catalog = [p for p in self.builtin if p.source == "catalog"]
        groups = {"builtin": builtin, "catalog": catalog, "user": self.user, "kicad": self.kicad}
        if source == "all":
            return self.user + catalog + builtin + self.kicad
        return groups.get(source, [])

    def counts(self) -> dict[str, int]:
        return {k: len(self.parts(k)) for k in SOURCES if k != "all"}

    def search(self, query: str, source: str = "all", limit: int = 500) -> list[LibPart]:
        toks = [t for t in query.lower().split() if t]
        pool = self.parts(source)
        if not toks:
            return pool[:limit]
        scored = []
        for p in pool:
            text = p.search_text
            if all(t in text for t in toks):
                name = p.name.lower()
                score = 0
                for t in toks:
                    if name == t:
                        score -= 100
                    elif name.startswith(t):
                        score -= 20
                    elif t in name:
                        score -= 5
                if p.source == "catalog":
                    score -= 3
                elif p.source == "user":
                    score -= 4
                scored.append((score, len(p.name), p))
        scored.sort(key=lambda s: (s[0], s[1]))
        return [s[2] for s in scored[:limit]]

    def tree(self, source: str = "all") -> "OrderedDict[str, OrderedDict]":
        """Nested category tree: {top: {sub: [parts]}} (parts under key '' when no sub-category)."""
        root: "OrderedDict[str, OrderedDict]" = OrderedDict()
        for p in self.parts(source):
            top, _, sub = p.category.partition("/")
            root.setdefault(top, OrderedDict()).setdefault(sub, []).append(p)
        return root

    def find(self, name: str) -> LibPart | None:
        for p in self.user + self.builtin + self.kicad:
            if p.name == name:
                return p
        return None
