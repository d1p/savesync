from __future__ import annotations

import io
import sys


def _fix_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 on Windows to avoid cp1252 issues."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
        elif stream is not None and hasattr(stream, "buffer"):
            setattr(
                sys,
                stream_name,
                io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"),
            )


from PySide6.QtWidgets import QApplication  # noqa: E402


def main() -> int:
    _fix_stdio()

    from savesync_bridge.core.env import load_env

    load_env()  # load .env before anything else

    app = QApplication(sys.argv)
    app.setApplicationName("SaveSync-Bridge")
    app.setOrganizationName("SaveSync")

    from savesync_bridge.ui.theme import apply_theme

    apply_theme(app)

    from savesync_bridge.core.config import load_config
    from savesync_bridge.core.sync_engine import SyncEngine

    config = load_config()
    engine = SyncEngine(config=config)

    from savesync_bridge.ui.main_window import MainWindow

    window = MainWindow(config=config, engine=engine)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
