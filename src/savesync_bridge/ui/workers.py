from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from savesync_bridge.cli.ludusavi import LudusaviGame, list_games
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
            games: list[LudusaviGame] = list_games(binary=self._engine._ludusavi_bin)
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
                    local = self._engine._get_local_manifest(game_id)
                    cloud = self._engine.get_cloud_manifest(game_id)
                    self.conflict_detected.emit(game_id, local, cloud)
                else:
                    self.game_updated.emit(game_id, result)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class PushWorker(QThread):
    """Runs ``SyncEngine.push()`` for one or more games in a background thread."""

    game_updated = Signal(str, object)  # game_id, SyncResult
    finished = Signal()
    error = Signal(str)

    def __init__(
        self,
        engine: SyncEngine,
        game_ids: list[str],
        parent: object = None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._game_ids = list(game_ids)

    def run(self) -> None:
        try:
            for game_id in self._game_ids:
                result: SyncResult = self._engine.push(game_id)
                self.game_updated.emit(game_id, result)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class PullWorker(QThread):
    """Runs ``SyncEngine.pull()`` for a single game in a background thread."""

    finished = Signal(str, object)  # game_id, SyncResult
    error = Signal(str)

    def __init__(
        self,
        engine: SyncEngine,
        game_id: str,
        manifest: GameManifest,
        target_wine_prefix: str | None = None,
        target_wine_user: str | None = None,
        parent: object = None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._game_id = game_id
        self._manifest = manifest
        self._target_wine_prefix = target_wine_prefix
        self._target_wine_user = target_wine_user

    def run(self) -> None:
        try:
            result: SyncResult = self._engine.pull(
                self._game_id,
                self._manifest,
                target_wine_prefix=self._target_wine_prefix,
                target_wine_user=self._target_wine_user,
            )
            self.finished.emit(self._game_id, result)
        except Exception as exc:
            self.error.emit(str(exc))
