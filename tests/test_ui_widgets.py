from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from savesync_bridge.core.config import AppConfig
from savesync_bridge.models.game import Game, GameManifest, Platform, SaveFile, SyncStatus
from savesync_bridge.ui.conflict_dialog import ConflictDialog
from savesync_bridge.ui.settings_dialog import SettingsDialog
from savesync_bridge.ui.theme import STATUS_COLORS, STATUS_LABELS
from savesync_bridge.ui.widgets.game_card import GameCard
from savesync_bridge.ui.widgets.game_list import GameListWidget
from savesync_bridge.ui.widgets.status_badge import StatusBadge

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 12, 10, 0, 0, tzinfo=timezone.utc)
_EARLIER = datetime(2026, 4, 10, 8, 0, 0, tzinfo=timezone.utc)


def _save_file(path: str, size: int = 512) -> SaveFile:
    return SaveFile(path=path, size=size, modified=_NOW)


@pytest.fixture()
def sample_game() -> Game:
    return Game(id="game1", name="Test Game", status=SyncStatus.SYNCED)


@pytest.fixture()
def local_manifest() -> GameManifest:
    return GameManifest(
        game_id="game1",
        host=Platform.WINDOWS,
        timestamp=_EARLIER,
        hash="sha256:aaa",
        files=(
            _save_file("save.dat", 1024),
            _save_file("config.ini", 256),
        ),
    )


@pytest.fixture()
def cloud_manifest() -> GameManifest:
    return GameManifest(
        game_id="game1",
        host=Platform.LINUX,
        timestamp=_NOW,
        hash="sha256:bbb",
        files=(
            _save_file("save.dat", 2048),
        ),
    )


@pytest.fixture()
def sample_config() -> AppConfig:
    return AppConfig(
        rclone_remote="myremote",
        s3_bucket="mybucket",
        s3_prefix="myprefix",
        ludusavi_path="/usr/bin/ludusavi",
        rclone_path=None,
    )


# ---------------------------------------------------------------------------
# StatusBadge tests
# ---------------------------------------------------------------------------


def test_status_badge_initial_text(qtbot):
    """StatusBadge displays the correct label for the initial status."""
    badge = StatusBadge(SyncStatus.SYNCED)
    qtbot.addWidget(badge)
    assert badge.text() == STATUS_LABELS[SyncStatus.SYNCED]


def test_status_badge_set_status_updates_text(qtbot):
    """set_status changes the displayed text."""
    badge = StatusBadge(SyncStatus.SYNCED)
    qtbot.addWidget(badge)

    badge.set_status(SyncStatus.CONFLICT)

    assert badge.text() == STATUS_LABELS[SyncStatus.CONFLICT]


def test_status_badge_set_status_updates_stylesheet(qtbot):
    """set_status embeds the correct colour into the stylesheet."""
    badge = StatusBadge(SyncStatus.UNKNOWN)
    qtbot.addWidget(badge)

    badge.set_status(SyncStatus.LOCAL_NEWER)

    expected_color = STATUS_COLORS[SyncStatus.LOCAL_NEWER]
    assert expected_color in badge.styleSheet()


def test_status_badge_all_statuses(qtbot):
    """StatusBadge can be set to every SyncStatus without error."""
    badge = StatusBadge(SyncStatus.UNKNOWN)
    qtbot.addWidget(badge)

    for status in SyncStatus:
        badge.set_status(status)
        assert badge.text() == STATUS_LABELS[status]


# ---------------------------------------------------------------------------
# GameCard tests
# ---------------------------------------------------------------------------


def test_game_card_push_signal(qtbot, sample_game):
    """Clicking Push emits push_requested with the correct game_id."""
    card = GameCard(sample_game)
    qtbot.addWidget(card)

    emitted: list[str] = []
    card.push_requested.connect(emitted.append)

    qtbot.mouseClick(card._push_btn, Qt.MouseButton.LeftButton)

    assert emitted == ["game1"]


def test_game_card_pull_signal(qtbot, sample_game):
    """Clicking Pull emits pull_requested with the correct game_id."""
    card = GameCard(sample_game)
    qtbot.addWidget(card)

    emitted: list[str] = []
    card.pull_requested.connect(emitted.append)

    qtbot.mouseClick(card._pull_btn, Qt.MouseButton.LeftButton)

    assert emitted == ["game1"]


