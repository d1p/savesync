from __future__ import annotations

import atexit
import configparser
import json
import logging
import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from typing import Callable

from savesync_bridge.core.binaries import resolve_rclone
from savesync_bridge.core.exceptions import RcloneError

# ---------------------------------------------------------------------------
# Child-process tracking – kill all rclone children on exit
# ---------------------------------------------------------------------------
_active_processes: list[subprocess.Popen] = []  # type: ignore[type-arg]


def _cleanup_children() -> None:
    """Terminate any still-running rclone child processes."""
    for proc in list(_active_processes):
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except OSError:
            pass
    _active_processes.clear()


atexit.register(_cleanup_children)

# On POSIX, also handle SIGTERM so daemon-style kills clean up children.
if sys.platform != "win32":
    def _sigterm_handler(signum: int, frame: object) -> None:
        _cleanup_children()
        sys.exit(128 + signum)

    signal.signal(signal.SIGTERM, _sigterm_handler)


def _run(
    cmd: list[str],
    *,
    report_cli: bool = True,
    **kwargs,
) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
    """Wrapper around subprocess.run that tracks children and emits on cli_bus.
    
    Ensures UTF-8 encoding on all platforms (especially important on Windows).
    """
    if report_cli:
        try:
            from savesync_bridge.core.cli_bus import cli_bus
            cli_bus.command_run.emit(" ".join(str(c) for c in cmd))
        except Exception:
            pass

    # Translate capture_output + strip check for Popen compatibility.
    popen_kwargs = dict(kwargs)
    popen_kwargs.pop("check", None)
    if popen_kwargs.pop("capture_output", False):
        popen_kwargs.setdefault("stdout", subprocess.PIPE)
        popen_kwargs.setdefault("stderr", subprocess.PIPE)
    
    # Ensure UTF-8 encoding for text mode (critical on Windows)
    if popen_kwargs.get('text'):
        popen_kwargs.setdefault('encoding', 'utf-8')
        popen_kwargs.setdefault('errors', 'replace')

    proc = subprocess.Popen(cmd, **popen_kwargs)
    _active_processes.append(proc)
    try:
        stdout, stderr = proc.communicate()
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    finally:
        try:
            _active_processes.remove(proc)
        except ValueError:
            pass

    result = subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)

    if report_cli:
        try:
            from savesync_bridge.core.cli_bus import cli_bus
            if result.stdout:
                text = result.stdout.decode("utf-8", errors="replace") if isinstance(result.stdout, bytes) else result.stdout
                if text.strip():
                    cli_bus.stdout_line.emit(text.strip())
            if result.stderr:
                text = result.stderr.decode("utf-8", errors="replace") if isinstance(result.stderr, bytes) else result.stderr
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
    report_cli: bool = True,
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
        report_cli=report_cli,
    )


_AUTH_URL_RE = re.compile(r"https?://\S+")


def _invoke_auth(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    binary: Path | None = None,
    config_file: Path | None = None,
    on_auth_url: Callable[[str], None] | None = None,
) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
    """Run an rclone auth command with ``--no-browser``, streaming stderr to
    detect the OAuth URL and forward it via *on_auth_url*."""
    if binary is None:
        binary = resolve_rclone()
    cmd = [str(binary), *_config_args(config_file), "--no-browser", *args]

    try:
        from savesync_bridge.core.cli_bus import cli_bus
        cli_bus.command_run.emit(" ".join(str(c) for c in cmd))
    except Exception:
        pass

    merged = _merged_env(env)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
        errors='replace',
        env=merged,
    )
    _active_processes.append(proc)

    stderr_lines: list[str] = []
    url_emitted = False
    try:
        assert proc.stderr is not None  # for type-checker
        for line in proc.stderr:
            line = line.rstrip("\n")
            stderr_lines.append(line)
            try:
                from savesync_bridge.core.cli_bus import cli_bus
                if line.strip():
                    cli_bus.stderr_line.emit(line.strip())
            except Exception:
                pass
            if not url_emitted and on_auth_url:
                m = _AUTH_URL_RE.search(line)
                if m:
                    on_auth_url(m.group(0))
                    url_emitted = True
        proc.wait()
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    finally:
        try:
            _active_processes.remove(proc)
        except ValueError:
            pass

    stdout = proc.stdout.read() if proc.stdout else ""
    stderr_text = "\n".join(stderr_lines)

    result = subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr_text)
    try:
        from savesync_bridge.core.cli_bus import cli_bus
        if result.stdout and result.stdout.strip():
            cli_bus.stdout_line.emit(result.stdout.strip())
        cli_bus.exit_code.emit(result.returncode)
    except Exception:
        pass
    return result


