from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class _CliEventBus(QObject):
    """Singleton signal bus for CLI subprocess events.

    Emit from anywhere in the codebase; connect in the UI layer.
    Thread-safe: Qt queues cross-thread signals automatically.
    """

    command_run = Signal(str)    # full command string
    stdout_line = Signal(str)    # stdout text
    stderr_line = Signal(str)    # stderr text
    exit_code = Signal(int)      # process exit code


# Module-level singleton — import and use directly
cli_bus = _CliEventBus()
