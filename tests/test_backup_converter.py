from __future__ import annotations

from pathlib import Path

import yaml

from savesync_bridge.core.backup_converter import convert_simple_backup_for_restore
from savesync_bridge.models.game import Platform


def _write_mapping(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_convert_windows_backup_to_proton(tmp_path: Path) -> None:
    backup_dir = tmp_path / "Hades"
    expected_path = (
        "/home/deck/.local/share/Steam/steamapps/compatdata/1145360/"
        "pfx/drive_c/users/steamuser/AppData/Roaming/Hades/Profile1.sav"
    )
    source_file = (
        backup_dir
        / "backup-1"
        / "drive-C"
        / "Users"
        / "Alice"
        / "AppData"
        / "Roaming"
        / "Hades"
        / "Profile1.sav"
    )
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("save-data", encoding="utf-8")

    _write_mapping(
        backup_dir / "mapping.yaml",
        {
            "name": "Hades",
            "drives": {"drive-C": "C:"},
            "backups": [
                {
                    "name": "backup-1",
                    "files": {
                        "C:/Users/Alice/AppData/Roaming/Hades/Profile1.sav": {
                            "hash": "abc",
                            "size": 9,
                        }
                    },
                }
            ],
        },
    )

    changed = convert_simple_backup_for_restore(
        backup_dir,
        Platform.WINDOWS,
        Platform.STEAM_DECK,
        target_proton_prefix=(
            "/home/deck/.local/share/Steam/steamapps/compatdata/1145360/pfx/drive_c"
        ),
    )

    assert changed is True
    target_file = (
        backup_dir
        / "backup-1"
        / "drive-0"
        / "home"
        / "deck"
        / ".local"
        / "share"
        / "Steam"
        / "steamapps"
        / "compatdata"
        / "1145360"
        / "pfx"
        / "drive_c"
        / "users"
        / "steamuser"
        / "AppData"
        / "Roaming"
        / "Hades"
        / "Profile1.sav"
    )
    assert target_file.exists()

    mapping = yaml.safe_load((backup_dir / "mapping.yaml").read_text(encoding="utf-8"))
    assert mapping["drives"] == {"drive-0": ""}
    assert list(mapping["backups"][0]["files"].keys()) == [expected_path]


def test_convert_proton_backup_to_windows(tmp_path: Path) -> None:
    backup_dir = tmp_path / "Hades"
    source_path = (
        "/home/deck/.local/share/Steam/steamapps/compatdata/1145360/"
        "pfx/drive_c/users/steamuser/AppData/Local/Hades/Profile1.sav"
    )
    source_file = (
        backup_dir
        / "backup-1"
        / "drive-0"
        / "home"
        / "deck"
        / ".local"
        / "share"
        / "Steam"
        / "steamapps"
        / "compatdata"
        / "1145360"
        / "pfx"
        / "drive_c"
        / "users"
        / "steamuser"
        / "AppData"
        / "Local"
        / "Hades"
        / "Profile1.sav"
    )
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("save-data", encoding="utf-8")

    _write_mapping(
        backup_dir / "mapping.yaml",
        {
            "name": "Hades",
            "drives": {"drive-0": ""},
            "backups": [
                {
                    "name": "backup-1",
                    "files": {source_path: {"hash": "abc", "size": 9}},
                }
            ],
        },
    )

    changed = convert_simple_backup_for_restore(
        backup_dir,
        Platform.STEAM_DECK,
        Platform.WINDOWS,
        env={
            "USERPROFILE": "C:/Users/Alice",
            "APPDATA": "C:/Users/Alice/AppData/Roaming",
            "LOCALAPPDATA": "C:/Users/Alice/AppData/Local",
        },
    )

    assert changed is True
    target_file = (
        backup_dir
        / "backup-1"
        / "drive-C"
        / "Users"
        / "Alice"
        / "AppData"
        / "Local"
        / "Hades"
        / "Profile1.sav"
    )
    assert target_file.exists()

    mapping = yaml.safe_load((backup_dir / "mapping.yaml").read_text(encoding="utf-8"))
    assert mapping["drives"] == {"drive-C": "C:"}
    assert list(mapping["backups"][0]["files"].keys()) == [
        "C:/Users/Alice/AppData/Local/Hades/Profile1.sav"
    ]


def test_convert_windows_backup_to_non_steam_wine_prefix(tmp_path: Path) -> None:
    backup_dir = tmp_path / "Hades"
    source_file = (
        backup_dir
        / "backup-1"
        / "drive-C"
        / "Users"
        / "Alice"
        / "AppData"
        / "Roaming"
        / "Hades"
        / "Profile1.sav"
    )
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("save-data", encoding="utf-8")

    _write_mapping(
        backup_dir / "mapping.yaml",
        {
            "name": "Hades",
            "drives": {"drive-C": "C:"},
            "backups": [
                {
                    "name": "backup-1",
                    "files": {
                        "C:/Users/Alice/AppData/Roaming/Hades/Profile1.sav": {
                            "hash": "abc",
                            "size": 9,
                        }
                    },
                }
            ],
        },
    )

    changed = convert_simple_backup_for_restore(
        backup_dir,
        Platform.WINDOWS,
        Platform.LINUX,
        target_wine_prefix="/home/deck/Games/heroic/Hades/prefix/drive_c",
        target_wine_user="deck",
    )

    assert changed is True
    target_file = (
        backup_dir
        / "backup-1"
        / "drive-0"
        / "home"
        / "deck"
        / "Games"
        / "heroic"
        / "Hades"
        / "prefix"
        / "drive_c"
        / "users"
        / "deck"
        / "AppData"
        / "Roaming"
        / "Hades"
        / "Profile1.sav"
    )
    assert target_file.exists()

    mapping = yaml.safe_load((backup_dir / "mapping.yaml").read_text(encoding="utf-8"))
    assert mapping["drives"] == {"drive-0": ""}
    assert list(mapping["backups"][0]["files"].keys()) == [
        "/home/deck/Games/heroic/Hades/prefix/drive_c/users/deck/AppData/Roaming/Hades/Profile1.sav"
    ]
