"""Simulation dialogs: part model override, sources editor and the serial monitor."""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..sim.models import TABLE, Resolution, resolve
from ..sim.units import fmt_eng

KIND_TERMINALS = {
    "resistor": ["1", "2"], "capacitor": ["+", "-"], "inductor": ["1", "2"], "link": ["1", "2"],
    "diode": ["A", "K"], "led": ["A", "K"], "bjt": ["C", "B", "E"], "fet": ["D", "G", "S"], "jfet": ["D", "G", "S"],
    "regulator": ["IN", "REF", "OUT", "EN"], "shuntref": ["REF", "A", "K"], "sensor": ["VS", "OUT", "GND"],
    "opto": ["A", "K", "C", "E"], "pot": ["1", "W", "3"], "battery": ["+", "-"], "buzzer": ["+", "-"],
}
KIND_PARAMS = {
    "resistor": {"r": 10e3}, "capacitor": {"c": 100e-9, "polarized": False}, "inductor": {"l": 10e-6},
    "link": {"r": 0.05}, "diode": {"is_": 4.352e-9, "n": 1.906, "rs": 0.65, "bv": 100.0, "imax": 0.3},
    "led": {"colour": "red", "vf": 1.85, "imax": 0.03, "rs": 6.0},
    "bjt": {"pol": 1, "is_": 1e-14, "bf": 200.0, "br": 4.0, "vaf": 80.0, "imax": 0.2, "pmax": 0.5},
    "fet": {"pol": 1, "vth": 2.0, "k": 1.0, "lam": 0.01, "imax": 5.0, "pmax": 1.0, "body": True},
    "jfet": {"pol": 1, "vp": -1.5, "idss": 3e-3}, "regulator": {"vset": 5.0, "vdo": 1.2, "ilim": 1.0, "iq": 5e-3,
                                                                "adj": False, "pol": 1},
    "shuntref": {"vref": 2.495}, "sensor": {"slope": 0.01, "offset": 0.0, "temp": 25.0},
    "opto": {"ctr": 1.0}, "pot": {"r": 10e3, "taper": "B"}, "battery": {"v": 9.0, "r": 1.0},
    "buzzer": {"r": 100.0},
}


