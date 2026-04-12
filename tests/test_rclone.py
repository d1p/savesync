from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from savesync_bridge.cli.rclone import (
    download,
    file_exists,
    list_files,
    upload,
)
from savesync_bridge.cli.rclone import read_file as rclone_read_file
from savesync_bridge.core.exceptions import RcloneError

FAKE_BINARY = Path("/fake/rclone")
REMOTE = "s3remote"
BUCKET = "test-bucket"
PREFIX = "saves/Hades"


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
            upload(tmp_path, REMOTE, BUCKET, PREFIX, binary=FAKE_BINARY)
        args = mock_run.call_args[0][0]
        assert args[0] == str(FAKE_BINARY)
        assert args[1] == "copy"
        assert str(tmp_path) in args
        assert f"{REMOTE}:{BUCKET}/{PREFIX}" in args

    def test_non_zero_raises_rclone_error(self, tmp_path: Path) -> None:
        proc = _make_proc(returncode=1, stderr="upload failed")
        with patch("subprocess.run", return_value=proc):
            with pytest.raises(RcloneError) as exc_info:
                upload(tmp_path, REMOTE, BUCKET, PREFIX, binary=FAKE_BINARY)
        assert exc_info.value.returncode == 1
        assert "upload failed" in exc_info.value.stderr

    def test_env_is_merged_into_subprocess(self, tmp_path: Path) -> None:
        proc = _make_proc()
        custom_env = {"MY_CUSTOM_VAR": "my_value"}
        with patch("subprocess.run", return_value=proc) as mock_run:
            upload(tmp_path, REMOTE, BUCKET, PREFIX, env=custom_env, binary=FAKE_BINARY)
        call_kwargs = mock_run.call_args[1]
        assert "env" in call_kwargs
        assert call_kwargs["env"]["MY_CUSTOM_VAR"] == "my_value"

    def test_env_merge_does_not_mutate_os_environ(self, tmp_path: Path) -> None:
        proc = _make_proc()
        custom_env = {"SAVESYNC_UNIQUE_KEY": "value"}
        with patch("subprocess.run", return_value=proc):
            upload(tmp_path, REMOTE, BUCKET, PREFIX, env=custom_env, binary=FAKE_BINARY)
        assert "SAVESYNC_UNIQUE_KEY" not in os.environ

    def test_env_includes_existing_os_environ_keys(self, tmp_path: Path) -> None:
        proc = _make_proc()
        with patch("subprocess.run", return_value=proc) as mock_run:
            upload(tmp_path, REMOTE, BUCKET, PREFIX, env={"X": "1"}, binary=FAKE_BINARY)
        call_env = mock_run.call_args[1]["env"]
        # PATH should exist in the merged env from os.environ
        assert "PATH" in call_env or len(call_env) > 1

    def test_no_shell_true(self, tmp_path: Path) -> None:
        proc = _make_proc()
        with patch("subprocess.run", return_value=proc) as mock_run:
            upload(tmp_path, REMOTE, BUCKET, PREFIX, binary=FAKE_BINARY)
        kwargs = mock_run.call_args[1]
        assert kwargs.get("shell", False) is False

    def test_no_env_passed_when_env_is_none(self, tmp_path: Path) -> None:
        proc = _make_proc()
        with patch("subprocess.run", return_value=proc) as mock_run:
            upload(tmp_path, REMOTE, BUCKET, PREFIX, binary=FAKE_BINARY)
        kwargs = mock_run.call_args[1]
        # When no env override, subprocess inherits from parent (env kwarg absent or None)
        assert kwargs.get("env") is None


class TestDownload:
    def test_cli_args(self, tmp_path: Path) -> None:
        proc = _make_proc()
        with patch("subprocess.run", return_value=proc) as mock_run:
            download(REMOTE, BUCKET, PREFIX, tmp_path, binary=FAKE_BINARY)
        args = mock_run.call_args[0][0]
        assert args[0] == str(FAKE_BINARY)
        assert args[1] == "copy"
        assert f"{REMOTE}:{BUCKET}/{PREFIX}" in args
        assert str(tmp_path) in args

    def test_remote_arg_comes_before_local(self, tmp_path: Path) -> None:
        proc = _make_proc()
        with patch("subprocess.run", return_value=proc) as mock_run:
            download(REMOTE, BUCKET, PREFIX, tmp_path, binary=FAKE_BINARY)
        args = mock_run.call_args[0][0]
        remote_idx = args.index(f"{REMOTE}:{BUCKET}/{PREFIX}")
        local_idx = args.index(str(tmp_path))
        assert remote_idx < local_idx

    def test_non_zero_raises_rclone_error(self, tmp_path: Path) -> None:
        proc = _make_proc(returncode=1, stderr="download failed")
        with patch("subprocess.run", return_value=proc):
            with pytest.raises(RcloneError) as exc_info:
                download(REMOTE, BUCKET, PREFIX, tmp_path, binary=FAKE_BINARY)
        assert exc_info.value.returncode == 1

    def test_no_shell_true(self, tmp_path: Path) -> None:
        proc = _make_proc()
        with patch("subprocess.run", return_value=proc) as mock_run:
            download(REMOTE, BUCKET, PREFIX, tmp_path, binary=FAKE_BINARY)
        kwargs = mock_run.call_args[1]
        assert kwargs.get("shell", False) is False