def test_game_card_details_signal(qtbot, sample_game):
    """Clicking Details emits details_requested with the correct game_id."""
    card = GameCard(sample_game)
    qtbot.addWidget(card)

    emitted: list[str] = []
    card.details_requested.connect(emitted.append)

    qtbot.mouseClick(card._details_btn, Qt.MouseButton.LeftButton)

    assert emitted == ["game1"]


def test_game_card_update_game_name(qtbot, sample_game):
    """update_game refreshes the displayed game name."""
    card = GameCard(sample_game)
    qtbot.addWidget(card)

    updated = Game(id="game1", name="Renamed Game", status=SyncStatus.LOCAL_NEWER)
    card.update_game(updated)

    assert card._name_label.text() == "Renamed Game"


def test_game_card_update_game_badge(qtbot, sample_game):
    """update_game refreshes the status badge."""
    card = GameCard(sample_game)
    qtbot.addWidget(card)

    updated = Game(id="game1", name="Test Game", status=SyncStatus.CONFLICT)
    card.update_game(updated)

    assert card._badge.text() == STATUS_LABELS[SyncStatus.CONFLICT]


def test_game_card_never_synced_label(qtbot):
    """A game with no local_manifest shows 'Never synced'."""
    game = Game(id="new", name="New Game", status=SyncStatus.UNKNOWN, local_manifest=None)
    card = GameCard(game)
    qtbot.addWidget(card)

    assert card._sync_label.text() == "Never synced"


# ---------------------------------------------------------------------------
# GameListWidget tests
# ---------------------------------------------------------------------------


def _make_games() -> list[Game]:
    return [
        Game(id="g1", name="Alpha", status=SyncStatus.SYNCED),
        Game(id="g2", name="Beta", status=SyncStatus.LOCAL_NEWER),
        Game(id="g3", name="Gamma", status=SyncStatus.CONFLICT),
    ]


def test_game_list_set_games_populates_cards(qtbot):
    """set_games creates a card for each game."""
    widget = GameListWidget()
    qtbot.addWidget(widget)

    widget.set_games(_make_games())

    assert set(widget._cards.keys()) == {"g1", "g2", "g3"}


def test_game_list_filter_shows_matching_only(qtbot):
    """set_filter hides cards that don't match the filter status."""
    widget = GameListWidget()
    qtbot.addWidget(widget)
    widget.set_games(_make_games())

    widget.set_filter(SyncStatus.LOCAL_NEWER)

    # isHidden() reflects explicit hide/show; isVisible() also requires parent to be shown
    assert widget._cards["g1"].isHidden()
    assert not widget._cards["g2"].isHidden()
    assert widget._cards["g3"].isHidden()


def test_game_list_filter_none_shows_all(qtbot):
    """set_filter(None) makes all cards visible."""
    widget = GameListWidget()
    qtbot.addWidget(widget)
    widget.set_games(_make_games())

    widget.set_filter(SyncStatus.CONFLICT)  # first hide some
    widget.set_filter(None)  # then show all

    for card in widget._cards.values():
        assert not card.isHidden()


def test_game_list_update_game_refreshes_card(qtbot):
    """update_game updates the existing card without recreating it."""
    widget = GameListWidget()
    qtbot.addWidget(widget)
    widget.set_games(_make_games())

    original_card = widget._cards["g1"]
    updated = Game(id="g1", name="Alpha Updated", status=SyncStatus.CLOUD_NEWER)
    widget.update_game(updated)

    # Same card object, updated content
    assert widget._cards["g1"] is original_card
    assert widget._cards["g1"]._name_label.text() == "Alpha Updated"


def test_game_list_replaces_all_on_set_games(qtbot):
    """Calling set_games twice replaces the entire list."""
    widget = GameListWidget()
    qtbot.addWidget(widget)

    widget.set_games(_make_games())
    assert len(widget._cards) == 3

    widget.set_games([Game(id="only", name="Only Game", status=SyncStatus.UNKNOWN)])
    assert list(widget._cards.keys()) == ["only"]


# ---------------------------------------------------------------------------
# ConflictDialog tests
# ---------------------------------------------------------------------------


def test_conflict_dialog_default_choice(qtbot, sample_game, local_manifest, cloud_manifest):
    """Without any user action, get_choice returns KEEP_NEITHER."""
    dlg = ConflictDialog(sample_game, local_manifest, cloud_manifest)
    qtbot.addWidget(dlg)

    assert dlg.get_choice() == ConflictDialog.Choice.KEEP_NEITHER


