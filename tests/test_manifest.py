from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from savesync_bridge.core.manifest import (
    compare,
    compare_meta,
    compute_confidence,
    diff_manifests,
    from_json,
    latest_modified,
    oldest_known_created,
    recommend_lineage,
    sync_meta_from_json,
    sync_meta_to_json,
    to_json,
    append_sync_history,
    load_sync_history,
    AUTO_SYNC_CONFIDENCE_THRESHOLD,
    ConfidenceResult,
    FileDiffEntry,
    ManifestDiff,
    SyncHistoryEntry,
)
from savesync_bridge.models.game import GameManifest, Platform, SaveFile, SyncMeta, SyncStatus

_UTC = UTC
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
    sf1 = SaveFile(path="slot1/save.dat", size=1024, modified=_T1, created=_T0)
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


def test_round_trip_preserves_optional_created_time() -> None:
    m = _manifest(files=(SaveFile(path="save.dat", size=128, modified=_T1, created=_T0),))
    restored = from_json(to_json(m))
    assert restored.files[0].created == _T0


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
    with pytest.raises((json.JSONDecodeError, KeyError, ValueError)):
        from_json("not valid json")


def test_json_contains_expected_keys() -> None:
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


def test_compare_conflict_when_local_timestamp_is_newer_but_hash_differs() -> None:
    local = _manifest(timestamp=_T2, hash_="sha256:local")
    cloud = _manifest(timestamp=_T1, hash_="sha256:cloud")
    assert compare(local, cloud) == SyncStatus.CONFLICT


def test_compare_conflict_when_cloud_timestamp_is_newer_but_hash_differs() -> None:
    local = _manifest(timestamp=_T1, hash_="sha256:local")
    cloud = _manifest(timestamp=_T2, hash_="sha256:cloud")
    assert compare(local, cloud) == SyncStatus.CONFLICT


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


def test_compare_synced_when_hashes_differ_but_all_files_identical_content() -> None:
    """If manifest hashes differ but all files have identical content (only metadata differs), treat as synced."""
    local = _manifest(
        timestamp=_T2,
        hash_="sha256:local",
        files=(
            SaveFile(path="save.dat", size=100, modified=_T2, file_hash="sha256:abc123"),
        ),
    )
    cloud = _manifest(
        timestamp=_T1,
        hash_="sha256:cloud",
        files=(
            SaveFile(path="save.dat", size=100, modified=_T1, file_hash="sha256:abc123"),
        ),
    )
    assert compare(local, cloud) == SyncStatus.SYNCED


def test_oldest_known_created_prefers_created_timestamp() -> None:
    manifest = _manifest(
        files=(
            SaveFile(path="a", size=1, modified=_T2, created=_T1),
            SaveFile(path="b", size=1, modified=_T1, created=_T0),
        )
    )
    assert oldest_known_created(manifest) == _T0


def test_oldest_known_created_falls_back_to_modified_timestamp() -> None:
    manifest = _manifest(
        files=(
            SaveFile(path="a", size=1, modified=_T2),
            SaveFile(path="b", size=1, modified=_T1),
        )
    )
    assert oldest_known_created(manifest) == _T1


def test_latest_modified_returns_most_recent_timestamp() -> None:
    manifest = _manifest(
        files=(
            SaveFile(path="a", size=1, modified=_T0),
            SaveFile(path="b", size=1, modified=_T2),
        )
    )
    assert latest_modified(manifest) == _T2


def test_recommend_lineage_prefers_cloud_when_local_looks_fresh() -> None:
    local = _manifest(
        files=(SaveFile(path="save.dat", size=1, modified=_T1, created=_T1),),
    )
    cloud = _manifest(
        files=(SaveFile(path="save.dat", size=1, modified=_T2, created=_T0),),
    )
    assert recommend_lineage(local, cloud) == "cloud"


def test_recommend_lineage_prefers_local_when_cloud_looks_fresh() -> None:
    local = _manifest(
        files=(SaveFile(path="save.dat", size=1, modified=_T2, created=_T0),),
    )
    cloud = _manifest(
        files=(SaveFile(path="save.dat", size=1, modified=_T1, created=_T1),),
    )
    assert recommend_lineage(local, cloud) == "local"


# ---------------------------------------------------------------------------
# SyncMeta round-trip
# ---------------------------------------------------------------------------


