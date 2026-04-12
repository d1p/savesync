from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from savesync_bridge.cli import ludusavi, rclone
from savesync_bridge.core import manifest as manifest_module
from savesync_bridge.core.config import AppConfig
from savesync_bridge.core.exceptions import LudusaviError, RcloneError, SyncError
from savesync_bridge.models.game import GameManifest, Platform, SaveFile, SyncStatus


@dataclass
class SyncResult:
    game_id: str
    status: SyncStatus
    error: str | None = None


def _default_state_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "savesync-bridge" / "states"


def _build_manifest(game_id: str, game_dir: Path) -> GameManifest:
    """Compute a GameManifest by hashing all files in *game_dir*."""
    save_files: list[SaveFile] = []
    hasher = hashlib.sha256()

    for f in sorted(game_dir.rglob("*")):
        if not f.is_file():
            continue
        data = f.read_bytes()
        hasher.update(data)
        modified = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
        save_files.append(
            SaveFile(
                path=str(f.relative_to(game_dir)),
                size=f.stat().st_size,
                modified=modified,
            )
        )

    host = Platform.WINDOWS if sys.platform == "win32" else Platform.LINUX
    return GameManifest(
        game_id=game_id,
        host=host,
        timestamp=datetime.now(tz=timezone.utc),
        hash=f"sha256:{hasher.hexdigest()}",
        files=tuple(save_files),
    )


