from __future__ import annotations

import configparser
import json
import os
import subprocess
from pathlib import Path

from savesync_bridge.core.binaries import resolve_rclone
from savesync_bridge.core.exceptions import RcloneError


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
        stdout = result.stdout
        if stdout:
            text = stdout.decode("utf-8", errors="replace") if isinstance(stdout, bytes) else stdout
            if text.strip():
                cli_bus.stdout_line.emit(text.strip())
        stderr = result.stderr
        if stderr:
            text = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr
            if text.strip():
                cli_bus.stderr_line.emit(text.strip())
        cli_bus.exit_code.emit(result.returncode)
    except Exception:
        pass
    return result


def _merged_env(extra: dict[str, str] | None) -> dict[str, str] | None:
    """Return a copy of os.environ merged with *extra*, or None if no extras."""
    if not extra:
        return None
    merged = dict(os.environ)
    merged.update(extra)
    return merged


def _remote_target(remote: str, bucket: str, prefix: str) -> str:
    parts = [segment.strip("/") for segment in (bucket, prefix) if segment.strip("/")]
    if not parts:
        return f"{remote}:"
    return f"{remote}:{'/'.join(parts)}"


def _config_args(config_file: Path | None) -> list[str]:
    if config_file is None:
        return []
    config_file.parent.mkdir(parents=True, exist_ok=True)
    return ["--config", str(config_file)]


def _invoke(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    binary: Path | None = None,
    config_file: Path | None = None,
    text: bool = True,
) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
    if binary is None:
        binary = resolve_rclone()
    cmd = [str(binary), *_config_args(config_file), *args]
    return _run(
        cmd,
        capture_output=True,
        text=text,
        check=False,
        env=_merged_env(env),
    )


def has_remote_config(remote: str, config_file: Path | None) -> bool:
    if config_file is None or not config_file.exists():
        return False
    parser = configparser.ConfigParser()
    parser.read(config_file, encoding="utf-8")
    return parser.has_section(remote)


def configure_google_drive_remote(
    remote: str,
    config_file: Path,
    client_id: str | None = None,
    client_secret: str | None = None,
    env: dict[str, str] | None = None,
    binary: Path | None = None,
) -> None:
    """Create or update a Google Drive remote and save its OAuth token."""
    args = [
        "config",
        "update" if has_remote_config(remote, config_file) else "create",
        remote,
    ]
    if args[1] == "create":
        args.append("drive")
    args.extend(
        [
            "type",
            "drive",
            "scope",
            "drive",
            "config_is_local",
            "true",
            "client_id",
            client_id or "",
            "client_secret",
            client_secret or "",
        ]
    )

    result = _invoke(args, env=env, binary=binary, config_file=config_file)
    if result.returncode != 0:
        raise RcloneError(
            f"Google Drive authentication failed: {result.stderr}",
            result.returncode,
            result.stderr,
        )


def reconnect_google_drive_remote(
    remote: str,
    config_file: Path,
    env: dict[str, str] | None = None,
    binary: Path | None = None,
) -> None:
    """Re-run the OAuth flow for an existing Google Drive remote."""
    result = _invoke(
        ["config", "reconnect", f"{remote}:"],
        env=env,
        binary=binary,
        config_file=config_file,
    )
    if result.returncode != 0:
        raise RcloneError(
            f"Google Drive reconnect failed: {result.stderr}",
            result.returncode,
            result.stderr,
        )


def delete_remote_config(
    remote: str,
    config_file: Path,
    env: dict[str, str] | None = None,
    binary: Path | None = None,
) -> None:
    """Delete a configured rclone remote and its saved token."""
    if not has_remote_config(remote, config_file):
        return
    result = _invoke(
        ["config", "delete", remote],
        env=env,
        binary=binary,
        config_file=config_file,
    )
    if result.returncode != 0:
        raise RcloneError(
            f"Deleting Google Drive configuration failed: {result.stderr}",
            result.returncode,
            result.stderr,
        )


def verify_google_drive_remote(
    remote: str,
    root: str,
    env: dict[str, str] | None = None,
    binary: Path | None = None,
    config_file: Path | None = None,
) -> None:
    """Verify that the configured Google Drive remote can be listed."""
    result = _invoke(
        ["lsjson", _remote_target(remote, root, "")],
        env=env,
        binary=binary,
        config_file=config_file,
    )
    if result.returncode != 0:
        raise RcloneError(
            f"Google Drive verification failed: {result.stderr}",
            result.returncode,
            result.stderr,
        )