def _sync_meta(
    game_id: str = "Celeste",
    hash_: str = "sha256:aabbcc",
    timestamp: datetime = _T0,
    compressed: bool = True,
    archive_name: str = "save.tar.gz",
    total_size: int = 4096,
) -> SyncMeta:
    return SyncMeta(
        game_id=game_id,
        hash=hash_,
        timestamp=timestamp,
        compressed=compressed,
        archive_name=archive_name,
        total_size=total_size,
    )


def test_sync_meta_round_trip() -> None:
    meta = _sync_meta()
    restored = sync_meta_from_json(sync_meta_to_json(meta))
    assert restored == meta


def test_sync_meta_json_contains_version() -> None:
    meta = _sync_meta()
    obj = json.loads(sync_meta_to_json(meta))
    assert obj["version"] == 2


def test_sync_meta_from_json_legacy_defaults() -> None:
    """Parsing JSON without compressed/archive_name fields uses defaults."""
    data = json.dumps({
        "game_id": "Hades",
        "hash": "sha256:abc",
        "timestamp": _T0.isoformat(),
    })
    meta = sync_meta_from_json(data)
    assert meta.compressed is False
    assert meta.archive_name == ""


# ---------------------------------------------------------------------------
# compare_meta
# ---------------------------------------------------------------------------


def test_compare_meta_synced() -> None:
    local = _manifest(hash_="sha256:same")
    cloud = _sync_meta(hash_="sha256:same")
    assert compare_meta(local, cloud) == SyncStatus.SYNCED


def test_compare_meta_conflict_when_local_timestamp_is_newer_but_hash_differs() -> None:
    local = _manifest(timestamp=_T2, hash_="sha256:local")
    cloud = _sync_meta(timestamp=_T1, hash_="sha256:cloud")
    assert compare_meta(local, cloud) == SyncStatus.CONFLICT


def test_compare_meta_conflict_when_cloud_timestamp_is_newer_but_hash_differs() -> None:
    local = _manifest(timestamp=_T1, hash_="sha256:local")
    cloud = _sync_meta(timestamp=_T2, hash_="sha256:cloud")
    assert compare_meta(local, cloud) == SyncStatus.CONFLICT


def test_compare_meta_conflict() -> None:
    local = _manifest(timestamp=_T1, hash_="sha256:a")
    cloud = _sync_meta(timestamp=_T1, hash_="sha256:b")
    assert compare_meta(local, cloud) == SyncStatus.CONFLICT


# ---------------------------------------------------------------------------
# compute_confidence
# ---------------------------------------------------------------------------

_T_OLD = datetime(2025, 1, 1, 0, 0, 0, tzinfo=_UTC)
_T_RECENT = datetime(2026, 4, 10, 12, 0, 0, tzinfo=_UTC)


def test_confidence_high_when_clear_lineage_and_dir_corroboration() -> None:
    """With clear creation gap, matching modification, and dir scan agreement → high confidence."""
    local = _manifest(
        hash_="sha256:local",
        files=(SaveFile(path="save.dat", size=512, modified=_T_RECENT, created=_T_OLD),),
    )
    cloud = _manifest(
        hash_="sha256:cloud",
        files=(SaveFile(path="save.dat", size=512, modified=_T_RECENT - timedelta(hours=1), created=_T_RECENT - timedelta(days=1)),),
    )
    result = compute_confidence(
        local, cloud,
        local_dir_oldest_created=_T_OLD,
        local_dir_file_count=3,
    )
    assert result.recommendation == "local"
    assert result.score >= AUTO_SYNC_CONFIDENCE_THRESHOLD
    assert result.safe_to_auto_sync is True
    assert result.label == "High"


def test_confidence_low_when_no_creation_dates() -> None:
    """Without creation dates, confidence cannot be high."""
    local = _manifest(
        hash_="sha256:local",
        files=(SaveFile(path="save.dat", size=512, modified=_T1),),
    )
    cloud = _manifest(
        hash_="sha256:cloud",
        files=(SaveFile(path="save.dat", size=512, modified=_T2),),
    )
    result = compute_confidence(local, cloud)
    assert result.score < AUTO_SYNC_CONFIDENCE_THRESHOLD
    assert result.safe_to_auto_sync is False


