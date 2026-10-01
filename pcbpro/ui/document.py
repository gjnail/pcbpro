"""Document: the open project plus undo/redo, selection and change notification."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ..model.board import Board, Project
from ..model.copper import fill_all_zones
from ..model.fileio import load_project, save_project
from ..model.geometry import rounded_rect_points

MAX_UNDO = 200


def blank_project(width: float = 60, height: float = 40, radius: float = 1.5, layers: int = 2,
                  thickness: float = 1.6, name: str = "Untitled") -> Project:
    p = Project(name)
    p.board = Board(outline=rounded_rect_points(0, 0, width, height, radius), layers=layers, thickness=thickness)
    return p


class Document(QObject):
    changed = Signal()  # model geometry / data changed
    replaced = Signal()  # whole project object replaced (open, new, undo)
    selection_changed = Signal()
    state_changed = Signal()  # path / dirty / undo availability
    message = Signal(str)

    def __init__(self, project: Project | None = None):
        super().__init__()
        self.project = project or blank_project()
        self.path: Path | None = None
        self.dirty = False
        self.undo_stack: list[tuple[str, dict]] = []
        self.redo_stack: list[tuple[str, dict]] = []
        self.selection: list = []
        self._pending: tuple[str, dict] | None = None
        self.auto_refill = True
        self._refill_timer = QTimer(self)
        self._refill_timer.setSingleShot(True)
        self._refill_timer.setInterval(350)
        self._refill_timer.timeout.connect(self._auto_refill)

    # ------------------------------------------------------------------ editing transactions
    def begin(self, label: str) -> None:
        if self._pending is None:
            self._pending = (label, self.project.to_dict())

    def commit(self) -> None:
        if self._pending is not None:
            self.undo_stack.append(self._pending)
            del self.undo_stack[:-MAX_UNDO]
            self.redo_stack.clear()
            self._pending = None
        self.project.touch()
        self.dirty = True
        self.changed.emit()
        self.state_changed.emit()
        if self.auto_refill and self.project.zones:
            self._refill_timer.start()

    def cancel(self) -> None:
        if self._pending is not None:
            state = self._pending[1]
            self._pending = None
            self._restore(state)

    def discard_pending(self) -> None:
        """Forget a transaction that turned out not to change anything."""
        self._pending = None

    @property
    def in_transaction(self) -> bool:
        return self._pending is not None

    @contextmanager
    def edit(self, label: str):
        self.begin(label)
        try:
            yield
        except Exception:
            self.cancel()
            raise
        self.commit()

    def live_update(self) -> None:
        """Notify views during an interactive drag (no undo entry yet)."""
        self.project.touch()
        self.changed.emit()

    # ------------------------------------------------------------------ undo / redo
    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    def can_redo(self) -> bool:
        return bool(self.redo_stack)

    def undo(self) -> None:
        if not self.undo_stack:
            return
        label, state = self.undo_stack.pop()
        self.redo_stack.append((label, self.project.to_dict()))
        self._restore(state)
        self.dirty = True
        self.message.emit(f"Undo: {label}")

    def redo(self) -> None:
        if not self.redo_stack:
            return
        label, state = self.redo_stack.pop()
        self.undo_stack.append((label, self.project.to_dict()))
        self._restore(state)
        self.dirty = True
        self.message.emit(f"Redo: {label}")

    def _restore(self, state: dict) -> None:
        sel = [it.uid for it in self.selection]
        p = Project.from_dict(state)
        if p.zones:
            fill_all_zones(p)
        self.project = p
        self.selection = [it for it in (p.find(u) for u in sel) if it is not None]
        self.replaced.emit()
        self.changed.emit()
        self.selection_changed.emit()
        self.state_changed.emit()

    # ------------------------------------------------------------------ selection
    def set_selection(self, items) -> None:
        items = list(dict.fromkeys(items))
        if [i.uid for i in items] != [i.uid for i in self.selection]:
            self.selection = items
            self.selection_changed.emit()

    def clear_selection(self) -> None:
        self.set_selection([])

    # ------------------------------------------------------------------ zones
    def refill_zones(self) -> None:
        if self.project.zones:
            fill_all_zones(self.project)
            self.changed.emit()

    def _auto_refill(self) -> None:
        if self.in_transaction:
            self._refill_timer.start()
            return
        if self.project.fills_stale:
            self.refill_zones()

    # ------------------------------------------------------------------ files
    def set_project(self, project: Project, path: Path | None = None) -> None:
        if project.zones and project.fills_stale:
            fill_all_zones(project)
        self.project = project
        self.path = Path(path) if path else None
        self.dirty = False
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.selection = []
        self._pending = None
        self.replaced.emit()
        self.changed.emit()
        self.selection_changed.emit()
        self.state_changed.emit()

    def open(self, path: str | Path) -> None:
        self.set_project(load_project(path), Path(path))

    def save(self, path: str | Path | None = None) -> None:
        target = Path(path) if path else self.path
        if target is None:
            raise ValueError("No file name")
        save_project(self.project, target)
        self.path = target
        self.dirty = False
        self.state_changed.emit()

    @property
    def title(self) -> str:
        name = self.path.name if self.path else f"{self.project.name} (unsaved)"
        return ("* " if self.dirty else "") + name
