"""The main window must fit a 1920x1080 screen: tab pages and docks may not demand a wide minimum width."""
import sys

from PySide6.QtTest import QTest


def test_main_window_fits_1080p(qapp):
    from pcbpro.ui.main_window import MainWindow
    w = MainWindow()
    w.resize(1600, 1000)
    w.show()
    QTest.qWait(50)
    pages = {w.tabs.tabText(i): w.tabs.widget(i).minimumSizeHint().width() for i in range(w.tabs.count())}
    assert max(pages.values()) < 900, pages
    assert w.minimumSizeHint().width() < 1500
    w.doc.dirty = False
    w.hide()  # not close(): closeEvent would save this window's geometry to the real settings
    w.deleteLater()


def test_flow_layout_matches_hbox_then_wraps(qapp):
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

    from pcbpro.ui.flow import FlowLayout

    def page(row):
        p = QWidget()
        lay = QVBoxLayout(p)
        lay.addLayout(row)
        btns = [QPushButton(f"Button {i}") for i in range(8)]
        for b in btns[:4]:
            row.addWidget(b)
        row.addSpacing(12)
        row.addWidget(btns[4])
        row.addStretch(1)
        for b in btns[5:]:
            row.addWidget(b)
        lay.addWidget(QLabel("body"), 1)
        p.resize(1400, 300)
        p.show()
        return p, btns

    hp, hb = page(QHBoxLayout())
    fp, fb = page(FlowLayout())
    QTest.qWait(50)
    if sys.platform != "darwin":  # the macOS style adds its own margins around buttons in a QHBoxLayout
        assert [b.geometry() for b in fb] == [b.geometry() for b in hb]  # wide: exactly a QHBoxLayout
    assert fp.minimumSizeHint().width() < hp.minimumSizeHint().width() / 3

    fp.resize(fb[4].geometry().right() + 40, 300)
    QTest.qWait(50)
    assert all(b.geometry().right() < fp.width() for b in fb)
    assert fb[4].y() == fb[0].y()
    assert fb[5].x() == fb[0].x() and fb[5].y() > fb[0].y()  # the group after the stretch moves down whole
    assert fp.findChild(QLabel).y() > fb[7].geometry().bottom()  # the page below makes room for the wrapped row
    for p in (hp, fp):
        p.close()
