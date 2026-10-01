"""Collect the licences of everything the Windows app bundles into one THIRD-PARTY-LICENSES.txt.

    python tools/third_party_licenses.py THIRD-PARTY-LICENSES.txt [--extra NAME=FILE ...]

Run it with the environment the app was built from (the release workflow does). For each bundled package it writes
the name, version, licence and home page from the package's metadata, then the full text of every licence file the
package ships. ``--extra`` adds texts a package refers to but doesn't include, such as the LGPL for Qt.
"""
from __future__ import annotations

import argparse
import sys
from importlib import metadata
from pathlib import Path

# what PyInstaller puts in dist/PCBPro (requirements.txt and what those pull in)
PACKAGES = ["PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6", "PyOpenGL", "numpy", "shapely",
            "mapbox_earcut", "numba", "llvmlite", "sounddevice", "cffi", "pycparser"]
LICENSE_WORDS = ("licen", "copying", "notice", "authors")


def licence_of(dist: metadata.Distribution) -> str:
    md = dist.metadata
    expr = md.get("License-Expression")
    if expr:
        return expr
    lic = (md.get("License") or "").strip()
    if lic and len(lic) < 200:
        return lic
    classifiers = [c.split(" :: ")[-1] for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
    return ", ".join(classifiers) or "see below"


def licence_files(dist: metadata.Distribution) -> list[Path]:
    out = []
    for f in dist.files or []:
        name = f.name.lower()
        if any(w in name for w in LICENSE_WORDS) and not name.endswith((".py", ".pyc", ".pyi")):
            p = Path(dist.locate_file(f))
            if p.is_file() and p.stat().st_size < 2_000_000:
                out.append(p)
    return out


def home_page(dist: metadata.Distribution) -> str:
    md = dist.metadata
    if md.get("Home-page"):
        return md["Home-page"]
    for url in md.get_all("Project-URL") or []:
        label, _, link = url.partition(",")
        if label.strip().lower() in ("homepage", "home", "source", "source code", "repository"):
            return link.strip()
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--extra", action="append", default=[], metavar="NAME=FILE")
    args = ap.parse_args()
    parts = ["Third-party software in PCBPro",
             "==============================",
             "",
             "PCBPro itself is under the MIT License (LICENSE). The Windows download also contains the software below,",
             "each under its own licence. Qt (through PySide6) is used under the GNU LGPL v3: PCBPro uses the unmodified Qt",
             "libraries as separate DLLs, which you may replace with your own build. The source of Qt is at",
             "https://download.qt.io/official_releases/qt/ and of PySide6 at https://code.qt.io/cgit/pyside/pyside-setup.git/.",
             ""]
    py_lic = Path(sys.base_prefix) / "LICENSE.txt"
    parts += ["-" * 100, f"Python {sys.version.split()[0]}  -  PSF License  -  https://www.python.org/", "-" * 100, ""]
    parts.append(py_lic.read_text(encoding="utf-8", errors="replace") if py_lic.exists() else
                 "See https://docs.python.org/3/license.html")
    missing = []
    for name in PACKAGES:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
            continue
        parts += ["", "-" * 100, f"{dist.metadata['Name']} {dist.version}  -  {licence_of(dist)}  -  {home_page(dist)}",
                  "-" * 100, ""]
        files = licence_files(dist)
        if not files:
            parts.append("(The package ships no licence file; see its home page.)")
        for f in files:
            parts += [f"[{f.name}]", f.read_text(encoding="utf-8", errors="replace").strip(), ""]
    try:
        import _sounddevice_data
        pa = Path(_sounddevice_data.__file__).parent / "portaudio-binaries" / "README.md"
        if pa.exists():
            parts += ["", "-" * 100, "PortAudio (bundled with sounddevice)  -  MIT  -  http://www.portaudio.com/", "-" * 100,
                      "", pa.read_text(encoding="utf-8", errors="replace").strip()]
    except ImportError:
        pass
    for extra in args.extra:
        title, _, path = extra.partition("=")
        parts += ["", "-" * 100, title, "-" * 100, "", Path(path).read_text(encoding="utf-8", errors="replace").strip()]
    Path(args.out).write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {len(PACKAGES) - len(missing)} packages" + (f", not installed: {missing}" if missing else ""))
    if missing:
        sys.exit(1)


if __name__ == "__main__":
    main()
