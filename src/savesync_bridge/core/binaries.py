from __future__ import annotations

import sys
from pathlib import Path


def _bin_dir() -> Path:
    """Return the directory that contains bundled binaries.

    When running as a PyInstaller frozen bundle, ``sys._MEIPASS`` points to
    the temporary extraction directory where data files are unpacked.
    In development the binaries live under the package source tree.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        # PyInstaller one-file: _MEIPASS/<platform>/
        return Path(sys._MEIPASS) / "bin"  # type: ignore[attr-defined]  # noqa: SLF001
    # Development / editable install
    return Path(__file__).parent.parent / "bin"


def _platform_key() -> str:
    return "windows" if sys.platform == "win32" else "linux"


def _bundled(name: str) -> Path | None:
    """Return the bundled binary path if it exists."""
    suffix = ".exe" if sys.platform == "win32" else ""
    path = _bin_dir() / _platform_key() / f"{name}{suffix}"
    return path if path.is_file() else None


def resolve_ludusavi() -> Path:
    """Return the path to the ludusavi binary.

    Prefers the bundled binary; falls back to PATH so dev installs still work.
    Raises FileNotFoundError if neither is found.
    """
    bundled = _bundled("ludusavi")
    if bundled:
        return bundled
    return _from_path("ludusavi")


def resolve_rclone() -> Path:
    """Return the path to the rclone binary.

    Prefers the bundled binary; falls back to PATH so dev installs still work.
    Raises FileNotFoundError if neither is found.
    """
    bundled = _bundled("rclone")
    if bundled:
        return bundled
    return _from_path("rclone")


def _from_path(name: str) -> Path:
    import shutil

    found = shutil.which(name)
    if found is None:
        raise FileNotFoundError(
            f"'{name}' binary not found. "
            "Run 'uv run python scripts/fetch_bins.py' to download the bundled version."
        )
    return Path(found)
