from __future__ import annotations

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
    except Exception:  # noqa: BLE001
        pass
    result = subprocess.run(cmd, **kwargs)
    try:
        from savesync_bridge.core.cli_bus import cli_bus  # noqa: F811
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
    except Exception:  # noqa: BLE001
        pass
    return result


def _merged_env(extra: dict[str, str] | None) -> dict[str, str] | None:
    """Return a copy of os.environ merged with *extra*, or None if no extras."""
    if not extra:
        return None
    merged = dict(os.environ)
    merged.update(extra)
    return merged


def upload(
    local_path: Path,
    remote: str,
    bucket: str,
    prefix: str,
    env: dict[str, str] | None = None,
    binary: Path | None = None,
) -> None:
    """Run ``rclone copy <local_path> <remote>:<bucket>/<prefix>``.

    Args:
        local_path: Local file or directory to upload.
        remote: Name of the rclone remote (e.g. ``"s3remote"``).
        bucket: S3 bucket name.
        prefix: Key prefix / sub-path inside the bucket.
        env: Extra environment variables merged into the subprocess env.
        binary: Path to the rclone binary. Defaults to ``resolve_rclone()``.

    Raises:
        RcloneError: If rclone exits with a non-zero code.
    """
    if binary is None:
        binary = resolve_rclone()

    result = _run(
        [str(binary), "copy", str(local_path), f"{remote}:{bucket}/{prefix}"],
        capture_output=True,
        text=True,
        check=False,
        env=_merged_env(env),
    )

    if result.returncode != 0:
        raise RcloneError(
            f"rclone copy (upload) failed: {result.stderr}",
            result.returncode,
            result.stderr,
        )


def download(
    remote: str,
    bucket: str,
    prefix: str,
    local_path: Path,
    env: dict[str, str] | None = None,
    binary: Path | None = None,
) -> None:
    """Run ``rclone copy <remote>:<bucket>/<prefix> <local_path>``.

    Args:
        remote: Name of the rclone remote.
        bucket: S3 bucket name.
        prefix: Key prefix / sub-path inside the bucket.
        local_path: Local destination directory.
        env: Extra environment variables merged into the subprocess env.
        binary: Path to the rclone binary. Defaults to ``resolve_rclone()``.

    Raises:
        RcloneError: If rclone exits with a non-zero code.
    """
    if binary is None:
        binary = resolve_rclone()

    result = _run(
        [str(binary), "copy", f"{remote}:{bucket}/{prefix}", str(local_path)],
        capture_output=True,
        text=True,
        check=False,
        env=_merged_env(env),
    )

    if result.returncode != 0:
        raise RcloneError(
            f"rclone copy (download) failed: {result.stderr}",
            result.returncode,
            result.stderr,
        )


def read_file(
    remote: str,
    bucket: str,
    key: str,
    env: dict[str, str] | None = None,
    binary: Path | None = None,
) -> bytes:
    """Run ``rclone cat <remote>:<bucket>/<key>`` and return raw stdout bytes.

    Args:
        remote: Name of the rclone remote.
        bucket: S3 bucket name.
        key: Full object key within the bucket.
        env: Extra environment variables merged into the subprocess env.
        binary: Path to the rclone binary. Defaults to ``resolve_rclone()``.

    Returns:
        Raw bytes of the remote file's contents.

    Raises:
        RcloneError: If rclone exits with a non-zero code.
    """
    if binary is None:
        binary = resolve_rclone()

    # Use text=False so stdout is returned as raw bytes — needed for binary saves.
    result = _run(
        [str(binary), "cat", f"{remote}:{bucket}/{key}"],
        capture_output=True,
        check=False,
        env=_merged_env(env),
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
    bucket: str,
    prefix: str,
    env: dict[str, str] | None = None,
    binary: Path | None = None,
) -> list[dict]:
    """Run ``rclone lsjson <remote>:<bucket>/<prefix>`` and return parsed JSON.

    Args:
        remote: Name of the rclone remote.
        bucket: S3 bucket name.
        prefix: Key prefix / sub-path inside the bucket.
        env: Extra environment variables merged into the subprocess env.
        binary: Path to the rclone binary. Defaults to ``resolve_rclone()``.

    Returns:
        List of file-metadata dicts as returned by rclone.

    Raises:
        RcloneError: If rclone exits with a non-zero code or returns invalid JSON.
    """
    if binary is None:
        binary = resolve_rclone()

    result = _run(
        [str(binary), "lsjson", f"{remote}:{bucket}/{prefix}"],
        capture_output=True,
        text=True,
        check=False,
        env=_merged_env(env),
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
    bucket: str,
    key: str,
    env: dict[str, str] | None = None,
    binary: Path | None = None,
) -> bool:
    """Return ``True`` if *key* exists in the remote bucket.

    Args:
        remote: Name of the rclone remote.
        bucket: S3 bucket name.
        key: Full object key within the bucket.
        env: Extra environment variables merged into the subprocess env.
        binary: Path to the rclone binary. Defaults to ``resolve_rclone()``.

    Returns:
        ``True`` if the object exists, ``False`` otherwise.
    """
    try:
        entries = list_files(remote, bucket, key, env=env, binary=binary)
        return len(entries) > 0
    except RcloneError:
        return False
