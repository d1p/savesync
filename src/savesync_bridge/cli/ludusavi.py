from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from savesync_bridge.core.binaries import resolve_ludusavi
from savesync_bridge.core.exceptions import LudusaviError


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
    """Wrapper around subprocess.run that emits on cli_bus (best-effort)."""
    try:
        from savesync_bridge.core.cli_bus import cli_bus
        cli_bus.command_run.emit(" ".join(str(c) for c in cmd))
    except Exception:
        pass
    result = subprocess.run(cmd, **kwargs)
    try:
        from savesync_bridge.core.cli_bus import cli_bus
        if result.stdout and isinstance(result.stdout, str):
            cli_bus.stdout_line.emit(result.stdout.strip())
        if result.stderr and isinstance(result.stderr, str):
            cli_bus.stderr_line.emit(result.stderr.strip())
        cli_bus.exit_code.emit(result.returncode)
    except Exception:
        pass
    return result


@dataclass
class SaveFileInfo:
    path: str
    size: int
    hash: str


@dataclass
class LudusaviGame:
    name: str
    save_files: list[SaveFileInfo] = field(default_factory=list)
    save_paths: list[str] = field(default_factory=list)


def list_games(
    games: list[str] | None = None,
    binary: Path | None = None,
) -> list[LudusaviGame]:
    """Run `ludusavi backup --preview --api` and parse JSON output.

    Uses the backup-preview mode to enumerate only games that are
    actually installed on the current system.  This is preferred over
    ``manifest show`` which downloads/processes every known game.

    Args:
        games: Optional subset of specific game identifiers to preview.
        binary: Path to the ludusavi binary. Defaults to ``resolve_ludusavi()``.

    Returns:
        List of detected games with their save paths and file metadata.

    Raises:
        LudusaviError: If ludusavi exits with a non-zero code or outputs invalid JSON.
    """
    if binary is None:
        binary = resolve_ludusavi()

    cmd = [str(binary), "backup", "--preview", "--api"]
    if games:
        cmd.extend(games)

    result = _run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise LudusaviError(
            f"ludusavi backup --preview failed: {result.stderr}",
            result.returncode,
            result.stderr,
        )

    stdout = result.stdout or ""
    if not stdout.strip():
        raise LudusaviError(
            "ludusavi backup --preview produced no output",
            result.returncode,
            result.stderr or "",
        )

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise LudusaviError(
            f"ludusavi returned invalid JSON: {exc}",
            0,
            result.stderr,
        ) from exc

    games: list[LudusaviGame] = []
    for game_name, game_data in data.get("games", {}).items():
        save_files = [
            SaveFileInfo(
                path=fp,
                size=info.get("bytes", 0),
                hash="",
            )
            for fp, info in game_data.get("files", {}).items()
        ]
        # Derive save_paths from the unique parent directories of each save file.
        seen: set[str] = set()
        save_paths: list[str] = []
        for sf in save_files:
            parent = str(Path(sf.path).parent)
            if parent not in seen:
                seen.add(parent)
                save_paths.append(parent)
        games.append(
            LudusaviGame(name=game_name, save_files=save_files, save_paths=save_paths)
        )

    return games


def get_game(game_name: str, binary: Path | None = None) -> LudusaviGame | None:
    """Preview one game and return its live save scan if Ludusavi reports it."""
    for game in list_games(games=[game_name], binary=binary):
        if game.name == game_name:
            return game
    return None


def backup_game(
    game_name: str,
    output_dir: Path,
    binary: Path | None = None,
) -> Path:
    """Run `ludusavi backup --api --path <output_dir> <game_name>`.

    Args:
        game_name: The Ludusavi game identifier.
        output_dir: Directory where Ludusavi will write the backup.
        binary: Path to the ludusavi binary. Defaults to ``resolve_ludusavi()``.

    Returns:
        ``output_dir`` — the directory containing the backup.

    Raises:
        LudusaviError: If ludusavi exits with a non-zero code or outputs invalid JSON.
    """
    if binary is None:
        binary = resolve_ludusavi()

    result = _run(
        [str(binary), "backup", "--api", "--force", "--path", str(output_dir), game_name],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise LudusaviError(
            f"ludusavi backup failed: {result.stderr}",
            result.returncode,
            result.stderr,
        )

    try:
        json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise LudusaviError(
            f"ludusavi returned invalid JSON: {exc}",
            0,
            result.stderr,
        ) from exc

    return output_dir


def restore_game(
    game_name: str,
    backup_dir: Path,
    binary: Path | None = None,
) -> None:
    """Run `ludusavi restore --api --path <backup_dir> <game_name>`.

    Args:
        game_name: The Ludusavi game identifier.
        backup_dir: Directory containing the backup to restore from.
        binary: Path to the ludusavi binary. Defaults to ``resolve_ludusavi()``.

    Raises:
        LudusaviError: If ludusavi exits with a non-zero code.
    """
    if binary is None:
        binary = resolve_ludusavi()

    result = _run(
        [str(binary), "restore", "--api", "--force", "--path", str(backup_dir), game_name],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise LudusaviError(
            f"ludusavi restore failed: {result.stderr}",
            result.returncode,
            result.stderr,
        )


def backup_games(
    game_names: list[str],
    output_dir: Path,
    binary: Path | None = None,
) -> dict[str, Path]:
    """Run `ludusavi backup --api --path <output_dir>` for multiple games in a single call.

    This is more efficient than calling backup_game() repeatedly, as it batches
    all backups into a single ludusavi invocation.

    Args:
        game_names: List of Ludusavi game identifiers.
        output_dir: Directory where Ludusavi will write the backups.
        binary: Path to the ludusavi binary. Defaults to ``resolve_ludusavi()``.

    Returns:
        Dictionary mapping game_name to the directory containing its backup.

    Raises:
        LudusaviError: If ludusavi exits with a non-zero code or outputs invalid JSON.
    """
    if not game_names:
        return {}

    if binary is None:
        binary = resolve_ludusavi()

    cmd = [str(binary), "backup", "--api", "--force", "--path", str(output_dir)]
    cmd.extend(game_names)

    result = _run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise LudusaviError(
            f"ludusavi backup failed: {result.stderr}",
            result.returncode,
            result.stderr,
        )

    try:
        json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise LudusaviError(
            f"ludusavi returned invalid JSON: {exc}",
            0,
            result.stderr,
        ) from exc

    # Return mapping of game_name -> backup_dir
    result_mapping: dict[str, Path] = {}
    for game_name in game_names:
        result_mapping[game_name] = output_dir / game_name

    return result_mapping
