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
QMainWindow, QDialog {
    background-color: #1e1e2e;
    color: #cdd6f4;
}
QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-size: 11pt;
}
QScrollArea {
    border: none;
    background-color: #1e1e2e;
}
QScrollArea > QWidget > QWidget {
    background-color: #1e1e2e;
}
QScrollBar:vertical {
    background-color: #181825;
    width: 8px;
    border-radius: 4px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background-color: #45475a;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    background-color: #181825;
    height: 8px;
    border-radius: 4px;
    margin: 0px;
}
QScrollBar::handle:horizontal {
    background-color: #45475a;
    border-radius: 4px;
    min-width: 20px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
QToolBar {
    background-color: #181825;
    border-bottom: 1px solid #45475a;
    spacing: 6px;
    padding: 4px 8px;
}
QToolButton {
    background-color: transparent;
    color: #cdd6f4;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 11pt;
}
QToolButton:hover {
    background-color: #313244;
    border-color: #45475a;
}
QToolButton:pressed {
    background-color: #45475a;
}
QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 4px 12px;
    font-size: 10pt;
}
QPushButton:hover {
    background-color: #3d3f59;
    border-color: #cba6f7;
}
QPushButton:pressed {
    background-color: #45475a;
}
QPushButton:checked {
    background-color: #45475a;
    border-color: #cba6f7;
    color: #cba6f7;
}
QPushButton#accent_btn {
    background-color: #cba6f7;
    color: #1e1e2e;
    border: none;
    font-weight: bold;
    padding: 6px 16px;
}
QPushButton#accent_btn:hover {
    background-color: #d8b4fe;
}
QPushButton#accent_btn:pressed {
    background-color: #b89ae8;
}
QLineEdit {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 11pt;
}
QLineEdit:focus {
    border-color: #cba6f7;
}
QLabel {
    background-color: transparent;
    color: #cdd6f4;
}
QFrame#sidebar {
    background-color: #181825;
    border-right: 1px solid #45475a;
}
QFrame#game_card {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
}
QFrame#game_card:hover {
    background-color: #3d3f59;
    border-color: #cba6f7;
}
QDialogButtonBox QPushButton {
    min-width: 80px;
    padding: 6px 16px;
}
"""


def apply_theme(app: QApplication) -> None:
    """Apply the dark stylesheet to the QApplication."""
    app.setStyleSheet(_STYLESHEET)