def test_conflict_dialog_keep_local(qtbot, sample_game, local_manifest, cloud_manifest):
    """Clicking 'Keep Mine' sets KEEP_LOCAL."""
    dlg = ConflictDialog(sample_game, local_manifest, cloud_manifest)
    qtbot.addWidget(dlg)

    keep_mine_btn = _find_button(dlg, "Keep Mine")
    assert keep_mine_btn is not None
    qtbot.mouseClick(keep_mine_btn, Qt.MouseButton.LeftButton)

    assert dlg.get_choice() == ConflictDialog.Choice.KEEP_LOCAL


def test_conflict_dialog_keep_cloud(qtbot, sample_game, local_manifest, cloud_manifest):
    """Clicking 'Keep Cloud' sets KEEP_CLOUD."""
    dlg = ConflictDialog(sample_game, local_manifest, cloud_manifest)
    qtbot.addWidget(dlg)

    keep_cloud_btn = _find_button(dlg, "Keep Cloud")
    assert keep_cloud_btn is not None
    qtbot.mouseClick(keep_cloud_btn, Qt.MouseButton.LeftButton)

    assert dlg.get_choice() == ConflictDialog.Choice.KEEP_CLOUD


def test_conflict_dialog_cancel(qtbot, sample_game, local_manifest, cloud_manifest):
    """Clicking 'Cancel' keeps KEEP_NEITHER."""
    dlg = ConflictDialog(sample_game, local_manifest, cloud_manifest)
    qtbot.addWidget(dlg)

    cancel_btn = _find_button(dlg, "Cancel (Do Nothing)")
    assert cancel_btn is not None
    qtbot.mouseClick(cancel_btn, Qt.MouseButton.LeftButton)

    assert dlg.get_choice() == ConflictDialog.Choice.KEEP_NEITHER


def test_conflict_dialog_window_title(qtbot, sample_game, local_manifest, cloud_manifest):
    """Dialog title includes the game name."""
    dlg = ConflictDialog(sample_game, local_manifest, cloud_manifest)
    qtbot.addWidget(dlg)

    assert sample_game.name in dlg.windowTitle()


# ---------------------------------------------------------------------------
# SettingsDialog tests
# ---------------------------------------------------------------------------


def test_settings_dialog_populates_from_config(qtbot, sample_config):
    """Fields are pre-filled from the supplied AppConfig."""
    dlg = SettingsDialog(sample_config)
    qtbot.addWidget(dlg)

    assert dlg._rclone_remote.text() == "myremote"
    assert dlg._s3_bucket.text() == "mybucket"
    assert dlg._s3_prefix.text() == "myprefix"
    assert dlg._ludusavi_path.text() == "/usr/bin/ludusavi"
    assert dlg._rclone_path.text() == ""


def test_settings_dialog_get_config_returns_current_values(qtbot, sample_config):
    """get_config reflects edits made to dialog fields."""
    dlg = SettingsDialog(sample_config)
    qtbot.addWidget(dlg)

    dlg._s3_bucket.setText("new-bucket")
    dlg._rclone_remote.setText("other-remote")

    cfg = dlg.get_config()

    assert cfg.s3_bucket == "new-bucket"
    assert cfg.rclone_remote == "other-remote"
    assert cfg.s3_prefix == "myprefix"  # unchanged


def test_settings_dialog_empty_paths_become_none(qtbot, sample_config):
    """Blank path fields are converted to None by get_config."""
    dlg = SettingsDialog(sample_config)
    qtbot.addWidget(dlg)

    dlg._ludusavi_path.setText("")
    cfg = dlg.get_config()

    assert cfg.ludusavi_path is None


def test_settings_dialog_preserves_known_games(qtbot):
    """get_config preserves known_games from the original config."""
    config = AppConfig(known_games=["Game A", "Game B"])
    dlg = SettingsDialog(config)
    qtbot.addWidget(dlg)

    cfg = dlg.get_config()

    assert cfg.known_games == ["Game A", "Game B"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_button(parent: object, text: str) -> QPushButton | None:
    """Find the first QPushButton with matching text under *parent*."""
    from PySide6.QtWidgets import QWidget

    if not isinstance(parent, QWidget):
        return None
    for btn in parent.findChildren(QPushButton):
        if btn.text() == text:
            return btn
    return None
