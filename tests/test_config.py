from __future__ import annotations

from pathlib import Path

from savesync_bridge.core.config import (
    DEFAULT_BACKUP_PATH,
    DEFAULT_DRIVE_REMOTE,
    AppConfig,
    load_config,
    rclone_config_path,
    save_config,
)


def test_app_config_defaults() -> None:
    cfg = AppConfig()
    assert cfg.drive_remote == DEFAULT_DRIVE_REMOTE
    assert cfg.drive_root == ""
    assert cfg.backup_path == DEFAULT_BACKUP_PATH
    assert cfg.drive_client_id is None
    assert cfg.drive_client_secret is None
    assert cfg.ludusavi_path is None
    assert cfg.rclone_path is None
    assert cfg.known_games == []
    assert cfg.excluded_games == []


def test_app_config_fields_mutable() -> None:
    cfg = AppConfig()
    cfg.drive_remote = "portable-drive"
    assert cfg.drive_remote == "portable-drive"


def test_load_config_creates_default_when_missing(tmp_path: Path) -> None:
    cfg = load_config(config_dir=tmp_path)
    assert isinstance(cfg, AppConfig)
    assert cfg.drive_remote == DEFAULT_DRIVE_REMOTE
    assert cfg.backup_path == DEFAULT_BACKUP_PATH


def test_load_config_does_not_raise_on_missing_dir(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent"
    cfg = load_config(config_dir=missing)
    assert isinstance(cfg, AppConfig)


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    cfg = AppConfig(
        drive_remote="travel-drive",
        drive_root="SyncRoot",
        backup_path="games/saves",
        drive_client_id="client-123",
        drive_client_secret="secret-456",
        known_games=["Celeste", "Hades"],
    )
    save_config(cfg, config_dir=tmp_path)
    restored = load_config(config_dir=tmp_path)

    assert restored.drive_remote == "travel-drive"
    assert restored.drive_root == "SyncRoot"
    assert restored.backup_path == "games/saves"
    assert restored.drive_client_id == "client-123"
    assert restored.drive_client_secret == "secret-456"
    assert restored.known_games == ["Celeste", "Hades"]


def test_save_and_load_excluded_games_round_trip(tmp_path: Path) -> None:
    cfg = AppConfig(excluded_games=["Hades", "Celeste"])
    save_config(cfg, config_dir=tmp_path)
    restored = load_config(config_dir=tmp_path)
    assert restored.excluded_games == ["Hades", "Celeste"]


def test_load_config_migrates_legacy_remote_fields(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        'rclone_remote = "legacy-remote"\n'
        's3_bucket = "legacy-root"\n'
        's3_prefix = "legacy-saves"\n'
        'known_games = []\n',
        encoding="utf-8",
    )

    cfg = load_config(config_dir=tmp_path)

    assert cfg.drive_remote == "legacy-remote"
    assert cfg.drive_root == "legacy-root"
    assert cfg.backup_path == "legacy-saves"


def test_save_creates_config_file(tmp_path: Path) -> None:
    cfg = AppConfig()
    save_config(cfg, config_dir=tmp_path)
    assert (tmp_path / "config.toml").exists()


def test_save_and_load_optional_paths(tmp_path: Path) -> None:
    cfg = AppConfig(
        ludusavi_path="/usr/local/bin/ludusavi",
        rclone_path="/usr/local/bin/rclone",
    )
    save_config(cfg, config_dir=tmp_path)
    restored = load_config(config_dir=tmp_path)
    assert restored.ludusavi_path == "/usr/local/bin/ludusavi"
    assert restored.rclone_path == "/usr/local/bin/rclone"


def test_save_and_load_empty_known_games(tmp_path: Path) -> None:
    cfg = AppConfig(known_games=[])
    save_config(cfg, config_dir=tmp_path)
    restored = load_config(config_dir=tmp_path)
    assert restored.known_games == []


def test_save_and_load_special_chars_in_strings(tmp_path: Path) -> None:
    cfg = AppConfig(
        drive_root='folder-"test"',
        backup_path="path\\with\\backslash",
        drive_client_secret='secret-"quoted"',
    )
    save_config(cfg, config_dir=tmp_path)
    restored = load_config(config_dir=tmp_path)
    assert restored.drive_root == 'folder-"test"'
    assert restored.backup_path == "path\\with\\backslash"
    assert restored.drive_client_secret == 'secret-"quoted"'


def test_rclone_config_path_defaults_under_config_dir(tmp_path: Path) -> None:
    assert rclone_config_path(tmp_path) == tmp_path / "rclone.conf"


def test_load_config_returns_app_config_type(tmp_path: Path) -> None:
    result = load_config(config_dir=tmp_path)
    assert type(result) is AppConfig
