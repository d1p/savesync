from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from savesync_bridge.cli.rclone import (
    configure_google_drive_remote,
    delete_remote_config,
    download,
    file_exists,
    has_remote_config,
    list_files,
    reconnect_google_drive_remote,
    upload,
    verify_google_drive_remote,
)
from savesync_bridge.cli.rclone import read_file as rclone_read_file
from savesync_bridge.core.exceptions import RcloneError

FAKE_BINARY = Path("/fake/rclone")
CONFIG_FILE = Path("/fake/rclone.conf")
REMOTE = "gdrive"
ROOT = "SyncRoot"
BACKUP_PATH = "saves/Hades"


def _make_proc(
    stdout: str | bytes = "",
    returncode: int = 0,
    stderr: str = "",
) -> MagicMock:
    mock = MagicMock()
    mock.stdout = stdout
    mock.returncode = returncode
    mock.stderr = stderr
    return mock


class TestUpload:
    def test_cli_args(self, tmp_path: Path) -> None:
        proc = _make_proc()
        with patch("subprocess.run", return_value=proc) as mock_run:
            upload(tmp_path, REMOTE, ROOT, BACKUP_PATH, binary=FAKE_BINARY, config_file=CONFIG_FILE)
        args = mock_run.call_args[0][0]
        assert args[0] == str(FAKE_BINARY)
        assert args[1:3] == ["--config", str(CONFIG_FILE)]
        assert args[3] == "copy"
        assert str(tmp_path) in args
        assert f"{REMOTE}:{ROOT}/{BACKUP_PATH}" in args

    def test_non_zero_raises_rclone_error(self, tmp_path: Path) -> None:
        proc = _make_proc(returncode=1, stderr="upload failed")
        with patch("subprocess.run", return_value=proc), pytest.raises(RcloneError) as exc_info:
            upload(tmp_path, REMOTE, ROOT, BACKUP_PATH, binary=FAKE_BINARY)
        assert exc_info.value.returncode == 1
        assert "upload failed" in exc_info.value.stderr

    def test_env_is_merged_into_subprocess(self, tmp_path: Path) -> None:
        proc = _make_proc()
        custom_env = {"MY_CUSTOM_VAR": "my_value"}
        with patch("subprocess.run", return_value=proc) as mock_run:
            upload(tmp_path, REMOTE, ROOT, BACKUP_PATH, env=custom_env, binary=FAKE_BINARY)
        assert mock_run.call_args[1]["env"]["MY_CUSTOM_VAR"] == "my_value"

    def test_env_merge_does_not_mutate_os_environ(self, tmp_path: Path) -> None:
        proc = _make_proc()
        with patch("subprocess.run", return_value=proc):
            upload(
                tmp_path,
                REMOTE,
                ROOT,
                BACKUP_PATH,
                env={"SAVESYNC_UNIQUE_KEY": "value"},
                binary=FAKE_BINARY,
            )
        assert "SAVESYNC_UNIQUE_KEY" not in os.environ

    def test_omits_root_when_empty(self, tmp_path: Path) -> None:
        proc = _make_proc()
        with patch("subprocess.run", return_value=proc) as mock_run:
            upload(tmp_path, REMOTE, "", BACKUP_PATH, binary=FAKE_BINARY)
        args = mock_run.call_args[0][0]
        assert f"{REMOTE}:{BACKUP_PATH}" in args


class TestDownload:
    def test_cli_args(self, tmp_path: Path) -> None:
        proc = _make_proc()
        with patch("subprocess.run", return_value=proc) as mock_run:
            download(
                REMOTE, ROOT, BACKUP_PATH, tmp_path,
                binary=FAKE_BINARY, config_file=CONFIG_FILE,
            )
        args = mock_run.call_args[0][0]
        assert args[0] == str(FAKE_BINARY)
        assert args[1:3] == ["--config", str(CONFIG_FILE)]
        assert args[3] == "copy"
        assert f"{REMOTE}:{ROOT}/{BACKUP_PATH}" in args
        assert str(tmp_path) in args

    def test_non_zero_raises_rclone_error(self, tmp_path: Path) -> None:
        proc = _make_proc(returncode=1, stderr="download failed")
        with patch("subprocess.run", return_value=proc), pytest.raises(RcloneError):
            download(REMOTE, ROOT, BACKUP_PATH, tmp_path, binary=FAKE_BINARY)


class TestReadFile:
    def test_returns_stdout_bytes(self) -> None:
        payload = b'{"game_id": "Hades"}'
        proc = _make_proc(stdout=payload)
        with patch("subprocess.run", return_value=proc):
            result = rclone_read_file(REMOTE, ROOT, "saves/Hades/manifest.json", binary=FAKE_BINARY)
        assert result == payload

    def test_cli_args(self) -> None:
        proc = _make_proc(stdout=b"data")
        with patch("subprocess.run", return_value=proc) as mock_run:
            rclone_read_file(
                REMOTE,
                ROOT,
                "saves/Hades/manifest.json",
                binary=FAKE_BINARY,
                config_file=CONFIG_FILE,
            )
        args = mock_run.call_args[0][0]
        assert args[1:3] == ["--config", str(CONFIG_FILE)]
        assert f"{REMOTE}:{ROOT}/saves/Hades/manifest.json" in args


