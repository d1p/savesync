from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml

from savesync_bridge.core.exceptions import SyncError
from savesync_bridge.core.path_translator import (
    windows_absolute_to_wine_prefix,
    wine_prefix_absolute_to_windows,
)
from savesync_bridge.models.game import Platform

type OriginalPathInfo = tuple[str, tuple[str, ...]]


def _normalize(path: str) -> str:
    return path.replace("\\", "/")


def _split_drive(path: str) -> tuple[str, str]:
    path = _normalize(path)
    if len(path) >= 2 and path[1] == ":":
        drive = path[:2]
        remainder = path[2:].lstrip("/")
        return drive, remainder
    return "", path.lstrip("/")


def _drive_folder_name(drive: str) -> str:
    if not drive:
        return "drive-0"
    return f"drive-{drive.replace(':', '')}"


def _locate_backup_root(backup_dir: Path) -> Path:
    direct = backup_dir / "mapping.yaml"
    if direct.exists():
        return backup_dir

    candidates = list(backup_dir.glob("*/mapping.yaml"))
    if len(candidates) == 1:
        return candidates[0].parent

    return backup_dir


def _stored_path_to_original(rel_path: Path, drives: Mapping[str, str]) -> OriginalPathInfo | None:
    parts = rel_path.parts
    drive_index = next((idx for idx, part in enumerate(parts) if part.startswith("drive-")), None)
    if drive_index is None:
        return None

    drive_folder = parts[drive_index]
    drive_root = drives.get(drive_folder)
    if drive_root is None:
        return None

    suffix = "/".join(parts[drive_index + 1 :])
    if drive_root:
        original = f"{drive_root}/{suffix}" if suffix else drive_root
    else:
        original = f"/{suffix}" if suffix else "/"
    return _normalize(original), parts[:drive_index]


def _original_to_stored_path(original_path: str, prefix: tuple[str, ...]) -> Path:
    drive, remainder = _split_drive(original_path)
    parts = [*prefix, _drive_folder_name(drive)]
    if remainder:
        parts.extend(part for part in remainder.split("/") if part)
    return Path(*parts)


def _iter_stored_files(backup_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(backup_root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in {"mapping.yaml", "registry.yaml"} and path.parent == backup_root:
            continue
        rel_path = path.relative_to(backup_root)
        if any(part.startswith("drive-") for part in rel_path.parts):
            files.append(rel_path)
    return files


def _rewrite_files(
    backup_root: Path,
    drives: Mapping[str, str],
    translate: Callable[[str], str],
) -> bool:
    moves: list[tuple[Path, Path]] = []
    for rel_path in _iter_stored_files(backup_root):
        original = _stored_path_to_original(rel_path, drives)
        if original is None:
            continue

        source_path, prefix = original
        target_path = _normalize(translate(source_path))
        target_rel_path = _original_to_stored_path(target_path, prefix)
        if target_rel_path != rel_path:
            moves.append((rel_path, target_rel_path))

    if not moves:
        return False

    temp_root = backup_root / ".savesync-rewrite"
    staged: list[tuple[Path, Path]] = []

    for index, (src_rel, dst_rel) in enumerate(moves):
        temp_path = temp_root / str(index)
        source = backup_root / src_rel
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        source.replace(temp_path)
        staged.append((temp_path, backup_root / dst_rel))

    for temp_path, destination in staged:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            destination.unlink()
        temp_path.replace(destination)

    shutil.rmtree(temp_root, ignore_errors=True)
    return True


def _rewrite_file_map(
    file_map: dict[str, Any] | None,
    translate: Callable[[str], str],
) -> dict[str, Any]:
    if not file_map:
        return {}

    updated: dict[str, Any] = {}
    for original_path, metadata in file_map.items():
        updated[_normalize(translate(original_path))] = metadata
    return updated


def _iter_mapping_paths(mapping: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []
    for backup in mapping.get("backups", []):
        paths.extend((backup.get("files") or {}).keys())
        for child in backup.get("children", []):
            paths.extend((child.get("files") or {}).keys())
    return paths


def _rewrite_mapping(mapping: dict[str, Any], translate: Callable[[str], str]) -> None:
    for backup in mapping.get("backups", []):
        backup["files"] = _rewrite_file_map(backup.get("files"), translate)
        for child in backup.get("children", []):
            child["files"] = _rewrite_file_map(child.get("files"), translate)


def _rebuild_drives(mapping: Mapping[str, Any], fallback: Mapping[str, str]) -> dict[str, str]:
    drives: dict[str, str] = {}
    for original_path in _iter_mapping_paths(mapping):
        drive, _ = _split_drive(original_path)
        folder = _drive_folder_name(drive)
        drives.setdefault(folder, drive)
    return drives or dict(fallback)


def _remove_empty_dirs(backup_root: Path) -> None:
    for path in sorted(backup_root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if not path.is_dir():
            continue
        try:
            path.rmdir()
        except OSError:
            continue


def _build_translator(
    from_platform: Platform,
    to_platform: Platform,
    *,
    target_wine_prefix: str | None,
    target_wine_user: str | None,
    env: Mapping[str, str] | None,
) -> Callable[[str], str] | None:
    if from_platform == to_platform:
        return None

    if from_platform == Platform.WINDOWS and to_platform in (Platform.LINUX, Platform.STEAM_DECK):
        if not target_wine_prefix:
            raise SyncError(
                "A Wine or Proton prefix is required to restore a Windows save on this machine"
            )
        return lambda path: windows_absolute_to_wine_prefix(
            path,
            target_wine_prefix,
            wine_user=target_wine_user,
        )

    if from_platform in (Platform.LINUX, Platform.STEAM_DECK) and to_platform == Platform.WINDOWS:
        return lambda path: wine_prefix_absolute_to_windows(path, env=env)

    return None


def convert_simple_backup_for_restore(
    backup_dir: Path,
    from_platform: Platform,
    to_platform: Platform,
    *,
    target_wine_prefix: str | None = None,
    target_wine_user: str | None = None,
    target_proton_prefix: str | None = None,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Rewrite a Ludusavi simple backup so it matches the target restore platform."""
    resolved_wine_prefix = target_wine_prefix or target_proton_prefix
    translate = _build_translator(
        from_platform,
        to_platform,
        target_wine_prefix=resolved_wine_prefix,
        target_wine_user=target_wine_user,
        env=env,
    )
    if translate is None:
        return False

    backup_root = _locate_backup_root(backup_dir)
    mapping_path = backup_root / "mapping.yaml"
    if not mapping_path.exists():
        return False

    mapping = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) or {}
    drives = {str(key): str(value) for key, value in (mapping.get("drives") or {}).items()}
    if not drives:
        return False

    files_changed = _rewrite_files(backup_root, drives, translate)
    _rewrite_mapping(mapping, translate)
    mapping["drives"] = _rebuild_drives(mapping, drives)
    mapping_path.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")
    if files_changed:
        _remove_empty_dirs(backup_root)
    return True
