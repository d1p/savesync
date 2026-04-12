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
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} hr ago"
    return f"{seconds // 86400} days ago"


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
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(12)

        # Game icon
        icon = QLabel("🎮")
        icon.setStyleSheet("font-size: 24pt; background: transparent;")
        icon.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        icon.setFixedWidth(36)
        outer.addWidget(icon)

        # Name + last-sync column
        info_col = QVBoxLayout()
        info_col.setSpacing(2)

        self._name_label = QLabel()
        self._name_label.setStyleSheet(
            "font-size: 13pt; font-weight: bold; background: transparent; color: #cdd6f4;"
        )
        self._sync_label = QLabel()
        self._sync_label.setStyleSheet(
            f"font-size: 10pt; color: {DARK_PALETTE['text_dim']}; background: transparent;"
        )
        info_col.addWidget(self._name_label)
        info_col.addWidget(self._sync_label)
        outer.addLayout(info_col)

        outer.addStretch()

        # Badge + action buttons
        right = QHBoxLayout()
        right.setSpacing(6)

        self._badge = StatusBadge(SyncStatus.UNKNOWN)
        right.addWidget(self._badge)

        self._push_btn = QPushButton("⬆ Push")
        self._pull_btn = QPushButton("⬇ Pull")
        self._details_btn = QPushButton("≡ Details")

        for btn in (self._push_btn, self._pull_btn, self._details_btn):
            btn.setFixedHeight(28)
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
        self._badge.set_status(game.status)