def upload(
    local_path: Path,
    remote: str,
    root: str,
    path: str,
    env: dict[str, str] | None = None,
    binary: Path | None = None,
    config_file: Path | None = None,
) -> None:
    """Run ``rclone copy <local_path> <remote-target>``.

    Args:
        local_path: Local file or directory to upload.
        remote: Name of the rclone remote (e.g. ``"s3remote"``).
        root: Top-level Drive folder. Leave empty for root-based remotes.
        path: Key prefix / sub-path inside the remote.
        env: Extra environment variables merged into the subprocess env.
        binary: Path to the rclone binary. Defaults to ``resolve_rclone()``.
        config_file: Optional rclone config file path containing saved auth.

    Raises:
        RcloneError: If rclone exits with a non-zero code.
    """
    target = _remote_target(remote, root, path)
    result = _invoke(
        ["copy", str(local_path), target],
        env=env,
        binary=binary,
        config_file=config_file,
    )

    if result.returncode != 0:
        raise RcloneError(
            f"rclone copy (upload) failed: {result.stderr}",
            result.returncode,
            result.stderr,
        )


def download(
    remote: str,
    root: str,
    path: str,
    local_path: Path,
    env: dict[str, str] | None = None,
    binary: Path | None = None,
    config_file: Path | None = None,
) -> None:
    """Run ``rclone copy <remote-target> <local_path>``.

    Args:
        remote: Name of the rclone remote.
        root: Top-level Drive folder. Leave empty for root-based remotes.
        path: Key prefix / sub-path inside the remote.
        local_path: Local destination directory.
        env: Extra environment variables merged into the subprocess env.
        binary: Path to the rclone binary. Defaults to ``resolve_rclone()``.
        config_file: Optional rclone config file path containing saved auth.

    Raises:
        RcloneError: If rclone exits with a non-zero code.
    """
    target = _remote_target(remote, root, path)
    result = _invoke(
        ["copy", target, str(local_path)],
        env=env,
        binary=binary,
        config_file=config_file,
    )

    if result.returncode != 0:
        raise RcloneError(
            f"rclone copy (download) failed: {result.stderr}",
            result.returncode,
            result.stderr,
        )


def read_file(
    remote: str,
    root: str,
    path: str,
    env: dict[str, str] | None = None,
    binary: Path | None = None,
    config_file: Path | None = None,
) -> bytes:
    """Run ``rclone cat <remote-target>`` and return raw stdout bytes.

    Args:
        remote: Name of the rclone remote.
        root: Top-level Drive folder. Leave empty for root-based remotes.
        path: Full object key within the remote.
        env: Extra environment variables merged into the subprocess env.
        binary: Path to the rclone binary. Defaults to ``resolve_rclone()``.
        config_file: Optional rclone config file path containing saved auth.

    Returns:
        Raw bytes of the remote file's contents.

    Raises:
        RcloneError: If rclone exits with a non-zero code.
    """
    target = _remote_target(remote, root, path)
    result = _invoke(
        ["cat", target],
        env=env,
        binary=binary,
        config_file=config_file,
        text=False,
    )

    if result.returncode != 0:
        raw = result.stderr
        stderr = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else (raw or "")
        raise RcloneError(
            f"rclone cat failed: {stderr}",
            result.returncode,
            stderr,
        )

    return result.stdout


def list_files(
    remote: str,
    root: str,
    path: str,
    env: dict[str, str] | None = None,
    binary: Path | None = None,
    config_file: Path | None = None,
) -> list[dict]:
    """Run ``rclone lsjson <remote-target>`` and return parsed JSON.

    Args:
        remote: Name of the rclone remote.
        root: Top-level Drive folder. Leave empty for root-based remotes.
        path: Key prefix / sub-path inside the remote.
        env: Extra environment variables merged into the subprocess env.
        binary: Path to the rclone binary. Defaults to ``resolve_rclone()``.
        config_file: Optional rclone config file path containing saved auth.

    Returns:
        List of file-metadata dicts as returned by rclone.

    Raises:
        RcloneError: If rclone exits with a non-zero code or returns invalid JSON.
    """
    target = _remote_target(remote, root, path)
    result = _invoke(
        ["lsjson", target],
        env=env,
        binary=binary,
        config_file=config_file,
    )

    if result.returncode != 0:
        raise RcloneError(
            f"rclone lsjson failed: {result.stderr}",
            result.returncode,
            result.stderr,
        )

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RcloneError(
            f"rclone lsjson returned invalid JSON: {exc}",
            0,
            result.stderr,
        ) from exc


def file_exists(
    remote: str,
    root: str,
    path: str,
    env: dict[str, str] | None = None,
    binary: Path | None = None,
    config_file: Path | None = None,
) -> bool:
    """Return ``True`` if *key* exists in the configured cloud target.

    Args:
        remote: Name of the rclone remote.
        root: Top-level Drive folder. Leave empty for root-based remotes.
        path: Full object key within the remote.
        env: Extra environment variables merged into the subprocess env.
        binary: Path to the rclone binary. Defaults to ``resolve_rclone()``.
        config_file: Optional rclone config file path containing saved auth.

    Returns:
        ``True`` if the object exists, ``False`` otherwise.
    """
    try:
        entries = list_files(
            remote,
            root,
            path,
            env=env,
            binary=binary,
            config_file=config_file,
        )
        return len(entries) > 0
    except RcloneError:
        return False
