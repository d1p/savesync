"""Persist and restore the last-known game list between sessions."""
from __future__ import annotations

import json
from pathlib import Path

from savesync_bridge.core import manifest as manifest_module
from savesync_bridge.models.game import Game, GameManifest


def _cache_file(config_dir: Path) -> Path:
    return config_dir / "game_cache.json"


def save_games(games: list[Game], config_dir: Path) -> None:
    """Write *games* to a JSON cache file."""
    config_dir.mkdir(parents=True, exist_ok=True)
    data = [
        {
            "id": g.id,
            "name": g.name,
            "steam_app_id": g.steam_app_id,
            "wine_prefix": g.wine_prefix,
            "wine_user": g.wine_user,
            "save_paths": list(g.save_paths),
            "excluded": g.excluded,
        }
        for g in games
    ]
    _cache_file(config_dir).write_text(
        json.dumps(data, indent=2), encoding="utf-8",
    )


def load_games(config_dir: Path, state_dir: Path | None = None) -> list[Game]:
    """Load cached games, attaching local manifests if available."""
    path = _cache_file(config_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    games: list[Game] = []
    for entry in data:
        local_manifest = _load_local_manifest(entry["id"], state_dir) if state_dir else None
        games.append(
            Game(
                id=entry["id"],
                name=entry["name"],
                steam_app_id=entry.get("steam_app_id"),
                wine_prefix=entry.get("wine_prefix"),
                wine_user=entry.get("wine_user"),
                save_paths=tuple(entry.get("save_paths", ())),
                excluded=entry.get("excluded", False),
                local_manifest=local_manifest,
            )
        )
    return games


def _load_local_manifest(game_id: str, state_dir: Path | None) -> GameManifest | None:
    if state_dir is None:
        return None
    path = state_dir / f"{game_id}.json"
    if not path.exists():
        return None
    try:
        return manifest_module.from_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def prune_stale_games(games: list[Game]) -> tuple[list[Game], list[str]]:
    """Remove games whose save paths no longer exist on disk.

    Returns:
        A tuple of (active_games, pruned_game_ids).
    """
    active: list[Game] = []
    pruned: list[str] = []
    for g in games:
        if not g.save_paths:
            # Games with no save paths are kept (cloud-only entries)
            active.append(g)
            continue
        if any(Path(p).exists() for p in g.save_paths):
            active.append(g)
        else:
            pruned.append(g.id)
    return active, pruned
