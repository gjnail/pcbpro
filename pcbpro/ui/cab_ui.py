"""Cabinet picker: the speaker-cabinet IR used by the audio play-through and Play live dialogs.

Lists the built-in cabinets, the cabinet IRs found on this computer (searched once in the background, then on
request) and files the user added. The choice is remembered and shared by both dialogs.
"""
from __future__ import annotations

import os
import threading

from PySide6.QtCore import QSettings, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QToolButton,
                               QVBoxLayout, QWidget)

from .. import APP_NAME
from ..sim.cabinet import builtin_irs, describe, find_irs, load_ir

_search = {"thread": None, "done": 0, "error": None}
_lock = threading.Lock()


def settings() -> QSettings:
    return QSettings(APP_NAME, APP_NAME)


def _paths(s: QSettings, key: str) -> list[str]:
    v = s.value(key, [])
    if isinstance(v, str):
        v = [v] if v else []
    return [p for p in (v or []) if isinstance(p, str) and os.path.isfile(p)]


def searching() -> bool:
    t = _search["thread"]
    return t is not None and t.is_alive()


def start_search() -> None:
    """Search this computer for cabinet IRs in a background thread; the result is saved in the settings."""
    with _lock:
        if searching():
            return

        def run():
            try:
                found = find_irs()
                s = settings()
                s.setValue("cab/found", found)
                s.setValue("cab/searched", True)
                s.sync()
                _search["error"] = None
            except Exception as e:  # pragma: no cover - reported in the picker
                _search["error"] = str(e)
            _search["done"] += 1

        t = threading.Thread(target=run, name="ir-search", daemon=True)
        _search["thread"] = t
        t.start()


class CabinetPicker(QWidget):
    """A combo of cabinet IRs (or Off) with a menu to add a file or search again. ``changed(path or None)``."""

    changed = Signal(object)

    def __init__(self, parent=None, auto_search: bool = True):
        super().__init__(parent)
        self.settings = settings()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        row = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.setMaxVisibleItems(28)
        self.combo.setStyleSheet("QComboBox { combobox-popup: 0; }")  # a scrolling list, not a screen-high menu
        self.combo.setToolTip("Speaker cabinet impulse response applied after the circuit (and to the dry signal)")
        self.more = QToolButton()
        self.more.setText("…")
        self.more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.more)
        menu.addAction("Add an IR file (.wav, .flac)…", self.browse)
        self.search_act = menu.addAction("Search this PC for cabinet IRs", lambda: (start_search(), self._poll()))
        self.more.setMenu(menu)
        row.addWidget(self.combo, 1)
        row.addWidget(self.more)
        lay.addLayout(row)
        self.note = QLabel()
        self.note.setProperty("muted", True)
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self._done = _search["done"]
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._poll)
        self.populate(self.settings.value("cab/path", "") or "")
        self.combo.currentIndexChanged.connect(self._chosen)
        if auto_search and str(self.settings.value("cab/searched", "false")).lower() != "true":
            start_search()
        self._poll()
        if searching():
            self._timer.start()

    # ------------------------------------------------------------------ list
    def populate(self, select: str = "") -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem("Off (no cabinet)", "")
        model = self.combo.model()

        def header(text):
            self.combo.addItem(text, None)
            item = model.item(self.combo.count() - 1)
            item.setEnabled(False)
            f = item.font()
            f.setBold(True)
            item.setFont(f)

        groups: dict[str, list[tuple[str, str]]] = {}
        user = _paths(self.settings, "cab/user")
        for p in builtin_irs() + _paths(self.settings, "cab/found"):
            g, n = describe(p)
            groups.setdefault(g, []).append((n, p))
        if user:
            groups["Added by you"] = [(describe(p)[1], p) for p in user]
        seen = set()
        for g, items in groups.items():
            header(g)
            for name, p in items:
                key = os.path.normcase(os.path.abspath(p))
                if key in seen:
                    continue
                seen.add(key)
                self.combo.addItem(name, p)
                self.combo.setItemData(self.combo.count() - 1, f"{g} · {name}\n{p}", 3)  # Qt.ToolTipRole
        i = self.combo.findData(select) if select else 0
        self.combo.setCurrentIndex(max(i, 0))
        self.combo.blockSignals(False)
        self._update_note()

    def path(self) -> str | None:
        return self.combo.currentData() or None

    def set_path(self, path: str | None) -> None:
        i = self.combo.findData(path or "")
        if i >= 0:
            self.combo.setCurrentIndex(i)

    def count(self) -> int:
        """Number of cabinets listed (headers and Off excluded)."""
        return sum(1 for i in range(self.combo.count()) if self.combo.itemData(i))

    # ------------------------------------------------------------------ events
    def _chosen(self, _i):
        p = self.path()
        self.settings.setValue("cab/path", p or "")
        self.changed.emit(p)

    def browse(self):
        start = os.path.dirname(self.path() or "") or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, "Cabinet impulse response", start,
                                              "Impulse responses (*.wav *.flac)")
        if path:
            self.add_file(path)

    def add_file(self, path: str) -> bool:
        try:
            load_ir(path, 48000)
        except Exception as e:
            QMessageBox.warning(self, "Cabinet IR", f"Could not use this file as a cabinet IR:\n{e}")
            return False
        user = [p for p in _paths(self.settings, "cab/user") if os.path.normcase(p) != os.path.normcase(path)]
        self.settings.setValue("cab/user", [path] + user[:19])
        self.populate(path)
        self._chosen(None)
        return True

    def _poll(self):
        if searching():
            self.search_act.setEnabled(False)
            self.note.setText("Searching this PC for cabinet IRs…")
            self.note.setVisible(True)
            if not self._timer.isActive():
                self._timer.start()
            return
        self._timer.stop()
        self.search_act.setEnabled(True)
        if self._done != _search["done"]:
            self._done = _search["done"]
            self.settings.sync()
            self.populate(self.path() or "")
        self._update_note()

    def _update_note(self):
        if searching():
            return
        if _search["error"]:
            self.note.setText(f"IR search failed: {_search['error']}")
        else:
            n = len(_paths(self.settings, "cab/found"))
            searched = str(self.settings.value("cab/searched", "false")).lower() == "true"
            self.note.setText(f"{n} cabinet IRs found on this PC, plus the built-in ones." if searched and n else
                              "No cabinet IRs found on this PC: use the built-in ones or add a file with …"
                              if searched else "")
        self.note.setVisible(bool(self.note.text()))

    def showEvent(self, ev):
        super().showEvent(ev)
        if searching():
            self._timer.start()