def test_confidence_capped_when_no_recommendation() -> None:
    """When recommend_lineage returns None, score is capped at 0.3."""
    local = _manifest(
        hash_="sha256:local",
        files=(SaveFile(path="save.dat", size=512, modified=_T1, created=_T0),),
    )
    cloud = _manifest(
        hash_="sha256:cloud",
        files=(SaveFile(path="save.dat", size=512, modified=_T0, created=_T0),),
    )
    result = compute_confidence(local, cloud)
    assert result.score <= 0.3


def test_confidence_medium_when_close_creation_dates() -> None:
    """Close creation dates → moderate confidence."""
    local = _manifest(
        hash_="sha256:local",
        files=(SaveFile(path="save.dat", size=512, modified=_T2, created=_T0),),
    )
    cloud = _manifest(
        hash_="sha256:cloud",
        files=(SaveFile(path="save.dat", size=512, modified=_T1, created=_T0 + timedelta(hours=2)),),
    )
    result = compute_confidence(local, cloud)
    assert 0.3 < result.score < AUTO_SYNC_CONFIDENCE_THRESHOLD


def test_confidence_result_has_reasons() -> None:
    local = _manifest(
        hash_="sha256:local",
        files=(SaveFile(path="save.dat", size=512, modified=_T_RECENT, created=_T_OLD),),
    )
    cloud = _manifest(
        hash_="sha256:cloud",
        files=(SaveFile(path="save.dat", size=512, modified=_T_RECENT, created=_T_RECENT),),
    )
    result = compute_confidence(local, cloud)
    assert len(result.reasons) > 0
    assert all(isinstance(r, str) for r in result.reasons)


def test_confidence_dir_scan_contradicts_lowers_score() -> None:
    """When directory scan contradicts the lineage recommendation, score drops."""
    local = _manifest(
        hash_="sha256:local",
        files=(SaveFile(path="save.dat", size=512, modified=_T_RECENT, created=_T_OLD),),
    )
    cloud = _manifest(
        hash_="sha256:cloud",
        files=(SaveFile(path="save.dat", size=512, modified=_T_RECENT - timedelta(hours=1), created=_T_RECENT - timedelta(days=1)),),
    )
    # With corroborating dir scan
    high = compute_confidence(local, cloud, local_dir_oldest_created=_T_OLD, local_dir_file_count=3)
    # With contradicting dir scan (local dir files are NEWER than cloud creation)
    low = compute_confidence(local, cloud, local_dir_oldest_created=_T_RECENT, local_dir_file_count=3)
    assert high.score > low.score


# ---------------------------------------------------------------------------
# Per-file hash round-trip
# ---------------------------------------------------------------------------


def test_round_trip_preserves_file_hash() -> None:
    sf = SaveFile(path="save.dat", size=512, modified=_T0, file_hash="sha256:abc123")
    m = _manifest(files=(sf,))
    json_str = to_json(m)
    restored = from_json(json_str)
    assert restored.files[0].file_hash == "sha256:abc123"


def test_round_trip_preserves_none_file_hash() -> None:
    sf = SaveFile(path="save.dat", size=512, modified=_T0)
    m = _manifest(files=(sf,))
    json_str = to_json(m)
    restored = from_json(json_str)
    assert restored.files[0].file_hash is None


# ---------------------------------------------------------------------------
# Machine ID round-trip
# ---------------------------------------------------------------------------


def test_round_trip_preserves_machine_id() -> None:
    m = GameManifest(
        game_id="Celeste", host=Platform.WINDOWS, timestamp=_T0,
        hash="sha256:abc", files=(), machine_id="desktop-win",
    )
    json_str = to_json(m)
    restored = from_json(json_str)
    assert restored.machine_id == "desktop-win"


def test_round_trip_machine_id_defaults_empty() -> None:
    m = _manifest()
    json_str = to_json(m)
    restored = from_json(json_str)
    assert restored.machine_id == ""


def test_sync_meta_round_trip_machine_id() -> None:
    meta = SyncMeta(
        game_id="Celeste", hash="sha256:abc", timestamp=_T0,
        compressed=True, archive_name="save.tar.gz", total_size=1024,
        machine_id="deck-linux",
    )
    json_str = sync_meta_to_json(meta)
    restored = sync_meta_from_json(json_str)
    assert restored.machine_id == "deck-linux"


# ---------------------------------------------------------------------------
# Per-file diff
# ---------------------------------------------------------------------------


