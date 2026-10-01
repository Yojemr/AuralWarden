from __future__ import annotations

import re


COLORS = {
    "background": "#07131d",
    "surface": "#0c1c27",
    "surface_alt": "#102531",
    "border": "#203744",
    "text": "#e7eef2",
    "muted": "#91a1aa",
    "accent": "#27c69a",
    "accent_hover": "#35d7aa",
    "cyan": "#18baf2",
    "warning": "#f0ac24",
    "danger": "#ef616c",
}


APP_STYLESHEET = """
* {
    font-family: "Segoe UI";
    font-size: 13px;
    color: #e7eef2;
}
QMainWindow, QDialog, QWidget#appRoot {
    background-color: #07131d;
}
QFrame[card="true"], QGroupBox {
    background-color: #0c1c27;
    border: 1px solid #203744;
    border-radius: 9px;
}
QFrame[card="true"]:hover {
    border-color: #294857;
}
QLabel[muted="true"] { color: #91a1aa; }
QLabel[title="true"] { font-size: 15px; font-weight: 600; }
QLabel[sectionTitle="true"] { font-size: 14px; font-weight: 600; }
QLabel[brand="true"] { font-size: 24px; font-weight: 650; }
QLabel[brandLight="true"] { font-size: 24px; font-weight: 350; color: #7fe3c4; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {
    background-color: #0e202c;
    border: 1px solid #29414f;
    border-radius: 6px;
    padding: 7px 9px;
    selection-background-color: #167d67;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus {
    border: 1px solid #27c69a;
}
QComboBox::drop-down { border: none; width: 26px; }
QComboBox QAbstractItemView {
    background-color: #102531;
    border: 1px solid #29414f;
    selection-background-color: #176d5b;
}
QPushButton {
    background-color: #102531;
    border: 1px solid #29414f;
    border-radius: 6px;
    padding: 8px 13px;
    font-weight: 550;
}
QPushButton:hover { background-color: #15303e; border-color: #3e6475; }
QPushButton:pressed { background-color: #0b1922; }
QPushButton:disabled { color: #5f7079; background-color: #0b1720; border-color: #182a34; }
QPushButton[primary="true"] {
    background-color: #178361;
    border-color: #239d79;
    color: white;
}
QPushButton[primary="true"]:hover { background-color: #209873; }
QPushButton[primary="true"]:disabled { color: #60727a; background-color: #102029; border-color: #1b313b; }
QPushButton[danger="true"] { color: #f6a0a7; }
QPushButton[flat="true"] { background: transparent; border: none; padding: 5px; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 34px; height: 18px; border-radius: 9px; background: #263b47; }
QCheckBox::indicator:checked { background: #27c69a; image: none; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { width: 7px; background: transparent; margin: 2px; }
QScrollBar::handle:vertical { background: #415865; border-radius: 3px; min-height: 36px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QTableWidget {
    background: #0c1c27;
    border: none;
    gridline-color: #203744;
    selection-background-color: #13392f;
}
QListWidget {
    background: #0c1c27;
    border: 1px solid #203744;
    border-radius: 6px;
    outline: none;
}
QListWidget::item { padding: 8px; border-bottom: 1px solid #1c313c; }
QListWidget::item:selected { background: #176d5b; color: #e7eef2; }
QHeaderView::section {
    background: #0c1c27;
    color: #91a1aa;
    border: none;
    border-bottom: 1px solid #29414f;
    padding: 6px;
    font-weight: 500;
}
QTableWidget::item { padding: 5px; border-bottom: 1px solid #1c313c; }
QToolTip { background: #102531; border: 1px solid #345463; color: #e7eef2; padding: 5px; }
QMenu { background: #0e202c; border: 1px solid #29414f; padding: 5px; }
QMenu::item { padding: 7px 24px 7px 10px; border-radius: 4px; }
QMenu::item:selected { background: #176d5b; }
QTabWidget::pane { border: 1px solid #203744; border-radius: 8px; top: -1px; }
QTabBar::tab { background: #0b1a24; padding: 9px 16px; color: #91a1aa; }
QTabBar::tab:selected { background: #123126; color: #7fe3c4; }
QMessageBox { background-color: #0c1c27; }
"""


def scaled_stylesheet(percent: int) -> str:
    """Scale pixel-based UI dimensions while preserving the selected design."""
    factor = max(0.9, min(1.25, int(percent) / 100.0))
    if abs(factor - 1.0) < 0.001:
        return APP_STYLESHEET

    def replace(match: re.Match[str]) -> str:
        value = max(1, round(int(match.group(1)) * factor))
        return f"{value}px"

    return re.sub(r"(?<![\w.])(\d+)px", replace, APP_STYLESHEET)