class PartModelDialog(QDialog):
    """Choose how a component is simulated: automatic, a catalogue model, a generic device kind, or excluded."""

    def __init__(self, project, comp, parent=None):
        super().__init__(parent)
        self.project = project
        self.comp = comp
        self.result_override: dict | None = None
        self.setWindowTitle(f"Simulation model: {comp.ref}")
        self.resize(560, 520)
        lay = QVBoxLayout(self)
        head = QLabel(f"<b>{comp.ref}</b> {comp.value}  ·  {comp.footprint.name}" +
                      (f"  ·  MPN {comp.mpn}" if comp.mpn else ""))
        head.setWordWrap(True)
        lay.addWidget(head)
        self.auto = resolve(comp)
        self.cur_override = copy.deepcopy((project.sim or {}).get("parts", {}).get(comp.uid, {}))
        form = QFormLayout()
        self.choice = QComboBox()
        self.choice.addItem(f"Automatic ({self.auto.model or self.auto.kind})", ("auto", None))
        self.choice.addItem("Exclude from the simulation", ("exclude", None))
        for kind in KIND_TERMINALS:
            self.choice.addItem(f"Generic: {kind}", ("kind", kind))
        for key in sorted(TABLE):
            self.choice.addItem(f"Model: {key} ({TABLE[key][0]})", ("model", key))
        form.addRow("Simulate as", self.choice)
        lay.addLayout(form)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setProperty("muted", True)
        lay.addWidget(self.info)
        lay.addWidget(QLabel("Pin mapping (pad numbers, comma separated):"))
        self.pins = QTableWidget(0, 3)
        self.pins.setHorizontalHeaderLabels(["Terminal", "Pad(s)", "Net"])
        self.pins.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.pins.verticalHeader().setVisible(False)
        lay.addWidget(self.pins, 1)
        lay.addWidget(QLabel("Parameters:"))
        self.params = QTableWidget(0, 2)
        self.params.setHorizontalHeaderLabels(["Name", "Value"])
        self.params.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.params.verticalHeader().setVisible(False)
        lay.addWidget(self.params, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        # current selection
        if self.cur_override.get("exclude"):
            self.choice.setCurrentIndex(1)
        elif self.cur_override.get("kind"):
            self._select(("kind", self.cur_override["kind"]))
        elif self.cur_override.get("model"):
            self._select(("model", self.cur_override["model"]))
        self.choice.currentIndexChanged.connect(lambda _i: self._load(fresh=True))
        self._load(fresh=False)

    def _select(self, data):
        for i in range(self.choice.count()):
            if self.choice.itemData(i) == data:
                self.choice.setCurrentIndex(i)
                return

    def _resolution(self, fresh: bool) -> Resolution:
        kind, key = self.choice.currentData()
        ov = {} if fresh else dict(self.cur_override)
        if kind == "exclude":
            return Resolution("excluded", "excluded")
        if kind == "kind":
            ov.pop("model", None)
            ov["kind"] = key
            if fresh:
                ov["params"] = dict(KIND_PARAMS.get(key, {}))
                ov["pins"] = {t: p for t, p in self.auto.pins.items() if t in KIND_TERMINALS.get(key, [])}
            r = resolve(self.comp, ov)
            for t in KIND_TERMINALS.get(key, []):
                r.pins.setdefault(t, [])
            return r
        if kind == "model":
            ov.pop("kind", None)
            ov["model"] = key
            if fresh:
                ov.pop("pins", None)
                ov.pop("params", None)
            return resolve(self.comp, ov)
        return resolve(self.comp, {} if fresh else {k: v for k, v in ov.items() if k in ("pins", "params")})

    def _load(self, fresh: bool):
        r = self._resolution(fresh)
        self.res = r
        text = f"Kind: {r.kind}"
        if r.note:
            text += f" · {r.note}"
        if r.verify:
            text += " · pinout not verified: check it against the datasheet"
        self.info.setText(text)
        self.pins.setRowCount(0)
        for t, pads in r.pins.items():
            row = self.pins.rowCount()
            self.pins.insertRow(row)
            it = QTableWidgetItem(t)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.pins.setItem(row, 0, it)
            self.pins.setItem(row, 1, QTableWidgetItem(", ".join(pads)))
            nets = ", ".join(sorted({self.comp.pad_nets.get(p) or "–" for p in pads}))
            it = QTableWidgetItem(nets)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.pins.setItem(row, 2, it)
        self.params.setRowCount(0)
        for k, v in r.params.items():
            if isinstance(v, (dict, list, tuple)) and k not in ("pairs",):
                continue
            row = self.params.rowCount()
            self.params.insertRow(row)
            it = QTableWidgetItem(k)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.params.setItem(row, 0, it)
            self.params.setItem(row, 1, QTableWidgetItem(repr(v) if not isinstance(v, str) else v))
        editable = r.kind not in ("excluded",)
        self.pins.setEnabled(editable)
        self.params.setEnabled(editable)

    def _accept(self):
        kind, key = self.choice.currentData()
        if kind == "auto":
            ov = {}
        elif kind == "exclude":
            ov = {"exclude": True}
        else:
            ov = {"kind": key} if kind == "kind" else {"model": key}
        if kind != "exclude":
            pins = {}
            for row in range(self.pins.rowCount()):
                t = self.pins.item(row, 0).text()
                pads = [s.strip() for s in self.pins.item(row, 1).text().split(",") if s.strip()]
                if pads and pads != self.res.pins.get(t) or kind == "kind":
                    pins[t] = pads
            if pins and (kind == "kind" or any(pins[t] != self.res.pins.get(t) for t in pins)):
                ov["pins"] = {t: p for t, p in pins.items() if p}
            params = {}
            for row in range(self.params.rowCount()):
                k = self.params.item(row, 0).text()
                raw = self.params.item(row, 1).text().strip()
                old = self.res.params.get(k)
                try:
                    val = _parse(raw, old)
                except ValueError:
                    continue
                if val != old or kind == "kind":
                    params[k] = val
            if params:
                ov["params"] = params
        self.result_override = ov
        self.accept()


def _parse(raw: str, old):
    if isinstance(old, bool) or raw.lower() in ("true", "false"):
        return raw.lower() in ("true", "1", "yes")
    if isinstance(old, (int, float)) or old is None:
        from ..sim.units import parse_value
        try:
            v = float(raw)
        except ValueError:
            v = parse_value(raw)
            if v is None:
                raise
        return int(v) if isinstance(old, int) and not isinstance(old, bool) and v == int(v) else v
    if isinstance(old, (list, tuple)):
        import ast
        return ast.literal_eval(raw)
    return raw


class SourcesDialog(QDialog):
    """Bench supplies and signal generators attached to nets (relative to ground)."""

    COLS = ["On", "Net", "Type", "Volts / amplitude", "Frequency (Hz)", "Series R (Ω)"]

    def __init__(self, project, auto_list: list[dict], parent=None):
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("Simulation sources")
        self.resize(680, 360)
        lay = QVBoxLayout(self)
        cfg = (project.sim or {}).get("sources")
        self.auto_cb = QCheckBox("Detect supplies automatically from net names and connectors")
        self.auto_cb.setChecked(cfg is None)
        lay.addWidget(self.auto_cb)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        lay.addWidget(self.table, 1)
        self.nets = [n for n in project.nets()]
        for s in (cfg if cfg is not None else auto_list):
            self._add_row(s)
        h = QHBoxLayout()
        add = QPushButton("Add source")
        add.clicked.connect(lambda: self._add_row({"net": self.nets[0] if self.nets else "", "kind": "dc", "v": 5.0,
                                                   "r": 0.05, "enabled": True}))
        rem = QPushButton("Remove")
        rem.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))
        h.addWidget(add)
        h.addWidget(rem)
        h.addStretch(1)
        lay.addLayout(h)
        note = QLabel("Sources connect between the net and ground. Batteries, DC jacks and USB sockets on the board "
                      "power it by themselves.")
        note.setWordWrap(True)
        note.setProperty("muted", True)
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.auto_cb.toggled.connect(lambda on: self.table.setEnabled(not on))
        self.table.setEnabled(not self.auto_cb.isChecked())

    def _add_row(self, s: dict):
        r = self.table.rowCount()
        self.table.insertRow(r)
        on = QCheckBox()
        on.setChecked(bool(s.get("enabled", True)))
        self.table.setCellWidget(r, 0, on)
        net = QComboBox()
        net.setEditable(True)
        net.addItems(self.nets)
        net.setCurrentText(s.get("net", ""))
        self.table.setCellWidget(r, 1, net)
        kind = QComboBox()
        kind.addItems(["dc", "sine", "square"])
        kind.setCurrentText(s.get("kind", "dc"))
        self.table.setCellWidget(r, 2, kind)
        for c, key, default, lo, hi, dec in ((3, "v", 5.0, -1000, 1000, 3), (4, "freq", 1000.0, 0, 1e7, 1),
                                             (5, "r", 0.05, 0, 1e7, 3)):
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setDecimals(dec)
            val = s.get("amp" if key == "v" and s.get("kind") == "sine" else key,
                        s.get("hi", default) if key == "v" else default)
            sp.setValue(float(val))
            self.table.setCellWidget(r, c, sp)

    def sources(self) -> list[dict] | None:
        if self.auto_cb.isChecked():
            return None
        out = []
        for r in range(self.table.rowCount()):
            kind = self.table.cellWidget(r, 2).currentText()
            v = self.table.cellWidget(r, 3).value()
            s = {"enabled": self.table.cellWidget(r, 0).isChecked(), "net": self.table.cellWidget(r, 1).currentText(),
                 "kind": kind, "r": self.table.cellWidget(r, 5).value(), "freq": self.table.cellWidget(r, 4).value()}
            if kind == "dc":
                s["v"] = v
            elif kind == "sine":
                s["amp"] = v
                s["offset"] = 0.0
            else:
                s["hi"] = v
                s["lo"] = 0.0
            out.append(s)
        return out


