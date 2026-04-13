from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from savesync_bridge.cli.ludusavi import LudusaviGame
from savesync_bridge.cli.rclone import has_remote_config
from savesync_bridge.core.config import (
    AppConfig,
    default_config_dir,
    rclone_config_path,
    save_config,
)
from savesync_bridge.core.game_cache import load_games, save_games
from savesync_bridge.core.path_translator import extract_wine_prefix_metadata
from savesync_bridge.core.sync_engine import SyncEngine, SyncResult
from savesync_bridge.models.game import Game, SyncStatus
from savesync_bridge.ui.conflict_dialog import ConflictDialog
from savesync_bridge.ui.settings_dialog import SettingsDialog
from savesync_bridge.ui.widgets.debug_panel import DebugPanel
from savesync_bridge.ui.widgets.game_list import GameListWidget
from savesync_bridge.ui.workers import (
    FetchCloudManifestWorker,
    PullWorker,
    PushWorker,
    ScanWorker,
    SyncWorker,
)


def _ludusavi_to_game(lg: LudusaviGame, excluded_ids: set[str] | None = None) -> Game:
    steam_app_id, wine_prefix, wine_user = extract_wine_prefix_metadata(lg.save_paths)
    return Game(
        id=lg.name,
        name=lg.name,
        steam_app_id=steam_app_id,
        wine_prefix=wine_prefix,
        wine_user=wine_user,
        save_paths=tuple(lg.save_paths),
        excluded=lg.name in (excluded_ids or set()),
    )


