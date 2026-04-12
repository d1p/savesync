from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from savesync_bridge.cli import rclone as rclone_cli
from savesync_bridge.cli.ludusavi import LudusaviGame, list_games
from savesync_bridge.core.config import AppConfig
from savesync_bridge.core.sync_engine import SyncEngine, SyncResult
from savesync_bridge.models.game import GameManifest, SyncStatus


class ScanWorker(QThread):
    """Runs ``list_games()`` in a background thread."""

    games_ready = Signal(list)  # list[LudusaviGame]
    error = Signal(str)

    def __init__(self, engine: SyncEngine, parent: object = None) -> None:
        super().__init__(parent)
        self._engine = engine

    def run(self) -> None:
        try:
            games: list[LudusaviGame] = list_games(binary=self._engine.ludusavi_bin)
            self.games_ready.emit(games)
        except Exception as exc:
            self.error.emit(str(exc))


class SyncWorker(QThread):
    """Runs ``SyncEngine.sync()`` for one or more games in a background thread.

    Emits ``conflict_detected`` when a game has conflicting saves on both sides.
    """

    game_updated = Signal(str, object)  # game_id, SyncResult
    conflict_detected = Signal(str, object, object)  # game_id, local_manifest, cloud_manifest
    finished = Signal()
    error = Signal(str)

    def __init__(
        self,
        engine: SyncEngine,
        game_ids: list[str],
        target_wine_contexts: dict[str, tuple[str | None, str | None]] | None = None,
        parent: object = None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._game_ids = list(game_ids)
        self._target_wine_contexts = target_wine_contexts or {}

    def run(self) -> None:
        try:
            for game_id in self._game_ids:
                target_wine_prefix, target_wine_user = self._target_wine_contexts.get(
                    game_id,
                    (None, None),
                )
                result: SyncResult = self._engine.sync(
                    game_id,
                    target_wine_prefix=target_wine_prefix,
                    target_wine_user=target_wine_user,
                )
                if result.status == SyncStatus.CONFLICT:
                    local = self._engine.get_local_manifest(game_id)
                    cloud = self._engine.get_cloud_manifest(game_id)
                    self.conflict_detected.emit(game_id, local, cloud)
                else:
                    self.game_updated.emit(game_id, result)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class PushWorker(QThread):
    """Runs ``SyncEngine.push()`` for games sequentially."""

    game_updated = Signal(str, object)  # game_id, SyncResult
    progress = Signal(int, int)  # done, total
    finished = Signal()
    error = Signal(str)

    def __init__(
        self,
        engine: SyncEngine,
        game_ids: list[str],
        concurrency: int = 1,
        parent: object = None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._game_ids = list(game_ids)

    def run(self) -> None:
        total = len(self._game_ids)
        done = 0
        self.progress.emit(0, total)
        try:
            for game_id in self._game_ids:
                result = self._engine.push(game_id)
                done += 1
                self.game_updated.emit(game_id, result)
                self.progress.emit(done, total)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class PullWorker(QThread):
    """Runs ``SyncEngine.pull()`` for one or more games sequentially."""

    game_done = Signal(str, object)  # game_id, SyncResult
    progress = Signal(int, int)  # done, total
    finished = Signal()
    error = Signal(str)

    def __init__(
        self,
        engine: SyncEngine,
        pull_specs: list[tuple[str, GameManifest, str | None, str | None]],
        concurrency: int = 1,
        parent: object = None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._pull_specs = list(pull_specs)

    def run(self) -> None:
        total = len(self._pull_specs)
        done = 0
        self.progress.emit(0, total)
        try:
            for game_id, manifest, wine_prefix, wine_user in self._pull_specs:
                result = self._engine.pull(
                    game_id,
                    manifest,
                    target_wine_prefix=wine_prefix,
                    target_wine_user=wine_user,
                )
                done += 1
                self.game_done.emit(game_id, result)
                self.progress.emit(done, total)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class FetchCloudManifestWorker(QThread):
    """Fetch cloud manifests for one or more games sequentially."""

    manifest_ready = Signal(str, object)  # game_id, GameManifest | None
    progress = Signal(int, int)  # done, total
    all_done = Signal()
    error = Signal(str)

    def __init__(
        self,
        engine: SyncEngine,
        game_ids: list[str],
        concurrency: int = 1,
        parent: object = None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._game_ids = list(game_ids)

    def run(self) -> None:
        total = len(self._game_ids)
        done = 0
        self.progress.emit(0, total)
        try:
            for game_id in self._game_ids:
                manifest = self._engine.get_cloud_manifest(game_id)
                done += 1
                self.manifest_ready.emit(game_id, manifest)
                self.progress.emit(done, total)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.all_done.emit()


class DriveConfigWorker(QThread):
    """Run Drive authentication or verification commands in the background."""

    completed = Signal(str, str)  # action, message
    error = Signal(str)

    def __init__(
        self,
        action: str,
        config: AppConfig,
        rclone_config_file: Path,
        parent: object = None,
    ) -> None:
        super().__init__(parent)
        self._action = action
        self._config = config
        self._rclone_config_file = rclone_config_file

    def run(self) -> None:
        try:
            binary = Path(self._config.rclone_path) if self._config.rclone_path else None

            if self._action == "authenticate":
                rclone_cli.configure_google_drive_remote(
                    self._config.drive_remote,
                    self._rclone_config_file,
                    client_id=self._config.drive_client_id,
                    client_secret=self._config.drive_client_secret,
                    binary=binary,
                )
                self.completed.emit(
                    self._action,
                    "Google Drive connected and token saved.",
                )
                return

            if self._action == "reconnect":
                rclone_cli.reconnect_google_drive_remote(
                    self._config.drive_remote,
                    self._rclone_config_file,
                    binary=binary,
                )
                self.completed.emit(self._action, "Google Drive token refreshed.")
                return

            if self._action == "disconnect":
                rclone_cli.delete_remote_config(
                    self._config.drive_remote,
                    self._rclone_config_file,
                    binary=binary,
                )
                self.completed.emit(self._action, "Saved Google Drive token removed.")
                return

            if self._action == "verify":
                rclone_cli.verify_google_drive_remote(
                    self._config.drive_remote,
                    self._config.drive_root,
                    binary=binary,
                    config_file=self._rclone_config_file,
                )
                self.completed.emit(self._action, "Google Drive connection verified.")
                return

            raise ValueError(f"Unsupported Drive action: {self._action}")
        except Exception as exc:
            self.error.emit(str(exc))
