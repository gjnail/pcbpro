"""Application look & feel: dark Fusion palette plus stylesheet."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#4c9aff"
ACCENT_DARK = "#2f6fd0"
BG = "#1d2026"
PANEL = "#23272f"
BASE = "#181b20"
BORDER = "#343a45"
TEXT = "#d9dde5"
TEXT_DIM = "#8b93a1"
GOOD = "#3fcf8e"
WARN = "#f5b83d"
BAD = "#f0605d"

STYLESHEET = f"""
QMainWindow, QDialog {{ background: {BG}; }}
QWidget {{ color: {TEXT}; font-size: 9.5pt; }}
QToolTip {{ background: #2b303a; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}
QMenuBar {{ background: {BG}; border-bottom: 1px solid {BORDER}; }}
QMenuBar::item {{ padding: 5px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: #2e3440; border-radius: 4px; }}
QMenu {{ background: #262a33; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 5px 26px 5px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT_DARK}; color: white; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
QToolBar {{ background: {BG}; border: none; spacing: 2px; padding: 3px; }}
QToolBar::separator {{ background: {BORDER}; width: 1px; margin: 4px 6px; }}
QToolButton {{ border: 1px solid transparent; border-radius: 6px; padding: 4px; }}
QToolButton:hover {{ background: #2c313b; border-color: {BORDER}; }}
QToolButton:checked {{ background: #1f3a63; border-color: {ACCENT_DARK}; }}
QToolButton:pressed {{ background: #1a2f50; }}
QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{ background: {PANEL}; padding: 6px 8px; border-bottom: 1px solid {BORDER};
                      font-weight: 600; color: {TEXT_DIM}; text-transform: uppercase; }}
QDockWidget > QWidget {{ background: {PANEL}; }}
QTabWidget::pane {{ border: none; background: {BG}; }}
QTabBar::tab {{ background: transparent; color: {TEXT_DIM}; padding: 7px 16px; border: none;
                border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {BASE}; border: 1px solid {BORDER}; border-radius: 5px; padding: 3px 6px;
    selection-background-color: {ACCENT_DARK}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: #262a33; border: 1px solid {BORDER}; selection-background-color: {ACCENT_DARK}; }}
QPushButton {{ background: #2c313b; border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 14px; }}
QPushButton:hover {{ background: #343a46; }}
QPushButton:pressed {{ background: #262b33; }}
QPushButton:disabled {{ color: #5c6370; }}
QPushButton[primary="true"] {{ background: {ACCENT_DARK}; border-color: {ACCENT}; color: white; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: {ACCENT}; }}
QPushButton[primary="true"]:disabled {{ background: #2c313b; border-color: {BORDER}; color: #5c6370; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; }}
QHeaderView::section {{ background: {PANEL}; color: {TEXT_DIM}; border: none; border-bottom: 1px solid {BORDER};
                        padding: 5px; font-weight: 600; }}
QTableWidget, QTreeWidget, QListWidget, QTableView, QTreeView {{
    background: {BASE}; border: 1px solid {BORDER}; border-radius: 6px; gridline-color: #2a2f38;
    alternate-background-color: #1c1f25; selection-background-color: #1f3a63; }}
QTreeWidget::item, QListWidget::item {{ padding: 3px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #3a404c; border-radius: 5px; min-height: 24px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #3a404c; border-radius: 5px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QStatusBar {{ background: {BG}; border-top: 1px solid {BORDER}; color: {TEXT_DIM}; }}
QStatusBar QLabel {{ color: {TEXT_DIM}; padding: 0 6px; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 8px; margin-top: 14px; padding-top: 8px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {TEXT_DIM}; }}
QProgressBar {{ background: {BASE}; border: 1px solid {BORDER}; border-radius: 5px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT_DARK}; border-radius: 4px; }}
QSplitter::handle {{ background: {BORDER}; }}
QLabel[muted="true"] {{ color: {TEXT_DIM}; }}
QLabel[heading="true"] {{ font-size: 13pt; font-weight: 700; }}
QFrame[card="true"] {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(BASE))
    pal.setColor(QPalette.AlternateBase, QColor("#1c1f25"))
    pal.setColor(QPalette.ToolTipBase, QColor("#2b303a"))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor("#2c313b"))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.BrightText, QColor("#ffffff"))
    pal.setColor(QPalette.Highlight, QColor(ACCENT_DARK))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.Link, QColor(ACCENT))
    pal.setColor(QPalette.PlaceholderText, QColor(TEXT_DIM))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor("#5c6370"))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)
