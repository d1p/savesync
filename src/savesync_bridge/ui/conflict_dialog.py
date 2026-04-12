from __future__ import annotations

import sys
from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from savesync_bridge.models.game import Game, GameManifest
from savesync_bridge.ui.theme import DARK_PALETTE


def _total_size(manifest: GameManifest) -> int:
    return sum(f.size for f in manifest.files)


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


class ConflictDialog(QDialog):
    """Dialog shown when a save CONFLICT is detected.

    Presents local and cloud save metadata side-by-side and lets the user
    choose which version to keep.
    """

    class Choice(Enum):
        KEEP_LOCAL = "local"
        KEEP_CLOUD = "cloud"
        KEEP_NEITHER = "cancel"

    def __init__(
        self,
        game: Game,
        local_manifest: GameManifest,
        cloud_manifest: GameManifest,
        parent: object = None,
    ) -> None:
        super().__init__(parent)
        self._choice = ConflictDialog.Choice.KEEP_NEITHER
        self.setWindowTitle(f"Conflict — {game.name}")
        self.setMinimumWidth(640)
        self._build_ui(game, local_manifest, cloud_manifest)

    def _build_ui(
        self,
        game: Game,
        local_manifest: GameManifest,
        cloud_manifest: GameManifest,
    ) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        title = QLabel(f"⚠  Save conflict detected for <b>{game.name}</b>")
        title.setStyleSheet("font-size: 14pt;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Both your local save and the cloud save have changed independently. "
            "Choose which version to keep."
        )
        subtitle.setStyleSheet(f"color: {DARK_PALETTE['text_dim']}; font-size: 10pt;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Side-by-side panels
        panels_row = QHBoxLayout()
        panels_row.setSpacing(12)

        host_label = "Your Save (Windows)" if sys.platform == "win32" else "Your Save (Steam Deck)"
        local_panel = self._make_panel(host_label, local_manifest, is_local=True)
        cloud_panel = self._make_panel("Cloud Save", cloud_manifest, is_local=False)

        panels_row.addWidget(local_panel, stretch=1)
        panels_row.addWidget(cloud_panel, stretch=1)
        layout.addLayout(panels_row)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        keep_local_btn = QPushButton("Keep Mine")
        keep_local_btn.setObjectName("accent_btn")

        keep_cloud_btn = QPushButton("Keep Cloud")
        cancel_btn = QPushButton("Cancel (Do Nothing)")

        keep_local_btn.clicked.connect(self._on_keep_local)
        keep_cloud_btn.clicked.connect(self._on_keep_cloud)
        cancel_btn.clicked.connect(self._on_cancel)

        btn_row.addWidget(keep_local_btn)
        btn_row.addWidget(keep_cloud_btn)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _make_panel(
        self,
        title: str,
        manifest: GameManifest,
        is_local: bool,
    ) -> QFrame:
        frame = QFrame()
        frame.setObjectName("game_card")
        frame.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(frame)
        layout.setSpacing(6)
        layout.setContentsMargins(12, 12, 12, 12)

        accent = DARK_PALETTE["accent"] if is_local else DARK_PALETTE["text_dim"]
        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"font-size: 13pt; font-weight: bold; color: {accent}; background: transparent;"
        )
        layout.addWidget(title_label)

        ts_str = manifest.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
        layout.addWidget(self._dim_label(f"📅  {ts_str}"))
        layout.addWidget(self._dim_label(f"📁  {len(manifest.files)} file(s)"))
        layout.addWidget(self._dim_label(f"💾  {_format_size(_total_size(manifest))}"))

        # Show up to 3 files
        for sf in list(manifest.files)[:3]:
            lbl = QLabel(f"  • {sf.path}  ({_format_size(sf.size)})")
            lbl.setStyleSheet(
                f"color: {DARK_PALETTE['text_dim']}; font-size: 9pt; background: transparent;"
            )
            layout.addWidget(lbl)

        extra = len(manifest.files) - 3
        if extra > 0:
            more = QLabel(f"  … and {extra} more file(s)")
            more.setStyleSheet(
                f"color: {DARK_PALETTE['text_dim']}; font-size: 9pt; background: transparent;"
            )
            layout.addWidget(more)

        layout.addStretch()
        return frame

    @staticmethod
    def _dim_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {DARK_PALETTE['text_dim']}; font-size: 10pt; background: transparent;"
        )
        return lbl

    def _on_keep_local(self) -> None:
        self._choice = ConflictDialog.Choice.KEEP_LOCAL
        self.accept()

    def _on_keep_cloud(self) -> None:
        self._choice = ConflictDialog.Choice.KEEP_CLOUD
        self.accept()

    def _on_cancel(self) -> None:
        self._choice = ConflictDialog.Choice.KEEP_NEITHER
        self.reject()

    def get_choice(self) -> ConflictDialog.Choice:
        """Return the user's resolution choice."""
        return self._choice
