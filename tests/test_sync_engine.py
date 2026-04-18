from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from savesync_bridge.core import manifest as manifest_module
from savesync_bridge.core.config import AppConfig
from savesync_bridge.core.exceptions import LudusaviError, RcloneError
from savesync_bridge.core.sync_engine import SyncEngine, SyncResult, scan_save_directories
from savesync_bridge.models.game import GameManifest, Platform, SaveFile, SyncStatus
from savesync_bridge.cli.ludusavi import LudusaviGame, SaveFileInfo

GAME_ID = "Hades"


def _make_config() -> AppConfig:
    return AppConfig(
        drive_remote="gdrive",
        drive_root="test-root",
        backup_path="saves",
    )


def _make_manifest(
    game_id: str = GAME_ID,
    host: Platform = Platform.WINDOWS,
    ts: datetime | None = None,
    content_hash: str = "sha256:abc123",
) -> GameManifest:
    if ts is None:
        ts = datetime(2026, 4, 12, 10, 0, 0, tzinfo=UTC)
    return GameManifest(
        game_id=game_id,
        host=host,
        timestamp=ts,
        hash=content_hash,
        files=(
            SaveFile(
                path="Profile1.sav",
                size=1024,
                modified=datetime(2026, 4, 12, 9, 0, 0, tzinfo=UTC),
            ),
        ),
    )


@pytest.fixture()
def config() -> AppConfig:
    return _make_config()


@pytest.fixture()
def engine(config: AppConfig, tmp_path: Path) -> SyncEngine:
    return SyncEngine(
        config=config,
        state_dir=tmp_path / "states",
    )


# ---------------------------------------------------------------------------
# get_cloud_manifest
# ---------------------------------------------------------------------------


class TestGetCloudManifest:
    def test_returns_manifest_when_found(self, engine: SyncEngine) -> None:
        m = _make_manifest()
        json_bytes = manifest_module.to_json(m).encode("utf-8")
        with patch("savesync_bridge.core.sync_engine.rclone") as mock_rclone:
            mock_rclone.read_file.return_value = json_bytes
            result = engine.get_cloud_manifest(GAME_ID)
        assert result is not None
        assert result.game_id == GAME_ID
        assert result.hash == "sha256:abc123"

    def test_calls_read_file_with_correct_key(self, engine: SyncEngine, config: AppConfig) -> None:
        m = _make_manifest()
        json_bytes = manifest_module.to_json(m).encode("utf-8")
        with patch("savesync_bridge.core.sync_engine.rclone") as mock_rclone:
            mock_rclone.read_file.return_value = json_bytes
            engine.get_cloud_manifest(GAME_ID)
        key = mock_rclone.read_file.call_args[1].get("key") or mock_rclone.read_file.call_args[0][2]
        assert GAME_ID in key
        assert "manifest.json" in key

    def test_reads_manifest_without_cli_probe_logging(self, engine: SyncEngine) -> None:
        m = _make_manifest()
        json_bytes = manifest_module.to_json(m).encode("utf-8")
        with patch("savesync_bridge.core.sync_engine.rclone") as mock_rclone:
            mock_rclone.read_file.return_value = json_bytes
            engine.get_cloud_manifest(GAME_ID)
        assert mock_rclone.read_file.call_args.kwargs["report_cli"] is False

    def test_returns_none_when_rclone_error(self, engine: SyncEngine) -> None:
        with patch("savesync_bridge.core.sync_engine.rclone") as mock_rclone:
            mock_rclone.read_file.side_effect = RcloneError("not found", 1, "")
            result = engine.get_cloud_manifest(GAME_ID)
        assert result is None


# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------


