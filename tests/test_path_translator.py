from __future__ import annotations

import pytest

from savesync_bridge.core.path_translator import (
    extract_wine_prefix_metadata,
    proton_absolute_to_windows,
    translate_save_path,
    windows_absolute_to_proton,
    windows_absolute_to_wine_prefix,
    windows_env_to_proton,
    wine_prefix_absolute_to_windows,
)
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


def test_extract_wine_prefix_metadata_for_steam() -> None:
    app_id, prefix, wine_user = extract_wine_prefix_metadata(
        [
            "/home/deck/.local/share/Steam/steamapps/compatdata/1145360/pfx/drive_c/users/steamuser/AppData/Roaming/Hades",
        ]
    )
    assert app_id == "1145360"
    assert prefix == ("/home/deck/.local/share/Steam/steamapps/compatdata/1145360/pfx/drive_c")
    assert wine_user == "steamuser"


def test_extract_wine_prefix_metadata_for_non_steam_prefix() -> None:
    app_id, prefix, wine_user = extract_wine_prefix_metadata(
        [
            "/home/deck/Games/heroic/Hades/prefix/drive_c/users/deck/AppData/Local/Hades/Profile1.sav",
        ]
    )
    assert app_id is None
    assert prefix == "/home/deck/Games/heroic/Hades/prefix/drive_c"
    assert wine_user == "deck"


def test_windows_absolute_to_proton() -> None:
    proton_prefix = _compat(APP_ID)
    path = "C:/Users/Player/AppData/Roaming/Hades/Profile1.sav"
    result = windows_absolute_to_proton(path, proton_prefix)
    assert result == f"{proton_prefix}/users/steamuser/AppData/Roaming/Hades/Profile1.sav"


def test_windows_absolute_to_wine_prefix_non_steam_user() -> None:
    wine_prefix = "/home/deck/Games/heroic/Hades/prefix/drive_c"
    path = "C:/Users/Player/AppData/Roaming/Hades/Profile1.sav"
    result = windows_absolute_to_wine_prefix(path, wine_prefix, wine_user="deck")
    assert result == f"{wine_prefix}/users/deck/AppData/Roaming/Hades/Profile1.sav"


def test_proton_absolute_to_windows() -> None:
    proton_path = _compat(APP_ID) + "/users/steamuser/AppData/Local/Hades/Profile1.sav"
    result = proton_absolute_to_windows(
        proton_path,
        env={
            "USERPROFILE": "C:/Users/Alice",
            "APPDATA": "C:/Users/Alice/AppData/Roaming",
            "LOCALAPPDATA": "C:/Users/Alice/AppData/Local",
        },
    )
    assert result == "C:/Users/Alice/AppData/Local/Hades/Profile1.sav"


def test_wine_prefix_absolute_to_windows_non_steam() -> None:
    wine_path = (
        "/home/deck/Games/heroic/Hades/prefix/drive_c/"
        "users/deck/AppData/Roaming/Hades/Profile1.sav"
    )
    result = wine_prefix_absolute_to_windows(
        wine_path,
        env={
            "USERPROFILE": "C:/Users/Alice",
            "APPDATA": "C:/Users/Alice/AppData/Roaming",
            "LOCALAPPDATA": "C:/Users/Alice/AppData/Local",
        },
    )
    assert result == "C:/Users/Alice/AppData/Roaming/Hades/Profile1.sav"
