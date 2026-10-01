"""Compare built-in footprints with the official KiCad library (datasheet-derived reference).

Usage:  python tools/verify_footprints.py [-v]
Requires the KiCad footprint library (Library > KiCad footprint libraries > Download).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from pcbpro.library.verify import REFERENCES, kicad_root, load_reference, verify_builtin  # noqa: E402
from pcbpro.model.footprints import find_part  # noqa: E402

root = kicad_root()
if root is None:
    sys.exit("KiCad footprint library not found - download it from Library > KiCad footprint libraries")
missing = [(k, v) for k, v in REFERENCES.items() if find_part(k) is None or load_reference(v, root) is None]
for k, v in missing:
    print(f"SKIP {k}: {'no built-in part' if find_part(k) is None else 'reference not found: ' + v}")
results = verify_builtin(root)
bad = [r for r in results if not r.ok()]
for r in results:
    print(r.summary())
    if "-v" in sys.argv and not r.ok():
        for d in r.deltas:
            if d.mine is None or d.pos_err > 0.1 or d.size_err > 0.3 or d.drill_err > 0.15 or not d.number_ok:
                m = d.mine
                print(f"      ref {d.ref.number:>6} ({d.ref.x:7.3f},{d.ref.y:7.3f}) {d.ref.w:.2f}x{d.ref.h:.2f} "
                      f"drill {d.ref.min_drill:.2f}  <->  "
                      + (f"mine {m.number:>6} {m.w:.2f}x{m.h:.2f} drill {m.min_drill:.2f} pos {d.pos_err:.3f}"
                         if m else "mine: MISSING"))
        for m in r.extra:
            print(f"      extra pad in mine: {m.number} ({m.x:.3f},{m.y:.3f}) {m.w:.2f}x{m.h:.2f}")
print(f"\n{len(results) - len(bad)}/{len(results)} footprints match the reference within tolerance")