class TestPush:
    def test_success_returns_synced(self, engine: SyncEngine) -> None:
        with (
            patch("savesync_bridge.core.sync_engine.ludusavi") as mock_lud,
            patch("savesync_bridge.core.sync_engine.rclone"),
        ):
            mock_lud.backup_game.return_value = Path("/tmp/staging/Hades")
            result = engine.push(GAME_ID)

        assert result.game_id == GAME_ID
        assert result.status == SyncStatus.SYNCED
        assert result.error is None

    def test_calls_backup_game(self, engine: SyncEngine) -> None:
        with (
            patch("savesync_bridge.core.sync_engine.ludusavi") as mock_lud,
            patch("savesync_bridge.core.sync_engine.rclone"),
        ):
            engine.push(GAME_ID)
        mock_lud.backup_game.assert_called_once()
        call_args = mock_lud.backup_game.call_args
        # game_name is first positional arg
        assert call_args[0][0] == GAME_ID

    def test_calls_rclone_upload_twice(self, engine: SyncEngine) -> None:
        """Should upload archive and manifest.json (manifest now contains all metadata).
        
        Note: _rotate_versions may also make additional uploads if old versions exist.
        """
        with (
            patch("savesync_bridge.core.sync_engine.ludusavi") as mock_lud,
            patch("savesync_bridge.core.sync_engine.rclone") as mock_rcl,
        ):
            mock_lud.backup_game.return_value = Path("/tmp/staging/Hades")
            engine.push(GAME_ID)
        # At minimum: archive + manifest (2 uploads)
        assert mock_rcl.upload.call_count >= 2

    def test_saves_local_manifest_after_push(self, engine: SyncEngine, tmp_path: Path) -> None:
        with (
            patch("savesync_bridge.core.sync_engine.ludusavi") as mock_lud,
            patch("savesync_bridge.core.sync_engine.rclone"),
        ):
            mock_lud.backup_game.return_value = Path("/tmp/x")
            engine.push(GAME_ID)
        state_file = tmp_path / "states" / f"{GAME_ID}.json"
        assert state_file.exists()

    def test_push_preserves_source_file_modified_time(self, engine: SyncEngine, tmp_path: Path) -> None:
        source_dir = tmp_path / "live-save"
        source_dir.mkdir()
        source_file = source_dir / "Profile1.sav"
        source_file.write_bytes(b"live-data")
        modified_ts = datetime(2026, 4, 12, 9, 30, 0, tzinfo=UTC).timestamp()
        os.utime(source_file, (modified_ts, modified_ts))

        live_game = LudusaviGame(
            name=GAME_ID,
            save_files=[SaveFileInfo(path=str(source_file), size=source_file.stat().st_size, hash="")],
            save_paths=[str(source_dir)],
        )

        def fake_backup(game_name: str, output_dir: Path, binary=None) -> Path:
            source_drive = source_file.drive.replace(":", "") or "0"
            source_tail = Path(str(source_file).replace(source_file.drive, "").lstrip("\\/"))
            staged = output_dir / "backup-1" / f"drive-{source_drive}" / source_tail
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(source_file.read_bytes())
            return output_dir

        with (
            patch("savesync_bridge.core.sync_engine.ludusavi") as mock_lud,
            patch("savesync_bridge.core.sync_engine.rclone"),
        ):
            mock_lud.get_game.return_value = live_game
            mock_lud.backup_game.side_effect = fake_backup
            engine.push(GAME_ID)

        saved_manifest = engine.get_local_manifest(GAME_ID)
        assert saved_manifest is not None
        profile = next(f for f in saved_manifest.files if f.path.endswith("Profile1.sav"))
        assert profile.modified == datetime(2026, 4, 12, 9, 30, 0, tzinfo=UTC)

    def test_returns_unknown_on_ludusavi_error(self, engine: SyncEngine) -> None:
        with (
            patch("savesync_bridge.core.sync_engine.ludusavi") as mock_lud,
            patch("savesync_bridge.core.sync_engine.rclone"),
        ):
            mock_lud.backup_game.side_effect = LudusaviError("backup failed", 1, "stderr")
            result = engine.push(GAME_ID)
        assert result.status == SyncStatus.UNKNOWN
        assert result.error is not None
        assert "backup failed" in result.error

    def test_returns_unknown_on_rclone_error(self, engine: SyncEngine) -> None:
        with (
            patch("savesync_bridge.core.sync_engine.ludusavi") as mock_lud,
            patch("savesync_bridge.core.sync_engine.rclone") as mock_rcl,
        ):
            mock_lud.backup_game.return_value = Path("/tmp/x")
            mock_rcl.upload.side_effect = RcloneError("upload failed", 1, "stderr")
            result = engine.push(GAME_ID)
        assert result.status == SyncStatus.UNKNOWN
        assert result.error is not None


