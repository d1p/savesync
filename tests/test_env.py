from __future__ import annotations

import os
from pathlib import Path

import pytest

from savesync_bridge.core.env import load_env

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_S3_KEYS = [
    "RCLONE_CONFIG_S3_TYPE",
    "RCLONE_CONFIG_S3_PROVIDER",
    "RCLONE_CONFIG_S3_ACCESS_KEY_ID",
    "RCLONE_CONFIG_S3_SECRET_ACCESS_KEY",
    "RCLONE_CONFIG_S3_REGION",
    "RCLONE_CONFIG_S3_ENDPOINT",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove any S3 env vars before each test to avoid cross-test leakage."""
    for key in _S3_KEYS:
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_load_env_sets_variables(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "RCLONE_CONFIG_S3_ACCESS_KEY_ID=MYKEY\n"
        "RCLONE_CONFIG_S3_SECRET_ACCESS_KEY=MYSECRET\n"
    )
    load_env(env_file)
    assert os.environ.get("RCLONE_CONFIG_S3_ACCESS_KEY_ID") == "MYKEY"
    assert os.environ.get("RCLONE_CONFIG_S3_SECRET_ACCESS_KEY") == "MYSECRET"


def test_load_env_sets_all_expected_keys(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    lines = "\n".join(f"{k}=val_{i}" for i, k in enumerate(_S3_KEYS))
    env_file.write_text(lines)
    load_env(env_file)
    for i, key in enumerate(_S3_KEYS):
        assert os.environ.get(key) == f"val_{i}"


def test_load_env_missing_file_does_not_raise(tmp_path: Path) -> None:
    """A missing .env file should NOT raise — it is optional."""
    load_env(tmp_path / "nonexistent.env")


def test_load_env_overrides_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RCLONE_CONFIG_S3_REGION", "us-west-2")
    env_file = tmp_path / ".env"
    env_file.write_text("RCLONE_CONFIG_S3_REGION=eu-central-1\n")
    load_env(env_file)
    assert os.environ["RCLONE_CONFIG_S3_REGION"] == "eu-central-1"


def test_load_env_no_argument_looks_in_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When called with no argument, load_env looks for .env in the cwd."""
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text("RCLONE_CONFIG_S3_TYPE=s3\n")
    load_env()
    assert os.environ.get("RCLONE_CONFIG_S3_TYPE") == "s3"


def test_load_env_empty_file_does_not_raise(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("")
    load_env(env_file)


def test_load_env_comments_ignored(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# This is a comment\n"
        "RCLONE_CONFIG_S3_PROVIDER=AWS\n"
        "# Another comment\n"
    )
    load_env(env_file)
    assert os.environ.get("RCLONE_CONFIG_S3_PROVIDER") == "AWS"
