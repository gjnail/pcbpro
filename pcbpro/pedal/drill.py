"""Enclosure drill templates: the unfolded box drawing (1:1 PDF / on screen) and Tayda coordinate exports."""
from __future__ import annotations

import csv
import datetime as _dt
import io
from pathlib import Path

from PySide6.QtCore import QMarginsF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPageLayout, QPageSize, QPainter, QPainterPath, QPdfWriter, QPen, QPolygonF

from ..model.board import Project
from ..model.geometry import iter_polygons, rounded_rect_points
from .enclosure import (FACE_NAMES, FACES, Enclosure, PanelHole, all_holes, export_diameter, get_enclosure)

GAP = 4.0  # mm between face A and the unfolded sides


# --------------------------------------------------------------------------- geometry of the unfolded drawing

def side_centres(enc: Enclosure) -> dict[str, tuple[float, float]]:
    """Centre of every side in drawing coordinates (mm, Y down, face A centred on the origin)."""
    W, H = enc.face_size
    d = enc.spec.depth
    return {"A": (0.0, 0.0), "B": (0.0, -(H / 2 + GAP + d / 2)), "D": (0.0, H / 2 + GAP + d / 2),
            "C": (-(W / 2 + GAP + d / 2), 0.0), "E": (W / 2 + GAP + d / 2, 0.0)}


def drawing_bounds(enc: Enclosure) -> QRectF:
    W, H = enc.face_size
    d = enc.spec.depth
    return QRectF(-(W / 2 + GAP + d), -(H / 2 + GAP + d), W + 2 * (GAP + d), H + 2 * (GAP + d))


def to_drawing(enc: Enclosure, face: str, x: float, y: float) -> QPointF:
    cx, cy = side_centres(enc)[face]
    return QPointF(cx + x, cy - y)


def from_drawing(enc: Enclosure, pt: QPointF) -> tuple[str, float, float] | None:
    """Side and Tayda coordinates under a drawing point (None outside the box)."""
    for face in FACES:
        w, h = enc.side_size(face)
        cx, cy = side_centres(enc)[face]
        if abs(pt.x() - cx) <= w / 2 and abs(pt.y() - cy) <= h / 2:
            return face, pt.x() - cx, cy - pt.y()
    return None


def side_outline(enc: Enclosure, face: str) -> QPolygonF:
    """Outline of a side in drawing coordinates; the walls are drawn as trapezoids showing the casting draft."""
    cx, cy = side_centres(enc)[face]
    if face == "A":
        W, H = enc.face_size
        pts = rounded_rect_points(cx - W / 2, cy - H / 2, W, H, enc.spec.corner_r)
        return QPolygonF([QPointF(x, y) for x, y in pts])
    w, h = enc.side_size(face)
    dr = enc.spec.draft
    if face in ("B", "D"):
        fold_y = cy + h / 2 if face == "B" else cy - h / 2
        rim_y = cy - h / 2 if face == "B" else cy + h / 2
        pts = [(cx - w / 2, fold_y), (cx + w / 2, fold_y), (cx + w / 2 + dr, rim_y), (cx - w / 2 - dr, rim_y)]
    else:
        fold_x = cx + w / 2 if face == "C" else cx - w / 2
        rim_x = cx - w / 2 if face == "C" else cx + w / 2
        pts = [(fold_x, cy - h / 2), (fold_x, cy + h / 2), (rim_x, cy + h / 2 + dr), (rim_x, cy - h / 2 - dr)]
    return QPolygonF([QPointF(x, y) for x, y in pts])


# --------------------------------------------------------------------------- painting helpers

def _scale(p: QPainter) -> float:
    return abs(p.transform().m11()) or 1.0


def _pen(p: QPainter, color, width_mm: float, style=Qt.SolidLine, min_px: float = 1.0) -> QPen:
    pen = QPen(QColor(color), max(width_mm, min_px / _scale(p)), style, Qt.RoundCap, Qt.RoundJoin)
    return pen


