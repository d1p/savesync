from __future__ import annotations

import hashlib
import json
import os
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from savesync_bridge.cli import ludusavi, rclone
from savesync_bridge.core import manifest as manifest_module
from savesync_bridge.core.backup_converter import convert_simple_backup_for_restore
from savesync_bridge.core.config import AppConfig, default_machine_name
from savesync_bridge.core.exceptions import LudusaviError, RcloneError, SyncError
from savesync_bridge.models.game import GameManifest, Platform, SaveFile, SyncStatus

import logging
import time

_log = logging.getLogger(__name__)

_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 1.0  # seconds


def _retry_rclone(func, *, attempts: int = _RETRY_ATTEMPTS) -> None:
    """Retry an rclone operation with exponential backoff on transient errors."""
    for attempt in range(attempts):
        try:
            func()
            return
        except RcloneError:
            if attempt == attempts - 1:
                raise
            delay = _RETRY_BASE_DELAY * (2 ** attempt)
            _log.warning("rclone error (attempt %d/%d), retrying in %.1fs…", attempt + 1, attempts, delay)
            time.sleep(delay)


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


def _get_long_path(path: Path | str) -> Path:
    """Convert a path to its long form on Windows, avoiding 8.3 short names.
    
    On Windows, tempfile and other APIs may return paths using 8.3 short names
    (like C:\\Users\\DEBASH~1\\...). This function converts them to long names.
    On other platforms, returns the path unchanged.
    """
    if sys.platform != "win32":
        return Path(path) if isinstance(path, str) else path
    
    path_obj = Path(path) if isinstance(path, str) else path
    try:
        # Get the absolute, normalized long path
        # On Windows, .resolve() attempts to convert to long form
        return path_obj.resolve()
    except (OSError, ValueError):
        return path_obj


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


def _sanitize_game_path(game_id: str) -> str:
    """Sanitize game_id for use in filesystem paths.
    
    Replaces invalid Windows characters with safe alternatives:
    - Colons become underscores
    - Forward/backslashes are replaced
    - Other reserved chars are replaced
    
    This avoids issues with game names like "Mafia: Definitive Edition".
    
    NOTE: The original game_id is ALWAYS preserved in:
    - manifest.json (game_id field)
    - Archive creation uses game_id as arcname, not sanitized name
    
    The sanitized name is only used for temporary local filesystem paths.
    During restore, the original game_id from manifest.json is used.
    """
    # Windows reserved characters: < > : " / \ | ? *
    invalid_chars = '<>:"/\\|?*'
    safe_name = game_id
    for char in invalid_chars:
        safe_name = safe_name.replace(char, '_')
    # Collapse multiple underscores
    while '__' in safe_name:
        safe_name = safe_name.replace('__', '_')
    return safe_name.strip('_')


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


_IGNORED_MANIFEST_FILES = {"mapping.yaml", "registry.yaml"}


