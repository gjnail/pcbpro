"""Convert text to polygons using Qt's font engine (used for silkscreen and copper text)."""
from __future__ import annotations

from functools import lru_cache

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from .geometry import transform_geom

FONT_FAMILY = "Arial"
_BASE_PT = 100.0


def _qt():
    from PySide6.QtGui import QFont, QFontMetricsF, QPainterPath, QTransform

    return QFont, QFontMetricsF, QPainterPath, QTransform


@lru_cache(maxsize=4096)
def text_path_local(text: str, size: float, bold: bool = True):
    """QPainterPath of `text` centred at the origin with cap height `size` mm."""
    QFont, QFontMetricsF, QPainterPath, QTransform = _qt()
    font = QFont(FONT_FAMILY)
    font.setPointSizeF(_BASE_PT)
    font.setBold(bold)
    fm = QFontMetricsF(font)
    cap = fm.capHeight() or fm.ascent() * 0.7
    path = QPainterPath()
    path.addText(0, 0, font, text)
    br = path.boundingRect()
    s = size / cap
    t = QTransform()
    t.scale(s, s)
    t.translate(-br.center().x(), cap / 2)
    return t.map(path)


@lru_cache(maxsize=4096)
def _text_polygon_local(text: str, size: float) -> BaseGeometry:
    path = text_path_local(text, size)
    geom: BaseGeometry = Polygon()
    for qpoly in path.toFillPolygons():
        pts = [(p.x(), p.y()) for p in qpoly]
        if len(pts) < 3:
            continue
        poly = Polygon(pts).buffer(0)
        geom = geom.symmetric_difference(poly)
    return geom


def text_geometry(text: str, x: float, y: float, size: float, rotation: float = 0.0, mirror: bool = False) -> BaseGeometry:
    if not text.strip():
        return Polygon()
    g = _text_polygon_local(text, round(size, 4))
    return transform_geom(g, x, y, rotation, mirror)
