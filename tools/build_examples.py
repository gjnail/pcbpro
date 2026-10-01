"""Regenerate the bundled example projects (placed, autorouted, zones filled).

    python tools/build_examples.py            # everything
    python tools/build_examples.py amp metal  # only some groups: 555, pedal, amp, metal
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication(sys.argv)

from pcbpro.examples import EXAMPLE_DIR, flasher_555  # noqa: E402
from pcbpro.model.copper import fill_all_zones  # noqa: E402
from pcbpro.model.drc import run_drc  # noqa: E402
from pcbpro.model.fileio import save_project  # noqa: E402
from pcbpro.route.autorouter import Autorouter  # noqa: E402

GROUPS = [a for a in sys.argv[1:] if not a.startswith("-")]


def want(group: str) -> bool:
    return not GROUPS or group in GROUPS


def report(p, target):
    for v in run_drc(p):
        print("  DRC:", v.severity, v.message)
    save_project(p, target)
    print("saved", target, f"({len(p.components)} parts, {len(p.tracks)} tracks, {len(p.vias)} vias)")


EXAMPLE_DIR.mkdir(parents=True, exist_ok=True)
if want("555"):
    p = flasher_555()
    fill_all_zones(p)
    r = Autorouter(p).run()
    print(f"routed {r.routed}, unrouted {r.failed}, tracks {len(r.tracks)}, vias {len(r.vias)}")
    report(p, EXAMPLE_DIR / "555_LED_Flasher.pcbpro")

if want("pedal"):
    from pcbpro.pedal.examples import overdrive_example  # noqa: E402
    report(overdrive_example(), EXAMPLE_DIR / "Three_Knob_Overdrive_125B.pcbpro")

if want("amp"):
    from pcbpro.amp.builder import AMP_EXAMPLES, DESIGNS, build_amp  # noqa: E402
    for design_name, file_name in AMP_EXAMPLES.items():
        p, notes = build_amp(DESIGNS[design_name](), route=True)
        report(p, EXAMPLE_DIR / file_name)

if want("metal"):
    from pcbpro.amp.metal_pedals import METAL_EXAMPLES, build_pedal  # noqa: E402
    for key, file_name in METAL_EXAMPLES.items():
        report(build_pedal(key, route=True), EXAMPLE_DIR / file_name)