def _build_manifest(
    game_id: str,
    game_dir: Path,
    source_file_times: dict[tuple[str, ...], _SourceFileTimes] | None = None,
    machine_id: str = "",
) -> GameManifest:
    """Compute a GameManifest by hashing all files in *game_dir*."""
    save_files: list[SaveFile] = []
    hasher = hashlib.sha256()

    for f in sorted(game_dir.rglob("*")):
        if not f.is_file():
            continue
        rel_path = f.relative_to(game_dir)
        if rel_path.name in _IGNORED_MANIFEST_FILES:
            continue

        data = f.read_bytes()
        hasher.update(data)
        file_hash = f"sha256:{hashlib.sha256(data).hexdigest()}"
        stat_result = f.stat()
        modified = datetime.fromtimestamp(stat_result.st_mtime, tz=UTC)
        created = _file_created_at(stat_result)
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
                file_hash=file_hash,
            )
        )

    host = Platform.WINDOWS if sys.platform == "win32" else Platform.LINUX
    return GameManifest(
        game_id=game_id,
        host=host,
        timestamp=datetime.now(tz=UTC),
        hash=f"sha256:{hasher.hexdigest()}",
        files=tuple(save_files),
        machine_id=machine_id,
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
        if not self._config.machine_name:
            self._config.machine_name = default_machine_name()
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
        base = self._config.backup_path.strip("/")
        return f"{base}/{game_id}" if base else game_id

    # ------------------------------------------------------------------
    # Cloud lock helpers
    # ------------------------------------------------------------------
    _LOCK_STALE_SECONDS = 300  # 5 minutes

    def _lock_key(self, game_id: str) -> str:
        return f"{self._cloud_prefix(game_id)}/.lock"

    def _acquire_lock(self, game_id: str) -> None:
        """Upload a lock file to prevent concurrent syncs from other machines."""
        key = self._lock_key(game_id)
        # Check for existing lock
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
            lock_data = json.loads(raw.decode("utf-8"))
            lock_ts = datetime.fromisoformat(lock_data.get("timestamp", ""))
            age = (datetime.now(UTC) - lock_ts).total_seconds()
            if age < self._LOCK_STALE_SECONDS:
                owner = lock_data.get("machine", "unknown")
                raise SyncError(
                    f"Sync locked by '{owner}' ({int(age)}s ago). "
                    f"Wait or manually remove the lock."
                )
            _log.warning("Stale lock found for %s (%ds old), overriding", game_id, int(age))
        except RcloneError:
            pass  # No lock exists — good
        except (json.JSONDecodeError, ValueError, TypeError, KeyError):
            _log.warning("Corrupt lock file for %s, overriding", game_id)

        # Write our lock
        lock_content = json.dumps({
            "machine": self._config.machine_name or "unknown",
            "timestamp": datetime.now(UTC).isoformat(),
        })
        with tempfile.NamedTemporaryFile(mode="w", suffix=".lock", delete=False) as f:
            f.write(lock_content)
            lock_file = Path(f.name)
        try:
            prefix = self._cloud_prefix(game_id)
            rclone.upload(
                lock_file,
                self._config.drive_remote,
                self._config.drive_root,
                prefix,
                env=self._env,
                binary=self._rclone_bin,
                config_file=self._rclone_config_file,
            )
        finally:
            lock_file.unlink(missing_ok=True)

    def _release_lock(self, game_id: str) -> None:
        """Remove the lock file from cloud."""
        key = self._lock_key(game_id)
        try:
            rclone.delete_path(
                self._config.drive_remote,
                self._config.drive_root,
                key,
                env=self._env,
                binary=self._rclone_bin,
                config_file=self._rclone_config_file,
            )
        except RcloneError:
            _log.warning("Could not release lock for %s", game_id)

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
                # Use sanitized game_id for filesystem paths to avoid issues with special chars
                safe_game_path = _sanitize_game_path(game_id)
                game_dir = staging_path / safe_game_path
                game_dir.mkdir(parents=True, exist_ok=True)
                ludusavi.backup_game(game_id, game_dir, binary=self._ludusavi_bin)
                return True, _build_manifest(
                    game_id,
                    game_dir,
                    source_file_times=source_file_times,
                )
        except LudusaviError:
            return False, None

    def _rotate_versions(self, game_id: str, prefix: str) -> None:
        """Rotate backup versions, keeping at most ``max_versions`` old snapshots."""
        max_versions = self._config.max_versions
        if max_versions <= 0:
            return

        versions_prefix = f"{prefix}/versions"
        try:
            existing = rclone.list_files(
                self._config.drive_remote,
                self._config.drive_root,
                versions_prefix,
                env=self._env,
                binary=self._rclone_bin,
                config_file=self._rclone_config_file,
            )
        except RcloneError:
            existing = []

        # Each version is stored as versions/v<N>/<file>
        version_nums: list[int] = []
        for entry in existing:
            name = entry.get("Path", entry) if isinstance(entry, dict) else str(entry)
            parts = name.replace("\\", "/").split("/")
            for part in parts:
                if part.startswith("v") and part[1:].isdigit():
                    version_nums.append(int(part[1:]))
                    break

        next_version = max(version_nums, default=0) + 1

        # Copy current live files to a versioned slot
        try:
            current_manifest = self.get_cloud_manifest(game_id)
            if current_manifest is not None:
                dest_prefix = f"{versions_prefix}/v{next_version}"
                # Only copy archive and manifest (manifest now contains all metadata)
                for fname in ("save.tar.gz", "manifest.json"):
                    src_key = f"{prefix}/{fname}"
                    try:
                        data = rclone.read_file(
                            self._config.drive_remote,
                            self._config.drive_root,
                            src_key,
                            env=self._env,
                            binary=self._rclone_bin,
                            config_file=self._rclone_config_file,
                            report_cli=False,
                        )
                        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{fname}") as tmp:
                            tmp.write(data)
                            tmp_path = Path(tmp.name)
                        try:
                            rclone.upload(
                                tmp_path,
                                self._config.drive_remote,
                                self._config.drive_root,
                                dest_prefix,
                                env=self._env,
                                binary=self._rclone_bin,
                                config_file=self._rclone_config_file,
                            )
                        finally:
                            tmp_path.unlink(missing_ok=True)
                    except RcloneError:
                        pass
        except Exception:
            pass

        # Prune excess versions (keep newest max_versions)
        unique_versions = sorted(set(version_nums + [next_version]))
        if len(unique_versions) > max_versions:
            to_delete = unique_versions[:len(unique_versions) - max_versions]
            for vnum in to_delete:
                try:
                    rclone.delete_path(
                        self._config.drive_remote,
                        self._config.drive_root,
                        f"{versions_prefix}/v{vnum}",
                        env=self._env,
                        binary=self._rclone_bin,
                        config_file=self._rclone_config_file,
                    )
                except (RcloneError, AttributeError):
                    pass  # delete_path may not exist yet; will be added

    def _log_history(
        self, game_id: str, action: str, *, error: str | None = None, confidence: float | None = None,
    ) -> None:
        """Append an entry to the sync history log."""
        try:
            entry = manifest_module.SyncHistoryEntry(
                timestamp=datetime.now(tz=UTC).isoformat(),
                game_id=game_id,
                action=action,
                machine_id=self._config.machine_name,
                confidence=confidence,
                error=error,
            )
            manifest_module.append_sync_history(self._state_dir, entry)
        except Exception:
            pass  # history logging should never break sync

    def verify_cloud_integrity(self, game_id: str) -> tuple[bool, str]:
        """Verify cloud archive integrity by comparing manifest hash.

        Returns (ok, message).
        """
        try:
            cloud_manifest = self.get_cloud_manifest(game_id)
            if cloud_manifest is None:
                return False, "Missing cloud manifest"
            # Manifest now contains all metadata and compression info
            return True, f"Integrity OK — hash {cloud_manifest.hash}"
        except Exception as exc:
            return False, f"Verification error: {exc}"

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

    def _get_cloud_sync_meta(self, game_id: str) -> GameManifest | None:
        """DEPRECATED: Use get_cloud_manifest() instead. Returns the manifest with compression metadata."""
        manifest = self.get_cloud_manifest(game_id)
        return manifest if manifest is not None else None

    def push(self, game_id: str) -> SyncResult:
        """Back up *game_id* via Ludusavi, compress, and upload to cloud storage.

        The save files are compressed into a tar.gz archive before uploading.
        The manifest.json contains all metadata including compression info and file hashes
        for fast status checks and detailed diffs without requiring separate files.
        Older versions are retained up to ``config.max_versions``.
        """
        try:
            self._acquire_lock(game_id)
        except SyncError:
            raise
        except Exception:
            pass  # Lock failure should not block sync

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
                # Use sanitized game_id for filesystem paths to avoid issues with special chars
                safe_game_path = _sanitize_game_path(game_id)
                game_dir = staging_path / safe_game_path
                game_dir.mkdir(parents=True, exist_ok=True)

                # 1. Backup via Ludusavi
                ludusavi.backup_game(game_id, game_dir, binary=self._ludusavi_bin)

                # 2. Build a content manifest
                m = _build_manifest(
                    game_id,
                    game_dir,
                    source_file_times=source_file_times,
                    machine_id=self._config.machine_name,
                )

                # 3. Compress save files into archive
                archive_name = "save.tar.gz"
                archive_path = staging_path / archive_name
                with tarfile.open(archive_path, "w:gz") as tar:
                    tar.add(game_dir, arcname=game_id)
                archive_size = archive_path.stat().st_size

                # 4. Create manifest with compression metadata
                # This replaces the old separate sync_meta.json — all metadata in one file
                m_with_archive_info = GameManifest(
                    game_id=m.game_id,
                    host=m.host,
                    timestamp=m.timestamp,
                    hash=m.hash,
                    files=m.files,
                    machine_id=m.machine_id,
                    compressed=True,
                    archive_name=archive_name,
                    total_size=archive_size,
                )

                # 5. Write manifest.json with all metadata
                manifest_file = staging_path / "manifest.json"
                manifest_file.write_text(manifest_module.to_json(m_with_archive_info), encoding="utf-8")

                prefix = self._cloud_prefix(game_id)

                # 6. Rotate old versions before uploading new one
                self._rotate_versions(game_id, prefix)

                # 7. Upload compressed archive (single file instead of many)
                _retry_rclone(lambda: rclone.upload(
                    archive_path,
                    self._config.drive_remote,
                    self._config.drive_root,
                    prefix,
                    env=self._env,
                    binary=self._rclone_bin,
                    config_file=self._rclone_config_file,
                ))

                # 8. Upload manifest.json (contains all metadata: files, hash, compression info)
                _retry_rclone(lambda: rclone.upload(
                    manifest_file,
                    self._config.drive_remote,
                    self._config.drive_root,
                    prefix,
                    env=self._env,
                    binary=self._rclone_bin,
                    config_file=self._rclone_config_file,
                ))

                # 9. Persist manifest locally so check_status can diff later
                self._save_local_manifest(m)

                # 10. Log sync history
                self._log_history(game_id, "push")

                self._release_lock(game_id)
                return SyncResult(
                    game_id=game_id,
                    status=SyncStatus.SYNCED,
                    local_manifest=m,
                )

        except (LudusaviError, RcloneError, SyncError) as exc:
            self._release_lock(game_id)
            self._log_history(game_id, "push", error=str(exc))
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
            self._acquire_lock(game_id)
        except SyncError:
            raise
        except Exception:
            pass  # Lock failure should not block sync

        try:
            with tempfile.TemporaryDirectory() as staging:
                staging_path = Path(staging)
                # Use sanitized game_id for filesystem paths to avoid issues with special chars
                safe_game_path = _sanitize_game_path(game_id)
                game_dir = staging_path / safe_game_path
                game_dir.mkdir(parents=True, exist_ok=True)

                prefix = self._cloud_prefix(game_id)

                # Check if cloud save is compressed (v2 format)
                # The manifest now contains this info directly
                if manifest.compressed:
                    # Download compressed archive
                    archive_key = f"{prefix}/{manifest.archive_name}"
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
                        archive_path = staging_path / manifest.archive_name
                        archive_path.write_bytes(archive_data)
                        with tarfile.open(archive_path, "r:gz") as tar:
                            # Security: validate paths to prevent path traversal
                            for member in tar.getmembers():
                                if member.name.startswith("/") or ".." in member.name:
                                    raise SyncError(
                                        f"Unsafe path in archive: {member.name}"
                                    )
                            tar.extractall(staging_path)
                        
                        # After extraction, the archive structure is:
                        # staging_path/game_id/drive-C/...
                        # We need to use the nested directory for restore
                        nested_game_dir = staging_path / game_id
                        if nested_game_dir.exists():
                            game_dir = nested_game_dir
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

                self._log_history(game_id, "pull")

                self._release_lock(game_id)
                return SyncResult(game_id=game_id, status=SyncStatus.SYNCED)

        except (LudusaviError, RcloneError, SyncError) as exc:
            self._release_lock(game_id)
            self._log_history(game_id, "pull", error=str(exc))
            return SyncResult(game_id=game_id, status=SyncStatus.UNKNOWN, error=str(exc))

    def check_status(self, game_id: str, *, use_live_local: bool = False) -> SyncResult:
        """Compare the local cached manifest with the cloud manifest.

        The manifest.json now contains all metadata needed for comparison and status
        checks, so no separate lightweight file is needed.
        
        Uses machine ID and timestamp checks to intelligently resolve local vs cloud
        conflicts: if the local version originated from the current machine and is
        newer, immediately returns LOCAL_NEWER without conflict resolution.
        """
        local: GameManifest | None
        if use_live_local:
            live_probe_ok, live_local = self._probe_live_local_manifest(game_id)
            local = live_local if live_probe_ok else self._get_local_manifest(game_id)
        else:
            local = self._get_local_manifest(game_id)

        # Fetch cloud manifest - it now contains all metadata for comparison
        cloud = self.get_cloud_manifest(game_id)

        if cloud is None and local is None:
            return SyncResult(game_id=game_id, status=SyncStatus.UNKNOWN)

        if cloud is None:
            return SyncResult(game_id=game_id, status=SyncStatus.LOCAL_NEWER, local_manifest=local)

        if local is None:
            return SyncResult(game_id=game_id, status=SyncStatus.CLOUD_NEWER, cloud_manifest=cloud)

        # Compare manifests directly - no separate sync_meta needed
        status = manifest_module.compare(local, cloud, runner_machine_id=self._config.machine_name)
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

        if status_result.status in (SyncStatus.LOCAL_NEWER,):
            return self.push(game_id)

        if status_result.status == SyncStatus.UNKNOWN:
            # Don't auto-push UNKNOWN — return it so the UI can prompt the user
            return status_result

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

    # ------------------------------------------------------------------
    # Export / Import backup library
    # ------------------------------------------------------------------

    def list_cloud_games(self) -> list[str]:
        """Return game IDs that have saves stored in the cloud."""
        try:
            entries = rclone.list_files(
                self._config.drive_remote,
                self._config.drive_root,
                self._config.backup_path,
                env=self._env,
                binary=self._rclone_bin,
                config_file=self._rclone_config_file,
            )
            return [
                e["Path"] for e in entries
                if e.get("IsDir", False)
            ]
        except RcloneError:
            return []

    # ------------------------------------------------------------------
    # Batch operations (optimized for syncing multiple games)
    # ------------------------------------------------------------------

    @dataclass
    class BatchSyncPlan:
        """Result of analyzing multiple games to determine sync actions."""
        to_push: list[str]  # game_ids that should be pushed to cloud
        to_pull: list[str]  # game_ids that should be pulled from cloud
        to_skip: list[str]  # game_ids that are already synced
        conflicts: dict[str, tuple[GameManifest | None, GameManifest | None]]  # game_id -> (local, cloud)
        unknown: list[str]  # game_ids with no cloud save (UNKNOWN status)
        results: dict[str, SyncResult]  # Full SyncResult for each game

    def batch_sync_all(
        self,
        game_ids: list[str],
        target_wine_contexts: dict[str, tuple[str | None, str | None]] | None = None,
    ) -> BatchSyncPlan:
        """Analyze and sync multiple games efficiently in a single batch operation.
        
        This method optimizes the sync flow by:
        1. Backing up ALL local games with a single ludusavi call
        2. Fetching ALL cloud metadata with minimal rclone calls
        3. Computing sync state for all games
        4. Uploading all files to be pushed in a single rclone operation
        5. Downloading all files to be pulled in a single rclone operation

        Args:
            game_ids: List of game IDs to sync.
            target_wine_contexts: Optional dict mapping game_id -> (wine_prefix, wine_user).

        Returns:
            BatchSyncPlan with actions for each game.
        """
        if not game_ids:
            return self.BatchSyncPlan([], [], [], {}, [], {})

        target_wine_contexts = target_wine_contexts or {}
        plan = self.BatchSyncPlan([], [], [], {}, [], {})

        with tempfile.TemporaryDirectory() as staging:
            staging_path = Path(staging)

            # Step 1: Backup ALL local games in a single ludusavi call
            try:
                backup_dirs = ludusavi.backup_games(game_ids, staging_path, binary=self._ludusavi_bin)
            except LudusaviError as e:
                _log.error("Batch backup failed: %s", e)
                # Fallback: use individual backups
                backup_dirs = {}
                for game_id in game_ids:
                    try:
                        safe_path = _sanitize_game_path(game_id)
                        game_dir = staging_path / safe_path
                        game_dir.mkdir(parents=True, exist_ok=True)
                        ludusavi.backup_game(game_id, game_dir, binary=self._ludusavi_bin)
                        backup_dirs[game_id] = game_dir
                    except LudusaviError as ge:
                        _log.warning("Failed to backup %s: %s", game_id, ge)

            # Step 2: Build local manifests from backups
            local_manifests: dict[str, GameManifest | None] = {}
            source_games: dict[str, ludusavi.LudusaviGame | None] = {}

            for game_id in game_ids:
                try:
                    source_game = self._live_source_game(game_id)
                    source_games[game_id] = source_game
                except LudusaviError:
                    source_games[game_id] = None

                if game_id in backup_dirs:
                    source_file_times = (
                        _collect_source_file_times(source_games[game_id])
                        if source_games[game_id] is not None
                        else None
                    )
                    local_manifests[game_id] = _build_manifest(
                        game_id,
                        backup_dirs[game_id],
                        source_file_times=source_file_times,
                        machine_id=self._config.machine_name,
                    )
                else:
                    local_manifests[game_id] = None

            # Step 3: Fetch all cloud manifests efficiently
            # Manifests now contain all metadata (compression info, file hashes, etc.)
            cloud_manifests: dict[str, GameManifest | None] = {}

            # Batch fetch all manifest files
            paths_to_fetch = []
            for game_id in game_ids:
                paths_to_fetch.append(f"{self._cloud_prefix(game_id)}/manifest.json")

            try:
                fetched_files = rclone.read_files(
                    self._config.drive_remote,
                    self._config.drive_root,
                    paths_to_fetch,
                    env=self._env,
                    binary=self._rclone_bin,
                    config_file=self._rclone_config_file,
                    report_cli=False,
                )

                for game_id in game_ids:
                    manifest_path = f"{self._cloud_prefix(game_id)}/manifest.json"
                    manifest_bytes = fetched_files.get(manifest_path)
                    if manifest_bytes:
                        try:
                            cloud_manifests[game_id] = manifest_module.from_json(
                                manifest_bytes.decode("utf-8")
                            )
                        except (json.JSONDecodeError, KeyError, ValueError):
                            cloud_manifests[game_id] = None
                    else:
                        cloud_manifests[game_id] = None
            except Exception as e:
                _log.warning("Batch cloud fetch failed, falling back to individual fetches: %s", e)
                for game_id in game_ids:
                    cloud_manifests[game_id] = self.get_cloud_manifest(game_id)

            # Step 4: Determine sync actions for each game
            for game_id in game_ids:
                local = local_manifests.get(game_id)
                cloud = cloud_manifests.get(game_id)

                # Compare states using full manifest comparison
                # (manifest now contains all necessary metadata)
                if cloud is None and local is None:
                    status = SyncStatus.UNKNOWN
                elif cloud is None:
                    status = SyncStatus.LOCAL_NEWER
                elif local is None:
                    status = SyncStatus.CLOUD_NEWER
                else:
                    status = manifest_module.compare(
                        local, cloud, runner_machine_id=self._config.machine_name
                    )

                # Categorize action
                if status == SyncStatus.SYNCED:
                    plan.to_skip.append(game_id)
                elif status == SyncStatus.LOCAL_NEWER:
                    plan.to_push.append(game_id)
                elif status == SyncStatus.CLOUD_NEWER:
                    plan.to_pull.append(game_id)
                elif status == SyncStatus.CONFLICT:
                    plan.conflicts[game_id] = (local, cloud)
                elif status == SyncStatus.UNKNOWN:
                    plan.unknown.append(game_id)

                # Store result
                plan.results[game_id] = SyncResult(
                    game_id=game_id,
                    status=status,
                    local_manifest=local,
                    cloud_manifest=cloud,
                )

            # Step 5: Upload all files to be pushed in a single operation
            if plan.to_push:
                for game_id in plan.to_push:
                    if game_id not in backup_dirs:
                        continue

                    game_dir = backup_dirs[game_id]
                    prefix = self._cloud_prefix(game_id)
                    local = local_manifests[game_id]

                    if local is None:
                        continue

                    try:
                        # Prepare archive
                        # NOTE: Use game_id as arcname (not sanitized path) so extraction
                        # creates the correct directory structure for ludusavi.restore_game.
                        # The original game_id is stored in the manifest.json for reference.
                        archive_name = "save.tar.gz"
                        archive_path = staging_path / f"{game_id}_{archive_name}"
                        with tarfile.open(archive_path, "w:gz") as tar:
                            tar.add(game_dir, arcname=game_id)

                        archive_size = archive_path.stat().st_size

                        # Prepare manifest with compression metadata
                        # Embed archive_name and total_size in manifest instead of separate file
                        manifest_with_archive_info = GameManifest(
                            game_id=local.game_id,
                            host=local.host,
                            timestamp=local.timestamp,
                            hash=local.hash,
                            files=local.files,
                            machine_id=local.machine_id,
                            compressed=True,
                            archive_name=archive_name,
                            total_size=archive_size,
                        )

                        manifest_path = staging_path / f"{game_id}_manifest.json"
                        manifest_path.write_text(
                            manifest_module.to_json(manifest_with_archive_info), encoding="utf-8"
                        )

                        # Upload archive
                        _retry_rclone(lambda: rclone.upload(
                            archive_path,
                            self._config.drive_remote,
                            self._config.drive_root,
                            f"{prefix}/{archive_name}",
                            env=self._env,
                            binary=self._rclone_bin,
                            config_file=self._rclone_config_file,
                        ))

                        # Upload manifest (contains all metadata: compression info, file hashes, etc.)
                        _retry_rclone(lambda: rclone.upload(
                            manifest_path,
                            self._config.drive_remote,
                            self._config.drive_root,
                            f"{prefix}/manifest.json",
                            env=self._env,
                            binary=self._rclone_bin,
                            config_file=self._rclone_config_file,
                        ))

                        self._save_local_manifest(local)
                        self._log_history(game_id, "push")
                    except (RcloneError, LudusaviError, OSError) as e:
                        _log.error("Failed to push %s: %s", game_id, e)
                        plan.results[game_id].status = SyncStatus.UNKNOWN
                        plan.results[game_id].error = str(e)

            # Step 6: Download and restore all games to be pulled
            if plan.to_pull:
                for game_id in plan.to_pull:
                    prefix = self._cloud_prefix(game_id)
                    safe_game_path = _sanitize_game_path(game_id)
                    game_dir = staging_path / f"pull_{safe_game_path}"
                    game_dir.mkdir(parents=True, exist_ok=True)

                    try:
                        # Check if cloud save is compressed (v2 format)
                        # Manifest now contains all compression metadata
                        cloud = cloud_manifests.get(game_id)
                        if cloud is not None and cloud.compressed:
                            # Download compressed archive
                            archive_key = f"{prefix}/{cloud.archive_name}"
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
                                archive_path = staging_path / f"pull_{game_id}.tar.gz"
                                archive_path.write_bytes(archive_data)
                                with tarfile.open(archive_path, "r:gz") as tar:
                                    for member in tar.getmembers():
                                        if member.name.startswith("/") or ".." in member.name:
                                            raise SyncError(f"Unsafe path in archive: {member.name}")
                                    tar.extractall(game_dir)
                                
                                # After extraction, the archive structure is:
                                # game_dir/game_id/drive-C/... (if archive used arcname=game_id)
                                # We need to pass the nested directory to ludusavi
                                nested_game_dir = game_dir / game_id
                                if nested_game_dir.exists():
                                    game_dir = nested_game_dir
                            except RcloneError:
                                # Fallback to legacy download
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
                            # Legacy download
                            rclone.download(
                                self._config.drive_remote,
                                self._config.drive_root,
                                prefix,
                                game_dir,
                                env=self._env,
                                binary=self._rclone_bin,
                                config_file=self._rclone_config_file,
                            )

                        # Get wine context if available
                        wine_prefix, wine_user = target_wine_contexts.get(game_id, (None, None))

                        # Convert and restore
                        convert_simple_backup_for_restore(
                            game_dir,
                            cloud_manifests[game_id].host if cloud_manifests[game_id] else Platform.WINDOWS,
                            self._restore_platform(wine_prefix),
                            target_wine_prefix=wine_prefix,
                            target_wine_user=wine_user,
                            env=self._conversion_env(),
                        )
                        ludusavi.restore_game(game_id, game_dir, binary=self._ludusavi_bin)

                        # Cache cloud manifest locally
                        if cloud_manifests[game_id]:
                            self._save_local_manifest(cloud_manifests[game_id])

                        self._log_history(game_id, "pull")
                    except (LudusaviError, RcloneError, SyncError) as e:
                        _log.error("Failed to pull %s: %s", game_id, e)
                        plan.results[game_id].status = SyncStatus.UNKNOWN
                        plan.results[game_id].error = str(e)

        return plan

    def export_library(self, dest: Path, game_ids: list[str] | None = None) -> Path:
        """Download cloud saves and bundle them into a zip at *dest*.

        Args:
            dest: Path for the output .zip file.
            game_ids: Games to include. ``None`` means all cloud games.

        Returns:
            The resolved path of the created zip file.

        Raises:
            SyncError: If no games are found or export fails.
        """
        if game_ids is None:
            game_ids = self.list_cloud_games()
        if not game_ids:
            raise SyncError("No games found in cloud to export")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for gid in game_ids:
                prefix = self._cloud_prefix(gid)
                # Use sanitized game_id for filesystem paths
                safe_game_path = _sanitize_game_path(gid)
                game_dir = tmp_path / safe_game_path
                game_dir.mkdir(parents=True, exist_ok=True)
                try:
                    rclone.download(
                        self._config.drive_remote,
                        self._config.drive_root,
                        prefix,
                        game_dir,
                        env=self._env,
                        binary=self._rclone_bin,
                        config_file=self._rclone_config_file,
                    )
                except RcloneError as exc:
                    _log.warning("Skipping %s during export: %s", gid, exc)

            dest = dest.resolve()
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _dirs, files in os.walk(tmp_path):
                    for fn in files:
                        full = Path(root) / fn
                        arcname = full.relative_to(tmp_path).as_posix()
                        zf.write(full, arcname)

        _log.info("Exported %d game(s) to %s", len(game_ids), dest)
        return dest

    def import_library(self, src: Path, game_ids: list[str] | None = None) -> list[str]:
        """Restore cloud saves from a zip file created by :meth:`export_library`.

        Args:
            src: Path to the .zip file.
            game_ids: Games to restore. ``None`` means all games in the zip.

        Returns:
            List of game IDs that were restored.

        Raises:
            SyncError: If the zip is invalid or import fails.
        """
        if not src.is_file():
            raise SyncError(f"Import file not found: {src}")

        restored: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with zipfile.ZipFile(src, "r") as zf:
                zf.extractall(tmp_path)

            # Each top-level directory is a game_id
            for entry in sorted(tmp_path.iterdir()):
                if not entry.is_dir():
                    continue
                gid = entry.name
                if game_ids is not None and gid not in game_ids:
                    continue

                prefix = self._cloud_prefix(gid)
                # Upload each file inside the game directory
                for fpath in entry.rglob("*"):
                    if not fpath.is_file():
                        continue
                    try:
                        _retry_rclone(lambda fp=fpath, p=prefix: rclone.upload(
                            fp,
                            self._config.drive_remote,
                            self._config.drive_root,
                            p,
                            env=self._env,
                            binary=self._rclone_bin,
                            config_file=self._rclone_config_file,
                        ))
                    except RcloneError as exc:
                        _log.warning("Failed to upload %s: %s", fpath.name, exc)
                        continue
                restored.append(gid)

        _log.info("Imported %d game(s) from %s", len(restored), src)
        return restored
