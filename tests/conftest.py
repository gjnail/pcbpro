import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtGui import QSurfaceFormat
    from PySide6.QtWidgets import QApplication
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def example(qapp):
    from pcbpro.examples import flasher_555
    from pcbpro.model.copper import fill_all_zones
    p = flasher_555()
    fill_all_zones(p)
    return p
