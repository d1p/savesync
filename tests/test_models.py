from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from savesync_bridge.models.game import (
    Game,
    GameManifest,
    Platform,
    SaveFile,
    SyncStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = timezone.utc

_NOW = datetime(2026, 4, 12, 10, 0, 0, tzinfo=_UTC)


def _save_file(path: str = "save.dat", size: int = 1024) -> SaveFile:
    return SaveFile(path=path, size=size, modified=_NOW)


def _manifest(
    game_id: str = "TestGame",
    host: Platform = Platform.WINDOWS,
    hash_: str = "sha256:abc123",
    files: tuple[SaveFile, ...] = (),
) -> GameManifest:
    return GameManifest(
        game_id=game_id,
        host=host,
        timestamp=_NOW,
        hash=hash_,
        files=files,
    )


# ---------------------------------------------------------------------------
# Platform
# ---------------------------------------------------------------------------


def test_platform_values() -> None:
    assert Platform.WINDOWS.value == "windows"
    assert Platform.LINUX.value == "linux"
    assert Platform.STEAM_DECK.value == "steam_deck"


def test_platform_members_all_present() -> None:
    members = {p.value for p in Platform}
    assert members == {"windows", "linux", "steam_deck"}


# ---------------------------------------------------------------------------
# SyncStatus
# ---------------------------------------------------------------------------


def test_sync_status_values() -> None:
    assert SyncStatus.SYNCED.value == "synced"
    assert SyncStatus.LOCAL_NEWER.value == "local_newer"
    assert SyncStatus.CLOUD_NEWER.value == "cloud_newer"
    assert SyncStatus.CONFLICT.value == "conflict"
    assert SyncStatus.UNKNOWN.value == "unknown"


def test_sync_status_equality() -> None:
    assert SyncStatus.SYNCED == SyncStatus.SYNCED
    assert SyncStatus.LOCAL_NEWER != SyncStatus.CLOUD_NEWER


# ---------------------------------------------------------------------------
# SaveFile
# ---------------------------------------------------------------------------


def test_save_file_construction() -> None:
    sf = SaveFile(path="slot1/save.dat", size=2048, modified=_NOW)
    assert sf.path == "slot1/save.dat"
    assert sf.size == 2048
    assert sf.modified == _NOW


def test_save_file_is_frozen() -> None:
    sf = _save_file()
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        sf.path = "other.dat"  # type: ignore[misc]


def test_save_file_datetime_must_be_timezone_aware() -> None:
    """Verify that our construction uses a timezone-aware datetime."""
    sf = _save_file()
    assert sf.modified.tzinfo is not None


# ---------------------------------------------------------------------------
# GameManifest
# ---------------------------------------------------------------------------


def test_game_manifest_construction() -> None:
    sf = _save_file()
    m = GameManifest(
        game_id="Celeste",
        host=Platform.STEAM_DECK,
        timestamp=_NOW,
        hash="sha256:deadbeef",
        files=(sf,),
    )
    assert m.game_id == "Celeste"
    assert m.host == Platform.STEAM_DECK
    assert m.hash == "sha256:deadbeef"
    assert len(m.files) == 1
    assert m.files[0] is sf


def test_game_manifest_is_frozen() -> None:
    m = _manifest()
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        m.game_id = "Other"  # type: ignore[misc]


def test_game_manifest_files_is_tuple() -> None:
    sf = _save_file()
    m = _manifest(files=(sf,))
    assert isinstance(m.files, tuple)


def test_game_manifest_empty_files() -> None:
    m = _manifest(files=())
    assert m.files == ()


# ---------------------------------------------------------------------------
# Game
# ---------------------------------------------------------------------------


def test_game_construction_minimal() -> None:
    g = Game(id="celeste", name="Celeste")
    assert g.id == "celeste"
    assert g.name == "Celeste"
    assert g.steam_app_id is None
    assert g.save_paths == ()
    assert g.status == SyncStatus.UNKNOWN
    assert g.local_manifest is None
    assert g.cloud_manifest is None


def test_game_construction_full() -> None:
    m_local = _manifest(host=Platform.WINDOWS)
    m_cloud = _manifest(host=Platform.STEAM_DECK)
    g = Game(
        id="celeste",
        name="Celeste",
        steam_app_id="504230",
        save_paths=("%LOCALAPPDATA%/Celeste",),
        status=SyncStatus.SYNCED,
        local_manifest=m_local,
        cloud_manifest=m_cloud,
    )
    assert g.steam_app_id == "504230"
    assert g.save_paths == ("%LOCALAPPDATA%/Celeste",)
    assert g.status == SyncStatus.SYNCED
    assert g.local_manifest is m_local
    assert g.cloud_manifest is m_cloud


def test_game_is_frozen() -> None:
    g = Game(id="x", name="X")
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        g.name = "Y"  # type: ignore[misc]


def test_game_save_paths_is_tuple() -> None:
    g = Game(id="x", name="X", save_paths=("%APPDATA%/X",))
    assert isinstance(g.save_paths, tuple)