def test_diff_manifests_identical_files() -> None:
    sf = SaveFile(path="save.dat", size=512, modified=_T0, file_hash="sha256:same")
    local = _manifest(files=(sf,))
    cloud = _manifest(files=(sf,))
    diff = diff_manifests(local, cloud)
    assert diff.total_files == 1
    assert diff.unchanged_count == 1
    assert diff.modified_count == 0


def test_diff_manifests_modified_file() -> None:
    local_f = SaveFile(path="save.dat", size=512, modified=_T0, file_hash="sha256:aaa")
    cloud_f = SaveFile(path="save.dat", size=600, modified=_T1, file_hash="sha256:bbb")
    local = _manifest(files=(local_f,))
    cloud = _manifest(files=(cloud_f,))
    diff = diff_manifests(local, cloud)
    assert diff.modified_count == 1
    assert diff.entries[0].status == "modified"


def test_diff_manifests_added_local() -> None:
    sf = SaveFile(path="new.dat", size=100, modified=_T0, file_hash="sha256:new")
    local = _manifest(files=(sf,))
    cloud = _manifest(files=())
    diff = diff_manifests(local, cloud)
    assert diff.added_local_count == 1
    assert diff.entries[0].status == "added_local"


def test_diff_manifests_added_cloud() -> None:
    sf = SaveFile(path="cloud.dat", size=100, modified=_T0, file_hash="sha256:cloud")
    local = _manifest(files=())
    cloud = _manifest(files=(sf,))
    diff = diff_manifests(local, cloud)
    assert diff.added_cloud_count == 1
    assert diff.entries[0].status == "added_cloud"


def test_diff_manifests_fallback_size_when_no_hash() -> None:
    local_f = SaveFile(path="save.dat", size=512, modified=_T0)
    cloud_f = SaveFile(path="save.dat", size=512, modified=_T1)
    local = _manifest(files=(local_f,))
    cloud = _manifest(files=(cloud_f,))
    diff = diff_manifests(local, cloud)
    assert diff.unchanged_count == 1  # same size → assumed unchanged


def test_diff_manifests_size_difference_counts_as_modified() -> None:
    local_f = SaveFile(path="save.dat", size=512, modified=_T0)
    cloud_f = SaveFile(path="save.dat", size=600, modified=_T1)
    local = _manifest(files=(local_f,))
    cloud = _manifest(files=(cloud_f,))
    diff = diff_manifests(local, cloud)
    assert diff.modified_count == 1


# ---------------------------------------------------------------------------
# Confidence scoring with per-file content match signal
# ---------------------------------------------------------------------------


def test_confidence_includes_content_match_reason() -> None:
    local = _manifest(
        hash_="sha256:local",
        files=(SaveFile(path="save.dat", size=512, modified=_T_RECENT, created=_T_OLD, file_hash="sha256:same"),),
    )
    cloud = _manifest(
        hash_="sha256:cloud",
        files=(SaveFile(path="save.dat", size=512, modified=_T_RECENT, created=_T_RECENT, file_hash="sha256:same"),),
    )
    result = compute_confidence(local, cloud)
    content_reasons = [r for r in result.reasons if "identical content" in r]
    assert len(content_reasons) > 0


# ---------------------------------------------------------------------------
# Sync history
# ---------------------------------------------------------------------------


def test_sync_history_append_and_load(tmp_path) -> None:
    entry = SyncHistoryEntry(
        timestamp="2026-01-01T00:00:00",
        game_id="Celeste",
        action="push",
        machine_id="desktop",
    )
    append_sync_history(tmp_path, entry)
    loaded = load_sync_history(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].game_id == "Celeste"
    assert loaded[0].action == "push"
    assert loaded[0].machine_id == "desktop"


def test_sync_history_limits_entries(tmp_path) -> None:
    for i in range(10):
        entry = SyncHistoryEntry(
            timestamp=f"2026-01-01T00:00:{i:02d}",
            game_id=f"Game{i}",
            action="push",
        )
        append_sync_history(tmp_path, entry, max_entries=5)
    loaded = load_sync_history(tmp_path)
    assert len(loaded) == 5
    assert loaded[0].game_id == "Game5"


def test_sync_history_empty_when_missing(tmp_path) -> None:
    loaded = load_sync_history(tmp_path)
    assert loaded == []
