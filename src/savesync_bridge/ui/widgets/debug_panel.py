from __future__ import annotations

import re
from datetime import UTC, datetime

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# ANSI colour → hex map (subset covering ludusavi / rclone output)
_ANSI_COLOURS = {
    "30": "#45475a",  # black  → surface
    "31": "#f38ba8",  # red    → error
    "32": "#a6e3a1",  # green  → success
    "33": "#fab387",  # yellow → warning
    "34": "#89b4fa",  # blue   → info
    "35": "#cba6f7",  # magenta → accent
    "36": "#89dceb",  # cyan
    "37": "#cdd6f4",  # white  → text
    "90": "#6c7086",  # bright black → dim
    "91": "#f38ba8",
    "92": "#a6e3a1",
    "93": "#fab387",
    "94": "#89b4fa",
    "95": "#cba6f7",
    "96": "#89dceb",
    "97": "#cdd6f4",
}

_ANSI_RE = re.compile(r"\x1b\[([0-9;]*)m")


def _ansi_to_html(text: str) -> str:
    """Convert ANSI escape sequences to HTML spans."""
    result: list[str] = []
    last = 0
    open_span = False

    for m in _ANSI_RE.finditer(text):
        chunk = text[last : m.start()]
        if chunk:
            result.append(chunk.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        codes = m.group(1).split(";")
        if open_span:
            result.append("</span>")
            open_span = False
        for code in codes:
            colour = _ANSI_COLOURS.get(code)
            if colour:
                result.append(f'<span style="color:{colour}">')
                open_span = True
                break
        last = m.end()

    tail = text[last:]
    if tail:
        result.append(tail.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    if open_span:
        result.append("</span>")
    return "".join(result)


class DebugPanel(QWidget):
    """Collapsible bottom panel that logs CLI commands and their output."""

    # Emitted when the panel is toggled so the splitter can adjust
    toggled = Signal(bool)  # True = expanded

    _HEADER_HEIGHT = 32

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._expanded = False
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @Slot(str)
    def log_command(self, command: str) -> None:
        """Log a CLI command line (shown in accent colour)."""
        ts = datetime.now(tz=UTC).strftime("%H:%M:%S")
        html = (
            f'<span style="color:#6c7086">[{ts}]</span> '
            f'<span style="color:#cba6f7; font-weight:bold">$ {_ansi_to_html(command)}</span>'
        )
        self._append_html(html)

    @Slot(str)
    def log_stdout(self, text: str) -> None:
        """Log stdout from a CLI process."""
        if not text.strip():
            return
        html = f'<span style="color:#cdd6f4">{_ansi_to_html(text)}</span>'
        self._append_html(html)

    @Slot(str)
    def log_stderr(self, text: str) -> None:
        """Log stderr from a CLI process — shown in warning/error colour."""
        if not text.strip():
            return
        html = f'<span style="color:#fab387">{_ansi_to_html(text)}</span>'
        self._append_html(html)

    @Slot(int)
    def log_exit(self, code: int) -> None:
        """Log process exit code."""
        colour = "#a6e3a1" if code == 0 else "#f38ba8"
        label = "OK" if code == 0 else f"FAILED ({code})"
        html = f'<span style="color:{colour}; font-style:italic">→ Exit {label}</span>'
        self._append_html(html)
        self._append_html('<span style="color:#45475a">─────────────────────</span>')

    @Slot(str)
    def log_info(self, text: str) -> None:
        """Log an informational message (e.g. sync-engine events)."""
        ts = datetime.now(tz=UTC).strftime("%H:%M:%S")
        html = (
            f'<span style="color:#6c7086">[{ts}]</span> '
            f'<span style="color:#89b4fa">{_ansi_to_html(text)}</span>'
        )
        self._append_html(html)

    def clear(self) -> None:
        self._log.clear()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header bar ──────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(self._HEADER_HEIGHT)
        header.setObjectName("debug_header")
        header.setStyleSheet(
            "#debug_header {"
            "background-color: #181825;"
            "border-top: 1px solid #45475a;"
            "}"
        )
        header.setCursor(Qt.CursorShape.PointingHandCursor)

        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(12, 0, 8, 0)

        self._toggle_icon = QLabel("▶")
        self._toggle_icon.setStyleSheet("color: #6c7086; font-size: 8pt;")
        h_layout.addWidget(self._toggle_icon)

        title = QLabel("Debug Console")
        title.setStyleSheet(
            "color: #cdd6f4; font-size: 10pt;"
            " font-weight: bold; padding-left: 6px;"
        )
        h_layout.addWidget(title)

        h_layout.addStretch()

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setFixedHeight(22)
        self._clear_btn.setStyleSheet(
            "QPushButton {"
            "  background: transparent;"
            "  color: #6c7086;"
            "  border: 1px solid #45475a;"
            "  border-radius: 4px;"
            "  padding: 0 8px;"
            "  font-size: 9pt;"
            "}"
            "QPushButton:hover { color: #cdd6f4; border-color: #6c7086; }"
        )
        self._clear_btn.clicked.connect(self.clear)
        h_layout.addWidget(self._clear_btn)

        outer.addWidget(header)

        # ── Log text area ────────────────────────────────────────────────
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setObjectName("debug_log")
        self._log.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._log.setStyleSheet(
            "#debug_log {"
            "  background-color: #11111b;"
            "  color: #cdd6f4;"
            "  font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;"
            "  font-size: 9pt;"
            "  border: none;"
            "  padding: 6px 10px;"
            "}"
        )
        self._log.setVisible(False)
        outer.addWidget(self._log)

        # Make the panel not steal space when collapsed
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self._HEADER_HEIGHT)

        # Click anywhere on header to toggle
        header.mousePressEvent = lambda _event: self._toggle()  # type: ignore[method-assign]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._log.setVisible(self._expanded)
        self._toggle_icon.setText("▼" if self._expanded else "▶")

        if self._expanded:
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.setFixedHeight(16777215)
            self.setMinimumHeight(180)
            self.setMaximumHeight(16777215)
        else:
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.setFixedHeight(self._HEADER_HEIGHT)

        self.toggled.emit(self._expanded)

    def _append_html(self, html: str) -> None:
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(html + "<br>")
        self._log.setTextCursor(cursor)
        self._log.ensureCursorVisible()
