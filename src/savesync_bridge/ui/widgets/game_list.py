from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from savesync_bridge.models.game import Game, SyncStatus
from savesync_bridge.ui.widgets.game_card import GameCard


class GameListWidget(QWidget):
    """Scrollable list of GameCard widgets with search and status filter."""

    sync_requested = Signal(str)
    exclude_toggled = Signal(str, bool)  # game_id, excluded
    force_push_requested = Signal(str)
    force_pull_requested = Signal(str)
    verify_requested = Signal(str)

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Header bar: search + count ----
        header = QWidget()
        header.setStyleSheet("background-color: #181825; border-bottom: 1px solid #313244;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 10, 16, 10)
        header_layout.setSpacing(12)

        self._search = QLineEdit()
        self._search.setObjectName("search_input")
        self._search.setPlaceholderText("\U0001f50d  Search games\u2026")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedHeight(34)
        self._search.textChanged.connect(self._on_search_changed)
        header_layout.addWidget(self._search)

        self._count_label = QLabel()
        self._count_label.setStyleSheet(
            "color: #6c7086; font-size: 9pt; background: transparent;"
        )
        header_layout.addWidget(self._count_label)

        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["Name (A-Z)", "Name (Z-A)", "Last Synced", "Status"])
        self._sort_combo.setFixedHeight(30)
        self._sort_combo.setStyleSheet(
            "QComboBox { font-size: 9pt; padding: 2px 6px; background: #313244; "
            "color: #cdd6f4; border: 1px solid #45475a; border-radius: 4px; }"
            "QComboBox::drop-down { border: none; }"
        )
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        header_layout.addWidget(self._sort_combo)

        root.addWidget(header)

        # ---- Scroll area ----
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout.setSpacing(6)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll)

        # ---- Empty state ----
        self._empty_state = QWidget()
        empty_layout = QVBoxLayout(self._empty_state)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        empty_icon = QLabel("\U0001f3ae")
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_icon.setStyleSheet("font-size: 48pt; background: transparent;")
        empty_layout.addWidget(empty_icon)

        empty_title = QLabel("No games found")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_title.setStyleSheet(
            "font-size: 14pt; font-weight: 600; color: #6c7086; background: transparent;"
        )
        empty_layout.addWidget(empty_title)

        empty_hint = QLabel("Click Refresh All to scan for games with Ludusavi")
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint.setStyleSheet(
            "font-size: 10pt; color: #585b70; background: transparent;"
        )
        empty_layout.addWidget(empty_hint)

        root.addWidget(self._empty_state)
        self._empty_state.setVisible(True)
        self._scroll.setVisible(False)

        self._cards: dict[str, GameCard] = {}
        self._games: dict[str, Game] = {}
        self._filter: SyncStatus | None = None
        self._search_text: str = ""
        self._sort_key: str = "Name (A-Z)"

    def set_games(self, games: list[Game]) -> None:
        """Replace the entire game list with *games*."""
        for card in self._cards.values():
            self._layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        self._games.clear()

        for game in games:
            card = GameCard(game)
            card.sync_requested.connect(self.sync_requested)
            card.exclude_toggled.connect(self.exclude_toggled)
            card.force_push_requested.connect(self.force_push_requested)
            card.force_pull_requested.connect(self.force_pull_requested)
            card.verify_requested.connect(self.verify_requested)
            self._layout.addWidget(card)
            self._cards[game.id] = card
            self._games[game.id] = game

        self._apply_sort()
        self._apply_filter()
        self._update_empty_state()

    def update_game(self, game: Game) -> None:
        """Refresh the card for *game* if it is already in the list."""
        if game.id in self._cards:
            self._cards[game.id].update_game(game)
            self._games[game.id] = game
            self._apply_filter()

    def set_filter(self, filter_status: SyncStatus | None | str) -> None:
        """Show only cards matching *filter_status*; ``None`` shows all. ``"excluded"`` shows excluded."""
        self._filter = filter_status
        self._apply_filter()

    def _on_search_changed(self, text: str) -> None:
        self._search_text = text.lower().strip()
        self._apply_filter()

    def _apply_filter(self) -> None:
        visible = 0
        for game_id, card in self._cards.items():
            game = self._games[game_id]
            show = True
            if self._filter == "excluded":
                if not game.excluded:
                    show = False
            elif self._filter is not None and game.status != self._filter:
                show = False
            if self._search_text and self._search_text not in game.name.lower():
                show = False
            card.setVisible(show)
            if show:
                visible += 1
        self._count_label.setText(f"{visible} of {len(self._cards)} games")

    def _update_empty_state(self) -> None:
        has_games = len(self._cards) > 0
        self._empty_state.setVisible(not has_games)
        self._scroll.setVisible(has_games)

    def _on_sort_changed(self, index: int) -> None:
        self._sort_key = self._sort_combo.currentText()
        self._apply_sort()

    def _apply_sort(self) -> None:
        """Re-order card widgets in the layout based on the current sort key."""
        from datetime import datetime

        status_order = {
            SyncStatus.CONFLICT: 0,
            SyncStatus.LOCAL_NEWER: 1,
            SyncStatus.CLOUD_NEWER: 2,
            SyncStatus.UNKNOWN: 3,
            SyncStatus.SYNCED: 4,
        }

        def sort_key(game_id: str):
            game = self._games[game_id]
            if self._sort_key == "Name (Z-A)":
                return game.name.lower()[::-1]
            if self._sort_key == "Last Synced":
                ts = game.local_manifest.timestamp if game.local_manifest else datetime.min
                return ts
            if self._sort_key == "Status":
                return (status_order.get(game.status, 99), game.name.lower())
            return game.name.lower()  # Name (A-Z) default

        reverse = self._sort_key in ("Last Synced",)
        sorted_ids = sorted(self._cards, key=sort_key, reverse=reverse)

        for card_id in sorted_ids:
            card = self._cards[card_id]
            self._layout.removeWidget(card)
            self._layout.addWidget(card)
