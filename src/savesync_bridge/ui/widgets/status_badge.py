from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from savesync_bridge.models.game import SyncStatus
from savesync_bridge.ui.theme import STATUS_COLORS, STATUS_LABELS


class StatusBadge(QLabel):
    """Pill-shaped badge displaying a SyncStatus with matching colour."""

    def __init__(self, status: SyncStatus, parent: object = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(26)
        self.set_status(status)

    def set_status(self, status: SyncStatus) -> None:
        """Update the badge text and colour to reflect *status*."""
        color = STATUS_COLORS.get(status, "#6c7086")
        label = STATUS_LABELS.get(status, "UNKNOWN")
        self.setText(label)
        self.setStyleSheet(
            f"background-color: {color}18; "
            f"color: {color}; "
            f"border: 1px solid {color}44; "
            f"border-radius: 13px; "
            f"padding: 2px 12px; "
            f"font-size: 9pt; "
            f"font-weight: 600; "
            f"letter-spacing: 0.5px;"
        )