class MainWindow(QMainWindow):
    """Main application window — Sync Center."""

    def __init__(
        self, config: AppConfig, engine: SyncEngine, config_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._engine = engine
        self._games: dict[str, Game] = {}
        self._active_workers: list[object] = []  # prevent GC of running QThreads
        self._config_dir = config_dir if config_dir is not None else default_config_dir()
        self._rclone_config_file = rclone_config_path(self._config_dir)

        self.setWindowTitle("SaveSync-Bridge")
        self.setMinimumSize(960, 640)

        self._build_toolbar()
        self._build_central()
        self._connect_signals()
        self._refresh_backup_panel()
        self._debug.log_info("SaveSync-Bridge started — click ▶ to expand console")

        # Restore cached games so the UI is not empty on launch
        self._restore_cached_games()
        # Auto-refresh to detect new games
        self._on_refresh()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setObjectName("main_toolbar")
        self.addToolBar(toolbar)

        self._refresh_action = toolbar.addAction("\u21bb  Refresh")
        self._refresh_action.setToolTip("Re-scan local games with Ludusavi")
        self._sync_all_action = toolbar.addAction("\u21bb  Sync All")
        self._sync_all_action.setToolTip("Smart sync all non-excluded games with Google Drive")
        toolbar.addSeparator()
        self._settings_action = toolbar.addAction("\u2601  Backups")
        self._settings_action.setToolTip("Open Google Drive and backup settings")

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        self._status_label = QLabel("Ready")
        self._status_label.setStyleSheet(
            "padding: 0 14px; color: #585b70; font-size: 9pt; font-weight: 500;"
        )
        toolbar.addWidget(self._status_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedWidth(160)
        self._progress_bar.setFixedHeight(14)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setVisible(False)
        self._progress_bar.setStyleSheet(
            "QProgressBar {"
            "  background-color: #313244; border: 1px solid #45475a;"
            "  border-radius: 7px;"
            "}"
            "QProgressBar::chunk {"
            "  background-color: #cba6f7; border-radius: 6px;"
            "}"
        )
        toolbar.addWidget(self._progress_bar)

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
        sidebar.setFixedWidth(180)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 20, 12, 12)
        sidebar_layout.setSpacing(4)

        logo = QLabel("SaveSync\nBridge")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(
            "font-size: 15pt; font-weight: 700; color: #cba6f7; "
            "padding: 0 0 12px 0; background: transparent; letter-spacing: -0.5px;"
        )
        sidebar_layout.addWidget(logo)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #313244; max-height: 1px; border: none;")
        sidebar_layout.addWidget(sep)
        sidebar_layout.addSpacing(14)

        filter_hdr = QLabel("FILTER")
        filter_hdr.setStyleSheet(
            "font-size: 8pt; color: #585b70; font-weight: 600; "
            "letter-spacing: 1.5px; background: transparent;"
        )
        sidebar_layout.addWidget(filter_hdr)
        sidebar_layout.addSpacing(6)

        self._filter_btns: list[tuple[SyncStatus | None | str, QPushButton]] = []
        for label, status, tip in [
            ("\u25cf  All Games", None, "Show all discovered games"),
            ("\u25cf  Local Newer", SyncStatus.LOCAL_NEWER, "Show games whose local save is newer than the cloud"),
            ("\u25cf  Conflicts", SyncStatus.CONFLICT, "Show games with conflicting local and cloud saves"),
            ("\u25cf  Synced", SyncStatus.SYNCED, "Show games that are in sync with the cloud"),
            ("\u25cf  Excluded", "excluded", "Show games excluded from sync"),
        ]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tip)
            btn.setStyleSheet(
                "text-align: left; padding: 7px 10px; border-radius: 6px; font-size: 10pt;"
            )
            sidebar_layout.addWidget(btn)
            self._filter_btns.append((status, btn))

        self._filter_btns[0][1].setChecked(True)
        sidebar_layout.addStretch()
        top_layout.addWidget(sidebar)

        self._game_list = GameListWidget()
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        backup_panel = QFrame()
        backup_panel.setObjectName("backup_panel")
        backup_panel.setStyleSheet(
            "QFrame#backup_panel {"
            "background-color: #181825; border-bottom: 1px solid #313244;"
            "}"
        )
        backup_layout = QHBoxLayout(backup_panel)
        backup_layout.setContentsMargins(20, 16, 20, 16)
        backup_layout.setSpacing(16)

        summary_col = QVBoxLayout()
        summary_col.setSpacing(4)
        backup_title = QLabel("\u2601  Backup Destination")
        backup_title.setStyleSheet(
            "font-size: 11pt; font-weight: 600; color: #cba6f7;"
        )
        summary_col.addWidget(backup_title)

        self._backup_status_label = QLabel()
        summary_col.addWidget(self._backup_status_label)

        self._backup_target_label = QLabel()
        self._backup_target_label.setStyleSheet("color: #bac2de; font-size: 9pt;")
        summary_col.addWidget(self._backup_target_label)

        self._backup_token_label = QLabel()
        self._backup_token_label.setStyleSheet("color: #585b70; font-size: 9pt;")
        summary_col.addWidget(self._backup_token_label)
        backup_layout.addLayout(summary_col)
        backup_layout.addStretch()

        manage_backups_btn = QPushButton("Manage Backups")
        manage_backups_btn.setObjectName("accent_btn")
        manage_backups_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        manage_backups_btn.setToolTip("Open Google Drive and backup settings")
        manage_backups_btn.clicked.connect(self._on_settings)
        backup_layout.addWidget(manage_backups_btn)

        content_layout.addWidget(backup_panel)
        content_layout.addWidget(self._game_list)
        top_layout.addWidget(content)

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
        self._sync_all_action.triggered.connect(self._on_sync_all)
        self._settings_action.triggered.connect(self._on_settings)

        self._game_list.sync_requested.connect(self._on_sync_game)
        self._game_list.exclude_toggled.connect(self._on_exclude_toggled)
        self._game_list.force_push_requested.connect(self._force_push_game)
        self._game_list.force_pull_requested.connect(self._on_force_pull_from_context)
        self._game_list.verify_requested.connect(self._on_verify_game)

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
        self._track_worker(worker)
        worker.start()

    def _on_games_ready(self, ludusavi_games: list[LudusaviGame]) -> None:
        excluded_ids = set(self._config.excluded_games)
        games = [_ludusavi_to_game(lg, excluded_ids) for lg in ludusavi_games]
        # Attach local manifests so cards can show last-sync time
        enriched: list[Game] = []
        for g in games:
            local_m = self._engine.get_local_manifest(g.id)
            if local_m is not None:
                g = Game(
                    id=g.id, name=g.name, steam_app_id=g.steam_app_id,
                    wine_prefix=g.wine_prefix, wine_user=g.wine_user,
                    save_paths=g.save_paths, status=g.status,
                    excluded=g.excluded,
                    local_manifest=local_m, cloud_manifest=g.cloud_manifest,
                )
            enriched.append(g)
        self._games = {g.id: g for g in enriched}
        self._game_list.set_games(enriched)
        count = len(enriched)
        self._set_status(f"{count} game(s) found")
        self._debug.log_info(f"Scan complete — {count} game(s) discovered")
        # Persist for next launch
        save_games(enriched, self._config_dir)

    def _on_sync_all(self) -> None:
        """Smart-sync all non-excluded games."""
        game_ids = [
            gid for gid, g in self._games.items() if not g.excluded
        ]
        if not game_ids:
            self._set_status("No games to sync (all excluded or none found)")
            return
        self._set_status(f"Syncing {len(game_ids)} game(s)…")
        self._debug.log_info(
            f"Sync All → {len(game_ids)} game(s): {', '.join(game_ids)}"
        )
        wine_contexts = {
            gid: (self._games[gid].wine_prefix, self._games[gid].wine_user)
            for gid in game_ids
        }
        worker = SyncWorker(
            self._engine, game_ids,
            target_wine_contexts=wine_contexts,
            parent=self,
        )
        worker.game_updated.connect(self._on_game_updated)
        worker.game_updated.connect(
            lambda gid, res: self._debug.log_info(f"  sync {gid} → {res.status.name}")
        )
        worker.conflict_detected.connect(self._on_conflict_detected)
        worker.unknown_detected.connect(self._on_unknown_detected)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(lambda: self._set_status("Sync complete"))
        worker.finished.connect(lambda: self._debug.log_info("Sync All complete"))
        worker.finished.connect(self._hide_progress)
        worker.error.connect(self._on_worker_error)
        self._track_worker(worker)
        worker.start()

    def _on_settings(self) -> None:
        from PySide6.QtWidgets import QDialog

        dlg = SettingsDialog(self._config, config_dir=self._config_dir, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._config = dlg.get_config()
            save_config(self._config, config_dir=self._config_dir)
            self._engine.update_config(self._config)
            self._refresh_backup_panel(verified=dlg.drive_was_verified())

    # ------------------------------------------------------------------
    # Game-card slots
    # ------------------------------------------------------------------

    def _on_sync_game(self, game_id: str) -> None:
        """Trigger a smart sync for a single game; shows conflict dialog if needed."""
        if game_id in self._games and self._games[game_id].excluded:
            self._set_status(f"'{game_id}' is excluded from sync")
            return
        self._set_status(f"Syncing {game_id}…")
        self._debug.log_info(f"Sync → {game_id}")
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
        worker.game_updated.connect(
            lambda gid, res: self._debug.log_info(f"  sync {gid} → {res.status.name}")
        )
        worker.conflict_detected.connect(self._on_conflict_detected)
        worker.unknown_detected.connect(self._on_unknown_detected)
        worker.finished.connect(lambda: self._set_status("Sync complete"))
        worker.error.connect(self._on_worker_error)
        self._track_worker(worker)
        worker.start()

    def _on_exclude_toggled(self, game_id: str, excluded: bool) -> None:
        """Persist the exclusion state for a game."""
        if game_id not in self._games:
            return
        old = self._games[game_id]
        updated = Game(
            id=old.id, name=old.name, steam_app_id=old.steam_app_id,
            wine_prefix=old.wine_prefix, wine_user=old.wine_user,
            save_paths=old.save_paths, status=old.status,
            excluded=excluded,
            local_manifest=old.local_manifest, cloud_manifest=old.cloud_manifest,
        )
        self._games[game_id] = updated
        # Update persisted exclusion list
        excluded_set = set(self._config.excluded_games)
        if excluded:
            excluded_set.add(game_id)
        else:
            excluded_set.discard(game_id)
        self._config.excluded_games = sorted(excluded_set)
        save_config(self._config, config_dir=self._config_dir)
        self._debug.log_info(
            f"{'Excluded' if excluded else 'Included'} '{game_id}' from sync"
        )

    # ------------------------------------------------------------------
    # Worker result handlers
    # ------------------------------------------------------------------

    def _on_game_updated(self, game_id: str, result: SyncResult) -> None:
        if game_id not in self._games:
            return
        old = self._games[game_id]
        # Re-read local manifest so last-sync time is current
        local_m = self._engine.get_local_manifest(game_id) or old.local_manifest
        updated = Game(
            id=old.id,
            name=old.name,
            steam_app_id=old.steam_app_id,
            wine_prefix=old.wine_prefix,
            wine_user=old.wine_user,
            save_paths=old.save_paths,
            status=result.status,
            excluded=old.excluded,
            local_manifest=local_m,
            cloud_manifest=old.cloud_manifest,
        )
        self._games[game_id] = updated
        self._game_list.update_game(updated)

    def _on_conflict_detected(
        self,
        game_id: str,
        local_manifest: object,
        cloud_manifest: object,
        confidence: object = None,
    ) -> None:
        if game_id not in self._games:
            return

        # Import here to avoid circular imports at module level
        from savesync_bridge.core.manifest import ConfidenceResult

        game = self._games[game_id]
        updated = Game(
            id=game.id,
            name=game.name,
            steam_app_id=game.steam_app_id,
            wine_prefix=game.wine_prefix,
            wine_user=game.wine_user,
            save_paths=game.save_paths,
            status=SyncStatus.CONFLICT,
            excluded=game.excluded,
            local_manifest=local_manifest,  # type: ignore[arg-type]
            cloud_manifest=cloud_manifest,  # type: ignore[arg-type]
        )
        self._games[game_id] = updated
        self._game_list.update_game(updated)

        # If confidence is high, auto-resolve without showing dialog
        conf: ConfidenceResult | None = confidence if isinstance(confidence, ConfidenceResult) else None
        if conf is not None and conf.safe_to_auto_sync and conf.recommendation is not None:
            self._debug.log_info(
                f"Auto-resolving {game_id}: confidence {conf.score:.0%} → keep {conf.recommendation}"
            )
            if conf.recommendation == "local":
                self._force_push_game(game_id)
            else:
                self._force_pull_game(game_id)
            return

        dlg = ConflictDialog(
            updated,
            local_manifest,  # type: ignore[arg-type]
            cloud_manifest,  # type: ignore[arg-type]
            parent=self,
        )
        dlg.exec()
        choice = dlg.get_choice()
        if choice == ConflictDialog.Choice.KEEP_LOCAL:
            self._force_push_game(game_id)
        elif choice == ConflictDialog.Choice.KEEP_CLOUD:
            self._force_pull_game(game_id)
        # KEEP_NEITHER → do nothing

    def _on_unknown_detected(self, game_id: str) -> None:
        """Prompt the user when a game's status is UNKNOWN (no cloud save found)."""
        if game_id not in self._games:
            return
        reply = QMessageBox.question(
            self,
            f"No cloud save — {game_id}",
            f"No existing cloud save was found for '{game_id}'.\n\n"
            "Would you like to push your local save to the cloud?\n"
            "(Choose 'No' to skip this game.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._force_push_game(game_id)
        else:
            self._debug.log_info(f"Skipped UNKNOWN game '{game_id}' — user chose not to push")

    def _on_force_pull_from_context(self, game_id: str) -> None:
        """Handle force-pull request from game card context menu."""
        self._force_pull_game(game_id)

    def _on_verify_game(self, game_id: str) -> None:
        """Verify cloud integrity for a game and show result."""
        ok, msg = self._engine.verify_cloud_integrity(game_id)
        self._debug.log_info(f"Verify {game_id}: {msg}")
        if ok:
            QMessageBox.information(self, f"Integrity — {game_id}", msg)
        else:
            QMessageBox.warning(self, f"Integrity — {game_id}", msg)

    def _force_push_game(self, game_id: str) -> None:
        """Force-push a single game (used after conflict resolution)."""
        self._set_status(f"Pushing {game_id}…")
        self._debug.log_info(f"Force push → {game_id}")
        worker = PushWorker(
            self._engine, [game_id], concurrency=1, parent=self,
        )
        worker.game_updated.connect(self._on_game_updated)
        worker.finished.connect(lambda: self._set_status("Push complete"))
        worker.error.connect(self._on_worker_error)
        self._track_worker(worker)
        worker.start()

    def _force_pull_game(self, game_id: str) -> None:
        """Force-pull a single game (used after conflict resolution)."""
        self._set_status(f"Fetching cloud manifest for '{game_id}'…")
        worker = FetchCloudManifestWorker(
            self._engine, [game_id], concurrency=1, parent=self,
        )
        worker.manifest_ready.connect(self._on_force_pull_manifest_ready)
        worker.error.connect(self._on_worker_error)
        self._track_worker(worker)
        worker.start()

    def _on_force_pull_manifest_ready(self, game_id: str, manifest: object) -> None:
        if manifest is None:
            self._set_status(f"No cloud save found for '{game_id}'")
            return
        game = self._games.get(game_id)
        wine_prefix = game.wine_prefix if game else None
        wine_user = game.wine_user if game else None
        self._set_status(f"Pulling {game_id}…")
        worker = PullWorker(
            self._engine,
            [(game_id, manifest, wine_prefix, wine_user)],
            parent=self,
        )
        worker.game_done.connect(self._on_game_updated)
        worker.finished.connect(lambda: self._set_status("Pull complete"))
        worker.error.connect(self._on_worker_error)
        self._track_worker(worker)
        worker.start()

    def _on_worker_error(self, msg: str) -> None:
        self._set_status(f"Error: {msg}")
        self._debug.log_stderr(f"ERROR: {msg}")

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------

    def _on_filter(self, status: SyncStatus | None | str) -> None:
        for s, btn in self._filter_btns:
            btn.setChecked(s == status)
        self._game_list.set_filter(status)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _restore_cached_games(self) -> None:
        """Load previously-discovered games from disk so the UI is not empty."""
        from savesync_bridge.core.sync_engine import _default_state_dir

        state_dir = self._engine._state_dir  # noqa: SLF001
        cached = load_games(self._config_dir, state_dir=state_dir)
        if cached:
            self._games = {g.id: g for g in cached}
            self._game_list.set_games(cached)
            self._set_status(f"{len(cached)} cached game(s) loaded")
            self._debug.log_info(
                f"Restored {len(cached)} game(s) from cache"
            )

    def _set_status(self, msg: str) -> None:
        self._status_label.setText(msg)

    def _track_worker(self, worker: object) -> None:
        """Keep a strong reference to *worker* so Python doesn't GC it mid-run."""
        self._active_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._release_worker(w))  # type: ignore[union-attr]

    def _release_worker(self, worker: object) -> None:
        try:
            self._active_workers.remove(worker)
        except ValueError:
            pass

    def _on_progress(self, done: int, total: int) -> None:
        if total <= 0:
            self._progress_bar.setVisible(False)
            return
        self._progress_bar.setVisible(True)
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(done)

    def _hide_progress(self) -> None:
        self._progress_bar.setVisible(False)

    def _refresh_backup_panel(self, verified: bool = False) -> None:
        connected = has_remote_config(self._config.drive_remote, self._rclone_config_file)

        if connected and verified:
            self._backup_status_label.setText("Google Drive connected and verified")
            self._backup_status_label.setStyleSheet("color: #a6e3a1; font-weight: bold;")
        elif connected:
            self._backup_status_label.setText("Google Drive token saved")
            self._backup_status_label.setStyleSheet("color: #fab387; font-weight: bold;")
        else:
            self._backup_status_label.setText("Google Drive not connected")
            self._backup_status_label.setStyleSheet("color: #89b4fa; font-weight: bold;")

        target_root = self._config.drive_root or "/"
        remote = self._config.drive_remote
        lib = self._config.backup_path
        self._backup_target_label.setText(
            f"Remote: {remote}:{target_root}  •  Backup library: {lib}"
        )
        self._backup_token_label.setText(f"Token store: {self._rclone_config_file}")
