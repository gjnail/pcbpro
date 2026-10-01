"""Oscilloscope, operating-point table and Bode plot for the simulation."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ..sim.units import fmt_eng

TRACE_COLORS = ["#ffd21f", "#2fd4ff", "#ff5fa2", "#7dff6a", "#ff9a3c", "#b18cff", "#f4f6ff", "#ff4b4b"]
GRID = QColor(52, 58, 70)
GRID_MAJOR = QColor(74, 82, 98)
BG = QColor(14, 16, 20)
TIMEBASES = [("1 ms", 1e-3), ("2 ms", 2e-3), ("5 ms", 5e-3), ("10 ms", 1e-2), ("20 ms", 2e-2), ("50 ms", 5e-2),
             ("100 ms", 0.1), ("200 ms", 0.2), ("500 ms", 0.5), ("1 s", 1.0), ("2 s", 2.0), ("5 s", 5.0),
             ("10 s", 10.0)]


def _nice(v: float) -> float:
    if v <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 5, 10):
        if m * e >= v:
            return m * e
    return 10 * e


def decimate(t: np.ndarray, v: np.ndarray, t0: float, t1: float, px: int):
    """Min/max per pixel column so fast edges (PWM, clocks) stay visible."""
    if len(t) == 0 or px <= 0:
        return None
    col = ((t - t0) / max(t1 - t0, 1e-15) * px).astype(np.int64)
    m = (col >= 0) & (col < px)
    if not m.any():
        return None
    col, vv = col[m], v[m]
    starts = np.flatnonzero(np.r_[True, np.diff(col) != 0])
    cols = col[starts]
    mins = np.minimum.reduceat(vv, starts)
    maxs = np.maximum.reduceat(vv, starts)
    return cols, mins, maxs


def frequency(t: np.ndarray, v: np.ndarray) -> float | None:
    if len(v) < 8:
        return None
    lo, hi = float(v.min()), float(v.max())
    if hi - lo < 1e-3:
        return None
    mid = (lo + hi) / 2
    above = v > mid
    rises = np.flatnonzero(~above[:-1] & above[1:])
    if len(rises) < 2:
        return None
    tr = t[rises]
    return float((len(tr) - 1) / (tr[-1] - tr[0])) if tr[-1] > tr[0] else None


class ScopeWidget(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.sim = controller
        self.window = 0.1
        self.trigger = "auto"
        self.frozen = False
        self.cursor_x = None
        self._frame = None
        self.setMinimumHeight(170)
        self.setMouseTracking(True)
        controller.updated.connect(self._refresh)

    def _refresh(self):
        if not self.frozen and self.isVisible():
            self.update()

    def mouseMoveEvent(self, ev):
        self.cursor_x = ev.position().x()
        self.update()

    def leaveEvent(self, ev):
        self.cursor_x = None
        self.update()

    def _window_data(self):
        buf = self.sim.scope
        t, v = buf.data(buf.t_last - self.window * 3.0)
        if len(t) == 0:
            return None
        t1 = float(t[-1])
        t0 = t1 - self.window
        if self.trigger in ("rising", "falling") and v.shape[1] > 0:
            tr = v[:, 0]
            lo, hi = float(tr.min()), float(tr.max())
            if hi - lo > 1e-3:
                mid = (lo + hi) / 2
                above = tr > mid
                edges = np.flatnonzero(~above[:-1] & above[1:]) if self.trigger == "rising" else \
                    np.flatnonzero(above[:-1] & ~above[1:])
                ok = edges[t[edges] <= t1 - self.window * 0.9]
                if len(ok):
                    t0 = float(t[ok[-1]]) - self.window * 0.1
                    t1 = t0 + self.window
        return t, v, t0, t1

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), BG)
        f = QFont("Segoe UI")
        f.setPixelSize(11)
        p.setFont(f)
        fm = QFontMetricsF(f)
        left, top, right, bottom = 54, 8, 10, 34
        plot = QRectF(left, top, max(10, self.width() - left - right), max(10, self.height() - top - bottom))
        nets = self.sim.scope.nets
        data = self._window_data() if nets else None
        # vertical range over all traces
        vmin, vmax = 0.0, max(self.sim.vmax(), 1.0)
        if data is not None:
            t, v, t0, t1 = data
            m = (t >= t0) & (t <= t1)
            if m.any():
                vmin = min(vmin, float(v[m].min()))
                vmax = max(vmax, float(v[m].max()))
        span = vmax - vmin
        vdiv = _nice(span / 8.0)
        vlo = math.floor(vmin / vdiv) * vdiv
        vhi = vlo + vdiv * max(8, math.ceil((vmax - vlo) / vdiv))
        ndiv = int(round((vhi - vlo) / vdiv))
        # grid
        for i in range(ndiv + 1):
            y = plot.bottom() - plot.height() * i / ndiv
            p.setPen(QPen(GRID_MAJOR if i in (0, ndiv) else GRID, 1, Qt.DotLine if 0 < i < ndiv else Qt.SolidLine))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QColor(140, 148, 162))
            lab = fmt_eng(vlo + i * vdiv, "V", 3)
            p.drawText(QRectF(0, y - 8, left - 6, 16), Qt.AlignRight | Qt.AlignVCenter, lab)
        for i in range(11):
            x = plot.left() + plot.width() * i / 10
            p.setPen(QPen(GRID if 0 < i < 10 else GRID_MAJOR, 1, Qt.DotLine if 0 < i < 10 else Qt.SolidLine))
            p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
        p.setPen(QColor(140, 148, 162))
        p.drawText(QRectF(plot.left(), plot.bottom() + 2, plot.width(), 14), Qt.AlignLeft,
                   f"{fmt_eng(self.window / 10, 's')}/div")
        if not nets:
            p.setPen(QColor(150, 156, 168))
            p.drawText(plot, Qt.AlignCenter, "Double-click a net while the simulation runs, or add one above, "
                                             "to probe it")
            return
        if data is None:
            p.setPen(QColor(150, 156, 168))
            p.drawText(plot, Qt.AlignCenter, "Press Run to start the simulation")
            self._legend(p, fm, plot, nets, None)
            return
        t, v, t0, t1 = data
        p.save()
        p.setClipRect(plot)

        def ymap(val):
            return plot.bottom() - (val - vlo) / (vhi - vlo) * plot.height()
        px = int(plot.width())
        for j in range(v.shape[1]):
            col = QColor(TRACE_COLORS[j % len(TRACE_COLORS)])
            dec = decimate(t, v[:, j], t0, t1, px)
            if dec is None:
                continue
            cols, mins, maxs = dec
            path = QPainterPath()
            first = True
            for c, lo, hi in zip(cols.tolist(), mins.tolist(), maxs.tolist()):
                x = plot.left() + c
                if first:
                    path.moveTo(x, ymap(lo))
                    first = False
                else:
                    path.lineTo(x, ymap(lo))
                if hi != lo:
                    path.lineTo(x, ymap(hi))
            p.setPen(QPen(col, 1.6))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        p.restore()
        self._frame = (plot, t0, t1)
        self._legend(p, fm, plot, nets, (t, v, t0, t1))
        if self.cursor_x is not None and plot.left() <= self.cursor_x <= plot.right():
            tc = t0 + (self.cursor_x - plot.left()) / plot.width() * (t1 - t0)
            p.setPen(QPen(QColor(255, 255, 255, 120), 1, Qt.DashLine))
            p.drawLine(QPointF(self.cursor_x, plot.top()), QPointF(self.cursor_x, plot.bottom()))
            k = min(max(int(np.searchsorted(t, tc)), 0), len(t) - 1)
            parts = [f"t = {fmt_eng(tc - t0, 's')}"] + [f"{n}: {fmt_eng(float(v[k, j]), 'V')}"
                                                        for j, n in enumerate(nets[:v.shape[1]])]
            text = "   ".join(parts)
            w = fm.horizontalAdvance(text) + 12
            bx = min(self.cursor_x + 8, self.width() - w - 4)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(28, 31, 38, 230))
            p.drawRoundedRect(QRectF(bx, plot.top() + 4, w, 18), 4, 4)
            p.setPen(QColor(230, 233, 240))
            p.drawText(QRectF(bx + 6, plot.top() + 4, w, 18), Qt.AlignVCenter, text)

    def _legend(self, p, fm, plot, nets, data):
        x = plot.left() + 70
        y = plot.bottom() + 18
        for j, n in enumerate(nets):
            col = QColor(TRACE_COLORS[j % len(TRACE_COLORS)])
            text = n
            if data is not None and j < data[1].shape[1]:
                t, v, t0, t1 = data
                m = (t >= t0) & (t <= t1)
                if m.any():
                    vv = v[m, j]
                    fr = frequency(t[m], vv)
                    text += f"  {fmt_eng(float(vv[-1]), 'V')}  ({fmt_eng(float(vv.min()), 'V')} … " \
                            f"{fmt_eng(float(vv.max()), 'V')})" + (f"  {fmt_eng(fr, 'Hz')}" if fr else "")
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(x, y - 8, 10, 10), 2, 2)
            p.setPen(QColor(210, 214, 222))
            p.drawText(QPointF(x + 14, y + 1), text)
            x += fm.horizontalAdvance(text) + 34
            if x > self.width() - 80:
                break


class BodePlot(QWidget):
    """Magnitude (dB) and phase against log frequency."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.freqs = np.zeros(0)
        self.curves: list[tuple[str, np.ndarray, str]] = []  # label, complex response, colour
        self.setMinimumHeight(200)

    def set_data(self, freqs, curves):
        self.freqs = np.asarray(freqs)
        self.curves = curves
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), BG)
        f = QFont("Segoe UI")
        f.setPixelSize(11)
        p.setFont(f)
        left, top, right, bottom = 48, 10, 12, 26
        plot = QRectF(left, top, max(10, self.width() - left - right), max(10, self.height() - top - bottom))
        if not len(self.freqs) or not self.curves:
            p.setPen(QColor(150, 156, 168))
            p.drawText(plot, Qt.AlignCenter, "No response yet")
            return
        f0, f1 = math.log10(self.freqs[0]), math.log10(self.freqs[-1])
        mags = [20 * np.log10(np.abs(h) + 1e-12) for _, h, _ in self.curves]
        top_db = math.ceil(max(float(m.max()) for m in mags) / 10) * 10 + 5
        bot_db = max(top_db - 80, math.floor(min(float(m.min()) for m in mags) / 10) * 10)
        for d in range(int(bot_db), int(top_db) + 1, 10):
            y = plot.bottom() - (d - bot_db) / (top_db - bot_db) * plot.height()
            p.setPen(QPen(GRID, 1, Qt.DotLine))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QColor(140, 148, 162))
            p.drawText(QRectF(0, y - 8, left - 6, 16), Qt.AlignRight | Qt.AlignVCenter, f"{d} dB")
        for dec in range(int(math.floor(f0)), int(math.ceil(f1)) + 1):
            for m in (1, 2, 5):
                fx = m * 10 ** dec
                if not (10 ** f0 <= fx <= 10 ** f1):
                    continue
                x = plot.left() + (math.log10(fx) - f0) / (f1 - f0) * plot.width()
                p.setPen(QPen(GRID_MAJOR if m == 1 else GRID, 1, Qt.DotLine))
                p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
                p.setPen(QColor(140, 148, 162))
                p.drawText(QPointF(x - 12, plot.bottom() + 14), fmt_eng(fx, "Hz", 2).replace(" ", ""))
        for (label, h, col), mag in zip(self.curves, mags):
            path = QPainterPath()
            for i, (fr, db) in enumerate(zip(self.freqs.tolist(), mag.tolist())):
                x = plot.left() + (math.log10(fr) - f0) / (f1 - f0) * plot.width()
                y = plot.bottom() - (min(max(db, bot_db), top_db) - bot_db) / (top_db - bot_db) * plot.height()
                path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
            p.setPen(QPen(QColor(col), 2))
            p.drawPath(path)
        x = plot.left() + 8
        for label, h, col in self.curves:
            p.setPen(QColor(col))
            p.drawText(QPointF(x, plot.top() + 14), label)
            x += QFontMetricsF(f).horizontalAdvance(label) + 20


