from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from savesync_bridge.models.game import Game, SyncStatus
from savesync_bridge.ui.theme import DARK_PALETTE
from savesync_bridge.ui.widgets.status_badge import StatusBadge


def _format_last_sync(game: Game) -> str:
    if game.local_manifest is None:
        return "Never synced"
    ts = game.local_manifest.timestamp
    now = datetime.now(tz=UTC)
    delta = now - ts
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        m = seconds // 60
        return f"{m} min ago"
    if seconds < 86400:
        h = seconds // 3600
        return f"{h} hr ago"
    d = seconds // 86400
    return f"{d} day{'s' if d != 1 else ''} ago"


def _format_sync_date(game: Game) -> str:
    if game.local_manifest is None:
        return ""
    ts = game.local_manifest.timestamp
    return ts.strftime("%b %d, %Y at %I:%M %p")


class GameCard(QFrame):
    """Card widget representing a single game with sync controls."""

    push_requested = Signal(str)
    pull_requested = Signal(str)
    details_requested = Signal(str)

    def __init__(self, game: Game, parent: object = None) -> None:
        super().__init__(parent)
        self.setObjectName("game_card")
        self._game = game
        self._build_ui()
        self.update_game(game)

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(14)

        # Game icon container
        icon_frame = QFrame()
        icon_frame.setFixedSize(44, 44)
        icon_frame.setStyleSheet(
            "background-color: rgba(203, 166, 247, 0.1);"
            "border-radius: 10px; border: none;"
        )
        icon_layout = QVBoxLayout(icon_frame)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon = QLabel("\U0001f3ae")
        icon.setStyleSheet("font-size: 20pt; background: transparent; border: none;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(icon)
        outer.addWidget(icon_frame)

        # Name + sync info column
        info_col = QVBoxLayout()
        info_col.setSpacing(3)

        self._name_label = QLabel()
        self._name_label.setStyleSheet(
            "font-size: 11pt; font-weight: 600; background: transparent;"
            "color: #cdd6f4; border: none;"
        )
        info_col.addWidget(self._name_label)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(12)

        self._sync_label = QLabel()
        self._sync_label.setStyleSheet(
            f"font-size: 9pt; color: {DARK_PALETTE['text_dim']};"
            "background: transparent; border: none;"
        )
        meta_row.addWidget(self._sync_label)

        self._date_label = QLabel()
        self._date_label.setStyleSheet(
            f"font-size: 9pt; color: {DARK_PALETTE['text_dim']};"
            "background: transparent; border: none;"
        )
        meta_row.addWidget(self._date_label)
        meta_row.addStretch()
        info_col.addLayout(meta_row)

        outer.addLayout(info_col)
        outer.addStretch()

        # Badge + action buttons
        right = QHBoxLayout()
        right.setSpacing(8)

        self._badge = StatusBadge(SyncStatus.UNKNOWN)
        right.addWidget(self._badge)

        self._push_btn = QPushButton("\u2b06 Push")
        self._push_btn.setObjectName("push_btn")
        self._push_btn.setToolTip("Upload this game's local save to Google Drive")
        self._pull_btn = QPushButton("\u2b07 Pull")
        self._pull_btn.setObjectName("pull_btn")
        self._pull_btn.setToolTip("Download this game's cloud save and restore it locally")
        self._details_btn = QPushButton("\u2261 Sync")
        self._details_btn.setObjectName("details_btn")
        self._details_btn.setToolTip("Smart sync: push, pull, or show conflict dialog as needed")

        for btn in (self._push_btn, self._pull_btn, self._details_btn):
            btn.setFixedHeight(30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            right.addWidget(btn)

        self._push_btn.clicked.connect(lambda: self.push_requested.emit(self._game.id))
        self._pull_btn.clicked.connect(lambda: self.pull_requested.emit(self._game.id))
        self._details_btn.clicked.connect(lambda: self.details_requested.emit(self._game.id))

        outer.addLayout(right)

    def update_game(self, game: Game) -> None:
        """Refresh displayed data from *game*."""
        self._game = game
        self._name_label.setText(game.name)
        self._sync_label.setText(_format_last_sync(game))
        self._date_label.setText(_format_sync_date(game))
        self._badge.set_status(game.status)