def has_remote_config(remote: str, config_file: Path | None) -> bool:
    if config_file is None or not config_file.exists():
        return False
    parser = configparser.ConfigParser()
    parser.read(config_file, encoding="utf-8")
    return parser.has_section(remote)


def _find_free_port() -> int:
    """Find a free TCP port on localhost."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


_RCLONE_AUTH_PORT = 53682
_log = logging.getLogger(__name__)


def _free_auth_port() -> None:
    """Kill stale rclone processes holding the OAuth callback port.

    Rclone hardcodes port 53682 for its OAuth redirect server.  On Steam Deck
    (and Flatpak environments in general) a previous auth attempt may leave a
    zombie rclone process bound to that port.  This helper detects and kills it
    so the next auth attempt can succeed.
    """
    import socket

    # Quick check: is the port actually in use?
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", _RCLONE_AUTH_PORT))
            return  # Port is free, nothing to do.
        except OSError:
            pass

    _log.info("Auth port %d is in use, searching for stale rclone processes…", _RCLONE_AUTH_PORT)

    # Try host-level ss via flatpak-spawn (Steam Deck / Flatpak).
    pid = _find_port_owner_flatpak()
    if pid is None:
        # Fallback: try inside the sandbox / native Linux.
        pid = _find_port_owner_proc()

    if pid is None:
        _log.warning(
            "Port %d is occupied but the owning process could not be found.",
            _RCLONE_AUTH_PORT,
        )
        return

    _log.info("Killing stale rclone process (PID %d) on port %d.", pid, _RCLONE_AUTH_PORT)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass  # Already gone.
    except PermissionError:
        # Inside Flatpak we may not be able to kill host processes directly;
        # fall back to flatpak-spawn.
        try:
            subprocess.run(
                ["flatpak-spawn", "--host", "kill", str(pid)],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            _log.warning("Could not kill PID %d – auth may fail.", pid)


def _find_port_owner_flatpak() -> int | None:
    """Use flatpak-spawn + ss on the host to find the PID owning the auth port."""
    try:
        result = subprocess.run(
            ["flatpak-spawn", "--host", "ss", "-tlnp",
             f"sport = :{_RCLONE_AUTH_PORT}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # Example output line:
        # LISTEN 0 4096 127.0.0.1:53682 0.0.0.0:* users:(("rclone",pid=85719,fd=6))
        for line in result.stdout.splitlines():
            if "rclone" in line and f":{_RCLONE_AUTH_PORT}" in line:
                import re
                m = re.search(r"pid=(\d+)", line)
                if m:
                    return int(m.group(1))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _find_port_owner_proc() -> int | None:
    """Parse /proc/net/tcp to find the PID owning the auth port (native Linux)."""
    hex_port = f"{_RCLONE_AUTH_PORT:04X}"
    try:
        with open("/proc/net/tcp", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 10:
                    continue
                local = parts[1]
                if local.endswith(f":{hex_port}") and parts[3] == "0A":  # LISTEN
                    inode = parts[9]
                    return _pid_for_inode(inode)
    except OSError:
        pass
    return None


def _pid_for_inode(inode: str) -> int | None:
    """Walk /proc/*/fd to find the process owning a socket inode."""
    target = f"socket:[{inode}]"
    proc = Path("/proc")
    for pid_dir in proc.iterdir():
        if not pid_dir.name.isdigit():
            continue
        fd_dir = pid_dir / "fd"
        try:
            for fd in fd_dir.iterdir():
                try:
                    if os.readlink(str(fd)) == target:
                        return int(pid_dir.name)
                except OSError:
                    continue
        except (PermissionError, OSError):
            continue
    return None


def configure_google_drive_remote(
    remote: str,
    config_file: Path,
    client_id: str | None = None,
    client_secret: str | None = None,
    env: dict[str, str] | None = None,
    binary: Path | None = None,
    on_auth_url: Callable[[str], None] | None = None,
) -> None:
    """Create or update a Google Drive remote and save its OAuth token."""
    _free_auth_port()
    port = _find_free_port()
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
            "drive.file",
            "config_is_local",
            "true",
            "client_id",
            client_id or "",
            "client_secret",
            client_secret or "",
            "--rc-addr",
            f"127.0.0.1:{port}",
        ]
    )

    result = _invoke_auth(args, env=env, binary=binary, config_file=config_file, on_auth_url=on_auth_url)
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
    on_auth_url: Callable[[str], None] | None = None,
) -> None:
    """Re-run the OAuth flow for an existing Google Drive remote."""
    _free_auth_port()
    result = _invoke_auth(
        ["config", "reconnect", f"{remote}:"],
        env=env,
        binary=binary,
        config_file=config_file,
        on_auth_url=on_auth_url,
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
    report_cli: bool = True,
) -> bytes:
    """Run ``rclone cat <remote-target>`` and return raw stdout bytes.

    Args:
        remote: Name of the rclone remote.
        root: Top-level Drive folder. Leave empty for root-based remotes.
        path: Full object key within the remote.
        env: Extra environment variables merged into the subprocess env.
        binary: Path to the rclone binary. Defaults to ``resolve_rclone()``.
        config_file: Optional rclone config file path containing saved auth.
        report_cli: Whether to emit this probe to the debug CLI event bus.

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
        report_cli=report_cli,
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
        stderr = result.stderr
        stderr_text = (
            stderr.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes)
            else (stderr or "")
        )
        lowered = stderr_text.lower()
        if "directory not found" in lowered or "no such file or directory" in lowered:
            return []
        raise RcloneError(
            f"rclone lsjson failed: {stderr_text}",
            result.returncode,
            stderr_text,
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


def delete_path(
    remote: str,
    root: str,
    path: str,
    env: dict[str, str] | None = None,
    binary: Path | None = None,
    config_file: Path | None = None,
) -> None:
    """Delete a directory (and all contents) from cloud storage via ``rclone purge``.

    Args:
        remote: Name of the rclone remote.
        root: Top-level Drive folder.
        path: Sub-path to delete.
        env: Extra environment variables.
        binary: Path to the rclone binary.
        config_file: Optional rclone config file path.

    Raises:
        RcloneError: If rclone exits with a non-zero code.
    """
    target = _remote_target(remote, root, path)
    result = _invoke(
        ["purge", target],
        env=env,
        binary=binary,
        config_file=config_file,
    )
    if result.returncode != 0:
        raise RcloneError(
            f"rclone purge failed: {result.stderr}",
            result.returncode,
            result.stderr,
        )


def read_files(
    remote: str,
    root: str,
    paths: list[str],
    env: dict[str, str] | None = None,
    binary: Path | None = None,
    config_file: Path | None = None,
    report_cli: bool = True,
) -> dict[str, bytes | None]:
    """Efficiently fetch multiple files from cloud storage.
    
    Reads each file individually but batches them to minimize overhead.
    If a file doesn't exist, that entry in the result dict will be None.

    Args:
        remote: Name of the rclone remote.
        root: Top-level Drive folder.
        paths: List of file paths to read.
        env: Extra environment variables.
        binary: Path to the rclone binary.
        config_file: Optional rclone config file path.
        report_cli: Whether to emit probes to the debug CLI event bus.

    Returns:
        Dictionary mapping path -> bytes (or None if file not found).
    """
    result_map: dict[str, bytes | None] = {}
    for path in paths:
        try:
            result_map[path] = read_file(
                remote,
                root,
                path,
                env=env,
                binary=binary,
                config_file=config_file,
                report_cli=report_cli,
            )
        except RcloneError:
            result_map[path] = None
    return result_map


def upload_files(
    files: dict[str, Path],
    remote: str,
    root: str,
    path: str,
    env: dict[str, str] | None = None,
    binary: Path | None = None,
    config_file: Path | None = None,
) -> None:
    """Upload multiple files to cloud storage in a single rclone operation.
    
    Uses rclone's copy command to upload all files from a directory at once.

    Args:
        files: Dictionary mapping filename -> local Path. Files are uploaded to path/<filename>.
        remote: Name of the rclone remote.
        root: Top-level Drive folder.
        path: Destination path prefix in the remote.
        env: Extra environment variables.
        binary: Path to the rclone binary.
        config_file: Optional rclone config file path.

    Raises:
        RcloneError: If rclone exits with a non-zero code.
    """
    if not files:
        return

    # For now, upload files individually. In future, could batch upload a directory.
    for filename, file_path in files.items():
        upload(
            file_path,
            remote,
            root,
            f"{path}/{filename}",
            env=env,
            binary=binary,
            config_file=config_file,
        )
