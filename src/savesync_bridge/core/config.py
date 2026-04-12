from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DRIVE_REMOTE = "gdrive"
DEFAULT_BACKUP_PATH = "savesync-bridge"


@dataclass
class AppConfig:
    drive_remote: str = DEFAULT_DRIVE_REMOTE
    drive_root: str = ""
    backup_path: str = DEFAULT_BACKUP_PATH
    drive_client_id: str | None = None
    drive_client_secret: str | None = None
    ludusavi_path: str | None = None
    rclone_path: str | None = None
    known_games: list[str] = field(default_factory=list)


def default_config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "savesync-bridge"


def _config_file(config_dir: Path) -> Path:
    return config_dir / "config.toml"


def rclone_config_path(config_dir: Path | None = None) -> Path:
    if config_dir is None:
        config_dir = default_config_dir()
    return config_dir / "rclone.conf"


def load_config(config_dir: Path | None = None) -> AppConfig:
    """Load application configuration from a TOML file.

    Args:
        config_dir: Directory containing ``config.toml``. Defaults to the
            platform-appropriate config directory.

    Returns:
        Loaded :class:`AppConfig`, or a default instance if the file does not
        exist.
    """
    if config_dir is None:
        config_dir = default_config_dir()

    cfg_file = _config_file(config_dir)
    if not cfg_file.exists():
        return AppConfig()

    with cfg_file.open("rb") as fh:
        data = tomllib.load(fh)

    return AppConfig(
        drive_remote=data.get("drive_remote", data.get("rclone_remote", DEFAULT_DRIVE_REMOTE)),
        drive_root=data.get("drive_root", data.get("s3_bucket", "")),
        backup_path=data.get("backup_path", data.get("s3_prefix", DEFAULT_BACKUP_PATH)),
        drive_client_id=data.get("drive_client_id"),
        drive_client_secret=data.get("drive_client_secret"),
        ludusavi_path=data.get("ludusavi_path"),
        rclone_path=data.get("rclone_path"),
        known_games=list(data.get("known_games", [])),
    )


def save_config(cfg: AppConfig, config_dir: Path | None = None) -> None:
    """Persist application configuration to a TOML file.

    Args:
        cfg: Configuration to save.
        config_dir: Target directory. Defaults to the platform-appropriate
            config directory. Created automatically if absent.
    """
    if config_dir is None:
        config_dir = default_config_dir()

    config_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = _config_file(config_dir)
    cfg_file.write_text(_to_toml(cfg), encoding="utf-8")


# ---------------------------------------------------------------------------
# Minimal TOML serialiser (stdlib tomllib is read-only; no extra dep needed
# for the flat key/value structure used here)
# ---------------------------------------------------------------------------


def _toml_str(value: str) -> str:
    """Wrap *value* in TOML basic-string quotes, escaping as required."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_array_of_str(values: list[str]) -> str:
    return "[" + ", ".join(_toml_str(v) for v in values) + "]"


def _to_toml(cfg: AppConfig) -> str:
    lines: list[str] = [
        f"drive_remote = {_toml_str(cfg.drive_remote)}",
        f"drive_root = {_toml_str(cfg.drive_root)}",
        f"backup_path = {_toml_str(cfg.backup_path)}",
    ]
    if cfg.drive_client_id is not None:
        lines.append(f"drive_client_id = {_toml_str(cfg.drive_client_id)}")
    if cfg.drive_client_secret is not None:
        lines.append(f"drive_client_secret = {_toml_str(cfg.drive_client_secret)}")
    if cfg.ludusavi_path is not None:
        lines.append(f"ludusavi_path = {_toml_str(cfg.ludusavi_path)}")
    if cfg.rclone_path is not None:
        lines.append(f"rclone_path = {_toml_str(cfg.rclone_path)}")
    lines.append(f"known_games = {_toml_array_of_str(cfg.known_games)}")
    return "\n".join(lines) + "\n"
