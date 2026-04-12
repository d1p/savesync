from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from savesync_bridge.cli.ludusavi import (
    LudusaviGame,
    SaveFileInfo,
    backup_game,
    list_games,
    restore_game,
)
from savesync_bridge.core.exceptions import LudusaviError

FAKE_BINARY = Path("/fake/ludusavi")

BACKUP_PREVIEW_JSON: dict = {
    "overall": {
        "totalGames": 2,
        "processedGames": 2,
        "totalBytes": 2048,
        "processedBytes": 2048,
        "changedGames": {"new": 0, "different": 0, "same": 2},
    },
    "games": {
        "Hades": {
            "decision": "Processed",
            "change": "Same",
            "files": {
                "C:/Users/user/AppData/Roaming/Supergiant Games/Hades/Profiles/Profile1.sav": {
                    "change": "Same",
                    "bytes": 2048,
                }
            },
            "registry": {},
        },
        "Stardew Valley": {
            "decision": "Processed",
            "change": "Same",
            "files": {},
            "registry": {},
        },
    },
}

BACKUP_JSON: dict = {
    "overall": {
        "totalGames": 1,
        "processedGames": 1,
        "totalBytes": 2048,
        "processedBytes": 2048,
    },
    "games": {
        "Hades": {
            "decision": "Processed",
            "files": {
                "C:/Users/user/AppData/Roaming/Supergiant Games/Hades/Profiles/Profile1.sav": {
                    "decision": "Processed",
                    "bytes": 1024,
                }
            },
        }
    },
}

RESTORE_JSON: dict = {
    "overall": {"totalGames": 1, "processedGames": 1},
    "games": {"Hades": {"decision": "Processed", "files": {}}},
}


def _make_proc(stdout: str = "", returncode: int = 0, stderr: str = "") -> MagicMock:
    mock = MagicMock()
    mock.stdout = stdout
    mock.returncode = returncode
    mock.stderr = stderr
    return mock


class TestListGames:
    def test_success_returns_game_list(self) -> None:
        proc = _make_proc(stdout=json.dumps(BACKUP_PREVIEW_JSON))
        with patch("subprocess.run", return_value=proc):
            games = list_games(binary=FAKE_BINARY)
        assert len(games) == 2
        names = {g.name for g in games}
        assert "Hades" in names
        assert "Stardew Valley" in names

    def test_hades_has_correct_save_file(self) -> None:
        proc = _make_proc(stdout=json.dumps(BACKUP_PREVIEW_JSON))
        with patch("subprocess.run", return_value=proc):
            games = list_games(binary=FAKE_BINARY)
        hades = next(g for g in games if g.name == "Hades")
        assert len(hades.save_files) == 1
        assert hades.save_files[0].size == 2048
        assert hades.save_files[0].hash == ""
        assert hades.save_paths == [str(Path("C:/Users/user/AppData/Roaming/Supergiant Games/Hades/Profiles"))]

    def test_stardew_has_no_save_files(self) -> None:
        proc = _make_proc(stdout=json.dumps(BACKUP_PREVIEW_JSON))
        with patch("subprocess.run", return_value=proc):
            games = list_games(binary=FAKE_BINARY)
        stardew = next(g for g in games if g.name == "Stardew Valley")
        assert stardew.save_files == []
        assert stardew.save_paths == []

    def test_cli_args_assembled_correctly(self) -> None:
        proc = _make_proc(stdout=json.dumps(BACKUP_PREVIEW_JSON))
        with patch("subprocess.run", return_value=proc) as mock_run:
            list_games(binary=FAKE_BINARY)
        args = mock_run.call_args[0][0]
        assert args[0] == str(FAKE_BINARY)
        assert args[1:] == ["backup", "--preview", "--api"]

    def test_no_shell_true(self) -> None:
        proc = _make_proc(stdout=json.dumps(BACKUP_PREVIEW_JSON))
        with patch("subprocess.run", return_value=proc) as mock_run:
            list_games(binary=FAKE_BINARY)
        kwargs = mock_run.call_args[1]
        assert kwargs.get("shell", False) is False

    def test_non_zero_exit_raises_ludusavi_error(self) -> None:
        proc = _make_proc(returncode=1, stderr="fatal error")
        with patch("subprocess.run", return_value=proc):
            with pytest.raises(LudusaviError) as exc_info:
                list_games(binary=FAKE_BINARY)
        assert exc_info.value.returncode == 1
        assert "fatal error" in exc_info.value.stderr

    def test_malformed_json_raises_ludusavi_error(self) -> None:
        proc = _make_proc(stdout="not valid json {{")
        with patch("subprocess.run", return_value=proc):
            with pytest.raises(LudusaviError):
                list_games(binary=FAKE_BINARY)

    def test_empty_games_dict_returns_empty_list(self) -> None:
        proc = _make_proc(stdout=json.dumps({"overall": {}, "games": {}}))
        with patch("subprocess.run", return_value=proc):
            games = list_games(binary=FAKE_BINARY)
        assert games == []


