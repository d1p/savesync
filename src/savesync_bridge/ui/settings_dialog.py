from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from savesync_bridge.core.config import (
    DEFAULT_RCLONE_REMOTE_BY_BACKEND,
    RCLONE_BACKEND_GOOGLE_DRIVE,
    RCLONE_BACKEND_S3,
    AppConfig,
)


class SettingsDialog(QDialog):
    """Application settings dialog populated from an :class:`AppConfig`."""

    def __init__(self, config: AppConfig, parent: object = None) -> None:
        super().__init__(parent)
        self._original_config = config
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)
        self._build_ui(config)

    def _build_ui(self, config: AppConfig) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        form = QFormLayout()
        form.setSpacing(10)
        form.setContentsMargins(0, 0, 0, 0)

        self._backend_label = QLabel("Cloud Provider:")
        self._backend = QComboBox()
        self._backend.addItem("Google Drive", RCLONE_BACKEND_GOOGLE_DRIVE)
        self._backend.addItem("S3 Compatible", RCLONE_BACKEND_S3)
        backend_index = self._backend.findData(config.rclone_backend)
        if backend_index >= 0:
            self._backend.setCurrentIndex(backend_index)
        self._backend.currentIndexChanged.connect(self._on_backend_changed)
        form.addRow(self._backend_label, self._backend)

        self._rclone_remote_label = QLabel("rclone Remote Name:")
        self._rclone_remote = QLineEdit(config.rclone_remote)
        form.addRow(self._rclone_remote_label, self._rclone_remote)

        self._s3_bucket_label = QLabel()
        self._s3_bucket = QLineEdit(config.s3_bucket)
        form.addRow(self._s3_bucket_label, self._s3_bucket)

        self._s3_prefix_label = QLabel()
        self._s3_prefix = QLineEdit(config.s3_prefix)
        form.addRow(self._s3_prefix_label, self._s3_prefix)

        self._ludusavi_path = QLineEdit(config.ludusavi_path or "")
        self._ludusavi_path.setPlaceholderText("(use bundled)")
        form.addRow("Ludusavi Binary:", self._make_path_row(self._ludusavi_path))

        self._rclone_path = QLineEdit(config.rclone_path or "")
        self._rclone_path.setPlaceholderText("(use bundled)")
        form.addRow("Rclone Binary:", self._make_path_row(self._rclone_path))

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_backend_fields(self._current_backend())

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

    def _current_backend(self) -> str:
        current = self._backend.currentData()
        if isinstance(current, str):
            return current
        return RCLONE_BACKEND_GOOGLE_DRIVE

    def _on_backend_changed(self) -> None:
        backend = self._current_backend()
        current_remote = self._rclone_remote.text().strip()
        if not current_remote or current_remote in DEFAULT_RCLONE_REMOTE_BY_BACKEND.values():
            self._rclone_remote.setText(DEFAULT_RCLONE_REMOTE_BY_BACKEND[backend])
        self._update_backend_fields(backend)

    def _update_backend_fields(self, backend: str) -> None:
        self._rclone_remote.setPlaceholderText(DEFAULT_RCLONE_REMOTE_BY_BACKEND[backend])
        if backend == RCLONE_BACKEND_S3:
            self._s3_bucket_label.setText("S3 Bucket:")
            self._s3_bucket.setPlaceholderText("my-bucket")
            self._s3_prefix_label.setText("S3 Prefix / Path:")
            self._s3_prefix.setPlaceholderText("savesync-bridge")
            return

        self._s3_bucket_label.setText("Drive Root Folder:")
        self._s3_bucket.setPlaceholderText("(optional)")
        self._s3_prefix_label.setText("Drive Folder Prefix:")
        self._s3_prefix.setPlaceholderText("savesync-bridge")

    def get_config(self) -> AppConfig:
        """Return a new :class:`AppConfig` reflecting the dialog's current values."""
        return AppConfig(
            rclone_backend=self._current_backend(),
            rclone_remote=self._rclone_remote.text().strip(),
            s3_bucket=self._s3_bucket.text().strip(),
            s3_prefix=self._s3_prefix.text().strip(),
            ludusavi_path=self._ludusavi_path.text().strip() or None,
            rclone_path=self._rclone_path.text().strip() or None,
            known_games=list(self._original_config.known_games),
        )
