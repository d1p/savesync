from __future__ import annotations

from pathlib import Path

import pytest

from savesync_bridge.core.config import AppConfig, load_config, save_config


# ---------------------------------------------------------------------------
# AppConfig defaults
# ---------------------------------------------------------------------------


def test_app_config_defaults() -> None:
    cfg = AppConfig()
    assert cfg.rclone_remote == "s3remote"
    assert cfg.s3_bucket == ""
    assert cfg.s3_prefix == "savesync-bridge"
    assert cfg.ludusavi_path is None
    assert cfg.rclone_path is None
    assert cfg.known_games == []


def test_app_config_fields_mutable() -> None:
    cfg = AppConfig()
    cfg.rclone_remote = "myremote"
    assert cfg.rclone_remote == "myremote"


# ---------------------------------------------------------------------------
# load_config creates default when file is absent
# ---------------------------------------------------------------------------


def test_load_config_creates_default_when_missing(tmp_path: Path) -> None:
    cfg = load_config(config_dir=tmp_path)
    assert isinstance(cfg, AppConfig)
    assert cfg.rclone_remote == "s3remote"


def test_load_config_does_not_raise_on_missing_dir(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent"
    cfg = load_config(config_dir=missing)
    assert isinstance(cfg, AppConfig)


# ---------------------------------------------------------------------------
# save_config / load_config round-trip
# ---------------------------------------------------------------------------


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    cfg = AppConfig(
        rclone_remote="r2remote",
        s3_bucket="my-bucket",
        s3_prefix="games/saves",
        known_games=["Celeste", "Hades"],
    )
    save_config(cfg, config_dir=tmp_path)
    restored = load_config(config_dir=tmp_path)

    assert restored.rclone_remote == "r2remote"
    assert restored.s3_bucket == "my-bucket"
    assert restored.s3_prefix == "games/saves"
    assert restored.known_games == ["Celeste", "Hades"]


def test_save_creates_config_file(tmp_path: Path) -> None:
    cfg = AppConfig()
    save_config(cfg, config_dir=tmp_path)
    config_file = tmp_path / "config.toml"
    assert config_file.exists()


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
    """String values with backslashes and quotes survive the round-trip."""
    cfg = AppConfig(s3_bucket='bucket-"test"', s3_prefix="path\\with\\backslash")
    save_config(cfg, config_dir=tmp_path)
    restored = load_config(config_dir=tmp_path)
    assert restored.s3_bucket == 'bucket-"test"'
    assert restored.s3_prefix == "path\\with\\backslash"


def test_load_config_returns_app_config_type(tmp_path: Path) -> None:
    result = load_config(config_dir=tmp_path)
    assert type(result) is AppConfig
