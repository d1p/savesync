from __future__ import annotations

import pytest

from savesync_bridge.core.path_translator import translate_save_path, windows_env_to_proton
from savesync_bridge.models.game import Platform

# Base Proton path template for assertions
_COMPAT = "~/.local/share/Steam/steamapps/compatdata/{}/pfx/drive_c"


def _compat(app_id: str) -> str:
    return _COMPAT.format(app_id)


APP_ID = "504230"


# ---------------------------------------------------------------------------
# windows_env_to_proton — parametrized cases (at least 8)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected_suffix"),
    [
        # 1. %APPDATA% → AppData/Roaming
        (
            "%APPDATA%/GameName",
            "/users/steamuser/AppData/Roaming/GameName",
        ),
        # 2. %LOCALAPPDATA% → AppData/Local
        (
            "%LOCALAPPDATA%/GameName",
            "/users/steamuser/AppData/Local/GameName",
        ),
        # 3. %USERPROFILE% → users/steamuser (then arbitrary subdirectory)
        (
            "%USERPROFILE%/AppData/Local/GameName",
            "/users/steamuser/AppData/Local/GameName",
        ),
        # 4. %PROGRAMDATA% → ProgramData
        (
            "%PROGRAMDATA%/GameName",
            "/ProgramData/GameName",
        ),
        # 5. Backslash separators are normalised
        (
            "%LOCALAPPDATA%\\GameName\\saves",
            "/users/steamuser/AppData/Local/GameName/saves",
        ),
        # 6. Env var is case-insensitive
        (
            "%appdata%/GameName",
            "/users/steamuser/AppData/Roaming/GameName",
        ),
        # 7. Mixed case env var
        (
            "%LocalAppData%/Saves",
            "/users/steamuser/AppData/Local/Saves",
        ),
        # 8. Path with deep nested subdirectory
        (
            "%APPDATA%/Publisher/Game/Profiles/save.dat",
            "/users/steamuser/AppData/Roaming/Publisher/Game/Profiles/save.dat",
        ),
        # 9. %USERPROFILE% only (no trailing path)
        (
            "%USERPROFILE%",
            "/users/steamuser",
        ),
    ],
)
def test_windows_env_to_proton(path: str, expected_suffix: str) -> None:
    result = windows_env_to_proton(path, APP_ID)
    expected = _compat(APP_ID) + expected_suffix
    assert result == expected, f"Got {result!r}, expected {expected!r}"


def test_windows_env_to_proton_no_env_var_passthrough() -> None:
    """Paths with no recognised env var are returned unchanged (normalised)."""
    path = "/home/user/.local/share/Game/save.dat"
    result = windows_env_to_proton(path, APP_ID)
    assert result == path


def test_windows_env_to_proton_backslash_no_env_passthrough() -> None:
    """Backslash-only path without env var is normalised to forward slashes."""
    path = "C:\\Users\\Player\\save.dat"
    result = windows_env_to_proton(path, APP_ID)
    # No env-var match; separators normalised
    assert result == "C:/Users/Player/save.dat"


# ---------------------------------------------------------------------------
# translate_save_path
# ---------------------------------------------------------------------------


def test_translate_same_platform_identity() -> None:
    path = "%LOCALAPPDATA%/GameName"
    assert translate_save_path(path, Platform.WINDOWS, Platform.WINDOWS) == path


def test_translate_same_platform_linux_identity() -> None:
    path = "~/.local/share/Game/save.dat"
    assert translate_save_path(path, Platform.LINUX, Platform.LINUX) == path


def test_translate_windows_to_steam_deck() -> None:
    path = "%APPDATA%/GameName"
    result = translate_save_path(path, Platform.WINDOWS, Platform.STEAM_DECK, APP_ID)
    expected = _compat(APP_ID) + "/users/steamuser/AppData/Roaming/GameName"
    assert result == expected


def test_translate_windows_to_linux() -> None:
    """WINDOWS → LINUX is treated the same as WINDOWS → STEAM_DECK."""
    path = "%LOCALAPPDATA%/GameName"
    result = translate_save_path(path, Platform.WINDOWS, Platform.LINUX, APP_ID)
    expected = _compat(APP_ID) + "/users/steamuser/AppData/Local/GameName"
    assert result == expected


def test_translate_windows_to_steam_deck_no_app_id_raises() -> None:
    with pytest.raises(ValueError, match="steam_app_id"):
        translate_save_path("%APPDATA%/Game", Platform.WINDOWS, Platform.STEAM_DECK)


def test_translate_steam_deck_to_windows() -> None:
    proton_path = _compat(APP_ID) + "/users/steamuser/AppData/Roaming/GameName"
    result = translate_save_path(proton_path, Platform.STEAM_DECK, Platform.WINDOWS)
    assert result == "%APPDATA%/GameName"


def test_translate_steam_deck_to_windows_local_appdata() -> None:
    proton_path = _compat(APP_ID) + "/users/steamuser/AppData/Local/Game/save.dat"
    result = translate_save_path(proton_path, Platform.STEAM_DECK, Platform.WINDOWS)
    assert result == "%LOCALAPPDATA%/Game/save.dat"