# ---------------------------------------------------------------------------
# pull
# ---------------------------------------------------------------------------


class TestPull:
    def test_success_returns_synced(self, engine: SyncEngine) -> None:
        m = _make_manifest()
        with (
            patch("savesync_bridge.core.sync_engine.ludusavi"),
            patch("savesync_bridge.core.sync_engine.rclone"),
            patch.object(engine, "_get_cloud_sync_meta", return_value=None),
        ):
            result = engine.pull(GAME_ID, m)
        assert result.game_id == GAME_ID
        assert result.status == SyncStatus.SYNCED
        assert result.error is None

    def test_calls_rclone_download(self, engine: SyncEngine) -> None:
        m = _make_manifest()
        with (
            patch("savesync_bridge.core.sync_engine.ludusavi"),
            patch("savesync_bridge.core.sync_engine.rclone") as mock_rcl,
            patch.object(engine, "_get_cloud_sync_meta", return_value=None),
        ):
            engine.pull(GAME_ID, m)
        mock_rcl.download.assert_called_once()

    def test_calls_restore_game(self, engine: SyncEngine) -> None:
        m = _make_manifest()
        with (
            patch("savesync_bridge.core.sync_engine.ludusavi") as mock_lud,
            patch("savesync_bridge.core.sync_engine.rclone"),
            patch.object(engine, "_get_cloud_sync_meta", return_value=None),
        ):
            engine.pull(GAME_ID, m)
        mock_lud.restore_game.assert_called_once()
        assert mock_lud.restore_game.call_args[0][0] == GAME_ID

    def test_converts_backup_before_restore(self, engine: SyncEngine) -> None:
        m = _make_manifest(host=Platform.WINDOWS)
        wine_prefix = "/home/deck/Games/heroic/Hades/prefix/drive_c"
        with (
            patch("savesync_bridge.core.sync_engine.ludusavi"),
            patch("savesync_bridge.core.sync_engine.rclone"),
            patch(
                "savesync_bridge.core.sync_engine.convert_simple_backup_for_restore"
            ) as mock_convert,
            patch.object(engine, "_get_cloud_sync_meta", return_value=None),
        ):
            engine.pull(
                GAME_ID,
                m,
                target_wine_prefix=wine_prefix,
                target_wine_user="deck",
            )
        mock_convert.assert_called_once()
        assert mock_convert.call_args.kwargs["target_wine_prefix"] == wine_prefix
        assert mock_convert.call_args.kwargs["target_wine_user"] == "deck"

    def test_saves_cloud_manifest_as_local_after_pull(
        self, engine: SyncEngine, tmp_path: Path
    ) -> None:
        m = _make_manifest()
        with (
            patch("savesync_bridge.core.sync_engine.ludusavi"),
            patch("savesync_bridge.core.sync_engine.rclone"),
            patch.object(engine, "_get_cloud_sync_meta", return_value=None),
        ):
            engine.pull(GAME_ID, m)
        state_file = tmp_path / "states" / f"{GAME_ID}.json"
        assert state_file.exists()
        loaded = manifest_module.from_json(state_file.read_text())
        assert loaded.hash == m.hash

    def test_returns_unknown_on_rclone_error(self, engine: SyncEngine) -> None:
        m = _make_manifest()
        with (
            patch("savesync_bridge.core.sync_engine.ludusavi"),
            patch("savesync_bridge.core.sync_engine.rclone") as mock_rcl,
            patch.object(engine, "_get_cloud_sync_meta", return_value=None),
        ):
            mock_rcl.download.side_effect = RcloneError("download failed", 1, "")
            result = engine.pull(GAME_ID, m)
        assert result.status == SyncStatus.UNKNOWN
        assert "download failed" in result.error

    def test_returns_unknown_on_ludusavi_error(self, engine: SyncEngine) -> None:
        m = _make_manifest()
        with (
            patch("savesync_bridge.core.sync_engine.ludusavi") as mock_lud,
            patch("savesync_bridge.core.sync_engine.rclone"),
            patch.object(engine, "_get_cloud_sync_meta", return_value=None),
        ):
            mock_lud.restore_game.side_effect = LudusaviError("restore failed", 1, "")
            result = engine.pull(GAME_ID, m)
        assert result.status == SyncStatus.UNKNOWN


