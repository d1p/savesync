from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from savesync_bridge.core.game_cache import load_games, save_games
from savesync_bridge.core.manifest import to_json
from savesync_bridge.models.game import Game, GameManifest, Platform, SaveFile


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    games = [
        Game(id="GameA", name="Game A", steam_app_id="123", save_paths=("/a",)),
        Game(id="GameB", name="Game B"),
    ]
    save_games(games, tmp_path)
    loaded = load_games(tmp_path)
    assert len(loaded) == 2
    assert loaded[0].id == "GameA"
    assert loaded[0].name == "Game A"
    assert loaded[0].steam_app_id == "123"
    assert loaded[0].save_paths == ("/a",)
    assert loaded[1].id == "GameB"


def test_load_returns_empty_when_missing(tmp_path: Path) -> None:
    assert load_games(tmp_path) == []


def test_load_attaches_local_manifest(tmp_path: Path) -> None:
    state_dir = tmp_path / "states"
    state_dir.mkdir()

    manifest = GameManifest(
        game_id="GameA",
        host=Platform.WINDOWS,
        timestamp=datetime(2025, 6, 1, tzinfo=UTC),
        hash="sha256:abc",
        files=(SaveFile(path="save.dat", size=100, modified=datetime(2025, 6, 1, tzinfo=UTC)),),
    )
    (state_dir / "GameA.json").write_text(to_json(manifest), encoding="utf-8")

    games = [Game(id="GameA", name="Game A")]
    save_games(games, tmp_path)
    loaded = load_games(tmp_path, state_dir=state_dir)
    assert loaded[0].local_manifest is not None
    assert loaded[0].local_manifest.game_id == "GameA"


def test_load_handles_corrupt_cache(tmp_path: Path) -> None:
    (tmp_path / "game_cache.json").write_text("not json", encoding="utf-8")
    assert load_games(tmp_path) == []


def test_save_and_load_preserves_excluded(tmp_path: Path) -> None:
    games = [
        Game(id="GameA", name="Game A", excluded=True),
        Game(id="GameB", name="Game B", excluded=False),
    ]
    save_games(games, tmp_path)
    loaded = load_games(tmp_path)
    assert loaded[0].excluded is True
    assert loaded[1].excluded is False
