from __future__ import annotations

import hashlib
import json
import os
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from savesync_bridge.cli import ludusavi, rclone
from savesync_bridge.core import manifest as manifest_module
from savesync_bridge.core.backup_converter import convert_simple_backup_for_restore
from savesync_bridge.core.config import AppConfig
from savesync_bridge.core.exceptions import LudusaviError, RcloneError, SyncError
from savesync_bridge.models.game import GameManifest, Platform, SaveFile, SyncMeta, SyncStatus


@dataclass
class SyncResult:
    game_id: str
    status: SyncStatus
    error: str | None = None
    local_manifest: GameManifest | None = None
    cloud_manifest: GameManifest | None = None
    confidence: object | None = None  # manifest.ConfidenceResult when available
    save_dir_stat: object | None = None  # SaveDirStat when available


@dataclass(frozen=True)
class _SourceFileTimes:
    modified: datetime
    created: datetime | None


def _default_state_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "savesync-bridge" / "states"


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def _split_drive(path: str) -> tuple[str, str]:
    normalized = _normalize_path(path)
    if len(normalized) >= 2 and normalized[1] == ":":
        return normalized[:2], normalized[2:].lstrip("/")
    return "", normalized.lstrip("/")


def _drive_folder_name(drive: str) -> str:
    if not drive:
        return "drive-0"
    return f"drive-{drive.replace(':', '')}"


def _source_key_for_original_path(path: str) -> tuple[str, ...]:
    drive, remainder = _split_drive(path)
    parts = [_drive_folder_name(drive)]
    if remainder:
        parts.extend(part for part in remainder.split("/") if part)
    return tuple(parts)


def _source_key_for_staged_path(rel_path: Path) -> tuple[str, ...] | None:
    parts = rel_path.parts
    drive_index = next((idx for idx, part in enumerate(parts) if part.startswith("drive-")), None)
    if drive_index is None:
        return None
    return tuple(parts[drive_index:])


def _file_created_at(stat_result: os.stat_result) -> datetime | None:
    raw_birth = getattr(stat_result, "st_birthtime", None)
    if raw_birth is not None:
        return datetime.fromtimestamp(raw_birth, tz=UTC)
    if sys.platform == "win32":
        return datetime.fromtimestamp(stat_result.st_ctime, tz=UTC)
    return None


def _collect_source_file_times(game: ludusavi.LudusaviGame) -> dict[tuple[str, ...], _SourceFileTimes]:
    source_times: dict[tuple[str, ...], _SourceFileTimes] = {}
    for source_file in game.save_files:
        path = Path(source_file.path)
        try:
            stat_result = path.stat()
        except OSError:
            continue
        source_times[_source_key_for_original_path(source_file.path)] = _SourceFileTimes(
            modified=datetime.fromtimestamp(stat_result.st_mtime, tz=UTC),
            created=_file_created_at(stat_result),
        )
    return source_times


@dataclass(frozen=True)
class SaveDirStat:
    """Comprehensive metadata gathered from ALL files in save game directories."""

    total_files: int
    oldest_created: datetime | None
    newest_created: datetime | None
    oldest_modified: datetime | None
    newest_modified: datetime | None
    total_size: int


def scan_save_directories(save_paths: tuple[str, ...] | list[str]) -> SaveDirStat:
    """Walk ALL files in the given save directories and collect metadata.

    This goes beyond the Ludusavi-mapped files to check every file in the save
    directory tree, providing a broader picture for confidence scoring.
    """
    total_files = 0
    total_size = 0
    oldest_created: datetime | None = None
    newest_created: datetime | None = None
    oldest_modified: datetime | None = None
    newest_modified: datetime | None = None

    for dir_path_str in save_paths:
        dir_path = Path(dir_path_str)
        if not dir_path.is_dir():
            continue
        for f in dir_path.rglob("*"):
            if not f.is_file():
                continue
            try:
                stat_result = f.stat()
            except OSError:
                continue
            total_files += 1
            total_size += stat_result.st_size

            mod = datetime.fromtimestamp(stat_result.st_mtime, tz=UTC)
            cre = _file_created_at(stat_result)

            if oldest_modified is None or mod < oldest_modified:
                oldest_modified = mod
            if newest_modified is None or mod > newest_modified:
                newest_modified = mod

            if cre is not None:
                if oldest_created is None or cre < oldest_created:
                    oldest_created = cre
                if newest_created is None or cre > newest_created:
                    newest_created = cre

    return SaveDirStat(
        total_files=total_files,
        oldest_created=oldest_created,
        newest_created=newest_created,
        oldest_modified=oldest_modified,
        newest_modified=newest_modified,
        total_size=total_size,
    )


