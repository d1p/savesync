from __future__ import annotations

from savesync_bridge.models.game import Platform

# Base Proton path (home-relative) for compatdata
_STEAM_COMPAT_BASE = "~/.local/share/Steam/steamapps/compatdata/{steam_app_id}/pfx/drive_c"

# Maps upper-cased Windows env-var prefix → Proton drive_c-relative subdirectory
_ENV_TO_PROTON_REL: dict[str, str] = {
    "%USERPROFILE%": "users/steamuser",
    "%APPDATA%": "users/steamuser/AppData/Roaming",
    "%LOCALAPPDATA%": "users/steamuser/AppData/Local",
    "%PROGRAMDATA%": "ProgramData",
}


def _normalize(path: str) -> str:
    """Normalise Windows backslashes to forward slashes."""
    return path.replace("\\", "/")


def windows_env_to_proton(path: str, steam_app_id: str) -> str:
    """Map a Windows env-var path to its Proton compatdata equivalent.

    Args:
        path: Windows-style path, e.g. ``%APPDATA%/GameName``.
        steam_app_id: Steam application ID used to locate the compatdata prefix.

    Returns:
        Proton-translated path under ``~/.local/share/Steam/steamapps/compatdata/``.
        Paths that contain no recognised environment variable are returned
        with backslashes normalised to forward slashes.
    """
    path = _normalize(path)
    upper = path.upper()

    base = _STEAM_COMPAT_BASE.format(steam_app_id=steam_app_id)
    for env_var, proton_rel in _ENV_TO_PROTON_REL.items():
        if upper.startswith(env_var):
            remainder = path[len(env_var):].lstrip("/")
            if remainder:
                return f"{base}/{proton_rel}/{remainder}"
            return f"{base}/{proton_rel}"

    return path


def _proton_to_windows(path: str) -> str:
    """Attempt to reverse-map a Proton path back to a Windows env-var path."""
    path = _normalize(path)
    # Sort by length descending so more specific paths match before shorter ones
    for env_var, proton_rel in sorted(
        _ENV_TO_PROTON_REL.items(), key=lambda kv: len(kv[1]), reverse=True
    ):
        marker = f"/pfx/drive_c/{proton_rel}/"
        idx = path.find(marker)
        if idx != -1:
            remainder = path[idx + len(marker):]
            return f"{env_var}/{remainder}"
        # Path ends exactly at the env-var root (no trailing content)
        marker_end = f"/pfx/drive_c/{proton_rel}"
        if path.endswith(marker_end):
            return env_var

    return path


def translate_save_path(
    path: str,
    from_platform: Platform,
    to_platform: Platform,
    steam_app_id: str | None = None,
) -> str:
    """Translate a save path between platforms.

    Args:
        path: The save path to translate.
        from_platform: The source platform.
        to_platform: The destination platform.
        steam_app_id: Required when translating from Windows to Steam Deck / Linux.

    Returns:
        Translated path string.

    Raises:
        ValueError: If ``steam_app_id`` is not provided when required.
    """
    if from_platform == to_platform:
        return path

    if from_platform == Platform.WINDOWS and to_platform in (
        Platform.LINUX,
        Platform.STEAM_DECK,
    ):
        if steam_app_id is None:
            raise ValueError(
                "steam_app_id is required to translate a path from Windows to "
                f"{to_platform.value}"
            )
        return windows_env_to_proton(path, steam_app_id)

    if from_platform in (Platform.LINUX, Platform.STEAM_DECK) and to_platform == Platform.WINDOWS:
        return _proton_to_windows(path)

    return path
