import csv
import io
from urllib.parse import unquote

from PySide6.QtTest import QTest

from pcbpro.fab.suppliers import (SUPPLIERS, Line, fab_links, order_csv, order_text, scaled, search_terms,
                                  shopping_list, supplier_by_key)
from pcbpro.model.board import Component
from pcbpro.model.footprints import chip


def _terms(section, value, package="", **kw):
    return search_terms(Line(section, 1, value, package, **kw))


def test_search_terms_use_shop_style_words():
    assert _terms("Resistors", "4k7", "R_Axial_L6.3mm_D2.5mm_P10.16mm") == "4.7K 1/4W metal film"
    assert _terms("Resistors", "47R", "R_Axial_L6.3mm_D2.5mm_P10.16mm") == "47 ohm 1/4W metal film"
    assert _terms("Resistors", "10k", "R_0805_2012Metric") == "10K resistor 0805"
    assert _terms("Film capacitors", "2n2", "C_Rect_L7.2mm_W2.5mm_P5.00mm") == "2.2nF film capacitor"
    assert _terms("Electrolytic capacitors", "100u", "CP_Radial_D6.3mm_P2.5mm") == "100uF 25V electrolytic"
    assert _terms("Ceramic capacitors", "47p", "C_Rect_Ceramic_P5.08mm") == "47pF ceramic capacitor"
    assert _terms("Potentiometers", "B25K", "Pot_Alpha_16mm_RV16AF-41") == "25K linear potentiometer"
    assert _terms("Potentiometers", "A100K", "Pot_Alpha_9mm_RD901F-40_Vertical") == "100K audio potentiometer 9mm"
    assert _terms("LEDs", "Red", "LED_D3mm") == "red LED 3mm"
    assert _terms("ICs", "NE555", "SOIC-8_3.9x4.9mm_P1.27mm") == "NE555 SOIC-8"
    assert _terms("ICs", "TL072", "DIP-8_W7.62mm") == "TL072"  # Tayda's DIP listings don't say "DIP"
    assert _terms("Switches", "RESET", "SW_PUSH_6mm") == "6mm tactile switch"
    assert _terms("Jacks & connectors", "PWR 5V", "PinHeader_1x02_P2.54mm") == "2.54mm pin header 1x2"
    # a manufacturer part number always wins
    assert _terms("ICs", "TL072", "DIP-8_W7.62mm", mpn="TL072CP") == "TL072CP"


def test_supplier_urls():
    tayda = supplier_by_key("tayda")
    url = tayda.search_url("4.7K 1/4W metal film")
    assert url.startswith("https://www.taydaelectronics.com/catalogsearch/result/?q=")
    assert unquote(url.split("q=")[1]) == "4.7K 1/4W metal film"
    lcsc = supplier_by_key("lcsc")
    line = Line("ICs", 1, "TL072", "SOIC-8", lcsc="C6961", query="TL072")
    assert lcsc.line_url(line) == "https://www.lcsc.com/product-detail/C6961.html"
    assert "keywords=TL072" in supplier_by_key("digikey").line_url(line)  # no part page there: search
    for s in SUPPLIERS:
        assert s.url.startswith("https://") and "{q}" in s.search
    names = [f.name for f in fab_links()]
    assert names[:4] == ["JLCPCB", "PCBWay", "OSH Park", "AISLER"] and len(names) > 4


def test_pedal_shopping_list(qapp):
    from pcbpro.pedal.examples import overdrive_example
    lines = shopping_list(overdrive_example(route=False))
    by_value = {ln.value: ln for ln in lines}
    assert by_value["4k7"].qty == 2 and by_value["4k7"].refs == "R1, R5"
    assert by_value["DIP-8 socket"].query == "8 pin DIP socket"  # added for the TL072
    assert by_value["Hammond 125B"].query == "125B enclosure"
    assert by_value["3PDT"].query == "3PDT footswitch"
    assert [ln.section for ln in lines][-1] == "Hardware"
    assert all(ln.query for ln in lines)
    rows = list(csv.DictReader(io.StringIO(order_csv(scaled(lines, 3)))))
    assert len(rows) == len(lines)
    assert next(r for r in rows if r["Value"] == "4k7")["Quantity"] == "6"
    text = order_text(lines, "Overdrive")
    assert text.startswith("Overdrive - parts to buy") and "HARDWARE" in text


def test_shopping_list_keeps_part_numbers():
    from pcbpro.model.board import Project
    p = Project()
    p.components += [Component("R1", "10k", chip("R", "0805"), 5, 5, lcsc="C17414"),
                     Component("R2", "10k", chip("R", "0805"), 9, 5, lcsc="C17414")]
    (line,) = shopping_list(p)
    assert (line.qty, line.lcsc, line.refs) == (2, "C17414", "R1, R2")


def test_buy_parts_dialog(qapp, monkeypatch, tmp_path):
    from pcbpro.ui import shop
    from pcbpro.ui.main_window import MainWindow
    opened = []
    monkeypatch.setattr(shop, "open_url", opened.append)
    monkeypatch.setattr(shop, "_open_folder", lambda path: None)
    monkeypatch.setattr(shop.QMessageBox, "information", lambda *a, **k: None)
    w = MainWindow()
    w.show()
    from pcbpro.ui import pedal_ui
    pedal_ui.open_pedal_example(w)
    w.doc.path = tmp_path / "overdrive.pcbpro"
    menu = next(a.menu() for a in w.menuBar().actions() if a.text().replace("&", "") == "Order")
    titles = [a.text() for a in menu.actions()]
    assert "&Buy components…" in titles and "Component supplier websites" in titles
    w.tabs.setCurrentWidget(w.order_page)
    QTest.qWait(100)
    assert "parts on" in w.order_page.parts_card.summary.text()
    dlg = shop.show_buy_parts(w, "tayda")
    assert dlg.supplier().key == "tayda" and dlg.pedal_card.isVisibleTo(dlg)
    row = next(r for r in range(dlg.table.rowCount()) if dlg.table.item(r, 1) and dlg.table.item(r, 1).text() == "4k7")
    dlg.open_row(row)
    assert opened[-1] == "https://www.taydaelectronics.com/catalogsearch/result/?q=4.7K%201%2F4W%20metal%20film"
    dlg.table.item(row, 5).setText("4.7K metal film")  # the user refines the search words
    dlg.open_row(row)
    assert opened[-1].endswith("q=4.7K%20metal%20film")
    dlg.sets.setValue(2)
    assert dlg.table.item(row, 0).text() == "4"
    assert dlg.table.item(row, 5).text() == "4.7K metal film"  # kept across the refill
    dlg.set_supplier("digikey")
    dlg.upload_list()
    assert opened[-1] == "https://www.digikey.com/en/mylists/"
    order = tmp_path / "Three-knob_overdrive_fab" / "Three-knob_overdrive_parts_order.csv"
    assert order.exists() and "4.7K metal film" in order.read_text(encoding="utf-8")
    dlg.tayda_drill()
    assert opened[-1] == "https://drill.taydakits.com/"
    assert (order.parent / "Three-knob_overdrive_Tayda_drill.txt").exists()
    assert shop.show_buy_parts(w) is dlg  # one dialog per window
    dlg.close()
    w.doc.dirty = False
    w.close()