# ---------------------------------------------------------------------------
# check_status
# ---------------------------------------------------------------------------


class TestCheckStatus:
    def _write_local(self, engine: SyncEngine, m: GameManifest) -> None:
        engine._state_dir.mkdir(parents=True, exist_ok=True)
        (engine._state_dir / f"{m.game_id}.json").write_text(
            manifest_module.to_json(m), encoding="utf-8"
        )

    def test_synced_when_hashes_match(self, engine: SyncEngine) -> None:
        m = _make_manifest()
        self._write_local(engine, m)
        with (
            patch.object(engine, "_get_cloud_sync_meta", return_value=None),
            patch.object(engine, "get_cloud_manifest", return_value=m),
        ):
            result = engine.check_status(GAME_ID)
        assert result.status == SyncStatus.SYNCED

    def test_local_newer_when_no_cloud(self, engine: SyncEngine) -> None:
        m = _make_manifest()
        self._write_local(engine, m)
        with (
            patch.object(engine, "_get_cloud_sync_meta", return_value=None),
            patch.object(engine, "get_cloud_manifest", return_value=None),
        ):
            result = engine.check_status(GAME_ID)
        assert result.status == SyncStatus.LOCAL_NEWER

    def test_cloud_newer_when_no_local(self, engine: SyncEngine) -> None:
        m = _make_manifest()
        with (
            patch.object(engine, "_get_cloud_sync_meta", return_value=None),
            patch.object(engine, "get_cloud_manifest", return_value=m),
        ):
            result = engine.check_status(GAME_ID)
        assert result.status == SyncStatus.CLOUD_NEWER

    def test_unknown_when_neither_local_nor_cloud(self, engine: SyncEngine) -> None:
        with (
            patch.object(engine, "_get_cloud_sync_meta", return_value=None),
            patch.object(engine, "get_cloud_manifest", return_value=None),
        ):
            result = engine.check_status(GAME_ID)
        assert result.status == SyncStatus.UNKNOWN

    def test_conflict_status_from_manifest_compare_when_local_timestamp_is_newer(
        self, engine: SyncEngine
    ) -> None:
        local = _make_manifest(ts=datetime(2026, 4, 12, 12, 0, 0, tzinfo=UTC))
        cloud = _make_manifest(
            ts=datetime(2026, 4, 12, 10, 0, 0, tzinfo=UTC),
            content_hash="sha256:different",
        )
        self._write_local(engine, local)
        with (
            patch.object(engine, "_get_cloud_sync_meta", return_value=None),
            patch.object(engine, "get_cloud_manifest", return_value=cloud),
        ):
            result = engine.check_status(GAME_ID)
        assert result.status == SyncStatus.CONFLICT

    def test_conflict_status_from_manifest_compare_when_cloud_timestamp_is_newer(
        self, engine: SyncEngine
    ) -> None:
        local = _make_manifest(
            ts=datetime(2026, 4, 12, 8, 0, 0, tzinfo=UTC),
            content_hash="sha256:old",
        )
        cloud = _make_manifest(
            ts=datetime(2026, 4, 12, 12, 0, 0, tzinfo=UTC),
            content_hash="sha256:new",
        )
        self._write_local(engine, local)
        with (
            patch.object(engine, "_get_cloud_sync_meta", return_value=None),
            patch.object(engine, "get_cloud_manifest", return_value=cloud),
        ):
            result = engine.check_status(GAME_ID)
        assert result.status == SyncStatus.CONFLICT

    def test_conflict_status_when_hash_differs(
        self, engine: SyncEngine
    ) -> None:
        local = _make_manifest(content_hash="sha256:old")
        self._write_local(engine, local)
        cloud = GameManifest(
            game_id=GAME_ID,
            host=Platform.WINDOWS,
            hash="sha256:new",
            timestamp=datetime(2026, 4, 12, 12, 0, 0, tzinfo=UTC),
            files=(),
            compressed=True,
            archive_name="save.tar.gz",
            total_size=1024,
        )
        with patch.object(engine, "get_cloud_manifest", return_value=cloud):
            result = engine.check_status(GAME_ID)
        assert result.status == SyncStatus.CONFLICT

    def test_conflict_falls_back_to_full_manifest_when_ignored_files_differ(
        self, engine: SyncEngine
    ) -> None:
        local = GameManifest(
            game_id=GAME_ID,
            host=Platform.WINDOWS,
            timestamp=datetime(2026, 4, 12, 10, 0, 0, tzinfo=UTC),
            hash="sha256:local",
            files=(
                SaveFile(
                    path="Profile1.sav",
                    size=1024,
                    modified=datetime(2026, 4, 12, 9, 0, 0, tzinfo=UTC),
                    file_hash="sha256:abc123",
                ),
            ),
        )
        self._write_local(engine, local)

        cloud = GameManifest(
            game_id=GAME_ID,
            host=Platform.WINDOWS,
            timestamp=datetime(2026, 4, 12, 9, 0, 0, tzinfo=UTC),
            hash="sha256:cloud",
            files=(
                SaveFile(
                    path="Profile1.sav",
                    size=1024,
                    modified=datetime(2026, 4, 12, 9, 0, 0, tzinfo=UTC),
                    file_hash="sha256:abc123",
                ),
                SaveFile(
                    path="mapping.yaml",
                    size=128,
                    modified=datetime(2026, 4, 12, 9, 0, 0, tzinfo=UTC),
                    file_hash="sha256:ignored",
                ),
            ),
            compressed=True,
            archive_name="save.tar.gz",
            total_size=2048,
        )

        with patch.object(engine, "get_cloud_manifest", return_value=cloud):
            result = engine.check_status(GAME_ID)
        assert result.status == SyncStatus.SYNCED

    def test_direct_manifest_comparison(self, engine: SyncEngine) -> None:
        """check_status should compare full manifests directly."""
        local = _make_manifest(content_hash="sha256:same")
        self._write_local(engine, local)
        cloud = GameManifest(
            game_id=GAME_ID,
            host=Platform.WINDOWS,
            hash="sha256:same",
            timestamp=local.timestamp,
            files=local.files,
            compressed=True,
            archive_name="save.tar.gz",
            total_size=1024,
        )
        with patch.object(engine, "get_cloud_manifest", return_value=cloud):
            result = engine.check_status(GAME_ID)
        assert result.status == SyncStatus.SYNCED


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