class TestListFiles:
    def test_returns_parsed_json_list(self) -> None:
        files = [{"Name": "save.dat", "Size": 1024, "IsDir": False}]
        proc = _make_proc(stdout=json.dumps(files))
        with patch("subprocess.run", return_value=proc):
            result = list_files(REMOTE, ROOT, BACKUP_PATH, binary=FAKE_BINARY)
        assert result == files

    def test_malformed_json_raises_rclone_error(self) -> None:
        proc = _make_proc(stdout="not json {{")
        with patch("subprocess.run", return_value=proc), pytest.raises(RcloneError):
            list_files(REMOTE, ROOT, BACKUP_PATH, binary=FAKE_BINARY)


class TestFileExists:
    def test_returns_true_when_file_found(self) -> None:
        files = [{"Name": "manifest.json", "Size": 512}]
        proc = _make_proc(stdout=json.dumps(files))
        with patch("subprocess.run", return_value=proc):
            result = file_exists(REMOTE, ROOT, f"{BACKUP_PATH}/manifest.json", binary=FAKE_BINARY)
        assert result is True

    def test_returns_false_on_rclone_error(self) -> None:
        proc = _make_proc(returncode=1, stderr="not found")
        with patch("subprocess.run", return_value=proc):
            result = file_exists(REMOTE, ROOT, f"{BACKUP_PATH}/missing.json", binary=FAKE_BINARY)
        assert result is False


class TestDriveConfigHelpers:
    def test_has_remote_config_reads_ini_sections(self, tmp_path: Path) -> None:
        config_file = tmp_path / "rclone.conf"
        config_file.write_text("[gdrive]\ntype = drive\n", encoding="utf-8")
        assert has_remote_config("gdrive", config_file) is True
        assert has_remote_config("other", config_file) is False

    def test_configure_google_drive_remote_creates_remote(self, tmp_path: Path) -> None:
        proc = _make_proc(stdout="ok")
        config_file = tmp_path / "rclone.conf"
        with patch("subprocess.run", return_value=proc) as mock_run:
            configure_google_drive_remote(
                "gdrive",
                config_file,
                client_id="client-id",
                client_secret="client-secret",
                binary=FAKE_BINARY,
            )
        args = mock_run.call_args[0][0]
        assert args[:5] == [str(FAKE_BINARY), "--config", str(config_file), "config", "create"]
        assert "client_id" in args and "client-id" in args
        assert "client_secret" in args and "client-secret" in args

    def test_configure_google_drive_remote_updates_existing_remote(self, tmp_path: Path) -> None:
        proc = _make_proc(stdout="ok")
        config_file = tmp_path / "rclone.conf"
        config_file.write_text("[gdrive]\ntype = drive\n", encoding="utf-8")
        with patch("subprocess.run", return_value=proc) as mock_run:
            configure_google_drive_remote("gdrive", config_file, binary=FAKE_BINARY)
        args = mock_run.call_args[0][0]
        assert args[:5] == [str(FAKE_BINARY), "--config", str(config_file), "config", "update"]

    def test_reconnect_google_drive_remote_uses_reconnect_command(self, tmp_path: Path) -> None:
        proc = _make_proc(stdout="ok")
        config_file = tmp_path / "rclone.conf"
        with patch("subprocess.run", return_value=proc) as mock_run:
            reconnect_google_drive_remote("gdrive", config_file, binary=FAKE_BINARY)
        args = mock_run.call_args[0][0]
        assert args[-3:] == ["config", "reconnect", "gdrive:"]

    def test_delete_remote_config_skips_missing_remote(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            delete_remote_config("missing", tmp_path / "rclone.conf", binary=FAKE_BINARY)
        mock_run.assert_not_called()

    def test_delete_remote_config_runs_delete_for_existing_remote(self, tmp_path: Path) -> None:
        proc = _make_proc(stdout="ok")
        config_file = tmp_path / "rclone.conf"
        config_file.write_text("[gdrive]\ntype = drive\n", encoding="utf-8")
        with patch("subprocess.run", return_value=proc) as mock_run:
            delete_remote_config("gdrive", config_file, binary=FAKE_BINARY)
        args = mock_run.call_args[0][0]
        assert args[-3:] == ["config", "delete", "gdrive"]

    def test_verify_google_drive_remote_lists_root(self) -> None:
        proc = _make_proc(stdout="[]")
        with patch("subprocess.run", return_value=proc) as mock_run:
            verify_google_drive_remote(
                "gdrive", "SyncRoot",
                binary=FAKE_BINARY, config_file=CONFIG_FILE,
            )
        args = mock_run.call_args[0][0]
        assert args[-2:] == ["lsjson", "gdrive:SyncRoot"]