class TestBackupGame:
    def test_success_returns_output_dir(self, tmp_path: Path) -> None:
        proc = _make_proc(stdout=json.dumps(BACKUP_JSON))
        with patch("subprocess.run", return_value=proc):
            result = backup_game("Hades", tmp_path, binary=FAKE_BINARY)
        assert result == tmp_path

    def test_cli_args_assembled_correctly(self, tmp_path: Path) -> None:
        proc = _make_proc(stdout=json.dumps(BACKUP_JSON))
        with patch("subprocess.run", return_value=proc) as mock_run:
            backup_game("Hades", tmp_path, binary=FAKE_BINARY)
        args = mock_run.call_args[0][0]
        assert args[0] == str(FAKE_BINARY)
        assert args[1] == "backup"
        assert "--api" in args
        assert "--force" in args
        assert "--path" in args
        path_idx = args.index("--path")
        assert args[path_idx + 1] == str(tmp_path)
        assert "Hades" in args

    def test_no_shell_true(self, tmp_path: Path) -> None:
        proc = _make_proc(stdout=json.dumps(BACKUP_JSON))
        with patch("subprocess.run", return_value=proc) as mock_run:
            backup_game("Hades", tmp_path, binary=FAKE_BINARY)
        kwargs = mock_run.call_args[1]
        assert kwargs.get("shell", False) is False

    def test_non_zero_exit_raises_ludusavi_error(self, tmp_path: Path) -> None:
        proc = _make_proc(returncode=2, stderr="backup failed")
        with patch("subprocess.run", return_value=proc):
            with pytest.raises(LudusaviError) as exc_info:
                backup_game("Hades", tmp_path, binary=FAKE_BINARY)
        assert exc_info.value.returncode == 2
        assert "backup failed" in exc_info.value.stderr

    def test_malformed_json_raises_ludusavi_error(self, tmp_path: Path) -> None:
        proc = _make_proc(stdout="{bad json{{")
        with patch("subprocess.run", return_value=proc):
            with pytest.raises(LudusaviError):
                backup_game("Hades", tmp_path, binary=FAKE_BINARY)


class TestRestoreGame:
    def test_success_returns_none(self, tmp_path: Path) -> None:
        proc = _make_proc(stdout=json.dumps(RESTORE_JSON))
        with patch("subprocess.run", return_value=proc):
            result = restore_game("Hades", tmp_path, binary=FAKE_BINARY)
        assert result is None

    def test_cli_args_assembled_correctly(self, tmp_path: Path) -> None:
        proc = _make_proc(stdout=json.dumps(RESTORE_JSON))
        with patch("subprocess.run", return_value=proc) as mock_run:
            restore_game("Hades", tmp_path, binary=FAKE_BINARY)
        args = mock_run.call_args[0][0]
        assert args[0] == str(FAKE_BINARY)
        assert args[1] == "restore"
        assert "--api" in args
        assert "--force" in args
        assert "--path" in args
        path_idx = args.index("--path")
        assert args[path_idx + 1] == str(tmp_path)
        assert "Hades" in args

    def test_no_shell_true(self, tmp_path: Path) -> None:
        proc = _make_proc(stdout=json.dumps(RESTORE_JSON))
        with patch("subprocess.run", return_value=proc) as mock_run:
            restore_game("Hades", tmp_path, binary=FAKE_BINARY)
        kwargs = mock_run.call_args[1]
        assert kwargs.get("shell", False) is False

    def test_non_zero_exit_raises_ludusavi_error(self, tmp_path: Path) -> None:
        proc = _make_proc(returncode=1, stderr="restore failed")
        with patch("subprocess.run", return_value=proc):
            with pytest.raises(LudusaviError) as exc_info:
                restore_game("Hades", tmp_path, binary=FAKE_BINARY)
        assert exc_info.value.returncode == 1
        assert "restore failed" in exc_info.value.stderr
