"""Built-in footprints vs. the official KiCad library (datasheet-derived land patterns)."""
import copy

import pytest

from pcbpro.library.verify import KNOWN_VARIANTS, REFERENCES, compare, kicad_root, load_reference
from pcbpro.model.footprints import find_part

ROOT = kicad_root()
needs_kicad = pytest.mark.skipif(ROOT is None, reason="KiCad footprint library not installed "
                                                     "(Library > KiCad footprint libraries > Download)")


def test_every_reference_names_a_builtin_part():
    missing = [n for n in REFERENCES if find_part(n) is None]
    assert missing == []


@needs_kicad
@pytest.mark.parametrize("name", sorted(REFERENCES), ids=str)
def test_builtin_matches_datasheet_reference(qapp, name):
    ref = load_reference(REFERENCES[name], ROOT)
    assert ref is not None, f"reference footprint {REFERENCES[name]} not found"
    res = compare(find_part(name).make(), ref, name, REFERENCES[name], KNOWN_VARIANTS.get(name, (set(), ""))[0])
    assert res.ok(), res.summary()


@needs_kicad
def test_comparator_detects_errors(qapp):
    """Shift one pad, mislabel another and shrink a third: the check must flag each."""
    ref = load_reference(REFERENCES["SOIC-8"], ROOT)
    good = find_part("SOIC-8").make()
    assert compare(good, ref).ok()
    bad = copy.deepcopy(good)
    bad.pads[0].y += 0.3
    assert compare(bad, ref).max_pos > 0.25
    bad = copy.deepcopy(good)
    bad.pads[0].number, bad.pads[1].number = bad.pads[1].number, bad.pads[0].number
    assert compare(bad, ref).numbering_errors == 2
    bad = copy.deepcopy(good)
    bad.pads[2].w = 0.8
    assert not compare(bad, ref).ok()


@needs_kicad
def test_tactile_switch_pairs_pins_across_the_row(qapp):
    """Regression: the internally connected legs are the ones in the same row (6.5 mm apart)."""
    fp = find_part("Tactile switch 6x6 THT").make()
    ones = [p for p in fp.pads if p.number == "1"]
    assert len(ones) == 2 and abs(ones[0].y - ones[1].y) < 1e-6 and abs(abs(ones[0].x - ones[1].x) - 6.5) < 1e-6
