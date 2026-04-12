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


def _mock_popen(proc: MagicMock):
    """Return a context-manager that patches subprocess.Popen to behave like
    the old subprocess.run mock: the Popen instance returns (stdout, stderr)
    from communicate() and exposes returncode/poll."""
    popen_inst = MagicMock()
    popen_inst.communicate.return_value = (proc.stdout, proc.stderr)
    popen_inst.returncode = proc.returncode
    popen_inst.poll.return_value = proc.returncode
    popen_inst.wait.return_value = proc.returncode
    return patch("subprocess.Popen", return_value=popen_inst)


def _mock_popen_streaming(proc: MagicMock):
    """Like _mock_popen but for _invoke_auth which iterates stderr line-by-line
    and calls stdout.read()."""
    popen_inst = MagicMock()
    stderr_text = proc.stderr or ""
    popen_inst.stderr.__iter__ = MagicMock(
        return_value=iter(stderr_text.splitlines(keepends=True) if stderr_text else [])
    )
    stdout_text = proc.stdout or ""
    popen_inst.stdout.read.return_value = stdout_text
    popen_inst.returncode = proc.returncode
    popen_inst.poll.return_value = proc.returncode
    popen_inst.wait.return_value = proc.returncode
    return patch("subprocess.Popen", return_value=popen_inst)


class TestUpload:
    def test_cli_args(self, tmp_path: Path) -> None:
        proc = _make_proc()
        with _mock_popen(proc) as mock_popen:
            upload(tmp_path, REMOTE, ROOT, BACKUP_PATH, binary=FAKE_BINARY, config_file=CONFIG_FILE)
        args = mock_popen.call_args[0][0]
        assert args[0] == str(FAKE_BINARY)
        assert args[1:3] == ["--config", str(CONFIG_FILE)]
        assert args[3] == "copy"
        assert str(tmp_path) in args
        assert f"{REMOTE}:{ROOT}/{BACKUP_PATH}" in args

    def test_non_zero_raises_rclone_error(self, tmp_path: Path) -> None:
        proc = _make_proc(returncode=1, stderr="upload failed")
        with _mock_popen(proc), pytest.raises(RcloneError) as exc_info:
            upload(tmp_path, REMOTE, ROOT, BACKUP_PATH, binary=FAKE_BINARY)
        assert exc_info.value.returncode == 1
        assert "upload failed" in exc_info.value.stderr

    def test_env_is_merged_into_subprocess(self, tmp_path: Path) -> None:
        proc = _make_proc()
        custom_env = {"MY_CUSTOM_VAR": "my_value"}
        with _mock_popen(proc) as mock_popen:
            upload(tmp_path, REMOTE, ROOT, BACKUP_PATH, env=custom_env, binary=FAKE_BINARY)
        assert mock_popen.call_args[1]["env"]["MY_CUSTOM_VAR"] == "my_value"

    def test_env_merge_does_not_mutate_os_environ(self, tmp_path: Path) -> None:
        proc = _make_proc()
        with _mock_popen(proc):
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
        with _mock_popen(proc) as mock_popen:
            upload(tmp_path, REMOTE, "", BACKUP_PATH, binary=FAKE_BINARY)
        args = mock_popen.call_args[0][0]
        assert f"{REMOTE}:{BACKUP_PATH}" in args


class TestDownload:
    def test_cli_args(self, tmp_path: Path) -> None:
        proc = _make_proc()
        with _mock_popen(proc) as mock_popen:
            download(
                REMOTE, ROOT, BACKUP_PATH, tmp_path,
                binary=FAKE_BINARY, config_file=CONFIG_FILE,
            )
        args = mock_popen.call_args[0][0]
        assert args[0] == str(FAKE_BINARY)
        assert args[1:3] == ["--config", str(CONFIG_FILE)]
        assert args[3] == "copy"
        assert f"{REMOTE}:{ROOT}/{BACKUP_PATH}" in args
        assert str(tmp_path) in args

    def test_non_zero_raises_rclone_error(self, tmp_path: Path) -> None:
        proc = _make_proc(returncode=1, stderr="download failed")
        with _mock_popen(proc), pytest.raises(RcloneError):
            download(REMOTE, ROOT, BACKUP_PATH, tmp_path, binary=FAKE_BINARY)