class TestReadFile:
    def test_returns_stdout_bytes(self) -> None:
        payload = b'{"game_id": "Hades"}'
        proc = _make_proc(stdout=payload)
        with patch("subprocess.run", return_value=proc):
            result = rclone_read_file(REMOTE, BUCKET, "saves/Hades/manifest.json", binary=FAKE_BINARY)
        assert result == payload

    def test_cli_args(self) -> None:
        proc = _make_proc(stdout=b"data")
        with patch("subprocess.run", return_value=proc) as mock_run:
            rclone_read_file(REMOTE, BUCKET, "saves/Hades/manifest.json", binary=FAKE_BINARY)
        args = mock_run.call_args[0][0]
        assert args[0] == str(FAKE_BINARY)
        assert args[1] == "cat"
        assert f"{REMOTE}:{BUCKET}/saves/Hades/manifest.json" in args

    def test_non_zero_raises_rclone_error(self) -> None:
        proc = _make_proc(returncode=1, stderr="object not found")
        with patch("subprocess.run", return_value=proc):
            with pytest.raises(RcloneError) as exc_info:
                rclone_read_file(REMOTE, BUCKET, "saves/missing.json", binary=FAKE_BINARY)
        assert exc_info.value.returncode == 1

    def test_no_shell_true(self) -> None:
        proc = _make_proc(stdout=b"x")
        with patch("subprocess.run", return_value=proc) as mock_run:
            rclone_read_file(REMOTE, BUCKET, "key", binary=FAKE_BINARY)
        kwargs = mock_run.call_args[1]
        assert kwargs.get("shell", False) is False


class TestListFiles:
    def test_returns_parsed_json_list(self) -> None:
        files = [{"Name": "save.dat", "Size": 1024, "IsDir": False}]
        proc = _make_proc(stdout=json.dumps(files))
        with patch("subprocess.run", return_value=proc):
            result = list_files(REMOTE, BUCKET, PREFIX, binary=FAKE_BINARY)
        assert result == files

    def test_returns_empty_list(self) -> None:
        proc = _make_proc(stdout="[]")
        with patch("subprocess.run", return_value=proc):
            result = list_files(REMOTE, BUCKET, PREFIX, binary=FAKE_BINARY)
        assert result == []

    def test_cli_args(self) -> None:
        proc = _make_proc(stdout="[]")
        with patch("subprocess.run", return_value=proc) as mock_run:
            list_files(REMOTE, BUCKET, PREFIX, binary=FAKE_BINARY)
        args = mock_run.call_args[0][0]
        assert args[0] == str(FAKE_BINARY)
        assert args[1] == "lsjson"
        assert f"{REMOTE}:{BUCKET}/{PREFIX}" in args

    def test_non_zero_raises_rclone_error(self) -> None:
        proc = _make_proc(returncode=1, stderr="listing failed")
        with patch("subprocess.run", return_value=proc):
            with pytest.raises(RcloneError) as exc_info:
                list_files(REMOTE, BUCKET, PREFIX, binary=FAKE_BINARY)
        assert exc_info.value.returncode == 1

    def test_malformed_json_raises_rclone_error(self) -> None:
        proc = _make_proc(stdout="not json {{")
        with patch("subprocess.run", return_value=proc):
            with pytest.raises(RcloneError):
                list_files(REMOTE, BUCKET, PREFIX, binary=FAKE_BINARY)


class TestFileExists:
    def test_returns_true_when_file_found(self) -> None:
        files = [{"Name": "manifest.json", "Size": 512}]
        proc = _make_proc(stdout=json.dumps(files))
        with patch("subprocess.run", return_value=proc):
            result = file_exists(REMOTE, BUCKET, f"{PREFIX}/manifest.json", binary=FAKE_BINARY)
        assert result is True

    def test_returns_false_when_list_empty(self) -> None:
        proc = _make_proc(stdout="[]")
        with patch("subprocess.run", return_value=proc):
            result = file_exists(REMOTE, BUCKET, f"{PREFIX}/missing.json", binary=FAKE_BINARY)
        assert result is False

    def test_returns_false_on_rclone_error(self) -> None:
        proc = _make_proc(returncode=1, stderr="not found")
        with patch("subprocess.run", return_value=proc):
            result = file_exists(REMOTE, BUCKET, f"{PREFIX}/missing.json", binary=FAKE_BINARY)
        assert result is False