class TestSync:
    def test_pushes_when_local_newer(self, engine: SyncEngine) -> None:
        local_newer = SyncResult(GAME_ID, SyncStatus.LOCAL_NEWER)
        synced = SyncResult(GAME_ID, SyncStatus.SYNCED)
        with (
            patch.object(engine, "check_status", return_value=local_newer),
            patch.object(engine, "push", return_value=synced) as mock_push,
        ):
            result = engine.sync(GAME_ID)
        mock_push.assert_called_once_with(GAME_ID)
        assert result.status == SyncStatus.SYNCED

    def test_pulls_when_cloud_newer(self, engine: SyncEngine) -> None:
        m = _make_manifest()
        cloud_newer = SyncResult(GAME_ID, SyncStatus.CLOUD_NEWER)
        synced = SyncResult(GAME_ID, SyncStatus.SYNCED)
        with (
            patch.object(engine, "check_status", return_value=cloud_newer),
            patch.object(engine, "get_cloud_manifest", return_value=m),
            patch.object(engine, "pull", return_value=synced) as mock_pull,
        ):
            result = engine.sync(
                GAME_ID,
                target_wine_prefix="/home/deck/Games/heroic/Hades/prefix/drive_c",
                target_wine_user="deck",
            )
        mock_pull.assert_called_once_with(
            GAME_ID,
            m,
            target_wine_prefix="/home/deck/Games/heroic/Hades/prefix/drive_c",
            target_wine_user="deck",
        )
        assert result.status == SyncStatus.SYNCED

    def test_returns_conflict_when_conflict(self, engine: SyncEngine) -> None:
        conflict = SyncResult(GAME_ID, SyncStatus.CONFLICT)
        with patch.object(engine, "check_status", return_value=conflict):
            result = engine.sync(GAME_ID)
        assert result.status == SyncStatus.CONFLICT

    def test_no_op_when_already_synced(self, engine: SyncEngine) -> None:
        synced = SyncResult(GAME_ID, SyncStatus.SYNCED)
        with (
            patch.object(engine, "check_status", return_value=synced),
            patch.object(engine, "push") as mock_push,
            patch.object(engine, "pull") as mock_pull,
        ):
            result = engine.sync(GAME_ID)
        mock_push.assert_not_called()
        mock_pull.assert_not_called()
        assert result.status == SyncStatus.SYNCED

    def test_error_propagation_from_push(self, engine: SyncEngine) -> None:
        local_newer = SyncResult(GAME_ID, SyncStatus.LOCAL_NEWER)
        unknown = SyncResult(GAME_ID, SyncStatus.UNKNOWN, error="oops")
        with (
            patch.object(engine, "check_status", return_value=local_newer),
            patch.object(engine, "push", return_value=unknown),
        ):
            result = engine.sync(GAME_ID)
        assert result.status == SyncStatus.UNKNOWN
        assert result.error == "oops"

    def test_returns_unknown_when_cloud_manifest_missing_on_pull(self, engine: SyncEngine) -> None:
        cloud_newer = SyncResult(GAME_ID, SyncStatus.CLOUD_NEWER)
        with (
            patch.object(engine, "check_status", return_value=cloud_newer),
            patch.object(engine, "get_cloud_manifest", return_value=None),
        ):
            result = engine.sync(GAME_ID)
        assert result.status == SyncStatus.UNKNOWN
        assert result.error is not None

    def test_sync_uses_live_local_probe_instead_of_cached_manifest(self, engine: SyncEngine) -> None:
        cached = _make_manifest(content_hash="sha256:same")
        live_local = _make_manifest(content_hash="sha256:live")
        cloud = _make_manifest(content_hash="sha256:same")
        engine._save_local_manifest(cached)

        with (
            patch.object(engine, "_probe_live_local_manifest", return_value=(True, live_local)),
            patch.object(engine, "_get_cloud_sync_meta", return_value=None),
            patch.object(engine, "get_cloud_manifest", return_value=cloud),
        ):
            result = engine.sync(GAME_ID)

        assert result.status == SyncStatus.CONFLICT
        assert result.local_manifest == live_local
        assert result.cloud_manifest == cloud


