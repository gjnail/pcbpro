"""Photo-realistic board surface textures (solder mask, copper, finish, silkscreen, contact shadows).

RGB carries the colour, alpha carries the specular / metalness strength used by the 3D shader.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

from ..model.artwork import mask_openings, silkscreen
from ..model.board import Project
from ..model.copper import pad_geom
from .canvas import geom_to_path

MASK_RGB = {
    "Green": ((24, 96, 52), (58, 146, 74)),
    "Red": ((150, 26, 26), (196, 64, 52)),
    "Blue": ((22, 54, 128), (50, 100, 178)),
    "Black": ((20, 20, 22), (46, 46, 50)),
    "White": ((226, 226, 222), (244, 244, 240)),
    "Purple": ((74, 36, 112), (110, 70, 152)),
    "Yellow": ((212, 176, 22), (232, 202, 64)),
}
SILK_RGB = {"White": (242, 242, 238), "Black": (22, 22, 22)}
FINISH_RGB = {
    "HASL (lead-free)": (206, 208, 212),
    "HASL": (200, 202, 206),
    "ENIG": (226, 180, 84),
    "OSP": (206, 128, 84),
}
FR4_RGB = (190, 170, 112)
EDGE_RGB = (176, 160, 108)

SPEC_MASK, SPEC_SILK, SPEC_FR4, SPEC_METAL = 110, 18, 25, 245


def _copper_path(project: Project, layer: str) -> tuple[QPainterPath, list]:
    """Pads, vias and zones as one fill path; tracks returned separately (drawn as strokes)."""
    path = QPainterPath()
    path.setFillRule(Qt.WindingFill)
    for c in project.components:
        for pad in c.footprint.pads:
            if layer in c.pad_copper_layers(pad, project.copper_layers):
                path.addPath(geom_to_path(pad_geom(c, pad)))
    for v in project.vias:
        path.addEllipse(QPointF(v.x, v.y), v.diameter / 2, v.diameter / 2)
    for z in project.zones:
        if z.layer == layer and z.uid in project.zone_fills:
            path.addPath(geom_to_path(project.zone_fills[z.uid]))
    tracks = [t for t in project.tracks if t.layer == layer]
    return path, tracks


def _draw_copper(p: QPainter, path: QPainterPath, tracks, color: QColor) -> None:
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawPath(path)
    pen = QPen(color, 0.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    for t in tracks:
        pen.setWidthF(t.width)
        p.setPen(pen)
        p.drawLine(QPointF(t.x1, t.y1), QPointF(t.x2, t.y2))


def _shadows(p: QPainter, project: Project, side: str) -> None:
    """Soft contact shadows under component bodies (cheap ambient occlusion)."""
    p.setPen(Qt.NoPen)
    for c in project.components:
        if c.side != side or c.footprint.model.get("type", "none") == "none":
            continue
        x0, y0, x1, y1 = c.footprint.courtyard
        m = 0.25
        p.save()
        p.translate(c.x, c.y)
        p.rotate(-c.rotation)
        if c.mirror:
            p.scale(-1, 1)
        w, h = x1 - x0 - 2 * m, y1 - y0 - 2 * m
        steps = 6
        for i in range(steps):
            grow = 0.12 * (steps - i)
            p.setBrush(QColor(0, 0, 0, 16))
            r = QRectF(x0 + m - grow, y0 + m - grow, w + 2 * grow, h + 2 * grow)
            p.drawRoundedRect(r, grow + 0.2, grow + 0.2)
        p.restore()


def board_textures(project: Project, max_px: int = 4096, px_per_mm: float = 28.0):
    """Render (top, bottom) RGBA textures as uint8 numpy arrays of shape (H, W, 4)."""
    x0, y0, x1, y1 = project.board.bounds()
    bw, bh = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
    ppm = min(px_per_mm, max_px / max(bw, bh))
    W, H = max(8, int(bw * ppm)), max(8, int(bh * ppm))
    b = project.board
    mask_rgb, mask_cu_rgb = MASK_RGB.get(b.mask_color, MASK_RGB["Green"])
    silk_rgb = SILK_RGB.get(b.silk_color, SILK_RGB["White"])
    fin_rgb = FINISH_RGB.get(b.finish, FINISH_RGB["HASL (lead-free)"])
    board_path = QPainterPath()
    board_path.setFillRule(Qt.OddEvenFill)
    board_path.addPath(geom_to_path(b.polygon()))

    out = []
    for side, layer in (("top", "F.Cu"), ("bottom", "B.Cu")):
        color = QImage(W, H, QImage.Format_RGB888)
        color.fill(QColor(*mask_rgb))
        spec = QImage(W, H, QImage.Format_Grayscale8)
        spec.fill(SPEC_MASK)
        cu_path, tracks = _copper_path(project, layer)
        opening = geom_to_path(mask_openings(project, side))
        silk = geom_to_path(silkscreen(project, side))
        for img, is_spec in ((color, False), (spec, True)):
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.scale(ppm, ppm)
            p.translate(-x0, -y0)
            # copper under the mask shows through as a lighter tint
            if not is_spec:
                _draw_copper(p, cu_path, tracks, QColor(*mask_cu_rgb))
            # mask openings expose bare laminate...
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(*FR4_RGB) if not is_spec else QColor(SPEC_FR4, SPEC_FR4, SPEC_FR4))
            p.drawPath(opening)
            # ...and plated copper wherever copper sits inside an opening
            p.save()
            p.setClipPath(opening)
            _draw_copper(p, cu_path, tracks, QColor(*fin_rgb) if not is_spec else QColor(SPEC_METAL, SPEC_METAL, SPEC_METAL))
            p.restore()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(*silk_rgb) if not is_spec else QColor(SPEC_SILK, SPEC_SILK, SPEC_SILK))
            p.drawPath(silk)
            if not is_spec:
                _shadows(p, project, side)
            p.end()
        rgb = _qimage_array(color, 3)
        a = _qimage_array(spec, 1)
        rgba = np.concatenate([rgb, a], axis=2)
        out.append(np.ascontiguousarray(rgba))
    return out[0], out[1]


def _qimage_array(img: QImage, channels: int) -> np.ndarray:
    bpl = img.bytesPerLine()
    arr = np.frombuffer(img.constBits(), dtype=np.uint8, count=bpl * img.height()).reshape(img.height(), bpl)
    return arr[:, : img.width() * channels].reshape(img.height(), img.width(), channels).copy()