def draw_text(p: QPainter, x: float, y: float, text: str, size_mm: float, color="#222", align=Qt.AlignCenter,
              bold: bool = False, min_px: int = 7) -> None:
    """Text of cap height ``size_mm`` at a drawing position, unaffected by the painter's scaling."""
    s = _scale(p)
    dev = p.transform().map(QPointF(x, y))
    font = QFont("Segoe UI")
    font.setPixelSize(max(min_px, int(round(size_mm * s * 1.4))))
    font.setBold(bold)
    p.save()
    p.resetTransform()
    p.setFont(font)
    p.setPen(QColor(color))
    w, h = 200000, font.pixelSize() * 1.6
    if align & Qt.AlignLeft:
        r = QRectF(dev.x(), dev.y() - h / 2, w, h)
    elif align & Qt.AlignRight:
        r = QRectF(dev.x() - w, dev.y() - h / 2, w, h)
    else:
        r = QRectF(dev.x() - w / 2, dev.y() - h / 2, w, h)
    p.drawText(r, (align & (Qt.AlignLeft | Qt.AlignRight | Qt.AlignHCenter)) | Qt.AlignVCenter, text)
    p.restore()


HOLE_COLORS = {"pot": "#1f5fbf", "pot9": "#1f5fbf", "footswitch": "#b3261e", "jack": "#1b7f4c", "dc": "#8a4fbf",
               "toggle": "#c77a12", "submini": "#c77a12", "rotary": "#c77a12"}


def hole_color(h: PanelHole) -> str:
    if h.kind.startswith(("led", "bezel")):
        return "#d18a00"
    return HOLE_COLORS.get(h.kind, "#333333")


