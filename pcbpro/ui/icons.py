"""Vector toolbar icons drawn with QPainter (no image assets needed)."""
from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

FG = QColor("#d9dde5")
ACC = QColor("#4c9aff")
CU = QColor("#e0584f")
GOLD = QColor("#e2b34a")
GREEN = QColor("#3fcf8e")


def _pen(c=FG, w=1.8):
    return QPen(c, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)


def _draw(name: str, p: QPainter) -> None:
    p.setPen(_pen())
    p.setBrush(Qt.NoBrush)
    if name == "select":
        path = QPainterPath()
        path.moveTo(7, 4); path.lineTo(7, 23); path.lineTo(12, 18.5); path.lineTo(15.5, 26)
        path.lineTo(18.5, 24.5); path.lineTo(15, 17.5); path.lineTo(21.5, 17); path.closeSubpath()
        p.setBrush(QColor(FG.red(), FG.green(), FG.blue(), 60)); p.drawPath(path)
    elif name == "route":
        p.setPen(_pen(CU, 3.0))
        p.drawPolyline(QPolygonF([QPointF(5, 24), QPointF(12, 24), QPointF(22, 14), QPointF(22, 7)]))
        p.setPen(Qt.NoPen); p.setBrush(GOLD)
        p.drawEllipse(QPointF(5, 24), 3, 3); p.drawEllipse(QPointF(22, 7), 3, 3)
    elif name == "via":
        p.setPen(Qt.NoPen); p.setBrush(QColor("#b9bec8")); p.drawEllipse(QPointF(14, 14), 9, 9)
        p.setBrush(QColor("#1d2026")); p.drawEllipse(QPointF(14, 14), 4, 4)
    elif name == "zone":
        poly = QPolygonF([QPointF(4, 8), QPointF(18, 4), QPointF(25, 13), QPointF(20, 24), QPointF(6, 22)])
        p.setBrush(QColor(224, 88, 79, 90)); p.setPen(_pen(CU, 1.8)); p.drawPolygon(poly)
        p.setClipRegion(poly.toPolygon()); p.setPen(_pen(CU, 1.0))
        for i in range(-20, 40, 5):
            p.drawLine(QPointF(i, 28), QPointF(i + 24, 4))
        p.setClipping(False)
    elif name == "text":
        f = QFont("Segoe UI", 17); f.setBold(True); p.setFont(f); p.setPen(FG)
        p.drawText(QRectF(0, 0, 28, 28), Qt.AlignCenter, "T")
    elif name == "outline":
        p.setPen(QPen(GOLD, 2.0, Qt.DashLine)); p.drawRoundedRect(QRectF(4, 6, 20, 16), 3, 3)
        p.setPen(Qt.NoPen); p.setBrush(GOLD)
        for x, y in ((4, 6), (24, 6), (24, 22), (4, 22)):
            p.drawRect(QRectF(x - 2, y - 2, 4, 4))
    elif name == "measure":
        p.save(); p.translate(14, 14); p.rotate(-35)
        p.drawRect(QRectF(-12, -4, 24, 8))
        for i in range(-9, 12, 3):
            p.drawLine(QPointF(i, -4), QPointF(i, -1 if i % 2 else 0.5))
        p.restore()
    elif name == "connect":
        p.setPen(_pen(ACC, 2.0)); p.drawLine(QPointF(7, 21), QPointF(21, 7))
        p.setPen(Qt.NoPen); p.setBrush(GOLD)
        p.drawRect(QRectF(3, 17, 8, 8)); p.drawEllipse(QPointF(21, 7), 4.2, 4.2)
    elif name == "place":
        p.setBrush(QColor("#2a2f38")); p.drawRoundedRect(QRectF(7, 7, 14, 14), 2, 2)
        p.setPen(_pen(QColor("#b9bec8"), 1.6))
        for i in (10, 14, 18):
            p.drawLine(QPointF(i, 7), QPointF(i, 3)); p.drawLine(QPointF(i, 21), QPointF(i, 25))
            p.drawLine(QPointF(7, i), QPointF(3, i)); p.drawLine(QPointF(21, i), QPointF(25, i))
    elif name == "autoroute":
        p.setPen(_pen(CU, 2.6))
        p.drawPolyline(QPolygonF([QPointF(3, 25), QPointF(9, 25), QPointF(15, 19)]))
        path = QPainterPath()
        path.moveTo(17, 3); path.lineTo(10, 15); path.lineTo(15, 15); path.lineTo(12, 25)
        path.lineTo(22, 11); path.lineTo(17, 11); path.lineTo(21, 3); path.closeSubpath()
        p.setPen(Qt.NoPen); p.setBrush(GOLD); p.drawPath(path)
    elif name == "drc":
        path = QPainterPath()
        path.moveTo(14, 3); path.lineTo(24, 7); path.lineTo(24, 14)
        path.cubicTo(24, 20, 19, 24, 14, 26); path.cubicTo(9, 24, 4, 20, 4, 14)
        path.lineTo(4, 7); path.closeSubpath()
        p.setBrush(QColor(63, 207, 142, 50)); p.setPen(_pen(GREEN, 1.8)); p.drawPath(path)
        p.drawPolyline(QPolygonF([QPointF(9, 14), QPointF(13, 18), QPointF(19, 10)]))
    elif name == "refill":
        poly = QPolygonF([QPointF(3, 7), QPointF(17, 4), QPointF(22, 12), QPointF(15, 23), QPointF(4, 20)])
        p.setBrush(QColor(224, 88, 79, 110)); p.setPen(_pen(CU, 1.6)); p.drawPolygon(poly)
        p.setPen(_pen(FG, 2.0)); p.drawArc(QRectF(13, 13, 12, 12), 60 * 16, 270 * 16)
        p.setPen(Qt.NoPen); p.setBrush(FG)
        p.drawPolygon(QPolygonF([QPointF(26, 12), QPointF(26.5, 18), QPointF(21, 15.5)]))
    elif name == "cube":
        top = QPolygonF([QPointF(14, 3), QPointF(25, 9), QPointF(14, 15), QPointF(3, 9)])
        left = QPolygonF([QPointF(3, 9), QPointF(14, 15), QPointF(14, 26), QPointF(3, 20)])
        right = QPolygonF([QPointF(25, 9), QPointF(14, 15), QPointF(14, 26), QPointF(25, 20)])
        p.setPen(_pen(FG, 1.4))
        p.setBrush(QColor("#3fae6a")); p.drawPolygon(top)
        p.setBrush(QColor("#2a7a4a")); p.drawPolygon(left)
        p.setBrush(QColor("#1f5c38")); p.drawPolygon(right)
    elif name == "order":
        p.setPen(_pen(FG, 1.9))
        p.drawPolyline(QPolygonF([QPointF(2, 5), QPointF(6, 5), QPointF(9, 19), QPointF(22, 19), QPointF(25, 9), QPointF(7.5, 9)]))
        p.setPen(Qt.NoPen); p.setBrush(FG)
        p.drawEllipse(QPointF(11, 23.5), 2, 2); p.drawEllipse(QPointF(20, 23.5), 2, 2)
    elif name == "new":
        path = QPainterPath()
        path.moveTo(7, 3); path.lineTo(17, 3); path.lineTo(22, 8); path.lineTo(22, 25); path.lineTo(7, 25); path.closeSubpath()
        p.drawPath(path); p.drawPolyline(QPolygonF([QPointF(17, 3), QPointF(17, 8), QPointF(22, 8)]))
        p.setPen(_pen(ACC, 2)); p.drawLine(QPointF(14.5, 12), QPointF(14.5, 20)); p.drawLine(QPointF(10.5, 16), QPointF(18.5, 16))
    elif name == "open":
        path = QPainterPath()
        path.moveTo(3, 7); path.lineTo(10, 7); path.lineTo(12, 9); path.lineTo(24, 9); path.lineTo(24, 22); path.lineTo(3, 22)
        path.closeSubpath(); p.setBrush(QColor(226, 179, 74, 60)); p.setPen(_pen(GOLD, 1.8)); p.drawPath(path)
    elif name == "save":
        p.drawRoundedRect(QRectF(4, 4, 20, 20), 2, 2)
        p.drawRect(QRectF(9, 4, 10, 6)); p.drawRect(QRectF(8, 15, 12, 9))
    elif name in ("undo", "redo"):
        p.save()
        if name == "redo":
            p.translate(28, 0); p.scale(-1, 1)
        path = QPainterPath(); path.moveTo(8, 11); path.cubicTo(14, 5, 25, 7, 23, 17); path.cubicTo(22, 22, 17, 23, 14, 23)
        p.drawPath(path)
        p.setPen(Qt.NoPen); p.setBrush(FG)
        p.drawPolygon(QPolygonF([QPointF(3, 12), QPointF(11, 6), QPointF(11, 15)]))
        p.restore()
    elif name == "rotate":
        p.drawArc(QRectF(5, 5, 18, 18), 30 * 16, 290 * 16)
        p.setPen(Qt.NoPen); p.setBrush(FG)
        p.drawPolygon(QPolygonF([QPointF(24, 4), QPointF(24, 12), QPointF(16.5, 9)]))
    elif name == "flip":
        p.setPen(QPen(FG, 1.4, Qt.DashLine)); p.drawLine(QPointF(14, 3), QPointF(14, 25))
        p.setPen(Qt.NoPen); p.setBrush(CU); p.drawPolygon(QPolygonF([QPointF(11, 6), QPointF(11, 22), QPointF(3, 22)]))
        p.setBrush(QColor(52, 110, 220)); p.drawPolygon(QPolygonF([QPointF(17, 6), QPointF(17, 22), QPointF(25, 22)]))
    elif name == "delete":
        p.drawLine(QPointF(5, 8), QPointF(23, 8)); p.drawLine(QPointF(11, 8), QPointF(12, 4)); p.drawLine(QPointF(12, 4), QPointF(16, 4))
        p.drawLine(QPointF(16, 4), QPointF(17, 8))
        path = QPainterPath(); path.moveTo(7, 8); path.lineTo(8.5, 25); path.lineTo(19.5, 25); path.lineTo(21, 8)
        p.drawPath(path); p.drawLine(QPointF(12, 12), QPointF(12, 21)); p.drawLine(QPointF(16, 12), QPointF(16, 21))
    elif name == "fit":
        for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            cx, cy = 14 + sx * 9, 14 + sy * 9
            p.drawLine(QPointF(cx, cy), QPointF(cx - sx * 6, cy)); p.drawLine(QPointF(cx, cy), QPointF(cx, cy - sy * 6))
        p.drawRect(QRectF(10, 10, 8, 8))
    elif name == "gerber":
        for i, c in enumerate((QColor(52, 110, 220), GREEN, CU)):
            y = 18 - i * 5
            poly = QPolygonF([QPointF(14, y - 5), QPointF(25, y), QPointF(14, y + 5), QPointF(3, y)])
            p.setPen(_pen(QColor("#1d2026"), 1.0)); p.setBrush(c); p.drawPolygon(poly)
    elif name == "camera":
        p.drawRoundedRect(QRectF(3, 8, 22, 15), 3, 3); p.drawRect(QRectF(9, 5, 8, 3)); p.drawEllipse(QPointF(14, 15.5), 4.5, 4.5)
    elif name == "library":
        for i, c in enumerate((CU, GOLD, ACC)):
            p.setBrush(c.darker(130)); p.setPen(_pen(c, 1.4)); p.drawRoundedRect(QRectF(4 + i * 7, 5, 5.5, 18), 1, 1)
    elif name == "grid":
        p.setPen(Qt.NoPen); p.setBrush(FG)
        for x in range(6, 26, 5):
            for y in range(6, 26, 5):
                p.drawEllipse(QPointF(x, y), 1.1, 1.1)
    elif name == "layers":
        for i, c in enumerate((QColor(52, 110, 220), CU)):
            y = 16 - i * 6
            poly = QPolygonF([QPointF(14, y - 6), QPointF(25, y), QPointF(14, y + 6), QPointF(3, y)])
            p.setPen(_pen(c.lighter(130), 1.4)); p.setBrush(QColor(c.red(), c.green(), c.blue(), 150)); p.drawPolygon(poly)
    elif name == "board":
        p.setBrush(QColor("#1f5c38")); p.setPen(_pen(GOLD, 1.6)); p.drawRoundedRect(QRectF(3, 6, 22, 16), 3, 3)
        p.setPen(Qt.NoPen); p.setBrush(GOLD)
        for x in (7, 21):
            for y in (10, 18):
                p.drawEllipse(QPointF(x, y), 1.5, 1.5)
    elif name == "pedal":  # stompbox: enclosure, two knobs, LED and footswitch
        p.setBrush(QColor("#e8862a")); p.setPen(_pen(FG, 1.4)); p.drawRoundedRect(QRectF(6, 3, 16, 22), 2.5, 2.5)
        p.setPen(Qt.NoPen); p.setBrush(QColor("#1d2026"))
        p.drawEllipse(QPointF(10.5, 8), 2.6, 2.6); p.drawEllipse(QPointF(17.5, 8), 2.6, 2.6)
        p.setBrush(QColor("#ff4a3d")); p.drawEllipse(QPointF(14, 14.5), 1.2, 1.2)
        p.setBrush(QColor("#d9dde5")); p.drawEllipse(QPointF(14, 20), 2.8, 2.8)
    elif name == "drill":  # drill template: box outline with crosshair holes
        p.setPen(_pen(FG, 1.4)); p.drawRect(QRectF(5, 5, 18, 18))
        p.setPen(_pen(ACC, 1.4))
        for cx, cy, r in ((10, 10, 2.4), (18, 10, 2.4), (14, 18, 3.2)):
            p.drawEllipse(QPointF(cx, cy), r, r)
            p.drawLine(QPointF(cx - r - 1.5, cy), QPointF(cx + r + 1.5, cy))
            p.drawLine(QPointF(cx, cy - r - 1.5), QPointF(cx, cy + r + 1.5))
    elif name == "parts":  # DIP chip: what the component suppliers sell
        p.setPen(_pen(FG, 1.6))
        for y in (9, 14, 19):
            p.drawLine(QPointF(4, y), QPointF(8, y)); p.drawLine(QPointF(20, y), QPointF(24, y))
        p.setBrush(QColor("#2c313b")); p.drawRoundedRect(QRectF(8, 5, 12, 18), 2, 2)
        p.setPen(Qt.NoPen); p.setBrush(ACC); p.drawEllipse(QPointF(11.5, 8.5), 1.3, 1.3)
    elif name == "simulate":  # run: play triangle with a lit LED
        p.setPen(Qt.NoPen); p.setBrush(GREEN)
        p.drawPolygon(QPolygonF([QPointF(7, 5), QPointF(22, 14), QPointF(7, 23)]))
        p.setBrush(QColor(255, 210, 60, 230)); p.drawEllipse(QPointF(22, 22), 3.2, 3.2)
    elif name == "stop":
        p.setPen(Qt.NoPen); p.setBrush(CU); p.drawRoundedRect(QRectF(7, 7, 14, 14), 2, 2)
    elif name == "scope":  # oscilloscope: screen with a square wave
        p.setBrush(QColor("#13161b")); p.drawRoundedRect(QRectF(3, 5, 22, 18), 3, 3)
        p.setPen(_pen(GOLD, 1.6))
        p.drawPolyline(QPolygonF([QPointF(6, 18), QPointF(10, 18), QPointF(10, 10), QPointF(15, 10),
                                  QPointF(15, 18), QPointF(20, 18), QPointF(20, 10), QPointF(23, 10)]))
    elif name == "amp":  # vacuum tube: glass bulb with a glowing heater on a socket
        path = QPainterPath()
        path.moveTo(9, 22); path.lineTo(9, 10); path.arcTo(QRectF(9, 3, 10, 10), 180, -180); path.lineTo(19, 22)
        p.setBrush(QColor(200, 220, 235, 70)); p.setPen(_pen(FG, 1.4)); p.drawPath(path)
        p.setPen(Qt.NoPen); p.setBrush(QColor("#5b6068")); p.drawRect(QRectF(11.5, 9, 5, 9))
        p.setBrush(QColor("#ff8a2a")); p.drawEllipse(QPointF(14, 19.5), 1.6, 1.2)
        p.setBrush(QColor("#2c313b")); p.drawRoundedRect(QRectF(7, 22, 14, 3.5), 1.2, 1.2)
    else:
        p.drawEllipse(QPointF(14, 14), 8, 8)


