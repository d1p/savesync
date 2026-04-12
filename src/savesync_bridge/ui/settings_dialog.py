from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from savesync_bridge.cli.rclone import has_remote_config
from savesync_bridge.core.config import (
    DEFAULT_BACKUP_PATH,
    DEFAULT_DRIVE_REMOTE,
    AppConfig,
    default_config_dir,
    rclone_config_path,
    save_config,
)
from savesync_bridge.ui.workers import DriveConfigWorker


class SettingsDialog(QDialog):
    """Backup settings dialog with Google Drive authentication controls."""

    def __init__(
        self,
        config: AppConfig,
        config_dir: Path | None = None,
        parent: object = None,
    ) -> None:
        super().__init__(parent)
        self._original_config = config
        self._config_dir = config_dir if config_dir is not None else default_config_dir()
        self._rclone_config_file = rclone_config_path(self._config_dir)
        self._drive_verified = False
        self._worker: DriveConfigWorker | None = None

        self.setWindowTitle("Backups")
        self.setMinimumWidth(640)
        self._build_ui(config)
        self._update_connection_status()

    def _build_ui(self, config: AppConfig) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(22, 22, 22, 22)

        title = QLabel("Backup Destination")
        title.setStyleSheet("font-size: 18pt; font-weight: bold; color: #cba6f7;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Connect Google Drive once, keep the saved token"
            " in the app config, and choose where backups live in Drive."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #bac2de;")
        layout.addWidget(subtitle)

        status_card = QFrame()
        status_card.setObjectName("backup_status_card")
        status_card.setStyleSheet(
            "QFrame#backup_status_card {"
            "background-color: #181825; border: 1px solid #45475a; "
            "border-radius: 10px; padding: 10px;"
            "}"
        )
        status_layout = QVBoxLayout(status_card)
        status_layout.setSpacing(6)
        status_layout.setContentsMargins(14, 14, 14, 14)

        self._connection_status = QLabel()
        self._connection_status.setStyleSheet("font-size: 11pt; font-weight: bold;")
        status_layout.addWidget(self._connection_status)

        self._connection_hint = QLabel()
        self._connection_hint.setWordWrap(True)
        self._connection_hint.setStyleSheet("color: #bac2de;")
        status_layout.addWidget(self._connection_hint)

        self._token_location = QLabel()
        self._token_location.setWordWrap(True)
        self._token_location.setStyleSheet("color: #6c7086; font-size: 10pt;")
        status_layout.addWidget(self._token_location)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self._auth_btn = QPushButton("Authenticate Google Drive")
        self._auth_btn.setObjectName("accent_btn")
        self._auth_btn.clicked.connect(lambda: self._start_drive_action("authenticate"))
        action_row.addWidget(self._auth_btn)

        self._verify_btn = QPushButton("Check Connection")
        self._verify_btn.clicked.connect(lambda: self._start_drive_action("verify"))
        action_row.addWidget(self._verify_btn)

        self._reconnect_btn = QPushButton("Refresh Sign-In")
        self._reconnect_btn.clicked.connect(lambda: self._start_drive_action("reconnect"))
        action_row.addWidget(self._reconnect_btn)

        self._disconnect_btn = QPushButton("Remove Saved Token")
        self._disconnect_btn.clicked.connect(lambda: self._start_drive_action("disconnect"))
        action_row.addWidget(self._disconnect_btn)

        action_row.addStretch()
        status_layout.addLayout(action_row)
        layout.addWidget(status_card)

        form = QFormLayout()
        form.setSpacing(10)
        form.setContentsMargins(0, 0, 0, 0)

        self._drive_remote = QLineEdit(config.drive_remote)
        self._drive_remote.setPlaceholderText(DEFAULT_DRIVE_REMOTE)
        form.addRow("Drive Remote Name:", self._drive_remote)

        self._drive_root = QLineEdit(config.drive_root)
        self._drive_root.setPlaceholderText("(optional top-level folder)")
        form.addRow("Drive Folder:", self._drive_root)

        self._backup_path = QLineEdit(config.backup_path)
        self._backup_path.setPlaceholderText(DEFAULT_BACKUP_PATH)
        form.addRow("Backup Library:", self._backup_path)

        self._drive_client_id = QLineEdit(config.drive_client_id or "")
        self._drive_client_id.setPlaceholderText("(optional, uses rclone default if blank)")
        form.addRow("Google Client ID:", self._drive_client_id)

        self._drive_client_secret = QLineEdit(config.drive_client_secret or "")
        self._drive_client_secret.setPlaceholderText("(optional)")
        self._drive_client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Google Client Secret:", self._drive_client_secret)

        self._ludusavi_path = QLineEdit(config.ludusavi_path or "")
        self._ludusavi_path.setPlaceholderText("(use bundled)")
        form.addRow("Ludusavi Binary:", self._make_path_row(self._ludusavi_path))

        self._rclone_path = QLineEdit(config.rclone_path or "")
        self._rclone_path.setPlaceholderText("(use bundled)")
        form.addRow("Rclone Binary:", self._make_path_row(self._rclone_path))

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _make_path_row(self, line_edit: QLineEdit) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(line_edit)

        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(lambda: self._browse_path(line_edit))
        row.addWidget(browse_btn)
        return container

    def _browse_path(self, line_edit: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Binary")
        if path:
            line_edit.setText(path)

    def _normalized_config(self) -> AppConfig:
        return AppConfig(
            drive_remote=self._drive_remote.text().strip() or DEFAULT_DRIVE_REMOTE,
            drive_root=self._drive_root.text().strip(),
            backup_path=self._backup_path.text().strip() or DEFAULT_BACKUP_PATH,
            drive_client_id=self._drive_client_id.text().strip() or None,
            drive_client_secret=self._drive_client_secret.text().strip() or None,
            ludusavi_path=self._ludusavi_path.text().strip() or None,
            rclone_path=self._rclone_path.text().strip() or None,
            known_games=list(self._original_config.known_games),
        )

    def _persist_current_config(self) -> AppConfig:
        cfg = self._normalized_config()
        save_config(cfg, config_dir=self._config_dir)
        self._original_config = cfg
        return cfg

    def _start_drive_action(self, action: str) -> None:
        if self._worker is not None and self._worker.isRunning():
            return

        cfg = self._persist_current_config()

        if action in {"verify", "reconnect", "disconnect"} and not has_remote_config(
            cfg.drive_remote,
            self._rclone_config_file,
        ):
            QMessageBox.warning(
                self,
                "Google Drive",
                "Authenticate Google Drive first so a saved token exists for this remote.",
            )
            return

        self._set_busy(True, action)
        self._worker = DriveConfigWorker(action, cfg, self._rclone_config_file, parent=self)
        self._worker.completed.connect(self._on_drive_action_complete)
        self._worker.error.connect(self._on_drive_action_error)
        self._worker.finished.connect(lambda: self._set_busy(False, action))
        self._worker.start()

    def _on_drive_action_complete(self, action: str, message: str) -> None:
        self._drive_verified = action in {"authenticate", "reconnect", "verify"}
        self._update_connection_status(status_override=message)
        QMessageBox.information(self, "Google Drive", message)

    def _on_drive_action_error(self, message: str) -> None:
        self._drive_verified = False
        self._update_connection_status(status_override=message, is_error=True)
        QMessageBox.warning(self, "Google Drive", message)

    def _set_busy(self, busy: bool, action: str) -> None:
        for button in [self._auth_btn, self._verify_btn, self._reconnect_btn, self._disconnect_btn]:
            button.setEnabled(not busy)

        if busy:
            self._connection_hint.setText(
                {
                    "authenticate": "Waiting for the Google browser sign-in flow to complete…",
                    "reconnect": "Refreshing the saved Google Drive sign-in…",
                    "disconnect": "Removing the saved Google Drive token…",
                    "verify": "Checking the current Google Drive connection…",
                }[action]
            )
            return

        self._update_connection_status()

    def _update_connection_status(
        self,
        status_override: str | None = None,
        is_error: bool = False,
    ) -> None:
        cfg = self._normalized_config()
        connected = has_remote_config(cfg.drive_remote, self._rclone_config_file)

        _style = "font-size: 11pt; font-weight: bold; color: {};"
        if is_error:
            self._connection_status.setText("Connection Error")
            self._connection_status.setStyleSheet(_style.format("#f38ba8"))
            self._connection_hint.setText(
                status_override or "Google Drive authentication failed."
            )
        elif connected and self._drive_verified:
            self._connection_status.setText("Google Drive Connected")
            self._connection_status.setStyleSheet(_style.format("#a6e3a1"))
            root = cfg.drive_root or '/'
            self._connection_hint.setText(
                status_override
                or (
                    f"Uploads will use {cfg.drive_remote}:{root}"
                    f" and store backups under {cfg.backup_path}."
                )
            )
        elif connected:
            self._connection_status.setText("Saved Token Found")
            self._connection_status.setStyleSheet(_style.format("#fab387"))
            self._connection_hint.setText(
                status_override
                or (
                    "A saved Google Drive token exists for this"
                    " remote. Use Check Connection to verify"
                    " it still works."
                )
            )
        else:
            self._connection_status.setText("Google Drive Not Connected")
            self._connection_status.setStyleSheet(_style.format("#89b4fa"))
            self._connection_hint.setText(
                status_override
                or (
                    "Authenticate once to save a reusable"
                    " Google Drive token for uploads"
                    " and downloads."
                )
            )

        self._token_location.setText(
            ("Saved token config: " if connected else "Token will be stored in: ")
            + str(self._rclone_config_file)
        )
        self._auth_btn.setText(
            "Re-authenticate Google Drive" if connected else "Authenticate Google Drive"
        )
        self._verify_btn.setEnabled(connected)
        self._reconnect_btn.setEnabled(connected)
        self._disconnect_btn.setEnabled(connected)

    def accept(self) -> None:
        save_config(self._normalized_config(), config_dir=self._config_dir)
        super().accept()

    def get_config(self) -> AppConfig:
        """Return a new :class:`AppConfig` reflecting the dialog's current values."""
        return self._normalized_config()

    def drive_is_connected(self) -> bool:
        return has_remote_config(self.get_config().drive_remote, self._rclone_config_file)

    def drive_was_verified(self) -> bool:
        return self._drive_verified