class OpTable(QTableWidget):
    """Net voltages and per-part current / power."""

    def __init__(self, controller, parent=None):
        super().__init__(0, 4, parent)
        self.sim = controller
        self.setHorizontalHeaderLabels(["Item", "Voltage / model", "Current", "Power"])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    def refresh(self):
        if not self.isVisible():
            return
        sim = self.sim
        ck = sim.ck
        if ck is None or not sim.running:
            if self.rowCount():
                self.setRowCount(0)
            return
        rows = []
        for net in sorted(ck.net_node, key=lambda s: s.lower()):
            v = sim.net_voltage(net)
            rows.append((f"net {net}", fmt_eng(v, "V") if v is not None else "—", "", ""))
        power = (sim.snap or {}).get("power") or {}
        for uid, info in ck.parts.items():
            if info.status != "simulated":
                continue
            p = power.get(uid)
            rows.append((info.ref, info.res.model, "", fmt_eng(abs(p), "W") if p is not None else ""))
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                it = self.item(r, c)
                if it is None:
                    it = QTableWidgetItem()
                    self.setItem(r, c, it)
                if it.text() != text:
                    it.setText(text)


class ScopePanel(QWidget):
    """Bottom dock: probes toolbar + scope, and the operating-point table."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.sim = controller
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 6)
        bar = QHBoxLayout()
        self.add_combo = QComboBox()
        self.add_combo.setMinimumWidth(140)
        self.add_combo.setToolTip("Add a probe")
        self.add_combo.activated.connect(self._add)
        bar.addWidget(QLabel("Probe"))
        bar.addWidget(self.add_combo)
        self.clear_btn = QPushButton("Clear probes")
        self.clear_btn.clicked.connect(lambda: self.sim.set_probes([]))
        bar.addWidget(self.clear_btn)
        bar.addSpacing(12)
        bar.addWidget(QLabel("Time span"))
        self.tb = QComboBox()
        for text, v in TIMEBASES:
            self.tb.addItem(text, v)
        self.tb.setCurrentIndex(6)
        bar.addWidget(self.tb)
        bar.addWidget(QLabel("Trigger"))
        self.trig = QComboBox()
        self.trig.addItems(["auto", "rising", "falling"])
        bar.addWidget(self.trig)
        self.freeze = QCheckBox("Hold")
        bar.addWidget(self.freeze)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.tabs = QTabWidget()
        self.scope = ScopeWidget(controller)
        self.op = OpTable(controller)
        self.tabs.addTab(self.scope, "Oscilloscope")
        self.tabs.addTab(self.op, "Operating point")
        lay.addWidget(self.tabs, 1)
        self.tb.currentIndexChanged.connect(lambda i: setattr(self.scope, "window", self.tb.itemData(i)) or
                                            self.scope.update())
        self.scope.window = self.tb.currentData()
        self.trig.currentTextChanged.connect(lambda t: setattr(self.scope, "trigger", t))
        self.freeze.toggled.connect(lambda on: setattr(self.scope, "frozen", on))
        controller.started.connect(self._fill_nets)
        self._fill_nets()

    def _fill_nets(self):
        self.add_combo.blockSignals(True)
        self.add_combo.clear()
        self.add_combo.addItem("add net…")
        for n in self.sim.doc.project.nets():
            self.add_combo.addItem(n)
        self.add_combo.blockSignals(False)

    def _add(self, i):
        if i <= 0:
            return
        net = self.add_combo.itemText(i)
        if net not in self.sim.probes:
            self.sim.set_probes(self.sim.probes + [net])
        self.add_combo.setCurrentIndex(0)

    def showEvent(self, ev):
        super().showEvent(ev)
        self._fill_nets()
