from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from savesync_bridge.core import manifest as manifest_module
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


def _format_dt_short(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%b %d, %Y %I:%M %p")


def _format_file_dates(game: Game) -> str:
    """Return a compact string with oldest-created and latest-modified dates."""
    m = game.local_manifest
    if m is None:
        return ""
    oldest = manifest_module.oldest_known_created(m)
    latest = manifest_module.latest_modified(m)
    parts: list[str] = []
    if oldest is not None:
        parts.append(f"Created: {_format_dt_short(oldest)}")
    if latest is not None:
        parts.append(f"Modified: {_format_dt_short(latest)}")
    return "  ·  ".join(parts)


def _fresh_local_save_warning(game: Game) -> str | None:
    if game.local_manifest is None or game.cloud_manifest is None:
        return None
    if manifest_module.recommend_lineage(game.local_manifest, game.cloud_manifest) != "cloud":
        return None
    return "Fresh local save detected. Cloud looks like the older save lineage."


class GameCard(QFrame):
    """Card widget representing a single game with sync controls."""

    sync_requested = Signal(str)
    exclude_toggled = Signal(str, bool)  # game_id, excluded

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

        # File dates row (created / modified)
        self._file_dates_label = QLabel()
        self._file_dates_label.setStyleSheet(
            f"font-size: 8pt; color: {DARK_PALETTE['text_dim']};"
            "background: transparent; border: none;"
        )
        info_col.addWidget(self._file_dates_label)

        # Confidence label
        self._confidence_label = QLabel()
        self._confidence_label.setStyleSheet(
            "font-size: 8pt; padding: 2px 6px; border-radius: 4px;"
            "background: transparent; border: none;"
        )
        self._confidence_label.setVisible(False)
        info_col.addWidget(self._confidence_label)

        self._warning_label = QLabel()
        self._warning_label.setWordWrap(True)
        self._warning_label.setVisible(False)
        self._warning_label.setStyleSheet(
            "font-size: 9pt; padding: 6px 8px; border-radius: 8px;"
            "background: rgba(250, 179, 135, 0.10);"
            "border: 1px solid rgba(250, 179, 135, 0.28);"
            f"color: {DARK_PALETTE['text']};"
        )
        info_col.addWidget(self._warning_label)

        outer.addLayout(info_col)
        outer.addStretch()

        # Badge + action buttons
        right = QHBoxLayout()
        right.setSpacing(8)

        self._badge = StatusBadge(SyncStatus.UNKNOWN)
        right.addWidget(self._badge)

        self._exclude_cb = QCheckBox()
        self._exclude_cb.setToolTip("Exclude this game from sync")
        self._exclude_cb.setStyleSheet(
            "QCheckBox { spacing: 0px; background: transparent; border: none; }"
            "QCheckBox::indicator { width: 16px; height: 16px; }"
        )
        right.addWidget(self._exclude_cb)

        self._sync_btn = QPushButton("\u21bb Sync")
        self._sync_btn.setObjectName("sync_btn")
        self._sync_btn.setToolTip("Smart sync: push, pull, or show conflict dialog as needed")

        self._sync_btn.setFixedHeight(30)
        self._sync_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        right.addWidget(self._sync_btn)

        self._sync_btn.clicked.connect(lambda: self.sync_requested.emit(self._game.id))
        self._exclude_cb.toggled.connect(self._on_exclude_toggled)

        outer.addLayout(right)

    def _on_exclude_toggled(self, checked: bool) -> None:
        self.exclude_toggled.emit(self._game.id, checked)
        self._sync_btn.setEnabled(not checked)
        self._sync_btn.setStyleSheet(
            "opacity: 0.4;" if checked else ""
        )

    def update_game(self, game: Game) -> None:
        """Refresh displayed data from *game*."""
        self._game = game
        self._name_label.setText(game.name)
        self._sync_label.setText(_format_last_sync(game))
        self._date_label.setText(_format_sync_date(game))

        # File dates
        file_dates_text = _format_file_dates(game)
        self._file_dates_label.setText(file_dates_text)
        self._file_dates_label.setVisible(bool(file_dates_text))

        # Confidence scoring
        if game.local_manifest is not None and game.cloud_manifest is not None:
            confidence = manifest_module.compute_confidence(
                game.local_manifest, game.cloud_manifest,
            )
            color_map = {"High": "#a6e3a1", "Medium": "#f9e2af", "Low": "#f38ba8"}
            color = color_map.get(confidence.label, DARK_PALETTE["text_dim"])
            self._confidence_label.setText(
                f"Confidence: {confidence.label} ({confidence.score:.0%})"
            )
            self._confidence_label.setStyleSheet(
                f"font-size: 8pt; color: {color}; padding: 2px 6px;"
                "border-radius: 4px; background: transparent; border: none;"
            )
            self._confidence_label.setVisible(True)
        else:
            self._confidence_label.setVisible(False)

        warning = _fresh_local_save_warning(game)
        self._warning_label.setText(warning or "")
        self._warning_label.setVisible(warning is not None)
        self._badge.set_status(game.status)
        # Update exclude checkbox without retriggering signal
        self._exclude_cb.blockSignals(True)
        self._exclude_cb.setChecked(game.excluded)
        self._exclude_cb.blockSignals(False)
        self._sync_btn.setEnabled(not game.excluded)