class SyncEngine:
    """Orchestrates backup / restore / sync operations via Ludusavi and rclone."""

    def __init__(
        self,
        config: AppConfig,
        env: dict[str, str] | None = None,
        ludusavi_bin: Path | None = None,
        rclone_bin: Path | None = None,
        work_dir: Path | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self._config = config
        self._env = env
        self._ludusavi_bin = ludusavi_bin
        self._rclone_bin = rclone_bin
        self._work_dir = work_dir
        self._state_dir: Path = state_dir if state_dir is not None else _default_state_dir()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _cloud_prefix(self, game_id: str) -> str:
        return f"{self._config.s3_prefix}/{game_id}"

    def _local_manifest_path(self, game_id: str) -> Path:
        return self._state_dir / f"{game_id}.json"

    def _get_local_manifest(self, game_id: str) -> GameManifest | None:
        path = self._local_manifest_path(game_id)
        if not path.exists():
            return None
        try:
            return manifest_module.from_json(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def _save_local_manifest(self, m: GameManifest) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._local_manifest_path(m.game_id).write_text(
            manifest_module.to_json(m), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_cloud_manifest(self, game_id: str) -> GameManifest | None:
        """Fetch manifest.json from S3 for *game_id*. Returns ``None`` if absent.

        Args:
            game_id: Ludusavi game identifier.

        Returns:
            Parsed :class:`~savesync_bridge.models.game.GameManifest`, or ``None``.
        """
        key = f"{self._cloud_prefix(game_id)}/manifest.json"
        try:
            raw = rclone.read_file(
                self._config.rclone_remote,
                self._config.s3_bucket,
                key,
                env=self._env,
                binary=self._rclone_bin,
            )
            return manifest_module.from_json(raw.decode("utf-8"))
        except RcloneError:
            return None

    def push(self, game_id: str) -> SyncResult:
        """Back up *game_id* via Ludusavi and upload the result to S3.

        Args:
            game_id: Ludusavi game identifier.

        Returns:
            :class:`SyncResult` with status ``SYNCED`` on success, ``UNKNOWN`` on error.
        """
        try:
            with tempfile.TemporaryDirectory() as staging:
                staging_path = Path(staging)
                game_dir = staging_path / game_id
                game_dir.mkdir(parents=True, exist_ok=True)

                # 1. Backup via Ludusavi
                ludusavi.backup_game(game_id, game_dir, binary=self._ludusavi_bin)

                # 2. Build a content manifest
                m = _build_manifest(game_id, game_dir)

                # 3. Write manifest.json into staging
                manifest_file = staging_path / "manifest.json"
                manifest_file.write_text(manifest_module.to_json(m), encoding="utf-8")

                prefix = self._cloud_prefix(game_id)

                # 4. Upload game-save files
                rclone.upload(
                    game_dir,
                    self._config.rclone_remote,
                    self._config.s3_bucket,
                    prefix,
                    env=self._env,
                    binary=self._rclone_bin,
                )

                # 5. Upload manifest.json
                rclone.upload(
                    manifest_file,
                    self._config.rclone_remote,
                    self._config.s3_bucket,
                    prefix,
                    env=self._env,
                    binary=self._rclone_bin,
                )

                # 6. Persist manifest locally so check_status can diff later
                self._save_local_manifest(m)

                return SyncResult(game_id=game_id, status=SyncStatus.SYNCED)

        except (LudusaviError, RcloneError, SyncError) as exc:
            return SyncResult(game_id=game_id, status=SyncStatus.UNKNOWN, error=str(exc))

    def pull(self, game_id: str, manifest: GameManifest) -> SyncResult:
        """Download saves from S3 and restore them via Ludusavi.

        Args:
            game_id: Ludusavi game identifier.
            manifest: The cloud manifest describing the save to restore.

        Returns:
            :class:`SyncResult` with status ``SYNCED`` on success, ``UNKNOWN`` on error.
        """
        try:
            with tempfile.TemporaryDirectory() as staging:
                staging_path = Path(staging)
                game_dir = staging_path / game_id
                game_dir.mkdir(parents=True, exist_ok=True)

                prefix = self._cloud_prefix(game_id)

                # 1. Download from S3
                rclone.download(
                    self._config.rclone_remote,
                    self._config.s3_bucket,
                    prefix,
                    game_dir,
                    env=self._env,
                    binary=self._rclone_bin,
                )

                # 2. Restore via Ludusavi
                ludusavi.restore_game(game_id, game_dir, binary=self._ludusavi_bin)

                # 3. Cache the cloud manifest locally
                self._save_local_manifest(manifest)

                return SyncResult(game_id=game_id, status=SyncStatus.SYNCED)

        except (LudusaviError, RcloneError, SyncError) as exc:
            return SyncResult(game_id=game_id, status=SyncStatus.UNKNOWN, error=str(exc))

    def check_status(self, game_id: str) -> SyncResult:
        """Compare the local cached manifest with the cloud manifest.

        Args:
            game_id: Ludusavi game identifier.

        Returns:
            :class:`SyncResult` reflecting ``SYNCED``, ``LOCAL_NEWER``,
            ``CLOUD_NEWER``, ``CONFLICT``, or ``UNKNOWN``.
        """
        cloud = self.get_cloud_manifest(game_id)
        local = self._get_local_manifest(game_id)

        if cloud is None and local is None:
            return SyncResult(game_id=game_id, status=SyncStatus.UNKNOWN)

        if cloud is None:
            return SyncResult(game_id=game_id, status=SyncStatus.LOCAL_NEWER)

        if local is None:
            return SyncResult(game_id=game_id, status=SyncStatus.CLOUD_NEWER)

        status = manifest_module.compare(local, cloud)
        return SyncResult(game_id=game_id, status=status)

    def sync(self, game_id: str) -> SyncResult:
        """Smart sync: push, pull, or report conflict based on manifest comparison.

        Returns ``CONFLICT`` if both local and cloud are independently modified —
        the caller must resolve via the conflict dialog before proceeding.

        Args:
            game_id: Ludusavi game identifier.

        Returns:
            :class:`SyncResult` with the final sync status.
        """
        status_result = self.check_status(game_id)

        if status_result.status == SyncStatus.SYNCED:
            return status_result

        if status_result.status == SyncStatus.CONFLICT:
            return SyncResult(game_id=game_id, status=SyncStatus.CONFLICT)

        if status_result.status in (SyncStatus.LOCAL_NEWER, SyncStatus.UNKNOWN):
            return self.push(game_id)

        if status_result.status == SyncStatus.CLOUD_NEWER:
            cloud = self.get_cloud_manifest(game_id)
            if cloud is None:
                return SyncResult(
                    game_id=game_id,
                    status=SyncStatus.UNKNOWN,
                    error="Cloud manifest vanished during sync",
                )
            return self.pull(game_id, cloud)

        return status_result