class SerialMonitor(QDialog):
    """USART output of an emulated microcontroller, with a line to send text back."""

    def __init__(self, controller, uid: str, title: str, parent=None):
        super().__init__(parent)
        self.sim = controller
        self.uid = uid
        self.setWindowTitle(f"Serial monitor: {title}")
        self.resize(560, 380)
        self.setAttribute(Qt.WA_DeleteOnClose)
        lay = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        f = QFont("Consolas")
        f.setStyleHint(QFont.Monospace)
        self.text.setFont(f)
        self.text.setPlainText(controller.serial.get(uid, ""))
        lay.addWidget(self.text, 1)
        h = QHBoxLayout()
        self.line = QLineEdit()
        self.line.setPlaceholderText("Text to send")
        self.line.returnPressed.connect(self._send)
        self.eol = QComboBox()
        self.eol.addItems(["Newline", "No line ending", "CR+LF"])
        b = QPushButton("Send")
        b.clicked.connect(self._send)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.text.clear)
        h.addWidget(self.line, 1)
        h.addWidget(self.eol)
        h.addWidget(b)
        h.addWidget(clear)
        lay.addLayout(h)
        controller.serial_received.connect(self._received)

    def _received(self, uid, text):
        if uid != self.uid:
            return
        cur = self.text.textCursor()
        cur.movePosition(QTextCursor.End)
        cur.insertText(text)
        self.text.setTextCursor(cur)
        self.text.ensureCursorVisible()

    def _send(self):
        eol = {"Newline": "\n", "No line ending": "", "CR+LF": "\r\n"}[self.eol.currentText()]
        self.sim.send_serial(self.uid, self.line.text() + eol)
        self.line.clear()