@lru_cache(maxsize=None)
def icon(name: str) -> QIcon:
    ic = QIcon()
    for scale in (1, 2):
        pm = QPixmap(28 * scale, 28 * scale)
        pm.setDevicePixelRatio(scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        _draw(name, p)
        p.end()
        ic.addPixmap(pm)
    return ic


def app_icon() -> QIcon:
    ic = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        s = size / 64.0
        p.scale(s, s)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1b6b3f"))
        p.drawRoundedRect(QRectF(4, 4, 56, 56), 12, 12)
        p.setBrush(QColor("#111418"))
        p.drawRoundedRect(QRectF(20, 20, 24, 24), 3, 3)
        p.setPen(QPen(QColor("#e2b34a"), 3.2, Qt.SolidLine, Qt.RoundCap))
        for i in range(4):
            v = 24 + i * 5.3
            p.drawLine(QPointF(v, 20), QPointF(v, 13)); p.drawLine(QPointF(v, 44), QPointF(v, 51))
            p.drawLine(QPointF(20, v), QPointF(13, v)); p.drawLine(QPointF(44, v), QPointF(51, v))
        p.setPen(QPen(QColor("#4c9aff"), 2.6))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(32, 32), 5.5, 5.5)
        p.end()
        ic.addPixmap(pm)
    return ic
