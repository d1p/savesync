from __future__ import annotations

import sys
from enum import Enum

from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
)

from savesync_bridge.core import manifest as manifest_module
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


def _format_dt(value: object) -> str:
    if value is None:
        return "Unknown"
    return value.strftime("%Y-%m-%d %H:%M:%S UTC")


def _recommendation(recommended_lineage: manifest_module.LineageRecommendation | None) -> str | None:
    if recommended_lineage == "local":
        return (
            "Recommendation: your local files look like the older-established save lineage. "
            "The cloud files were created later, which often happens after a fresh start or launcher touch."
        )

    if recommended_lineage == "cloud":
        return (
            "Recommendation: the cloud files look like the older-established save lineage. "
            "Your local files were created later, which can indicate a fresh start or a recreated save set."
        )

    return None


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
        self._suggested_choice = ConflictDialog.Choice.KEEP_NEITHER
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
            "The save contents differ, so SaveSync stopped instead of trusting file timestamps alone. "
            "Choose which version to keep after reviewing the original file dates below."
        )
        subtitle.setStyleSheet(f"color: {DARK_PALETTE['text_dim']}; font-size: 10pt;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        recommended_lineage = manifest_module.recommend_lineage(local_manifest, cloud_manifest)
        recommendation = _recommendation(recommended_lineage)

        # Compute confidence
        self._confidence = manifest_module.compute_confidence(local_manifest, cloud_manifest)

        if recommendation is not None:
            recommendation_label = QLabel(recommendation)
            recommendation_label.setWordWrap(True)
            recommendation_label.setStyleSheet(
                "background: rgba(166, 227, 161, 0.08); "
                "border: 1px solid rgba(166, 227, 161, 0.25); "
                "border-radius: 8px; padding: 10px;"
                f"color: {DARK_PALETTE['text']}; font-size: 10pt;"
            )
            layout.addWidget(recommendation_label)

        # Confidence indicator
        conf = self._confidence
        color_map = {"High": "#a6e3a1", "Medium": "#f9e2af", "Low": "#f38ba8"}
        conf_color = color_map.get(conf.label, DARK_PALETTE["text_dim"])
        conf_text = f"Confidence: {conf.label} ({conf.score:.0%})"
        if conf.reasons:
            conf_text += "\n" + "\n".join(f"  • {r}" for r in conf.reasons)
        conf_label = QLabel(conf_text)
        conf_label.setWordWrap(True)
        conf_label.setStyleSheet(
            f"background: rgba(205, 214, 244, 0.05); "
            f"border: 1px solid {conf_color}40; "
            f"border-radius: 8px; padding: 10px;"
            f"color: {DARK_PALETTE['text']}; font-size: 9pt;"
        )
        layout.addWidget(conf_label)

        # Side-by-side panels
        panels_row = QHBoxLayout()
        panels_row.setSpacing(12)

        host_label = "Your Save (Windows)" if sys.platform == "win32" else "Your Save (Steam Deck)"
        local_panel = self._make_panel(host_label, local_manifest, is_local=True)
        cloud_panel = self._make_panel("Cloud Save", cloud_manifest, is_local=False)

        panels_row.addWidget(local_panel, stretch=1)
        panels_row.addWidget(cloud_panel, stretch=1)
        layout.addLayout(panels_row)

        # Per-file diff section
        diff = manifest_module.diff_manifests(local_manifest, cloud_manifest)
        if diff.total_files > 0:
            diff_frame = self._make_diff_panel(diff)
            layout.addWidget(diff_frame)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        keep_local_btn = QPushButton("Keep Mine")
        keep_local_btn.setObjectName("accent_btn")
        keep_local_btn.setToolTip("Upload your local save to the cloud, overwriting the cloud version")

        keep_cloud_btn = QPushButton("Keep Cloud")
        keep_cloud_btn.setToolTip("Download the cloud save and overwrite your local files")
        cancel_btn = QPushButton("Cancel (Do Nothing)")
        cancel_btn.setToolTip("Leave both saves unchanged and resolve later")

        if recommended_lineage == "local":
            self._suggested_choice = ConflictDialog.Choice.KEEP_LOCAL
            keep_local_btn.setDefault(True)
            keep_local_btn.setAutoDefault(True)
            keep_local_btn.setFocus()
        elif recommended_lineage == "cloud":
            self._suggested_choice = ConflictDialog.Choice.KEEP_CLOUD
            keep_cloud_btn.setDefault(True)
            keep_cloud_btn.setAutoDefault(True)
            keep_cloud_btn.setFocus()

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
        layout.addWidget(self._dim_label(f"📅  Snapshot captured {ts_str}"))
        layout.addWidget(
            self._dim_label(
                f"🌱  Oldest file created {_format_dt(manifest_module.oldest_known_created(manifest))}"
            )
        )
        layout.addWidget(
            self._dim_label(
                f"🕒  Last file modified {_format_dt(manifest_module.latest_modified(manifest))}"
            )
        )
        layout.addWidget(self._dim_label(f"📁  {len(manifest.files)} file(s)"))
        layout.addWidget(self._dim_label(f"💾  {_format_size(_total_size(manifest))}"))

        if manifest.machine_id:
            layout.addWidget(self._dim_label(f"🖥  From: {manifest.machine_id}"))

        # Show up to 3 files with timestamps
        for sf in list(manifest.files)[:3]:
            file_detail = f"  • {sf.path}  ({_format_size(sf.size)})"
            if sf.created is not None:
                file_detail += f"  created {_format_dt(sf.created)}"
            file_detail += f"  modified {_format_dt(sf.modified)}"
            lbl = QLabel(file_detail)
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

    def _make_diff_panel(self, diff: manifest_module.ManifestDiff) -> QFrame:
        """Build a collapsible per-file diff view."""
        frame = QFrame()
        frame.setObjectName("diff_panel")
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setStyleSheet(
            "QFrame#diff_panel {"
            f"  background-color: {DARK_PALETTE['surface0']};"
            f"  border: 1px solid {DARK_PALETTE['surface1']};"
            "  border-radius: 8px;"
            "}"
        )

        outer = QVBoxLayout(frame)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(4)

        summary_parts: list[str] = []
        if diff.unchanged_count:
            summary_parts.append(f"{diff.unchanged_count} unchanged")
        if diff.modified_count:
            summary_parts.append(f"{diff.modified_count} modified")
        if diff.added_local_count:
            summary_parts.append(f"{diff.added_local_count} local-only")
        if diff.added_cloud_count:
            summary_parts.append(f"{diff.added_cloud_count} cloud-only")

        header = QLabel(f"📋  File Differences — {', '.join(summary_parts)}")
        header.setStyleSheet(
            f"font-size: 10pt; font-weight: 600; color: {DARK_PALETTE['text']}; background: transparent;"
        )
        outer.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(160)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QFrame()
        container.setStyleSheet("background: transparent;")
        diff_layout = QVBoxLayout(container)
        diff_layout.setContentsMargins(0, 4, 0, 0)
        diff_layout.setSpacing(2)

        status_icons = {
            "unchanged": ("  ✓", "#a6e3a1"),
            "modified": ("  ✎", "#f9e2af"),
            "added_local": ("  + local", "#89b4fa"),
            "added_cloud": ("  + cloud", "#cba6f7"),
        }

        for entry in diff.entries:
            icon, color = status_icons.get(entry.status, ("  ?", DARK_PALETTE["text_dim"]))
            size_info = ""
            if entry.local_file and entry.cloud_file and entry.status == "modified":
                size_info = f"  ({_format_size(entry.local_file.size)} → {_format_size(entry.cloud_file.size)})"
            elif entry.local_file:
                size_info = f"  ({_format_size(entry.local_file.size)})"
            elif entry.cloud_file:
                size_info = f"  ({_format_size(entry.cloud_file.size)})"

            lbl = QLabel(f"{icon}  {entry.path}{size_info}")
            lbl.setStyleSheet(
                f"color: {color}; font-size: 9pt; font-family: monospace; background: transparent;"
            )
            diff_layout.addWidget(lbl)

        diff_layout.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll)

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

    def get_suggested_choice(self) -> ConflictDialog.Choice:
        """Return the heuristic default choice shown to the user."""
        return self._suggested_choice

    def get_confidence(self) -> manifest_module.ConfidenceResult:
        """Return the computed confidence result."""
        return self._confidence