def draw_unfolded(p: QPainter, project: Project, enc: Enclosure, holes: list[PanelHole] | None = None, *,
                  ink: str = "#1b1b1b", faint: str = "#9aa0a8", show_board: bool = True, show_hardware: bool = True,
                  show_coords: bool = True, selected: str | None = None, paper: str | None = None,
                  faces: tuple = FACES) -> None:
    """Draw the unfolded enclosure with all holes. The painter must already map 1 unit to 1 mm (Y down)."""
    holes = all_holes(project, enc) if holes is None else holes
    holes = [h for h in holes if h.face in faces]
    thin = 0.15
    p.setRenderHint(QPainter.Antialiasing, True)
    for face in faces:
        poly = side_outline(enc, face)
        p.setPen(_pen(p, ink, 0.3))
        p.setBrush(QColor(paper) if paper else Qt.NoBrush)
        p.drawPolygon(poly)
        cx, cy = side_centres(enc)[face]
        w, h = enc.side_size(face)
        # centre lines (Tayda measures from here)
        p.setPen(_pen(p, faint, thin, Qt.DashDotLine))
        p.drawLine(QPointF(cx - w / 2, cy), QPointF(cx + w / 2, cy))
        p.drawLine(QPointF(cx, cy - h / 2), QPointF(cx, cy + h / 2))
        # side letter and name: A goes in the empty corner outside the face, the walls get theirs near the rim
        if face == "A":
            draw_text(p, cx - w / 2 - 2.5, cy - h / 2 - 2.5, "A", 3.0, faint, Qt.AlignRight, True)
            draw_text(p, cx - w / 2 - 2.5, cy - h / 2 + 1.6, "Face", 1.3, faint, Qt.AlignRight)
            draw_text(p, cx - w / 2 - 2.5, cy - h / 2 + 3.8, "(outside)", 1.1, faint, Qt.AlignRight)
            continue
        lx, ly = {"B": (cx - w / 2 + 4, cy - h / 2 + 4), "D": (cx - w / 2 + 4, cy + h / 2 - 4),
                  "C": (cx - w / 2 + 4, cy - h / 2 + 5), "E": (cx + w / 2 - 4, cy - h / 2 + 5)}[face]
        draw_text(p, lx, ly, face, 3.0, faint, Qt.AlignCenter, True)
        rim = {"B": (lx + 3.5, ly), "D": (lx + 3.5, ly), "C": (cx - w / 2 + 2.5, cy + h / 2 - 4),
               "E": (cx + w / 2 - 2.5, cy + h / 2 - 4)}[face]
        align = Qt.AlignRight if face == "E" else Qt.AlignLeft
        draw_text(p, rim[0], rim[1], f"{FACE_NAMES[face]} · rim/lid edge", 1.2, faint, align)
    # board footprint seen through face A (helps sanity-check the mirroring)
    if show_board and "A" in faces and len(project.board.outline) >= 3:
        board = enc.geom_to_face(project.board.polygon())
        path = QPainterPath()
        for poly in iter_polygons(board):
            path.addPolygon(QPolygonF([QPointF(x, -y) for x, y in poly.exterior.coords]))
        p.setPen(_pen(p, "#4f8f68", thin, Qt.DashLine))
        tint = QColor("#2e7d4f")
        tint.setAlpha(26)
        p.setBrush(tint)
        p.drawPath(path)
        bb = path.boundingRect()
        draw_text(p, bb.center().x(), bb.bottom() - 2.0, "PCB (seen through the face)", 1.2, "#4f8f68")
    # holes
    for hl in holes:
        c = to_drawing(enc, hl.face, hl.x, hl.y)
        col = hole_color(hl)
        d = export_diameter(hl, enc)
        r = d / 2
        _, _, outer = hl.effective_body()
        if show_hardware and outer > d:
            p.setPen(_pen(p, col, thin, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, outer / 2, outer / 2)
        sel = selected is not None and hl.uid == selected
        p.setPen(_pen(p, col, 0.35 if not sel else 0.6))
        fill = QColor(col)
        fill.setAlpha(60 if sel else 28)
        p.setBrush(fill)
        p.drawEllipse(c, r, r)
        # centre-punch crosshair
        p.setPen(_pen(p, ink, thin))
        k = r + 1.8
        p.drawLine(QPointF(c.x() - k, c.y()), QPointF(c.x() + k, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - k), QPointF(c.x(), c.y() + k))
        if sel:
            p.setPen(_pen(p, "#ff9d00", 0.4))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, r + 1.2, r + 1.2)
        label = hl.label or hl.hardware.label
        ring = max(r, outer / 2 if show_hardware else 0.0)
        if hl.face in ("C", "E"):
            ty = c.y() + ring + 2.0
            draw_text(p, c.x(), ty, f"Ø{d:g}", 1.2, col)
            if show_coords:
                draw_text(p, c.x(), ty + 2.1, f"{_z(hl.x):+.1f}, {_z(hl.y):+.1f}", 1.0, ink)
        else:
            draw_text(p, c.x(), c.y() - ring - 1.6, label, 1.3, col)
            txt = f"Ø{d:g}" + (f"  ({_z(hl.x):+.1f}, {_z(hl.y):+.1f})" if show_coords else "")
            draw_text(p, c.x(), c.y() + ring + 1.7, txt, 1.1, ink)


def _z(v: float) -> float:
    """Avoid printing -0.0."""
    return 0.0 if abs(v) < 0.005 else v


# --------------------------------------------------------------------------- PDF