# ---------------------------------------------------------------------------
# scan_save_directories
# ---------------------------------------------------------------------------


class TestScanSaveDirectories:
    def test_returns_stats_for_existing_files(self, tmp_path: Path) -> None:
        save_dir = tmp_path / "saves"
        save_dir.mkdir()
        (save_dir / "slot1.sav").write_text("data1")
        (save_dir / "slot2.sav").write_text("more data here")

        stat = scan_save_directories([str(save_dir)])
        assert stat.total_files == 2
        assert stat.total_size > 0
        assert stat.oldest_modified is not None
        assert stat.newest_modified is not None

    def test_handles_nonexistent_directory(self) -> None:
        stat = scan_save_directories(["/nonexistent/path"])
        assert stat.total_files == 0
        assert stat.total_size == 0
        assert stat.oldest_created is None

    def test_scans_subdirectories_recursively(self, tmp_path: Path) -> None:
        (tmp_path / "sub" / "deep").mkdir(parents=True)
        (tmp_path / "file1.dat").write_text("a")
        (tmp_path / "sub" / "file2.dat").write_text("bb")
        (tmp_path / "sub" / "deep" / "file3.dat").write_text("ccc")

        stat = scan_save_directories([str(tmp_path)])
        assert stat.total_files == 3

    def test_empty_directory_returns_zero_stats(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        stat = scan_save_directories([str(empty)])
        assert stat.total_files == 0
        assert stat.total_size == 0


# ---------------------------------------------------------------------------
# sync — UNKNOWN status does not auto-push
# ---------------------------------------------------------------------------


class TestSyncUnknownNoAutoPush:
    def test_unknown_returns_unknown_instead_of_pushing(self, engine: SyncEngine) -> None:
        """When check_status returns UNKNOWN (no cloud save), sync returns UNKNOWN without auto-pushing."""
        unknown = SyncResult(GAME_ID, SyncStatus.UNKNOWN)
        with (
            patch.object(engine, "check_status", return_value=unknown),
            patch.object(engine, "push") as mock_push,
        ):
            result = engine.sync(GAME_ID)
        mock_push.assert_not_called()
        assert result.status == SyncStatus.UNKNOWN


# ---------------------------------------------------------------------------
# verify_cloud_integrity
# ---------------------------------------------------------------------------


class TestVerifyCloudIntegrity:
    def test_ok_when_manifest_exists(self, engine: SyncEngine) -> None:
        m = _make_manifest(content_hash="sha256:abc123")
        with patch.object(engine, "get_cloud_manifest", return_value=m):
            ok, msg = engine.verify_cloud_integrity(GAME_ID)
        assert ok is True
        assert "OK" in msg

    def test_fails_when_manifest_missing(self, engine: SyncEngine) -> None:
        with patch.object(engine, "get_cloud_manifest", return_value=None):
            ok, msg = engine.verify_cloud_integrity(GAME_ID)
        assert ok is False


# ---------------------------------------------------------------------------
# Export / Import backup library
# ---------------------------------------------------------------------------


class TestExportImport:
    def test_list_cloud_games(self, engine: SyncEngine) -> None:
        entries = [
            {"Path": "Hades", "IsDir": True},
            {"Path": "Celeste", "IsDir": True},
            {"Path": "manifest.json", "IsDir": False},
        ]
        with patch("savesync_bridge.cli.rclone.list_files", return_value=entries):
            result = engine.list_cloud_games()
        assert result == ["Hades", "Celeste"]

    def test_list_cloud_games_handles_rclone_error(self, engine: SyncEngine) -> None:
        with patch("savesync_bridge.cli.rclone.list_files", side_effect=RcloneError("fail", 1, "")):
            result = engine.list_cloud_games()
        assert result == []

    def test_export_creates_zip(self, engine: SyncEngine, tmp_path: Path) -> None:
        dest = tmp_path / "backup.zip"

        def fake_download(_remote, _root, _prefix, local_path, **kw):
            (local_path / "save.tar.gz").write_bytes(b"fake archive data")

        with (
            patch("savesync_bridge.cli.rclone.download", side_effect=fake_download),
        ):
            result = engine.export_library(dest, game_ids=["Hades"])

        assert result == dest.resolve()
        assert dest.exists()
        import zipfile
        with zipfile.ZipFile(dest, "r") as zf:
            names = zf.namelist()
        assert "Hades/save.tar.gz" in names

    def test_export_raises_on_empty(self, engine: SyncEngine, tmp_path: Path) -> None:
        from savesync_bridge.core.exceptions import SyncError
        dest = tmp_path / "backup.zip"
        with pytest.raises(SyncError, match="No games found"):
            engine.export_library(dest, game_ids=[])

    def test_import_restores_files(self, engine: SyncEngine, tmp_path: Path) -> None:
        # Create a zip with a fake game save
        import zipfile
        src = tmp_path / "backup.zip"
        with zipfile.ZipFile(src, "w") as zf:
            zf.writestr("Hades/save.tar.gz", b"fake data")
            zf.writestr("Hades/manifest.json", '{"fake": true}')

        uploaded = []

        def fake_upload(local_file, _remote, _root, _prefix, **kw):
            uploaded.append(local_file.name)

        with patch("savesync_bridge.cli.rclone.upload", side_effect=fake_upload):
            result = engine.import_library(src)

        assert "Hades" in result
        assert "save.tar.gz" in uploaded
        assert "manifest.json" in uploaded

    def test_import_raises_on_missing_file(self, engine: SyncEngine, tmp_path: Path) -> None:
        from savesync_bridge.core.exceptions import SyncError
        with pytest.raises(SyncError, match="not found"):
            engine.import_library(tmp_path / "nonexistent.zip")


# ---------------------------------------------------------------------------
# Cloud lock
# ---------------------------------------------------------------------------


class TestBuildManifest:
    def test_build_manifest_ignores_mapping_yaml(self, tmp_path: Path) -> None:
        game_dir1 = tmp_path / "Hades1"
        game_dir1.mkdir()
        (game_dir1 / "mapping.yaml").write_text("version: 1\n", encoding="utf-8")
        save1 = game_dir1 / "drive-0" / "save.dat"
        save1.parent.mkdir(parents=True)
        save1.write_bytes(b"content")

        game_dir2 = tmp_path / "Hades2"
        game_dir2.mkdir()
        mapping2 = game_dir2 / "nested" / "mapping.yaml"
        mapping2.parent.mkdir(parents=True)
        mapping2.write_text("version: 2\n", encoding="utf-8")
        save2 = game_dir2 / "drive-0" / "save.dat"
        save2.parent.mkdir(parents=True)
        save2.write_bytes(b"content")

        from savesync_bridge.core.sync_engine import _build_manifest

        manifest1 = _build_manifest("Hades", game_dir1)
        manifest2 = _build_manifest("Hades", game_dir2)

        assert manifest1.hash == manifest2.hash
        assert all(f.path != "mapping.yaml" for f in manifest1.files)
        assert all("mapping.yaml" not in f.path for f in manifest2.files)


class TestCloudLock:
    def test_acquire_lock_succeeds_when_no_lock(self, engine: SyncEngine) -> None:
        """Lock acquisition succeeds when no existing lock."""
        with (
            patch("savesync_bridge.cli.rclone.read_file", side_effect=RcloneError("not found", 1, "")),
            patch("savesync_bridge.cli.rclone.upload") as mock_upload,
        ):
            engine._acquire_lock(GAME_ID)
        mock_upload.assert_called_once()

    def test_acquire_lock_fails_when_active(self, engine: SyncEngine) -> None:
        """Lock acquisition raises SyncError when another machine holds a fresh lock."""
        import json
        from savesync_bridge.core.exceptions import SyncError
        lock_data = json.dumps({
            "machine": "other-pc",
            "timestamp": datetime.now(UTC).isoformat(),
        }).encode("utf-8")
        with (
            patch("savesync_bridge.cli.rclone.read_file", return_value=lock_data),
            pytest.raises(SyncError, match="locked by"),
        ):
            engine._acquire_lock(GAME_ID)

    def test_acquire_lock_overrides_stale(self, engine: SyncEngine) -> None:
        """Stale locks (>5 min) are overridden."""
        import json
        old_ts = datetime(2020, 1, 1, tzinfo=UTC).isoformat()
        lock_data = json.dumps({
            "machine": "old-pc",
            "timestamp": old_ts,
        }).encode("utf-8")
        with (
            patch("savesync_bridge.cli.rclone.read_file", return_value=lock_data),
            patch("savesync_bridge.cli.rclone.upload") as mock_upload,
        ):
            engine._acquire_lock(GAME_ID)
        mock_upload.assert_called_once()

    def test_acquire_lock_overrides_corrupt_lock(self, engine: SyncEngine) -> None:
        """Corrupt or malformed lock content is treated as stale and overridden."""
        import json
        lock_data = json.dumps({
            "machine": "bad-pc",
            "timestamp": None,
        }).encode("utf-8")
        with (
            patch("savesync_bridge.cli.rclone.read_file", return_value=lock_data),
            patch("savesync_bridge.cli.rclone.upload") as mock_upload,
        ):
            engine._acquire_lock(GAME_ID)
        mock_upload.assert_called_once()

    def test_release_lock(self, engine: SyncEngine) -> None:
        with patch("savesync_bridge.cli.rclone.delete_path") as mock_delete:
            engine._release_lock(GAME_ID)
        mock_delete.assert_called_once()