def _build_manifest(
    game_id: str,
    game_dir: Path,
    source_file_times: dict[tuple[str, ...], _SourceFileTimes] | None = None,
) -> GameManifest:
    """Compute a GameManifest by hashing all files in *game_dir*."""
    save_files: list[SaveFile] = []
    hasher = hashlib.sha256()

    for f in sorted(game_dir.rglob("*")):
        if not f.is_file():
            continue
        data = f.read_bytes()
        hasher.update(data)
        stat_result = f.stat()
        modified = datetime.fromtimestamp(stat_result.st_mtime, tz=UTC)
        created = _file_created_at(stat_result)
        rel_path = f.relative_to(game_dir)
        if source_file_times is not None:
            source_key = _source_key_for_staged_path(rel_path)
            source_time = source_file_times.get(source_key) if source_key is not None else None
            if source_time is not None:
                modified = source_time.modified
                created = source_time.created
        save_files.append(
            SaveFile(
                path=str(rel_path),
                size=stat_result.st_size,
                modified=modified,
                created=created,
            )
        )

    host = Platform.WINDOWS if sys.platform == "win32" else Platform.LINUX
    return GameManifest(
        game_id=game_id,
        host=host,
        timestamp=datetime.now(tz=UTC),
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
        rclone_config_file: Path | None = None,
        work_dir: Path | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self._config = config
        self._env = env
        self._ludusavi_bin = ludusavi_bin
        self._rclone_bin = rclone_bin
        self._rclone_config_file = rclone_config_file
        self._work_dir = work_dir
        self._state_dir: Path = state_dir if state_dir is not None else _default_state_dir()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @property
    def ludusavi_bin(self) -> Path | None:
        return self._ludusavi_bin

    def _cloud_prefix(self, game_id: str) -> str:
        return f"{self._config.backup_path}/{game_id}"

    def update_config(self, config: AppConfig) -> None:
        self._config = config

    def _local_manifest_path(self, game_id: str) -> Path:
        return self._state_dir / f"{game_id}.json"

    def get_local_manifest(self, game_id: str) -> GameManifest | None:
        path = self._local_manifest_path(game_id)
        if not path.exists():
            return None
        try:
            return manifest_module.from_json(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    # Backward-compatible alias
    _get_local_manifest = get_local_manifest

    def _save_local_manifest(self, m: GameManifest) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._local_manifest_path(m.game_id).write_text(
            manifest_module.to_json(m), encoding="utf-8"
        )

    def _restore_platform(self, target_wine_prefix: str | None) -> Platform:
        if sys.platform == "win32":
            return Platform.WINDOWS
        if target_wine_prefix:
            return Platform.STEAM_DECK
        return Platform.LINUX

    def _conversion_env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self._env is not None:
            env.update(self._env)
        return env

    def _live_source_game(self, game_id: str) -> ludusavi.LudusaviGame | None:
        return ludusavi.get_game(game_id, binary=self._ludusavi_bin)

    def _probe_live_local_manifest(self, game_id: str) -> tuple[bool, GameManifest | None]:
        try:
            source_game = self._live_source_game(game_id)
        except LudusaviError:
            return False, None

        if source_game is None:
            return True, None

        source_file_times = _collect_source_file_times(source_game)
        if not source_file_times:
            return True, None

        try:
            with tempfile.TemporaryDirectory() as staging:
                staging_path = Path(staging)
                game_dir = staging_path / game_id
                game_dir.mkdir(parents=True, exist_ok=True)
                ludusavi.backup_game(game_id, game_dir, binary=self._ludusavi_bin)
                return True, _build_manifest(
                    game_id,
                    game_dir,
                    source_file_times=source_file_times,
                )
        except LudusaviError:
            return False, None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_cloud_manifest(self, game_id: str) -> GameManifest | None:
        """Fetch manifest.json from cloud storage for *game_id*. Returns ``None`` if absent."""
        key = f"{self._cloud_prefix(game_id)}/manifest.json"
        try:
            raw = rclone.read_file(
                self._config.drive_remote,
                self._config.drive_root,
                key,
                env=self._env,
                binary=self._rclone_bin,
                config_file=self._rclone_config_file,
                report_cli=False,
            )
            return manifest_module.from_json(raw.decode("utf-8"))
        except RcloneError:
            return None

    def _get_cloud_sync_meta(self, game_id: str) -> SyncMeta | None:
        """Fetch lightweight sync_meta.json from cloud. Returns ``None`` if absent."""
        key = f"{self._cloud_prefix(game_id)}/sync_meta.json"
        try:
            raw = rclone.read_file(
                self._config.drive_remote,
                self._config.drive_root,
                key,
                env=self._env,
                binary=self._rclone_bin,
                config_file=self._rclone_config_file,
                report_cli=False,
            )
            return manifest_module.sync_meta_from_json(raw.decode("utf-8"))
        except (RcloneError, json.JSONDecodeError, KeyError, ValueError):
            return None

    def push(self, game_id: str) -> SyncResult:
        """Back up *game_id* via Ludusavi, compress, and upload to cloud storage.

        The save files are compressed into a tar.gz archive before uploading.
        A lightweight sync_meta.json is uploaded alongside for fast status checks.
        The full manifest.json is also uploaded for backward compatibility.
        """
        try:
            try:
                source_game = self._live_source_game(game_id)
            except LudusaviError:
                source_game = None
            source_file_times = (
                _collect_source_file_times(source_game) if source_game is not None else None
            )

            with tempfile.TemporaryDirectory() as staging:
                staging_path = Path(staging)
                game_dir = staging_path / game_id
                game_dir.mkdir(parents=True, exist_ok=True)

                # 1. Backup via Ludusavi
                ludusavi.backup_game(game_id, game_dir, binary=self._ludusavi_bin)

                # 2. Build a content manifest
                m = _build_manifest(
                    game_id,
                    game_dir,
                    source_file_times=source_file_times,
                )

                # 3. Compress save files into archive
                archive_name = "save.tar.gz"
                archive_path = staging_path / archive_name
                with tarfile.open(archive_path, "w:gz") as tar:
                    tar.add(game_dir, arcname=game_id)
                archive_size = archive_path.stat().st_size

                # 4. Write manifest.json into staging (backward compat)
                manifest_file = staging_path / "manifest.json"
                manifest_file.write_text(manifest_module.to_json(m), encoding="utf-8")

                # 5. Write sync_meta.json (lightweight, for fast status check)
                sync_meta = SyncMeta(
                    game_id=game_id,
                    hash=m.hash,
                    timestamp=m.timestamp,
                    compressed=True,
                    archive_name=archive_name,
                    total_size=archive_size,
                )
                meta_file = staging_path / "sync_meta.json"
                meta_file.write_text(
                    manifest_module.sync_meta_to_json(sync_meta), encoding="utf-8",
                )

                prefix = self._cloud_prefix(game_id)

                # 6. Upload compressed archive (single file instead of many)
                rclone.upload(
                    archive_path,
                    self._config.drive_remote,
                    self._config.drive_root,
                    prefix,
                    env=self._env,
                    binary=self._rclone_bin,
                    config_file=self._rclone_config_file,
                )

                # 7. Upload manifest.json
                rclone.upload(
                    manifest_file,
                    self._config.drive_remote,
                    self._config.drive_root,
                    prefix,
                    env=self._env,
                    binary=self._rclone_bin,
                    config_file=self._rclone_config_file,
                )

                # 8. Upload sync_meta.json
                rclone.upload(
                    meta_file,
                    self._config.drive_remote,
                    self._config.drive_root,
                    prefix,
                    env=self._env,
                    binary=self._rclone_bin,
                    config_file=self._rclone_config_file,
                )

                # 9. Persist manifest locally so check_status can diff later
                self._save_local_manifest(m)

                return SyncResult(
                    game_id=game_id,
                    status=SyncStatus.SYNCED,
                    local_manifest=m,
                )

        except (LudusaviError, RcloneError, SyncError) as exc:
            return SyncResult(game_id=game_id, status=SyncStatus.UNKNOWN, error=str(exc))

    def pull(
        self,
        game_id: str,
        manifest: GameManifest,
        target_wine_prefix: str | None = None,
        target_wine_user: str | None = None,
    ) -> SyncResult:
        """Download saves from cloud storage and restore them via Ludusavi.

        Supports both compressed archives (v2+) and legacy uncompressed saves.
        """
        try:
            with tempfile.TemporaryDirectory() as staging:
                staging_path = Path(staging)
                game_dir = staging_path / game_id
                game_dir.mkdir(parents=True, exist_ok=True)

                prefix = self._cloud_prefix(game_id)

                # Check if cloud save is compressed (v2 format)
                sync_meta = self._get_cloud_sync_meta(game_id)
                if sync_meta is not None and sync_meta.compressed:
                    # Download compressed archive
                    archive_key = f"{prefix}/{sync_meta.archive_name}"
                    try:
                        archive_data = rclone.read_file(
                            self._config.drive_remote,
                            self._config.drive_root,
                            archive_key,
                            env=self._env,
                            binary=self._rclone_bin,
                            config_file=self._rclone_config_file,
                            report_cli=False,
                        )
                        archive_path = staging_path / sync_meta.archive_name
                        archive_path.write_bytes(archive_data)
                        with tarfile.open(archive_path, "r:gz") as tar:
                            # Security: validate paths to prevent path traversal
                            for member in tar.getmembers():
                                if member.name.startswith("/") or ".." in member.name:
                                    raise SyncError(
                                        f"Unsafe path in archive: {member.name}"
                                    )
                            tar.extractall(staging_path)
                    except RcloneError:
                        # Archive not found — fall back to legacy download
                        rclone.download(
                            self._config.drive_remote,
                            self._config.drive_root,
                            prefix,
                            game_dir,
                            env=self._env,
                            binary=self._rclone_bin,
                            config_file=self._rclone_config_file,
                        )
                else:
                    # Legacy: download individual files
                    rclone.download(
                        self._config.drive_remote,
                        self._config.drive_root,
                        prefix,
                        game_dir,
                        env=self._env,
                        binary=self._rclone_bin,
                        config_file=self._rclone_config_file,
                    )

                convert_simple_backup_for_restore(
                    game_dir,
                    manifest.host,
                    self._restore_platform(target_wine_prefix),
                    target_wine_prefix=target_wine_prefix,
                    target_wine_user=target_wine_user,
                    env=self._conversion_env(),
                )

                # Restore via Ludusavi
                ludusavi.restore_game(game_id, game_dir, binary=self._ludusavi_bin)

                # Cache the cloud manifest locally
                self._save_local_manifest(manifest)

                return SyncResult(game_id=game_id, status=SyncStatus.SYNCED)

        except (LudusaviError, RcloneError, SyncError) as exc:
            return SyncResult(game_id=game_id, status=SyncStatus.UNKNOWN, error=str(exc))

    def check_status(self, game_id: str, *, use_live_local: bool = False) -> SyncResult:
        """Compare the local cached manifest with the cloud sync metadata.

        Tries the lightweight sync_meta.json first for speed, then falls back
        to the full manifest.json for backward compatibility.
        """
        local: GameManifest | None
        if use_live_local:
            live_probe_ok, live_local = self._probe_live_local_manifest(game_id)
            local = live_local if live_probe_ok else self._get_local_manifest(game_id)
        else:
            local = self._get_local_manifest(game_id)

        # Fast path: try lightweight sync_meta.json
        cloud_meta = self._get_cloud_sync_meta(game_id)
        if cloud_meta is not None and local is not None:
            status = manifest_module.compare_meta(local, cloud_meta)
            return SyncResult(game_id=game_id, status=status, local_manifest=local)

        # Slow path: fall back to full manifest
        cloud = self.get_cloud_manifest(game_id)

        if cloud is None and local is None:
            return SyncResult(game_id=game_id, status=SyncStatus.UNKNOWN)

        if cloud is None:
            return SyncResult(game_id=game_id, status=SyncStatus.LOCAL_NEWER, local_manifest=local)

        if local is None:
            return SyncResult(game_id=game_id, status=SyncStatus.CLOUD_NEWER, cloud_manifest=cloud)

        status = manifest_module.compare(local, cloud)
        return SyncResult(
            game_id=game_id,
            status=status,
            local_manifest=local,
            cloud_manifest=cloud,
        )

    def sync(
        self,
        game_id: str,
        target_wine_prefix: str | None = None,
        target_wine_user: str | None = None,
    ) -> SyncResult:
        """Smart sync: push, pull, or report conflict based on manifest comparison.

        Returns ``CONFLICT`` if both local and cloud are independently modified —
        the caller must resolve via the conflict dialog before proceeding.

        Args:
            game_id: Ludusavi game identifier.

        Returns:
            :class:`SyncResult` with the final sync status.
        """
        status_result = self.check_status(game_id, use_live_local=True)

        if status_result.status == SyncStatus.SYNCED:
            return status_result

        if status_result.status == SyncStatus.CONFLICT:
            cloud = status_result.cloud_manifest or self.get_cloud_manifest(game_id)
            local = status_result.local_manifest

            # Scan ALL files in the save directories for broader metadata
            dir_stat: SaveDirStat | None = None
            confidence = None
            if local is not None and cloud is not None:
                try:
                    source_game = self._live_source_game(game_id)
                    if source_game is not None:
                        dir_stat = scan_save_directories(source_game.save_paths)
                except Exception:
                    pass

                confidence = manifest_module.compute_confidence(
                    local, cloud,
                    local_dir_oldest_created=dir_stat.oldest_created if dir_stat else None,
                    local_dir_newest_modified=dir_stat.newest_modified if dir_stat else None,
                    local_dir_file_count=dir_stat.total_files if dir_stat else None,
                )

            return SyncResult(
                game_id=game_id,
                status=SyncStatus.CONFLICT,
                local_manifest=local,
                cloud_manifest=cloud,
                confidence=confidence,
                save_dir_stat=dir_stat,
            )

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
            return self.pull(
                game_id,
                cloud,
                target_wine_prefix=target_wine_prefix,
                target_wine_user=target_wine_user,
            )

        return status_result
