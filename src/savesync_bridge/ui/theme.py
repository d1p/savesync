from __future__ import annotations

from PySide6.QtWidgets import QApplication

from savesync_bridge.models.game import SyncStatus

DARK_PALETTE = {
    "bg": "#1e1e2e",
    "bg_sidebar": "#181825",
    "bg_card": "#313244",
    "bg_card_hover": "#3d3f59",
    "accent": "#cba6f7",
    "success": "#a6e3a1",
    "warning": "#fab387",
    "error": "#f38ba8",
    "text": "#cdd6f4",
    "text_dim": "#6c7086",
    "border": "#45475a",
    "surface0": "#313244",
    "surface1": "#45475a",
    "surface2": "#585b70",
    "blue": "#89b4fa",
    "lavender": "#b4befe",
}

STATUS_COLORS: dict[SyncStatus, str] = {
    SyncStatus.SYNCED: "#a6e3a1",
    SyncStatus.LOCAL_NEWER: "#89b4fa",
    SyncStatus.CLOUD_NEWER: "#fab387",
    SyncStatus.CONFLICT: "#f38ba8",
    SyncStatus.UNKNOWN: "#6c7086",
}

STATUS_LABELS: dict[SyncStatus, str] = {
    SyncStatus.SYNCED: "SYNCED",
    SyncStatus.LOCAL_NEWER: "LOCAL NEWER",
    SyncStatus.CLOUD_NEWER: "CLOUD NEWER",
    SyncStatus.CONFLICT: "CONFLICT",
    SyncStatus.UNKNOWN: "UNKNOWN",
}

_STYLESHEET = """
/* ---- Base ---- */
QMainWindow, QDialog {
    background-color: #1e1e2e;
    color: #cdd6f4;
}
QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: "Segoe UI", "Inter", "SF Pro Display", sans-serif;
    font-size: 10pt;
}

/* ---- Scroll area ---- */
QScrollArea {
    border: none;
    background-color: #1e1e2e;
}
QScrollArea > QWidget > QWidget {
    background-color: #1e1e2e;
}
QScrollBar:vertical {
    background-color: transparent;
    width: 6px;
    border-radius: 3px;
    margin: 4px 2px;
}
QScrollBar::handle:vertical {
    background-color: #45475a;
    border-radius: 3px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background-color: #585b70;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    background-color: transparent;
    height: 6px;
    border-radius: 3px;
    margin: 2px 4px;
}
QScrollBar::handle:horizontal {
    background-color: #45475a;
    border-radius: 3px;
    min-width: 30px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ---- Toolbar ---- */
QToolBar {
    background-color: #181825;
    border-bottom: 1px solid #313244;
    spacing: 4px;
    padding: 6px 12px;
}
QToolButton {
    background-color: transparent;
    color: #bac2de;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 7px 16px;
    font-size: 10pt;
    font-weight: 500;
}
QToolButton:hover {
    background-color: #313244;
    color: #cdd6f4;
}
QToolButton:pressed {
    background-color: #45475a;
}

/* ---- Buttons ---- */
QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 8px;
    padding: 5px 14px;
    font-size: 10pt;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #45475a;
    border-color: #585b70;
}
QPushButton:pressed {
    background-color: #585b70;
}
QPushButton:checked {
    background-color: rgba(203, 166, 247, 0.15);
    border-color: #cba6f7;
    color: #cba6f7;
}
QPushButton#accent_btn {
    background-color: #cba6f7;
    color: #1e1e2e;
    border: none;
    font-weight: 600;
    padding: 7px 18px;
    border-radius: 8px;
}
QPushButton#accent_btn:hover {
    background-color: #d8b4fe;
}
QPushButton#accent_btn:pressed {
    background-color: #b89ae8;
}
QPushButton#push_btn {
    background-color: rgba(137, 180, 250, 0.12);
    color: #89b4fa;
    border: 1px solid rgba(137, 180, 250, 0.25);
}
QPushButton#push_btn:hover {
    background-color: rgba(137, 180, 250, 0.22);
    border-color: #89b4fa;
}
QPushButton#pull_btn {
    background-color: rgba(166, 227, 161, 0.12);
    color: #a6e3a1;
    border: 1px solid rgba(166, 227, 161, 0.25);
}
QPushButton#pull_btn:hover {
    background-color: rgba(166, 227, 161, 0.22);
    border-color: #a6e3a1;
}
QPushButton#details_btn {
    background-color: rgba(180, 190, 254, 0.12);
    color: #b4befe;
    border: 1px solid rgba(180, 190, 254, 0.25);
}
QPushButton#details_btn:hover {
    background-color: rgba(180, 190, 254, 0.22);
    border-color: #b4befe;
}

/* ---- Inputs ---- */
QLineEdit {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 8px;
    padding: 7px 12px;
    font-size: 10pt;
    selection-background-color: rgba(203, 166, 247, 0.3);
}
QLineEdit:focus {
    border-color: #cba6f7;
    background-color: #313244;
}
QLineEdit#search_input {
    background-color: #181825;
    border: 1px solid #313244;
    padding-left: 12px;
}
QLineEdit#search_input:focus {
    border-color: #45475a;
    background-color: #1e1e2e;
}

/* ---- Labels ---- */
QLabel {
    background-color: transparent;
    color: #cdd6f4;
}

/* ---- Sidebar ---- */
QFrame#sidebar {
    background-color: #181825;
    border-right: 1px solid #313244;
}

/* ---- Game card ---- */
QFrame#game_card {
    background-color: #313244;
    border: 1px solid transparent;
    border-radius: 10px;
}
QFrame#game_card:hover {
    background-color: #3d3f59;
    border-color: rgba(203, 166, 247, 0.35);
}

/* ---- Dialog ---- */
QDialogButtonBox QPushButton {
    min-width: 80px;
    padding: 7px 18px;
}

/* ---- Splitter ---- */
QSplitter::handle {
    background: #313244;
}
"""


def apply_theme(app: QApplication) -> None:
    """Apply the dark stylesheet to the QApplication."""
    app.setStyleSheet(_STYLESHEET)
