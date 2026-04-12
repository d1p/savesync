from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping

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

_STEAM_COMPAT_APP_ID_RE = re.compile(
    r"/compatdata/(?P<app_id>\d+)/pfx/drive_c(?:/|$)",
    re.IGNORECASE,
)
_WINE_PREFIX_RE = re.compile(r"(?P<prefix>.+?/drive_c)(?:/|$)", re.IGNORECASE)
_WINE_USER_RE = re.compile(r"^(?P<prefix>.+?/drive_c)/users/(?P<user>[^/]+)(?:/|$)", re.IGNORECASE)
_WINDOWS_DRIVE_RE = re.compile(r"^(?P<drive>[A-Za-z]:)(?P<rest>(?:/.*)?)$")
_WINDOWS_USER_RE = re.compile(
    r"^(?P<drive>[A-Za-z]:)/Users/[^/]+(?P<rest>(?:/.*)?)$",
    re.IGNORECASE,
)
_WINDOWS_PROGRAMDATA_RE = re.compile(
    r"^(?P<drive>[A-Za-z]:)/ProgramData(?P<rest>(?:/.*)?)$",
    re.IGNORECASE,
)
_WINE_DRIVE_C_RE = re.compile(r"^(?P<prefix>.+?/drive_c)(?P<rest>(?:/.*)?)$", re.IGNORECASE)


def _normalize(path: str) -> str:
    """Normalise Windows backslashes to forward slashes."""
    return path.replace("\\", "/")


def _join(base: str, suffix: str) -> str:
    if not suffix:
        return base
    return f"{base.rstrip('/')}{suffix}"


def extract_wine_prefix_metadata(paths: Iterable[str]) -> tuple[str | None, str | None, str | None]:
    """Extract Wine/Proton prefix metadata from scanned save paths.

    Returns the Steam app ID when the prefix is a Steam compatdata prefix,
    the prefix path ending in ``drive_c``, and the Windows user folder name
    inside that prefix when it can be inferred from a save path.
    """
    for raw_path in paths:
        normalized = _normalize(raw_path)
        match = _WINE_PREFIX_RE.search(normalized)
        if match:
            prefix = match.group("prefix")
            app_id_match = _STEAM_COMPAT_APP_ID_RE.search(normalized)
            user_match = _WINE_USER_RE.match(normalized)
            app_id = app_id_match.group("app_id") if app_id_match else None
            wine_user = user_match.group("user") if user_match else None
            return app_id, prefix, wine_user
    return None, None, None


def extract_proton_metadata(paths: Iterable[str]) -> tuple[str | None, str | None]:
    """Backward-compatible alias for Steam compatdata discovery."""
    app_id, prefix, _wine_user = extract_wine_prefix_metadata(paths)
    return app_id, prefix


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
            remainder = path[len(env_var) :].lstrip("/")
            if remainder:
                return f"{base}/{proton_rel}/{remainder}"
            return f"{base}/{proton_rel}"

    return path


def windows_absolute_to_wine_prefix(
    path: str,
    wine_prefix: str,
    wine_user: str | None = None,
) -> str:
    """Translate an absolute Windows save path into an absolute Wine/Proton path."""
    path = _normalize(path)
    wine_prefix = _normalize(wine_prefix).rstrip("/")
    resolved_wine_user = wine_user or "steamuser"

    if match := _WINDOWS_USER_RE.match(path):
        return _join(f"{wine_prefix}/users/{resolved_wine_user}", match.group("rest") or "")

    if match := _WINDOWS_PROGRAMDATA_RE.match(path):
        return _join(f"{wine_prefix}/ProgramData", match.group("rest") or "")

    if match := _WINDOWS_DRIVE_RE.match(path):
        return _join(wine_prefix, match.group("rest") or "")

    return path


def windows_absolute_to_proton(path: str, proton_prefix: str) -> str:
    """Backward-compatible alias for Steam compatdata path conversion."""
    return windows_absolute_to_wine_prefix(path, proton_prefix)


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
            remainder = path[idx + len(marker) :]
            return f"{env_var}/{remainder}"
        # Path ends exactly at the env-var root (no trailing content)
        marker_end = f"/pfx/drive_c/{proton_rel}"
        if path.endswith(marker_end):
            return env_var

    return path


def wine_prefix_absolute_to_windows(
    path: str,
    env: Mapping[str, str] | None = None,
) -> str:
    """Translate an absolute Wine/Proton path into an absolute Windows path."""
    path = _normalize(path)
    match = _WINE_DRIVE_C_RE.match(path)
    if not match:
        return path

    env_map = dict(os.environ)
    if env is not None:
        env_map.update(env)

    userprofile = _normalize(env_map.get("USERPROFILE", "C:/Users/Player"))
    appdata = _normalize(env_map.get("APPDATA", f"{userprofile}/AppData/Roaming"))
    localappdata = _normalize(env_map.get("LOCALAPPDATA", f"{userprofile}/AppData/Local"))
    programdata = _normalize(env_map.get("PROGRAMDATA", "C:/ProgramData"))
    rest = match.group("rest") or ""

    user_root_match = re.match(r"^/users/[^/]+", rest, re.IGNORECASE)
    user_root = user_root_match.group(0) if user_root_match else None

    if user_root and rest.startswith(f"{user_root}/AppData/Roaming"):
        suffix = rest[len(f"{user_root}/AppData/Roaming") :]
        return _join(appdata, suffix)

    if user_root and rest.startswith(f"{user_root}/AppData/Local"):
        suffix = rest[len(f"{user_root}/AppData/Local") :]
        return _join(localappdata, suffix)

    if user_root and rest.startswith(user_root):
        suffix = rest[len(user_root) :]
        return _join(userprofile, suffix)

    if rest.startswith("/ProgramData"):
        suffix = rest[len("/ProgramData") :]
        return _join(programdata, suffix)

    return _join("C:", rest)


def proton_absolute_to_windows(
    path: str,
    env: Mapping[str, str] | None = None,
) -> str:
    """Backward-compatible alias for Steam compatdata conversion."""
    return wine_prefix_absolute_to_windows(path, env=env)


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
                f"steam_app_id is required to translate a path from Windows to {to_platform.value}"
            )
        return windows_env_to_proton(path, steam_app_id)

    if from_platform in (Platform.LINUX, Platform.STEAM_DECK) and to_platform == Platform.WINDOWS:
        return _proton_to_windows(path)

    return path
