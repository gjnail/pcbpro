"""LCSC / EasyEDA import: real-response parsing, endpoint fallback, offline cache and file import."""
import json
import urllib.error
from pathlib import Path

import pytest

from pcbpro.library import easyeda

FIX = Path(__file__).parent / "fixtures"


def fixture(code):
    return json.loads((FIX / f"lcsc_{code}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("code,pads,model", [("C2040", 57, "qfn"), ("C165948", 18, None), ("C25804", 2, "chip"),
                                              ("C14663", 2, "chip")])
def test_real_responses_parse(qapp, code, pads, model):
    part = easyeda.parse_component(fixture(code), code)
    fp = part.footprint
    assert len(fp.pads) == pads
    if model:
        assert fp.model["type"] == model
    assert part.mpn and part.package


def test_usb_c_slots_and_pegs(qapp):
    fp = easyeda.parse_component(fixture("C165948"), "C165948").footprint
    assert sum(1 for p in fp.pads if p.is_slot) == 4
    assert sum(1 for p in fp.pads if p.kind == "npth") == 2


def test_resistor_metadata(qapp):
    part = easyeda.parse_component(fixture("C25804"), "C25804")
    assert part.prefix == "R"
    assert part.footprint.model["cls"] == "R"


@pytest.fixture
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr(easyeda, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(easyeda.time, "sleep", lambda s: None)
    return tmp_path


def test_endpoint_fallback_and_retry(qapp, offline, monkeypatch):
    calls = []

    def fake(url, timeout):
        calls.append(url)
        if "version=" in url:
            raise urllib.error.HTTPError(url, 503, "busy", None, None)
        return {"success": True, "result": fixture("C25804")}

    monkeypatch.setattr(easyeda, "_http_json", fake)
    part = easyeda.import_lcsc("C25804")
    assert len(part.footprint.pads) == 2
    assert len(calls) == easyeda.RETRIES + 2  # retried the first endpoint, then succeeded on the second
    assert (offline / "C25804.json").exists()  # cached for offline use


def test_offline_uses_cache(qapp, offline, monkeypatch):
    (offline / "C14663.json").write_text(json.dumps(fixture("C14663")), encoding="utf-8")

    def down(url, timeout):
        raise urllib.error.URLError("no network")

    monkeypatch.setattr(easyeda, "_http_json", down)
    part = easyeda.import_lcsc("C14663", refresh=True)
    assert part.from_cache and "cached" in part.warnings[0]


def test_unreachable_without_cache_gives_guidance(qapp, offline, monkeypatch):
    monkeypatch.setattr(easyeda, "_http_json", lambda url, timeout: (_ for _ in ()).throw(urllib.error.URLError("x")))
    with pytest.raises(easyeda.LcscError) as e:
        easyeda.import_lcsc("C1")
    assert "Import from file" in str(e.value) and "KiCad" in str(e.value)


def test_format_change_is_reported(qapp, offline, monkeypatch):
    monkeypatch.setattr(easyeda, "_http_json", lambda url, timeout: {"success": True, "result": {"newFormat": 1}})
    with pytest.raises(easyeda.LcscError) as e:
        easyeda.import_lcsc("C2")
    assert "unexpected format" in str(e.value)


def test_not_found(qapp, offline, monkeypatch):
    monkeypatch.setattr(easyeda, "_http_json", lambda url, timeout: {"success": False, "result": None})
    with pytest.raises(LookupError):
        easyeda.import_lcsc("C3")


def test_file_import_formats(qapp, tmp_path):
    raw = fixture("C2040")
    envelope = tmp_path / "C2040.json"
    envelope.write_text(json.dumps({"success": True, "result": raw}), encoding="utf-8")
    bare = tmp_path / "rp2040_record.json"
    bare.write_text(json.dumps(raw), encoding="utf-8")
    source = tmp_path / "footprint_source.json"
    ds = raw["packageDetail"]["dataStr"]
    source.write_text(json.dumps(ds if isinstance(ds, dict) else json.loads(ds)), encoding="utf-8")
    for path in (envelope, bare, source):
        part = easyeda.import_easyeda_file(path, "C2040")
        assert len(part.footprint.pads) == 57
    assert easyeda.import_easyeda_file(envelope).lcsc == "C2040"


def test_lcsc_import_agrees_with_kicad_reference(qapp):
    """Independent cross-check of the converter (coordinates, units, rotation) against the KiCad library."""
    from pcbpro.library.verify import compare, load_reference
    ref = load_reference("Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12")
    if ref is None:
        pytest.skip("KiCad footprint library not installed")
    fp = easyeda.parse_component(fixture("C165948"), "C165948").footprint
    res = compare(fp, ref)
    assert len(res.matched) >= 16
    assert res.max_pos < 0.15, res.summary()
