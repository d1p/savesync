from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from savesync_bridge.models.game import Game, SyncStatus
from savesync_bridge.ui.widgets.game_card import GameCard


class GameListWidget(QScrollArea):
    """Scrollable list of GameCard widgets with optional status filter."""

    push_requested = Signal(str)
    pull_requested = Signal(str)
    details_requested = Signal(str)

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout.setSpacing(8)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self.setWidget(self._container)

        self._cards: dict[str, GameCard] = {}
        self._games: dict[str, Game] = {}
        self._filter: SyncStatus | None = None

    def set_games(self, games: list[Game]) -> None:
        """Replace the entire game list with *games*."""
        for card in self._cards.values():
            self._layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        self._games.clear()

        for game in games:
            card = GameCard(game)
            card.push_requested.connect(self.push_requested)
            card.pull_requested.connect(self.pull_requested)
            card.details_requested.connect(self.details_requested)
            self._layout.addWidget(card)
            self._cards[game.id] = card
            self._games[game.id] = game

        self._apply_filter()

    def update_game(self, game: Game) -> None:
        """Refresh the card for *game* if it is already in the list."""
        if game.id in self._cards:
            self._cards[game.id].update_game(game)
            self._games[game.id] = game
            self._apply_filter()

    def set_filter(self, filter_status: SyncStatus | None) -> None:
        """Show only cards matching *filter_status*; ``None`` shows all."""
        self._filter = filter_status
        self._apply_filter()

    def _apply_filter(self) -> None:
        for game_id, card in self._cards.items():
            if self._filter is None:
                card.setVisible(True)
            else:
                card.setVisible(self._games[game_id].status == self._filter)
