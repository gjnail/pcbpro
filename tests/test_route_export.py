import zipfile

from pcbpro.export.assembly import bom_csv, cpl_csv
from pcbpro.export.excellon import drill_file
from pcbpro.export.gerber import generate_gerbers
from pcbpro.export.package import export_package
from pcbpro.fab.fabs import FABS, OrderOptions, board_spec, quote_all
from pcbpro.model.connectivity import get_connectivity
from pcbpro.model.drc import run_drc
from pcbpro.route.autorouter import Autorouter


def test_autorouter_completes_example_without_drc_errors(example):
    r = Autorouter(example).run()
    assert r.failed == 0 and r.routed > 10
    assert get_connectivity(example).unrouted_count() == 0
    errors = [v for v in run_drc(example) if v.severity == "error"]
    assert errors == [], [v.message for v in errors]


def test_gerbers_parse_with_independent_parser(example, tmp_path):
    Autorouter(example).run()
    res = export_package(example, tmp_path)
    names = {p.suffix for p in res.files}
    assert {".GTL", ".GBL", ".GTS", ".GBS", ".GTO", ".GBO", ".GKO", ".drl"} <= names
    with zipfile.ZipFile(res.zip_path) as zf:
        assert len(zf.namelist()) == len(res.files)
    try:
        from pygerber.gerberx3.api.v2 import GerberFile
    except ImportError:  # optional dev dependency
        return
    for p in res.files:
        if p.suffix.startswith(".G"):
            GerberFile.from_file(str(p)).parse()


def test_gerber_content(example):
    g = generate_gerbers(example)
    assert g["F.Cu"].startswith("%TF.GenerationSoftware")
    assert "%TF.FileFunction,Copper,L1,Top*%" in g["F.Cu"]
    assert "%TF.FileFunction,Soldermask,Top*%" in g["F.Mask"]
    for text in g.values():
        assert text.rstrip().endswith("M02*")
        assert "nan" not in text.lower()


def test_drill_and_assembly_files(example):
    pth = drill_file(example, True)
    npth = drill_file(example, False)
    assert "METRIC" in pth and pth.rstrip().endswith("M30")
    assert npth.count("\nX") == 4  # four M3 mounting holes
    bom = bom_csv(example)
    assert "U1" in bom and "H1" not in bom
    assert cpl_csv(example).splitlines()[0] == "Designator,Mid X,Mid Y,Layer,Rotation"


def test_quotes(example):
    spec = board_spec(example)
    assert spec.width == 50 and spec.height == 35
    quotes = quote_all(spec, OrderOptions(quantity=5))
    assert len(quotes) == len(FABS)
    osh = next(q for q in quotes if q.fab.key == "oshpark")
    assert osh.boards == 6  # sold in sets of three
    assert abs(osh.board_cost - 2 * 5.0 * (50 * 35 / 645.16)) < 0.01
    assert any("mask" in i for i in osh.issues)  # green isn't offered
    assert quotes[0].ok
