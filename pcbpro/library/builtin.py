"""Assembles the built-in parts library from every generator module.

Any module in this package named ``gen_*.py`` that defines ``entries()`` is picked up
automatically. ``entries()`` returns tuples of
``(category, name, prefix, default_value, footprint_factory, keywords[, extra])`` where
``extra`` is an optional dict of LibPart fields (mpn, manufacturer, description, lcsc).
Category may contain "/" to create sub-folders in the library tree.
"""
from __future__ import annotations

import importlib
import pkgutil

from ..model.footprints import LibPart

_CORE = ["gen_passive", "gen_ic", "gen_conn", "gen_misc"]


def generator_modules() -> list[str]:
    from . import __path__ as pkg_path
    found = sorted(m.name for m in pkgutil.iter_modules(pkg_path) if m.name.startswith("gen_"))
    return _CORE + [m for m in found if m not in _CORE]


def build_builtin() -> list[LibPart]:
    parts: list[LibPart] = []
    seen: set[str] = set()
    for modname in generator_modules():
        try:
            mod = importlib.import_module(f"{__package__}.{modname}")
        except Exception as e:  # a broken add-on generator must not take the whole library down
            import sys
            print(f"PCBPro: skipping library module {modname}: {e}", file=sys.stderr)
            continue
        if not hasattr(mod, "entries"):
            continue
        for entry in mod.entries():
            cat, name, prefix, value, factory, kw = entry[:6]
            extra = entry[6] if len(entry) > 6 else {}
            if name in seen:
                continue
            seen.add(name)
            parts.append(LibPart(cat, name, prefix, value, factory, kw, **extra))
    # real manufacturer parts that reuse the generic footprints above
    from .catalog import catalog_parts
    by_name = {p.name: p for p in parts}
    for p in catalog_parts(by_name):
        if p.name not in seen:
            seen.add(p.name)
            parts.append(p)
    return parts
