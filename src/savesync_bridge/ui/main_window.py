from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from savesync_bridge.cli.ludusavi import LudusaviGame
from savesync_bridge.core.config import AppConfig, save_config
from savesync_bridge.core.path_translator import extract_wine_prefix_metadata
from savesync_bridge.core.sync_engine import SyncEngine, SyncResult
from savesync_bridge.models.game import Game, GameManifest, SyncStatus
from savesync_bridge.ui.conflict_dialog import ConflictDialog
from savesync_bridge.ui.settings_dialog import SettingsDialog
from savesync_bridge.ui.widgets.debug_panel import DebugPanel
from savesync_bridge.ui.widgets.game_list import GameListWidget
from savesync_bridge.ui.workers import PullWorker, PushWorker, ScanWorker, SyncWorker


def _ludusavi_to_game(lg: LudusaviGame) -> Game:
    steam_app_id, wine_prefix, wine_user = extract_wine_prefix_metadata(lg.save_paths)
    return Game(
        id=lg.name,
        name=lg.name,
        steam_app_id=steam_app_id,
        wine_prefix=wine_prefix,
        wine_user=wine_user,
        save_paths=tuple(lg.save_paths),
    )


class MainWindow(QMainWindow):
    """Main application window — Sync Center."""

    def __init__(self, config: AppConfig, engine: SyncEngine) -> None:
        super().__init__()
        self._config = config
        self._engine = engine
        self._games: dict[str, Game] = {}

        self.setWindowTitle("SaveSync-Bridge")
        self.setMinimumSize(960, 640)

        self._build_toolbar()
        self._build_central()
        self._connect_signals()
        self._debug.log_info("SaveSync-Bridge started — click ▶ to expand console")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setObjectName("main_toolbar")
        self.addToolBar(toolbar)

        self._refresh_action = toolbar.addAction("↻  Refresh All")
        self._push_all_action = toolbar.addAction("⬆  Push All")
        self._pull_all_action = toolbar.addAction("⬇  Pull All")
        toolbar.addSeparator()
        self._settings_action = toolbar.addAction("⚙  Settings")

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        self._status_label = QLabel("Ready")
        self._status_label.setStyleSheet("padding: 0 10px; color: #6c7086; font-size: 10pt;")
        toolbar.addWidget(self._status_label)

    def _build_central(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        from PySide6.QtWidgets import QSplitter

        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("QSplitter::handle { background: #45475a; }")
        central_layout.addWidget(splitter)

        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)
        splitter.addWidget(top_widget)

        # ---- Sidebar ----
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(168)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 18, 10, 10)
        sidebar_layout.setSpacing(4)

        logo = QLabel("SaveSync\nBridge")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(
            "font-size: 14pt; font-weight: bold; color: #cba6f7; "
            "padding: 0 0 10px 0; background: transparent;"
        )
        sidebar_layout.addWidget(logo)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #45475a; max-height: 1px; border: none;")
        sidebar_layout.addWidget(sep)
        sidebar_layout.addSpacing(10)

        filter_hdr = QLabel("GAMES FILTER")
        filter_hdr.setStyleSheet(
            "font-size: 8pt; color: #6c7086; font-weight: bold; "
            "letter-spacing: 1px; background: transparent;"
        )
        sidebar_layout.addWidget(filter_hdr)
        sidebar_layout.addSpacing(4)

        self._filter_btns: list[tuple[SyncStatus | None, QPushButton]] = []
        for label, status in [
            ("● All", None),
            ("● Sync Issues", SyncStatus.LOCAL_NEWER),
            ("● Conflicts", SyncStatus.CONFLICT),
        ]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFlat(True)
            btn.setStyleSheet("text-align: left; padding: 5px 8px; border-radius: 4px;")
            sidebar_layout.addWidget(btn)
            self._filter_btns.append((status, btn))

        self._filter_btns[0][1].setChecked(True)
        sidebar_layout.addStretch()
        top_layout.addWidget(sidebar)

        # ---- Game list ----
        self._game_list = GameListWidget()
        top_layout.addWidget(self._game_list)

        # ---- Debug panel ----
        self._debug = DebugPanel()
        splitter.addWidget(self._debug)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._refresh_action.triggered.connect(self._on_refresh)
        self._push_all_action.triggered.connect(self._on_push_all)
        self._pull_all_action.triggered.connect(self._on_pull_all)
        self._settings_action.triggered.connect(self._on_settings)

        self._game_list.push_requested.connect(self._on_push_game)
        self._game_list.pull_requested.connect(self._on_pull_game)
        self._game_list.details_requested.connect(self._on_details_game)

        for status, btn in self._filter_btns:
            btn.clicked.connect(lambda _checked, s=status: self._on_filter(s))

        # Wire CLI subprocess events to the debug panel
        try:
            from savesync_bridge.core.cli_bus import cli_bus

            cli_bus.command_run.connect(self._debug.log_command)
            cli_bus.stdout_line.connect(self._debug.log_stdout)
            cli_bus.stderr_line.connect(self._debug.log_stderr)
            cli_bus.exit_code.connect(self._debug.log_exit)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Toolbar slots
    # ------------------------------------------------------------------

    def _on_refresh(self) -> None:
        self._set_status("Scanning games…")
        self._refresh_action.setEnabled(False)
        self._debug.log_info("Scanning games via ludusavi…")

        worker = ScanWorker(self._engine, parent=self)
        worker.games_ready.connect(self._on_games_ready)
        worker.error.connect(self._on_worker_error)
        worker.finished.connect(lambda: self._refresh_action.setEnabled(True))
        worker.start()

    def _on_games_ready(self, ludusavi_games: list[LudusaviGame]) -> None:
        games = [_ludusavi_to_game(lg) for lg in ludusavi_games]
        self._games = {g.id: g for g in games}
        self._game_list.set_games(games)
        count = len(games)
        self._set_status(f"{count} game(s) found")
        self._debug.log_info(f"Scan complete — {count} game(s) discovered")

    def _on_push_all(self) -> None:
        game_ids = list(self._games.keys())
        if not game_ids:
            self._set_status("No games to push")
            return
        self._set_status(f"Pushing {len(game_ids)} game(s)…")
        self._debug.log_info(f"Push All → {len(game_ids)} game(s): {', '.join(game_ids)}")
        worker = PushWorker(self._engine, game_ids, parent=self)
        worker.game_updated.connect(self._on_game_updated)
        worker.game_updated.connect(
            lambda gid, res: self._debug.log_info(f"  push {gid} → {res.status.name}")
        )
        worker.finished.connect(lambda: self._set_status("Push complete"))
        worker.finished.connect(lambda: self._debug.log_info("Push All complete"))
        worker.error.connect(self._on_worker_error)
        worker.start()

    def _on_pull_all(self) -> None:
        for game_id in list(self._games.keys()):
            cloud = self._engine.get_cloud_manifest(game_id)
            if cloud is not None:
                self._start_pull(game_id, cloud)

    def _on_settings(self) -> None:
        from PySide6.QtWidgets import QDialog

        dlg = SettingsDialog(self._config, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._config = dlg.get_config()
            save_config(self._config)

    # ------------------------------------------------------------------
    # Game-card slots
    # ------------------------------------------------------------------

    def _on_push_game(self, game_id: str) -> None:
        self._set_status(f"Pushing {game_id}…")
        self._debug.log_info(f"Push → {game_id}")
        worker = PushWorker(self._engine, [game_id], parent=self)
        worker.game_updated.connect(self._on_game_updated)
        worker.game_updated.connect(
            lambda gid, res: self._debug.log_info(f"  push {gid} → {res.status.name}")
        )
        worker.finished.connect(lambda: self._set_status("Push complete"))
        worker.error.connect(self._on_worker_error)
        worker.start()

    def _on_pull_game(self, game_id: str) -> None:
        cloud = self._engine.get_cloud_manifest(game_id)
        if cloud is None:
            self._set_status(f"No cloud save found for '{game_id}'")
            return
        self._start_pull(game_id, cloud)

    def _on_details_game(self, game_id: str) -> None:
        """Trigger a smart sync for the game; shows conflict dialog if needed."""
        self._set_status(f"Checking sync status for {game_id}…")
        worker = SyncWorker(
            self._engine,
            [game_id],
            target_wine_contexts={
                game_id: (
                    self._games[game_id].wine_prefix,
                    self._games[game_id].wine_user,
                )
            },
            parent=self,
        )
        worker.game_updated.connect(self._on_game_updated)
        worker.conflict_detected.connect(self._on_conflict_detected)
        worker.finished.connect(lambda: self._set_status("Status check complete"))
        worker.error.connect(self._on_worker_error)
        worker.start()

    # ------------------------------------------------------------------
    # Worker result handlers
    # ------------------------------------------------------------------

    def _start_pull(self, game_id: str, manifest: GameManifest) -> None:
        self._set_status(f"Pulling {game_id}…")
        wine_prefix = self._games.get(game_id).wine_prefix if game_id in self._games else None
        wine_user = self._games.get(game_id).wine_user if game_id in self._games else None
        worker = PullWorker(
            self._engine,
            game_id,
            manifest,
            target_wine_prefix=wine_prefix,
            target_wine_user=wine_user,
            parent=self,
        )
        worker.finished.connect(self._on_pull_done)
        worker.error.connect(self._on_worker_error)
        worker.start()

    def _on_pull_done(self, game_id: str, result: SyncResult) -> None:
        self._on_game_updated(game_id, result)
        self._set_status("Pull complete")

    def _on_game_updated(self, game_id: str, result: SyncResult) -> None:
        if game_id not in self._games:
            return
        old = self._games[game_id]
        updated = Game(
            id=old.id,
            name=old.name,
            steam_app_id=old.steam_app_id,
            wine_prefix=old.wine_prefix,
            wine_user=old.wine_user,
            save_paths=old.save_paths,
            status=result.status,
            local_manifest=old.local_manifest,
            cloud_manifest=old.cloud_manifest,
        )
        self._games[game_id] = updated
        self._game_list.update_game(updated)

    def _on_conflict_detected(
        self,
        game_id: str,
        local_manifest: object,
        cloud_manifest: object,
    ) -> None:
        if game_id not in self._games:
            return
        game = self._games[game_id]
        dlg = ConflictDialog(
            game,
            local_manifest,  # type: ignore[arg-type]
            cloud_manifest,  # type: ignore[arg-type]
            parent=self,
        )
        dlg.exec()
        choice = dlg.get_choice()
        if choice == ConflictDialog.Choice.KEEP_LOCAL:
            self._on_push_game(game_id)
        elif choice == ConflictDialog.Choice.KEEP_CLOUD:
            self._on_pull_game(game_id)
        # KEEP_NEITHER → do nothing

    def _on_worker_error(self, msg: str) -> None:
        self._set_status(f"Error: {msg}")
        self._debug.log_stderr(f"ERROR: {msg}")

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------

    def _on_filter(self, status: SyncStatus | None) -> None:
        for s, btn in self._filter_btns:
            btn.setChecked(s == status)
        self._game_list.set_filter(status)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, msg: str) -> None:
        self._status_label.setText(msg)
