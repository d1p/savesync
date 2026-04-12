from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AppConfig:
    rclone_remote: str = "s3remote"
    s3_bucket: str = ""
    s3_prefix: str = "savesync-bridge"
    ludusavi_path: str | None = None
    rclone_path: str | None = None
    known_games: list[str] = field(default_factory=list)


def _default_config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "savesync-bridge"


def _config_file(config_dir: Path) -> Path:
    return config_dir / "config.toml"


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
        config_dir = _default_config_dir()

    cfg_file = _config_file(config_dir)
    if not cfg_file.exists():
        return AppConfig()

    with cfg_file.open("rb") as fh:
        data = tomllib.load(fh)

    return AppConfig(
        rclone_remote=data.get("rclone_remote", "s3remote"),
        s3_bucket=data.get("s3_bucket", ""),
        s3_prefix=data.get("s3_prefix", "savesync-bridge"),
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
        config_dir = _default_config_dir()

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
        f"rclone_remote = {_toml_str(cfg.rclone_remote)}",
        f"s3_bucket = {_toml_str(cfg.s3_bucket)}",
        f"s3_prefix = {_toml_str(cfg.s3_prefix)}",
    ]
    if cfg.ludusavi_path is not None:
        lines.append(f"ludusavi_path = {_toml_str(cfg.ludusavi_path)}")
    if cfg.rclone_path is not None:
        lines.append(f"rclone_path = {_toml_str(cfg.rclone_path)}")
    lines.append(f"known_games = {_toml_array_of_str(cfg.known_games)}")
    return "\n".join(lines) + "\n"