def _scale_bar(p: QPainter, x: float, y: float, length: int = 50) -> None:
    p.setPen(_pen(p, "#000", 0.25))
    p.drawLine(QPointF(x, y), QPointF(x + length, y))
    for i in range(length // 10 + 1):
        tick = 2.0 if i % 5 == 0 or i == length // 10 else 1.2
        p.drawLine(QPointF(x + i * 10, y), QPointF(x + i * 10, y - tick))
    text = (f"{length} mm - measure this to check the print is 100 % scale" if length >= 50
            else f"{length} mm (check scale)")
    draw_text(p, x + length / 2, y + 2.2, text, 1.4, "#000")
    p.drawLine(QPointF(x, y + 5.5), QPointF(x + 25.4, y + 5.5))
    p.drawLine(QPointF(x, y + 5.5), QPointF(x, y + 4.3))
    p.drawLine(QPointF(x + 25.4, y + 5.5), QPointF(x + 25.4, y + 4.3))
    draw_text(p, x + 12.7, y + 7.3, "1 inch", 1.4, "#000")


def hole_rows(project: Project, enc: Enclosure) -> list[dict]:
    rows = []
    for h in sorted(all_holes(project, enc), key=lambda h: (FACES.index(h.face), -h.y, h.x)):
        rows.append({"Side": h.face, "Diameter": export_diameter(h, enc), "X": _z(round(h.x, 2)),
                     "Y": _z(round(h.y, 2)),
                     "Label": h.label or h.hardware.label, "Part": h.hardware.label,
                     "Source": h.ref or "panel"})
    return rows


def export_pdf(project: Project, path: str | Path, page: str = "A4") -> Path:
    """1:1 drill template (page 1) plus the coordinate table (page 2)."""
    enc = get_enclosure(project)
    if enc is None:
        raise ValueError("The design has no enclosure")
    path = Path(path)
    writer = QPdfWriter(str(path))
    writer.setResolution(1200)
    writer.setTitle(f"{project.name} - {enc.spec.name} drill template")
    writer.setCreator("PCBPro")
    size = QPageSize(QPageSize.Letter if page.lower() == "letter" else QPageSize.A4)
    bounds = drawing_bounds(enc)
    pw, ph = size.size(QPageSize.Millimeter).width(), size.size(QPageSize.Millimeter).height()
    margin = 5.0
    landscape = bounds.width() > bounds.height()
    if landscape:
        pw, ph = ph, pw
    writer.setPageLayout(QPageLayout(size, QPageLayout.Landscape if landscape else QPageLayout.Portrait,
                                     QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter))
    p = QPainter(writer)
    k = writer.resolution() / 25.4
    p.scale(k, k)
    date = _dt.date.today().isoformat()
    fits = bounds.width() <= pw - 2 * margin and bounds.height() <= ph - 2 * margin
    roomy = bounds.height() + 2 * margin + 30 <= ph
    title = f"{project.name}  -  {enc.spec.name} drill template"
    allowance = (f"powder-coat allowance +{enc.paint_allowance:.1f} mm included" if enc.paint_allowance
                 else "bare aluminium hole sizes")
    info = (f"Rev {project.revision} · {date} · {'landscape' if enc.landscape else 'portrait'} · panel A seen from "
            f"OUTSIDE · {allowance}")
    howto = ("Print at 100 % (\"actual size\", no fit-to-page). Tape to the box, centre-punch the crosshairs, "
             "pilot drill, then step drill to size.")
    if fits:
        p.save()
        top = margin + (16 if roomy else 0)
        bottom = ph - margin - (14 if roomy else 0)
        p.translate(pw / 2 - bounds.center().x(), (top + bottom) / 2 - bounds.center().y())
        draw_unfolded(p, project, enc, show_board=False)
        p.restore()
        if roomy:
            draw_text(p, margin + 3, margin + 3, title, 3.0, "#000", Qt.AlignLeft, True)
            draw_text(p, margin + 3, margin + 8, info, 1.6, "#333", Qt.AlignLeft)
            draw_text(p, margin + 3, margin + 11.5, howto, 1.6, "#333", Qt.AlignLeft)
            _scale_bar(p, margin + 3, ph - margin - 10)
        else:  # compact title in the empty corner of the cross-shaped drawing
            draw_text(p, margin + 2, margin + 2, project.name, 2.2, "#000", Qt.AlignLeft, True)
            draw_text(p, margin + 2, margin + 6, enc.spec.name, 1.6, "#333", Qt.AlignLeft)
            draw_text(p, margin + 2, margin + 9, "Print at 100 %", 1.6, "#333", Qt.AlignLeft)
            _scale_bar(p, pw - margin - 32, ph - margin - 9, 30)
    else:  # too big for one sheet at 1:1: one side per page
        first = True
        used = {h.face for h in all_holes(project, enc)} | {"A"}
        for face in FACES:
            if face not in used:
                continue
            if not first:
                writer.newPage()
            first = False
            cx, cy = side_centres(enc)[face]
            p.save()
            p.translate(pw / 2 - cx, ph / 2 - cy)
            draw_unfolded(p, project, enc, show_board=False, faces=(face,))
            p.restore()
            draw_text(p, margin + 3, margin + 3, f"{title} - side {face}", 2.6, "#000", Qt.AlignLeft, True)
            draw_text(p, margin + 3, margin + 7.5, howto, 1.5, "#333", Qt.AlignLeft)
            _scale_bar(p, margin + 3, ph - margin - 10)
    # coordinates page
    writer.newPage()
    y = margin + 2
    draw_text(p, margin, y, f"{project.name} - hole coordinates ({enc.spec.name})", 3.0, "#000", Qt.AlignLeft, True)
    y += 6
    for line in ("Tayda convention: millimetres from the centre of each side, +X right, +Y up, every side viewed "
                 "from outside in the unfolded layout.",
                 "A = face, B = top side, C = left side, D = bottom side, E = right side (lid removed).",
                 f"Board side facing the panel: {enc.face_side} (the layout is mirrored left/right when this is "
                 "'bottom')."):
        draw_text(p, margin, y, line, 1.7, "#333", Qt.AlignLeft)
        y += 4.2
    y += 3
    cols = [("Side", 12), ("Ø mm", 16), ("X mm", 18), ("Y mm", 18), ("Label", 60), ("Hardware", 48), ("From", 22)]
    x = margin
    for name, w in cols:
        draw_text(p, x, y, name, 1.8, "#000", Qt.AlignLeft, True)
        x += w
    y += 2.5
    p.setPen(_pen(p, "#888", 0.2))
    p.drawLine(QPointF(margin, y), QPointF(pw - margin, y))
    y += 3
    for r in hole_rows(project, enc):
        x = margin
        for (name, w), val in zip(cols, (r["Side"], f"{r['Diameter']:g}", f"{r['X']:+.2f}", f"{r['Y']:+.2f}",
                                         r["Label"], r["Part"], r["Source"])):
            draw_text(p, x, y, str(val), 1.7, "#111", Qt.AlignLeft)
            x += w
        y += 4.2
        if y > ph - margin - 5:
            writer.newPage()
            y = margin + 4
    p.end()
    return path


# --------------------------------------------------------------------------- text exports

def tayda_text(project: Project) -> str:
    """Plain-text coordinates in the order Tayda's drill tool asks for them."""
    enc = get_enclosure(project)
    if enc is None:
        return ""
    lines = [f"{project.name} - {enc.spec.name} ({'landscape' if enc.landscape else 'portrait'})",
             "Tayda drill coordinates: mm from the centre of each side, +X right, +Y up, lid removed.", ""]
    rows = hole_rows(project, enc)
    for face in FACES:
        these = [r for r in rows if r["Side"] == face]
        if not these:
            continue
        lines.append(f"Side {face} - {FACE_NAMES[face]}")
        for r in these:
            lines.append(f"  X {r['X']:+7.2f}   Y {r['Y']:+7.2f}   Ø {r['Diameter']:5.2f}   {r['Label']}")
        lines.append("")
    return "\n".join(lines)


def tayda_csv(project: Project) -> str:
    enc = get_enclosure(project)
    buf = io.StringIO()
    wr = csv.DictWriter(buf, fieldnames=["Side", "Diameter", "X", "Y", "Label", "Part", "Source"], lineterminator="\n")
    wr.writeheader()
    if enc is not None:
        for r in hole_rows(project, enc):
            wr.writerow(r)
    return buf.getvalue()
