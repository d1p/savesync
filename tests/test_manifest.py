from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from savesync_bridge.core.manifest import compare, from_json, to_json
from savesync_bridge.models.game import GameManifest, Platform, SaveFile, SyncStatus

_UTC = timezone.utc
_T0 = datetime(2026, 4, 12, 10, 0, 0, tzinfo=_UTC)
_T1 = _T0 + timedelta(hours=1)
_T2 = _T0 + timedelta(hours=2)


def _sf(path: str = "save.dat", size: int = 512) -> SaveFile:
    return SaveFile(path=path, size=size, modified=_T0)


def _manifest(
    game_id: str = "Celeste",
    host: Platform = Platform.WINDOWS,
    timestamp: datetime = _T0,
    hash_: str = "sha256:aabbcc",
    files: tuple[SaveFile, ...] = (),
) -> GameManifest:
    return GameManifest(
        game_id=game_id,
        host=host,
        timestamp=timestamp,
        hash=hash_,
        files=files,
    )


# ---------------------------------------------------------------------------
# to_json / from_json round-trip
# ---------------------------------------------------------------------------


def test_to_json_produces_string() -> None:
    m = _manifest(files=(_sf(),))
    result = to_json(m)
    assert isinstance(result, str)
    assert "Celeste" in result


def test_round_trip_empty_files() -> None:
    m = _manifest()
    assert from_json(to_json(m)) == m


def test_round_trip_with_files() -> None:
    sf1 = SaveFile(path="slot1/save.dat", size=1024, modified=_T1)
    sf2 = SaveFile(path="slot2/save.dat", size=2048, modified=_T2)
    m = _manifest(
        game_id="Hades",
        host=Platform.STEAM_DECK,
        timestamp=_T2,
        hash_="sha256:deadbeef",
        files=(sf1, sf2),
    )
    restored = from_json(to_json(m))
    assert restored == m


def test_round_trip_preserves_timezone() -> None:
    m = _manifest(timestamp=_T1)
    restored = from_json(to_json(m))
    assert restored.timestamp.tzinfo is not None
    assert restored.timestamp == _T1


def test_round_trip_platform_enum() -> None:
    for platform in Platform:
        m = _manifest(host=platform)
        assert from_json(to_json(m)).host == platform


def test_from_json_invalid_raises() -> None:
    with pytest.raises(Exception):
        from_json("not valid json")


def test_json_contains_expected_keys() -> None:
    import json

    m = _manifest()
    obj = json.loads(to_json(m))
    assert "game_id" in obj
    assert "host" in obj
    assert "timestamp" in obj
    assert "hash" in obj
    assert "files" in obj


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------


def test_compare_synced_same_hash() -> None:
    m1 = _manifest(timestamp=_T1, hash_="sha256:same")
    m2 = _manifest(timestamp=_T2, hash_="sha256:same")
    assert compare(m1, m2) == SyncStatus.SYNCED


def test_compare_local_newer() -> None:
    local = _manifest(timestamp=_T2, hash_="sha256:local")
    cloud = _manifest(timestamp=_T1, hash_="sha256:cloud")
    assert compare(local, cloud) == SyncStatus.LOCAL_NEWER


def test_compare_cloud_newer() -> None:
    local = _manifest(timestamp=_T1, hash_="sha256:local")
    cloud = _manifest(timestamp=_T2, hash_="sha256:cloud")
    assert compare(local, cloud) == SyncStatus.CLOUD_NEWER


def test_compare_conflict_same_timestamp_different_hash() -> None:
    """Both sides modified independently; timestamps are equal but hashes differ."""
    local = _manifest(timestamp=_T1, hash_="sha256:localmod")
    cloud = _manifest(timestamp=_T1, hash_="sha256:cloudmod")
    assert compare(local, cloud) == SyncStatus.CONFLICT


def test_compare_returns_sync_status_instance() -> None:
    m1 = _manifest()
    m2 = _manifest()
    result = compare(m1, m2)
    assert isinstance(result, SyncStatus)
