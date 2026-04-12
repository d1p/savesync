from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from savesync_bridge.core import manifest as manifest_module
from savesync_bridge.core.config import AppConfig
from savesync_bridge.core.exceptions import LudusaviError, RcloneError
from savesync_bridge.core.sync_engine import SyncEngine, SyncResult
from savesync_bridge.models.game import GameManifest, Platform, SaveFile, SyncStatus

GAME_ID = "Hades"


def _make_config() -> AppConfig:
    return AppConfig(
        rclone_remote="s3remote",
        s3_bucket="test-bucket",
        s3_prefix="saves",
    )


def _make_manifest(
    game_id: str = GAME_ID,
    host: Platform = Platform.WINDOWS,
    ts: datetime | None = None,
    content_hash: str = "sha256:abc123",
) -> GameManifest:
    if ts is None:
        ts = datetime(2026, 4, 12, 10, 0, 0, tzinfo=timezone.utc)
    return GameManifest(
        game_id=game_id,
        host=host,
        timestamp=ts,
        hash=content_hash,
        files=(
            SaveFile(
                path="Profile1.sav",
                size=1024,
                modified=datetime(2026, 4, 12, 9, 0, 0, tzinfo=timezone.utc),
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
            patch("savesync_bridge.core.sync_engine.rclone") as mock_rcl,
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
        """Should upload game files dir AND manifest.json separately."""
        with (
            patch("savesync_bridge.core.sync_engine.ludusavi") as mock_lud,
            patch("savesync_bridge.core.sync_engine.rclone") as mock_rcl,
        ):
            mock_lud.backup_game.return_value = Path("/tmp/staging/Hades")
            engine.push(GAME_ID)
        assert mock_rcl.upload.call_count == 2

    def test_saves_local_manifest_after_push(self, engine: SyncEngine, tmp_path: Path) -> None:
        with (
            patch("savesync_bridge.core.sync_engine.ludusavi") as mock_lud,
            patch("savesync_bridge.core.sync_engine.rclone"),
        ):
            mock_lud.backup_game.return_value = Path("/tmp/x")
            engine.push(GAME_ID)
        state_file = tmp_path / "states" / f"{GAME_ID}.json"
        assert state_file.exists()

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
        ):
            engine.pull(GAME_ID, m)
        mock_rcl.download.assert_called_once()

    def test_calls_restore_game(self, engine: SyncEngine) -> None:
        m = _make_manifest()
        with (
            patch("savesync_bridge.core.sync_engine.ludusavi") as mock_lud,
            patch("savesync_bridge.core.sync_engine.rclone"),
        ):
            engine.pull(GAME_ID, m)
        mock_lud.restore_game.assert_called_once()
        assert mock_lud.restore_game.call_args[0][0] == GAME_ID

    def test_saves_cloud_manifest_as_local_after_pull(
        self, engine: SyncEngine, tmp_path: Path
    ) -> None:
        m = _make_manifest()
        with (
            patch("savesync_bridge.core.sync_engine.ludusavi"),
            patch("savesync_bridge.core.sync_engine.rclone"),
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
        with patch.object(engine, "get_cloud_manifest", return_value=m):
            result = engine.check_status(GAME_ID)
        assert result.status == SyncStatus.SYNCED

    def test_local_newer_when_no_cloud(self, engine: SyncEngine) -> None:
        m = _make_manifest()
        self._write_local(engine, m)
        with patch.object(engine, "get_cloud_manifest", return_value=None):
            result = engine.check_status(GAME_ID)
        assert result.status == SyncStatus.LOCAL_NEWER

    def test_cloud_newer_when_no_local(self, engine: SyncEngine) -> None:
        m = _make_manifest()
        with patch.object(engine, "get_cloud_manifest", return_value=m):
            result = engine.check_status(GAME_ID)
        assert result.status == SyncStatus.CLOUD_NEWER

    def test_unknown_when_neither_local_nor_cloud(self, engine: SyncEngine) -> None:
        with patch.object(engine, "get_cloud_manifest", return_value=None):
            result = engine.check_status(GAME_ID)
        assert result.status == SyncStatus.UNKNOWN

    def test_local_newer_status_from_manifest_compare(self, engine: SyncEngine) -> None:
        local = _make_manifest(ts=datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc))
        cloud = _make_manifest(
            ts=datetime(2026, 4, 12, 10, 0, 0, tzinfo=timezone.utc),
            content_hash="sha256:different",
        )
        self._write_local(engine, local)
        with patch.object(engine, "get_cloud_manifest", return_value=cloud):
            result = engine.check_status(GAME_ID)
        assert result.status == SyncStatus.LOCAL_NEWER

    def test_cloud_newer_status_from_manifest_compare(self, engine: SyncEngine) -> None:
        local = _make_manifest(
            ts=datetime(2026, 4, 12, 8, 0, 0, tzinfo=timezone.utc),
            content_hash="sha256:old",
        )
        cloud = _make_manifest(
            ts=datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc),
            content_hash="sha256:new",
        )
        self._write_local(engine, local)
        with patch.object(engine, "get_cloud_manifest", return_value=cloud):
            result = engine.check_status(GAME_ID)
        assert result.status == SyncStatus.CLOUD_NEWER


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


class TestSync:
    def test_pushes_when_local_newer(self, engine: SyncEngine) -> None:
        with (
            patch.object(engine, "check_status", return_value=SyncResult(GAME_ID, SyncStatus.LOCAL_NEWER)),
            patch.object(engine, "push", return_value=SyncResult(GAME_ID, SyncStatus.SYNCED)) as mock_push,
        ):
            result = engine.sync(GAME_ID)
        mock_push.assert_called_once_with(GAME_ID)
        assert result.status == SyncStatus.SYNCED

    def test_pulls_when_cloud_newer(self, engine: SyncEngine) -> None:
        m = _make_manifest()
        with (
            patch.object(engine, "check_status", return_value=SyncResult(GAME_ID, SyncStatus.CLOUD_NEWER)),
            patch.object(engine, "get_cloud_manifest", return_value=m),
            patch.object(engine, "pull", return_value=SyncResult(GAME_ID, SyncStatus.SYNCED)) as mock_pull,
        ):
            result = engine.sync(GAME_ID)
        mock_pull.assert_called_once_with(GAME_ID, m)
        assert result.status == SyncStatus.SYNCED

    def test_returns_conflict_when_conflict(self, engine: SyncEngine) -> None:
        with patch.object(engine, "check_status", return_value=SyncResult(GAME_ID, SyncStatus.CONFLICT)):
            result = engine.sync(GAME_ID)
        assert result.status == SyncStatus.CONFLICT

    def test_no_op_when_already_synced(self, engine: SyncEngine) -> None:
        with (
            patch.object(engine, "check_status", return_value=SyncResult(GAME_ID, SyncStatus.SYNCED)),
            patch.object(engine, "push") as mock_push,
            patch.object(engine, "pull") as mock_pull,
        ):
            result = engine.sync(GAME_ID)
        mock_push.assert_not_called()
        mock_pull.assert_not_called()
        assert result.status == SyncStatus.SYNCED

    def test_error_propagation_from_push(self, engine: SyncEngine) -> None:
        with (
            patch.object(engine, "check_status", return_value=SyncResult(GAME_ID, SyncStatus.LOCAL_NEWER)),
            patch.object(engine, "push", return_value=SyncResult(GAME_ID, SyncStatus.UNKNOWN, error="oops")),
        ):
            result = engine.sync(GAME_ID)
        assert result.status == SyncStatus.UNKNOWN
        assert result.error == "oops"

    def test_returns_unknown_when_cloud_manifest_missing_on_pull(
        self, engine: SyncEngine
    ) -> None:
        with (
            patch.object(engine, "check_status", return_value=SyncResult(GAME_ID, SyncStatus.CLOUD_NEWER)),
            patch.object(engine, "get_cloud_manifest", return_value=None),
        ):
            result = engine.sync(GAME_ID)
        assert result.status == SyncStatus.UNKNOWN
        assert result.error is not None
