from __future__ import annotations

import os
from pathlib import Path

import pytest

from savesync_bridge.core.env import load_env

_DRIVE_KEYS = [
    "RCLONE_DRIVE_CLIENT_ID",
    "RCLONE_DRIVE_CLIENT_SECRET",
    "RCLONE_DRIVE_SCOPE",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _DRIVE_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_load_env_sets_variables(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "RCLONE_DRIVE_CLIENT_ID=MYCLIENT\n"
        "RCLONE_DRIVE_CLIENT_SECRET=MYSECRET\n"
    )
    load_env(env_file)
    assert os.environ.get("RCLONE_DRIVE_CLIENT_ID") == "MYCLIENT"
    assert os.environ.get("RCLONE_DRIVE_CLIENT_SECRET") == "MYSECRET"


def test_load_env_sets_all_expected_keys(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("\n".join(f"{key}=val_{index}" for index, key in enumerate(_DRIVE_KEYS)))
    load_env(env_file)
    for index, key in enumerate(_DRIVE_KEYS):
        assert os.environ.get(key) == f"val_{index}"


def test_load_env_missing_file_does_not_raise(tmp_path: Path) -> None:
    load_env(tmp_path / "nonexistent.env")


def test_load_env_overrides_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RCLONE_DRIVE_SCOPE", "drive.readonly")
    env_file = tmp_path / ".env"
    env_file.write_text("RCLONE_DRIVE_SCOPE=drive\n")
    load_env(env_file)
    assert os.environ["RCLONE_DRIVE_SCOPE"] == "drive"


def test_load_env_no_argument_looks_in_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text("RCLONE_DRIVE_CLIENT_ID=browser-client\n")
    load_env()
    assert os.environ.get("RCLONE_DRIVE_CLIENT_ID") == "browser-client"


def test_load_env_empty_file_does_not_raise(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("")
    load_env(env_file)


def test_load_env_comments_ignored(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# This is a comment\n"
        "RCLONE_DRIVE_SCOPE=drive\n"
        "# Another comment\n"
    )
    load_env(env_file)
    assert os.environ.get("RCLONE_DRIVE_SCOPE") == "drive"