class TestReadFile:
    def test_returns_stdout_bytes(self) -> None:
        payload = b'{"game_id": "Hades"}'
        proc = _make_proc(stdout=payload)
        with _mock_popen(proc):
            result = rclone_read_file(REMOTE, ROOT, "saves/Hades/manifest.json", binary=FAKE_BINARY)
        assert result == payload

    def test_cli_args(self) -> None:
        proc = _make_proc(stdout=b"data")
        with _mock_popen(proc) as mock_popen:
            rclone_read_file(
                REMOTE,
                ROOT,
                "saves/Hades/manifest.json",
                binary=FAKE_BINARY,
                config_file=CONFIG_FILE,
            )
        args = mock_popen.call_args[0][0]
        assert args[1:3] == ["--config", str(CONFIG_FILE)]
        assert f"{REMOTE}:{ROOT}/saves/Hades/manifest.json" in args


class TestListFiles:
    def test_returns_parsed_json_list(self) -> None:
        files = [{"Name": "save.dat", "Size": 1024, "IsDir": False}]
        proc = _make_proc(stdout=json.dumps(files))
        with _mock_popen(proc):
            result = list_files(REMOTE, ROOT, BACKUP_PATH, binary=FAKE_BINARY)
        assert result == files

    def test_malformed_json_raises_rclone_error(self) -> None:
        proc = _make_proc(stdout="not json {{")
        with _mock_popen(proc), pytest.raises(RcloneError):
            list_files(REMOTE, ROOT, BACKUP_PATH, binary=FAKE_BINARY)


class TestFileExists:
    def test_returns_true_when_file_found(self) -> None:
        files = [{"Name": "manifest.json", "Size": 512}]
        proc = _make_proc(stdout=json.dumps(files))
        with _mock_popen(proc):
            result = file_exists(REMOTE, ROOT, f"{BACKUP_PATH}/manifest.json", binary=FAKE_BINARY)
        assert result is True

    def test_returns_false_on_rclone_error(self) -> None:
        proc = _make_proc(returncode=1, stderr="not found")
        with _mock_popen(proc):
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
        with _mock_popen_streaming(proc) as mock_popen:
            configure_google_drive_remote(
                "gdrive",
                config_file,
                client_id="client-id",
                client_secret="client-secret",
                binary=FAKE_BINARY,
            )
        args = mock_popen.call_args[0][0]
        assert "--no-browser" in args
        assert "config" in args and "create" in args
        assert "client_id" in args and "client-id" in args
        assert "client_secret" in args and "client-secret" in args

    def test_configure_google_drive_remote_updates_existing_remote(self, tmp_path: Path) -> None:
        proc = _make_proc(stdout="ok")
        config_file = tmp_path / "rclone.conf"
        config_file.write_text("[gdrive]\ntype = drive\n", encoding="utf-8")
        with _mock_popen_streaming(proc) as mock_popen:
            configure_google_drive_remote("gdrive", config_file, binary=FAKE_BINARY)
        args = mock_popen.call_args[0][0]
        assert "--no-browser" in args
        assert "config" in args and "update" in args

    def test_reconnect_google_drive_remote_uses_reconnect_command(self, tmp_path: Path) -> None:
        proc = _make_proc(stdout="ok")
        config_file = tmp_path / "rclone.conf"
        with _mock_popen_streaming(proc) as mock_popen:
            reconnect_google_drive_remote("gdrive", config_file, binary=FAKE_BINARY)
        args = mock_popen.call_args[0][0]
        assert "--no-browser" in args
        assert args[-3:] == ["config", "reconnect", "gdrive:"]

    def test_delete_remote_config_skips_missing_remote(self, tmp_path: Path) -> None:
        with patch("subprocess.Popen") as mock_popen:
            delete_remote_config("missing", tmp_path / "rclone.conf", binary=FAKE_BINARY)
        mock_popen.assert_not_called()

    def test_delete_remote_config_runs_delete_for_existing_remote(self, tmp_path: Path) -> None:
        proc = _make_proc(stdout="ok")
        config_file = tmp_path / "rclone.conf"
        config_file.write_text("[gdrive]\ntype = drive\n", encoding="utf-8")
        with _mock_popen(proc) as mock_popen:
            delete_remote_config("gdrive", config_file, binary=FAKE_BINARY)
        args = mock_popen.call_args[0][0]
        assert args[-3:] == ["config", "delete", "gdrive"]

    def test_verify_google_drive_remote_lists_root(self) -> None:
        proc = _make_proc(stdout="[]")
        with _mock_popen(proc) as mock_popen:
            verify_google_drive_remote(
                "gdrive", "SyncRoot",
                binary=FAKE_BINARY, config_file=CONFIG_FILE,
            )
        args = mock_popen.call_args[0][0]
        assert args[-2:] == ["lsjson", "gdrive:SyncRoot"]
