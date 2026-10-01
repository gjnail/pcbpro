"""FlowLayout: a QHBoxLayout that wraps onto more lines when it runs out of width.

Toolbar rows above a page use it so their combined width doesn't set the window's minimum width: with room to spare
it lays out exactly like a QHBoxLayout, on a narrow window the row wraps instead.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLayout, QSizePolicy, QSpacerItem, QStyle, QWidget


class FlowLayout(QLayout):
    """Left-to-right row that wraps.

    On one line it matches QHBoxLayout: widgets get their size hints, addSpacing() adds a fixed gap and addStretch()
    takes the line's spare width. A stretch also splits the row into groups: when the group after it doesn't fit on
    the current line it starts a new line, and only a group too wide for a whole line breaks between its widgets.
    Wrapped lines are left-aligned. Keep a label with its field by adding both through addGroup().
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._vspacing = -1

    # ------------------------------------------------------------------ building
    def addItem(self, item):
        self._items.append(item)

    def addSpacing(self, size: int):
        self.addItem(QSpacerItem(size, 0, QSizePolicy.Fixed, QSizePolicy.Minimum))

    def addStretch(self, stretch: int = 1):
        self.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))

    def addGroup(self, *widgets) -> QWidget:
        """Add widgets that always stay together on one line (e.g. a label and its combo box)."""
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        for w in widgets:
            row.addWidget(w)
        self.addWidget(box)
        return box

    def setVerticalSpacing(self, spacing: int):
        self._vspacing = spacing
        self.invalidate()

    # ------------------------------------------------------------------ QLayout interface
    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self):
        """Everything on one line, like QHBoxLayout."""
        w = h = 0
        prev = False
        for item in self._items:
            if _is_spacer(item):
                w += item.sizeHint().width()
            elif not item.isEmpty():
                s = item.sizeHint()
                w += s.width() + (self._hspace() if prev else 0)
                h = max(h, s.height())
                prev = True
        m = self.contentsMargins()
        return QSize(w + m.left() + m.right(), h + m.top() + m.bottom())

    def minimumSize(self):
        """As narrow as the widest widget; the height for that width comes from heightForWidth()."""
        w = h = 0
        for item in self._items:
            if not item.isEmpty():
                s = item.minimumSize()
                w, h = max(w, s.width()), max(h, s.height())
        m = self.contentsMargins()
        return QSize(w + m.left() + m.right(), h + m.top() + m.bottom())

    # ------------------------------------------------------------------ layout
    def _smart(self, pm: QStyle.PixelMetric) -> int:
        p = self.parent()
        if p is None:
            return 6
        if p.isWidgetType():
            v = p.style().pixelMetric(pm, None, p)
        else:
            v = p.spacing()
        return v if v >= 0 else 6

    def _hspace(self) -> int:
        s = self.spacing()
        return s if s >= 0 else self._smart(QStyle.PM_LayoutHorizontalSpacing)

    def _vspace(self) -> int:
        return self._vspacing if self._vspacing >= 0 else self._smart(QStyle.PM_LayoutVerticalSpacing)

    def _groups(self):
        """Split the items at stretches: [(stretch_before, [items])]."""
        groups = [(None, [])]
        for item in self._items:
            if _is_stretch(item):
                groups.append((item, []))
            else:
                groups[-1][1].append(item)
        return groups

    def _layout(self, rect: QRect, apply: bool) -> int:
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        avail = max(1, r.width())
        hs, vs = self._hspace(), self._vspace()

        def width(line):
            w, prev = 0, False
            for item, iw in line:
                if not _is_spacer(item):
                    w += hs if prev else 0
                    prev = True
                w += iw
            return w

        def has_widgets(line):
            return any(not _is_spacer(it) for it, _ in line)

        # break into lines of (item, width); spacers stay in the lines, stretches get width 0 until placement
        lines = [[]]
        for stretch, items in self._groups():
            group = [(it, max(it.minimumSize().width(), min(it.sizeHint().width(), avail)))
                     for it in items if _is_spacer(it) or not it.isEmpty()]
            line = lines[-1]
            if stretch is not None:
                if width(line + [(stretch, 0)] + group) <= avail:
                    line += [(stretch, 0)] + group
                    continue
                if has_widgets(line):  # the group doesn't fit after the stretch: start it on a new line
                    lines.append([])
                    line = lines[-1]
                    if width(group) <= avail:
                        line += group
                        continue
                else:
                    line.append((stretch, 0))
            for it, iw in group:  # too wide for one line: break between its widgets
                if _is_spacer(it):
                    if has_widgets(line) or len(lines) == 1:  # no leading gap on a wrapped line
                        line.append((it, iw))
                    continue
                if has_widgets(line) and width(line + [(it, iw)]) > avail:
                    lines.append([])
                    line = lines[-1]
                line.append((it, iw))
        for line in lines:
            while line and _is_spacer(line[-1][0]) and not _is_stretch(line[-1][0]):
                line.pop()  # no trailing gap either
        lines = [line for line in lines if has_widgets(line)]
        heights = [max(it.heightForWidth(iw) if it.hasHeightForWidth() else it.sizeHint().height()
                       for it, iw in line if not _is_spacer(it)) for line in lines]
        total = sum(heights) + vs * max(0, len(lines) - 1)
        if apply:
            y = r.y()
            if len(lines) == 1:
                heights[0] = max(heights[0], r.height())  # one line gets the full height, as in a QHBoxLayout
            else:
                y += max(0, r.height() - total) // 2
            for line, h in zip(lines, heights):
                spare = max(0, avail - width(line))
                stretches = [i for i, (it, _) in enumerate(line) if _is_stretch(it)]
                x, prev = r.x(), False
                for i, (it, iw) in enumerate(line):
                    if _is_spacer(it):
                        if i in stretches:
                            k = stretches.index(i)
                            iw = spare // len(stretches) + (1 if k < spare % len(stretches) else 0)
                        x += iw
                        continue
                    x += hs if prev else 0
                    prev = True
                    it.setGeometry(QRect(x, y, iw, h))
                    x += iw
                y += h + vs
        return total + m.top() + m.bottom()


def _is_spacer(item) -> bool:
    return item.spacerItem() is not None


def _is_stretch(item) -> bool:
    sp = item.spacerItem()
    return sp is not None and sp.sizePolicy().horizontalPolicy() in (QSizePolicy.Expanding,
                                                                      QSizePolicy.MinimumExpanding)
