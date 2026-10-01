"""Run mode on the 2D canvas: copper tinted by voltage, glowing LEDs, smoke on overstressed parts, live readouts,
and the board's buttons, switches, pots and plugs operated with the mouse."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPen, QRadialGradient

from ..sim.units import fmt_eng
from .canvas import comp_transform, pad_qpath

STOPS = [(0.0, (46, 104, 255)), (0.33, (36, 210, 190)), (0.66, (240, 222, 60)), (1.0, (255, 64, 48))]


def volt_color(v: float, vmax: float, alpha: int = 150) -> QColor:
    if v is None:
        return QColor(120, 120, 130, alpha // 2)
    t = v / max(vmax, 1e-6)
    if t < 0:  # negative rails: purple
        k = min(-t, 1.0)
        return QColor(int(46 + (170 - 46) * k), int(104 - 60 * k), 255, alpha)
    t = min(t, 1.0)
    for (t0, c0), (t1, c1) in zip(STOPS, STOPS[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0)
            return QColor(*(int(a + (b - a) * f) for a, b in zip(c0, c1)), alpha)
    return QColor(*STOPS[-1][1], alpha)


def _hex(c: str, alpha: int = 255) -> QColor:
    q = QColor(c)
    q.setAlpha(alpha)
    return q


# 7-segment geometry in a unit digit box (x 0..1, y 0..1.6)
SEGMENTS = {"A": (0.15, 0.0, 0.85, 0.0), "B": (0.9, 0.05, 0.9, 0.75), "C": (0.9, 0.85, 0.9, 1.55),
            "D": (0.15, 1.6, 0.85, 1.6), "E": (0.1, 0.85, 0.1, 1.55), "F": (0.1, 0.05, 0.1, 0.75),
            "G": (0.15, 0.8, 0.85, 0.8)}


class SimTool:
    name = "sim"
    label = "Simulation"
    cursor = Qt.PointingHandCursor

    def __init__(self, canvas, controller):
        self.c = canvas
        self.sim = controller
        self.hover_text = ""
        self.hover_pos = None
        self._drag = None  # (control key, start y px, start value)
        self._pressed = None  # momentary control held down
        self._enc_timer = QTimer(canvas)
        self._enc_timer.setInterval(40)
        self._enc_timer.timeout.connect(self._enc_step)
        self._enc_queue: list[tuple[str, int]] = []
        controller.updated.connect(canvas.update)

    # ------------------------------------------------------------------ tool protocol
    @property
    def project(self):
        return self.c.doc.project

    def activate(self, **kwargs):
        self.reset()

    def deactivate(self):
        self.reset()

    def reset(self):
        self._release_momentary()
        self._drag = None
        self.hover_text = ""

    def hint(self) -> str:
        return ("Simulation running · click buttons and switches, drag or scroll pots, double-click a net to probe it "
                "· Esc stops")

    def key(self, ev) -> bool:
        if ev.key() == Qt.Key_Escape:
            self.sim.stop("")
            return True
        return False

    # ------------------------------------------------------------------ controls under the cursor
    def _controls_at(self, x, y):
        comp = self.c.component_at(x, y)
        if comp is None or self.sim.ck is None:
            return comp, []
        info = self.sim.ck.parts.get(comp.uid)
        return comp, (info.controls if info else [])

    def press(self, ev, x, y):
        comp, ctls = self._controls_at(x, y)
        if not ctls:
            return
        ctl = ctls[0]
        if ctl.kind == "momentary":
            self._pressed = ctl.key
            self.sim.set_control(ctl.key, 1)
        elif ctl.kind in ("toggle", "plug"):
            n = max(len(ctl.options), 2)
            self.sim.set_control(ctl.key, (int(self.sim.controls.get(ctl.key, ctl.value)) + 1) % n)
        elif ctl.kind == "pot":
            self._drag = (ctl.key, ev.position().y(), float(self.sim.controls.get(ctl.key, ctl.value)))
        elif ctl.kind == "encoder":
            self._rotate(ctl.key, -1 if ev.button() == Qt.RightButton else 1)
        elif ctl.kind == "temp":
            self._drag = (ctl.key, ev.position().y(), float(self.sim.controls.get(ctl.key, ctl.value)))
        self.c.update()

    def move(self, ev, x, y):
        if self._drag is not None:
            key, y0, v0 = self._drag
            ctl = self.sim.ck.control(key) if self.sim.ck else None
            dy = (y0 - ev.position().y())
            if ctl is not None and ctl.kind == "temp":
                v = min(max(v0 + dy * 0.5, ctl.lo), ctl.hi)
            else:
                v = min(max(v0 + dy / 160.0, 0.0), 1.0)
            self.sim.set_control(key, v)
            self.c.update()
            return
        self.hover_pos = ev.position()
        self.hover_text = self._describe(x, y)
        self.c.update()

    def release(self, ev, x, y):
        self._release_momentary()
        self._drag = None

    def double_click(self, ev, x, y):
        net = self._net_at(x, y)
        if net:
            self.sim.toggle_probe(net)

    def wheel(self, ev, x, y) -> bool:
        comp, ctls = self._controls_at(x, y)
        for ctl in ctls:
            step = 1 if ev.angleDelta().y() > 0 else -1
            if ctl.kind == "pot":
                v = float(self.sim.controls.get(ctl.key, ctl.value))
                self.sim.set_control(ctl.key, min(max(v + 0.04 * step, 0.0), 1.0))
                self.c.update()
                return True
            if ctl.kind == "encoder":
                self._rotate(ctl.key, step)
                return True
            if ctl.kind == "temp":
                v = float(self.sim.controls.get(ctl.key, ctl.value))
                self.sim.set_control(ctl.key, min(max(v + 2.0 * step, ctl.lo), ctl.hi))
                return True
        return False

    def _release_momentary(self):
        if self._pressed is not None:
            self.sim.set_control(self._pressed, 0)
            self._pressed = None

    def _rotate(self, key: str, steps: int):
        """One encoder detent = a full quadrature cycle, played out over a few frames so firmware can see it."""
        seq = [1, 2, 3, 0] if steps > 0 else [3, 2, 1, 0]
        for _ in range(abs(steps)):
            self._enc_queue += [(key, s) for s in seq]
        if not self._enc_timer.isActive():
            self._enc_timer.start()

    def _enc_step(self):
        if not self._enc_queue:
            self._enc_timer.stop()
            return
        key, s = self._enc_queue.pop(0)
        self.sim.set_control(key, s)

    # ------------------------------------------------------------------ readouts
    def _net_at(self, x, y):
        comp, pad = self.c.pad_at(x, y)
        if comp is not None and pad is not None:
            return comp.pad_nets.get(pad.number)
        t = self.c.track_at(x, y)
        if t is not None:
            return t.net
        v = self.c.via_at(x, y)
        if v is not None:
            return v.net
        return None

    def _describe(self, x, y) -> str:
        sim = self.sim
        if not sim.running or sim.ck is None:
            return ""
        comp, pad = self.c.pad_at(x, y)
        if comp is not None and pad is not None:
            v = sim.pad_voltage(comp, pad.number)
            net = comp.pad_nets.get(pad.number) or "unconnected"
            return f"{comp.ref}.{pad.number}  {net}   {fmt_eng(v, 'V') if v is not None else '—'}"
        for item in (self.c.via_at(x, y), self.c.track_at(x, y)):
            if item is not None:
                v = sim.item_voltage(item)
                return f"{item.net or 'no net'}   {fmt_eng(v, 'V') if v is not None else 'not connected'}"
        comp = self.c.component_at(x, y)
        if comp is not None:
            info = sim.ck.parts.get(comp.uid)
            if info is None:
                return comp.ref
            parts = [f"{comp.ref} {comp.value}", info.res.model]
            snap = sim.snap or {}
            p = (snap.get("power") or {}).get(comp.uid)
            if p is not None and info.status == "simulated":
                parts.append(f"{fmt_eng(abs(p), 'W')}")
            for uid, level, col, label in sim.led_states():
                if uid == comp.uid and info.res.kind == "led":
                    parts.append(f"brightness {level * 100:.0f} %")
            smoke = (snap.get("smoke") or {}).get(comp.uid)
            if smoke:
                parts.append(("⚠ " if smoke[0] == "warning" else "🔥 ") + smoke[1])
            if info.status != "simulated":
                parts.append(info.note or info.status)
            for ctl in info.controls:
                if ctl.kind == "pot":
                    parts.append(f"knob {float(sim.controls.get(ctl.key, ctl.value)) * 100:.0f} %")
            return "  ·  ".join(parts)
        return ""

    # ------------------------------------------------------------------ painting (world coordinates)
    def paint(self, p: QPainter):
        sim = self.sim
        if not sim.running or sim.ck is None:
            return
        proj = self.project
        vmax = sim.vmax()
        c = self.c
        # copper tint
        if c.visible.get("Zones", True):
            p.setPen(Qt.NoPen)
            for z in proj.zones:
                if not c.visible.get(z.layer, True):
                    continue
                path = c._zone_path(z)
                if path is None:
                    continue
                p.setBrush(volt_color(sim.item_voltage(z), vmax, 55))
                p.drawPath(path)
        pen = QPen(QColor(0, 0, 0), 0.2, Qt.SolidLine, Qt.RoundCap)
        for t in proj.tracks:
            if not c.visible.get(t.layer, True):
                continue
            pen.setColor(volt_color(sim.item_voltage(t), vmax, 190))
            pen.setWidthF(t.width * 0.8)
            p.setPen(pen)
            p.drawLine(QPointF(t.x1, t.y1), QPointF(t.x2, t.y2))
        p.setPen(Qt.NoPen)
        for v in proj.vias:
            p.setBrush(volt_color(sim.item_voltage(v), vmax, 200))
            p.drawEllipse(QPointF(v.x, v.y), v.diameter / 2 * 0.8, v.diameter / 2 * 0.8)
        for comp in proj.components:
            p.save()
            p.setTransform(comp_transform(comp), True)
            for pad in comp.footprint.pads:
                if pad.kind == "npth" or not pad.number:
                    continue
                v = sim.pad_voltage(comp, pad.number)
                if v is None:
                    continue
                p.save()
                p.translate(pad.x, pad.y)
                if pad.rotation:
                    p.rotate(-pad.rotation)
                p.scale(0.82, 0.82)
                p.setBrush(volt_color(v, vmax, 200))
                p.drawPath(pad_qpath(pad))
                p.restore()
            p.restore()
        self._paint_parts(p)

    def _paint_parts(self, p: QPainter):
        sim = self.sim
        proj = self.project
        snap = sim.snap or {}
        by_uid: dict[str, list] = {}
        for uid, level, col, label in sim.led_states():
            by_uid.setdefault(uid, []).append((level, col, label))
        for comp in proj.components:
            info = sim.ck.parts.get(comp.uid)
            if info is None:
                continue
            x0, y0, x1, y1 = comp.footprint.courtyard
            if info.status in ("unsupported", "error"):
                p.save()
                p.setTransform(comp_transform(comp), True)
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor(150, 150, 160, 90), Qt.BDiagPattern))
                p.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))
                p.restore()
            leds = by_uid.get(comp.uid)
            if leds:
                pos = info.res.params.get("led_pos")
                if info.res.params.get("segments"):
                    self._paint_segments(p, comp, info, leds)
                elif pos:  # LEDs at known spots on a module (Arduino L / ON)
                    for level, col, label in leds:
                        if label in pos and level > 0.01:
                            bx, by = comp.to_board(*pos[label])
                            self._glow(p, bx, by, 1.6 * (0.9 + 0.9 * level), level, QColor(col))
                else:
                    self._paint_glow(p, comp, leds)
            for ctl in info.controls:
                if ctl.kind == "pot":
                    self._paint_knob(p, comp, float(sim.controls.get(ctl.key, ctl.value)))
                elif ctl.kind in ("momentary", "toggle") and int(sim.controls.get(ctl.key, ctl.value)):
                    p.save()
                    p.setTransform(comp_transform(comp), True)
                    pen = QPen(QColor(120, 220, 255, 220), 2.0)
                    pen.setCosmetic(True)
                    p.setPen(pen)
                    p.setBrush(QColor(120, 220, 255, 50))
                    p.drawRoundedRect(QRectF(x0, y0, x1 - x0, y1 - y0), 0.4, 0.4)
                    p.restore()

    def _paint_glow(self, p: QPainter, comp, leds):
        level = max(l for l, _, _ in leds)
        if level <= 0.01:
            return
        # mix the colours of all lit dice (RGB LEDs)
        r = g = b = 0.0
        tot = 0.0
        for lv, col, _ in leds:
            q = QColor(col)
            r += q.red() * lv
            g += q.green() * lv
            b += q.blue() * lv
            tot += lv
        col = QColor(int(min(255, r / tot)), int(min(255, g / tot)), int(min(255, b / tot)))
        x0, y0, x1, y1 = comp.footprint.courtyard
        rad = max(x1 - x0, y1 - y0) * (0.9 + 0.9 * level)
        self._glow(p, comp.x, comp.y, rad, level, col)

    def _glow(self, p: QPainter, cx: float, cy: float, rad: float, level: float, col: QColor):
        grad = QRadialGradient(QPointF(cx, cy), rad)
        c0 = QColor(col)
        c0.setAlpha(int(230 * level))
        c1 = QColor(col)
        c1.setAlpha(int(90 * level))
        c2 = QColor(col)
        c2.setAlpha(0)
        grad.setColorAt(0.0, QColor(255, 255, 255, int(220 * level)))
        grad.setColorAt(0.15, c0)
        grad.setColorAt(0.45, c1)
        grad.setColorAt(1.0, c2)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(QPointF(cx, cy), rad, rad)

    def _paint_segments(self, p: QPainter, comp, info, leds):
        x0, y0, x1, y1 = comp.footprint.courtyard
        digits = info.res.params.get("digits", 1)
        p.save()
        p.setTransform(comp_transform(comp), True)
        w = (x1 - x0) / digits
        h = (y1 - y0)
        for level, col, label in leds:
            seg = label.rstrip("0123456789")
            idx = int(label[len(seg):] or 1) - 1
            q = QColor(col)
            q.setAlpha(int(40 + 215 * level))
            bx = x0 + w * idx + w * 0.22
            by = y0 + h * 0.12
            sw, sh = w * 0.56, h * 0.76 / 1.6
            pen = QPen(q if level > 0.02 else QColor(60, 30, 30, 120), max(w * 0.08, 0.3), Qt.SolidLine, Qt.RoundCap)
            p.setPen(pen)
            if seg in SEGMENTS:
                ax, ay, bx2, by2 = SEGMENTS[seg]
                p.drawLine(QPointF(bx + ax * sw, by + ay * sh), QPointF(bx + bx2 * sw, by + by2 * sh))
            elif seg == "DP":
                p.setPen(Qt.NoPen)
                p.setBrush(q if level > 0.02 else QColor(60, 30, 30, 120))
                p.drawEllipse(QPointF(bx + 1.1 * sw, by + 1.6 * sh), w * 0.05, w * 0.05)
        p.restore()

    def _paint_knob(self, p: QPainter, comp, pos: float):
        r = 2.2
        p.save()
        p.translate(comp.x, comp.y)
        pen = QPen(QColor(255, 255, 255, 200), 0.35, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(QColor(20, 22, 26, 200))
        p.drawEllipse(QPointF(0, 0), r, r)
        ang = math.radians(225 - 270 * pos)
        p.drawLine(QPointF(0, 0), QPointF(math.cos(ang) * r * 0.9, -math.sin(ang) * r * 0.9))
        pen.setColor(QColor(76, 154, 255, 230))
        pen.setWidthF(0.45)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(-r - 0.6, -r - 0.6, 2 * r + 1.2, 2 * r + 1.2), int(225 * 16), int(-270 * pos * 16))
        p.restore()

    # ------------------------------------------------------------------ painting (screen coordinates)
    def paint_screen(self, p: QPainter):
        sim = self.sim
        if not sim.running:
            return
        snap = sim.snap or {}
        f = QFont("Segoe UI")
        f.setPixelSize(11)
        p.setFont(f)
        fm = QFontMetricsF(f)
        # smoke markers
        for uid, (sev, msg) in (snap.get("smoke") or {}).items():
            comp = next((c for c in self.project.components if c.uid == uid), None)
            if comp is None:
                continue
            sp = self.c.to_screen(comp.x, comp.y)
            col = QColor(255, 80, 50) if sev == "error" else QColor(245, 184, 61)
            for i, (dx, dy, rr) in enumerate(((0, -14, 7), (-7, -20, 5), (6, -24, 6), (0, -31, 4))):
                c2 = QColor(170, 170, 175, 170 - i * 30) if sev == "error" else QColor(col.red(), col.green(),
                                                                                          col.blue(), 120)
                p.setPen(Qt.NoPen)
                p.setBrush(c2)
                p.drawEllipse(sp + QPointF(dx, dy), rr, rr)
            p.setBrush(col)
            p.drawEllipse(sp, 5, 5)
        # probe markers
        probes = set(sim.scope.nets)
        if probes:
            for comp in self.project.components:
                for pad in comp.footprint.pads:
                    net = comp.pad_nets.get(pad.number)
                    if net in probes:
                        sp = self.c.to_screen(*comp.pad_pos(pad))
                        idx = sim.scope.nets.index(net)
                        from .scope import TRACE_COLORS
                        p.setPen(QPen(QColor(TRACE_COLORS[idx % len(TRACE_COLORS)]), 2))
                        p.setBrush(Qt.NoBrush)
                        p.drawEllipse(sp, 6, 6)
                        break
        # status chip and colour legend
        t = snap.get("t", 0.0)
        ratio = snap.get("ratio", 0.0)
        text = f"  ▶ {fmt_eng(t, 's')}   ×{ratio:.2g} real time  " if not sim.paused else f"  ⏸ {fmt_eng(t, 's')}  "
        w = fm.horizontalAdvance(text) + 8
        r = QRectF(12, 10, w, 22)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 60, 36, 230) if not sim.paused else QColor(60, 50, 20, 230))
        p.drawRoundedRect(r, 6, 6)
        p.setPen(QColor(220, 240, 228))
        p.drawText(r, Qt.AlignVCenter | Qt.AlignLeft, text)
        vmax = sim.vmax()
        lx, ly, lw = 12, 38, 120
        for i in range(lw):
            p.setPen(volt_color(vmax * i / (lw - 1), vmax, 255))
            p.drawLine(QPointF(lx + i, ly), QPointF(lx + i, ly + 8))
        p.setPen(QColor(170, 176, 188))
        p.drawText(QPointF(lx, ly + 21), "0 V")
        lab = fmt_eng(vmax, "V")
        p.drawText(QPointF(lx + lw - fm.horizontalAdvance(lab), ly + 21), lab)
        # hover readout
        if self.hover_text and self.hover_pos is not None:
            tw = fm.horizontalAdvance(self.hover_text) + 16
            pos = self.hover_pos + QPointF(16, 18)
            x = min(pos.x(), self.c.width() - tw - 6)
            box = QRectF(x, pos.y(), tw, 22)
            p.setPen(QPen(QColor(70, 78, 92), 1))
            p.setBrush(QColor(24, 27, 33, 235))
            p.drawRoundedRect(box, 5, 5)
            p.setPen(QColor(230, 233, 240))
            p.drawText(box.adjusted(8, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, self.hover_text)
