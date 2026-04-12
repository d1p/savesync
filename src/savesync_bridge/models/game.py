from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Platform(Enum):
    WINDOWS = "windows"
    LINUX = "linux"
    STEAM_DECK = "steam_deck"


class SyncStatus(Enum):
    SYNCED = "synced"
    LOCAL_NEWER = "local_newer"
    CLOUD_NEWER = "cloud_newer"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SaveFile:
    path: str
    size: int
    modified: datetime


@dataclass(frozen=True)
class GameManifest:
    game_id: str
    host: Platform
    timestamp: datetime
    hash: str
    files: tuple[SaveFile, ...]


@dataclass(frozen=True)
class Game:
    id: str
    name: str
    steam_app_id: str | None = None
    wine_prefix: str | None = None
    wine_user: str | None = None
    save_paths: tuple[str, ...] = ()
    status: SyncStatus = SyncStatus.UNKNOWN
    local_manifest: GameManifest | None = None
    cloud_manifest: GameManifest | None = None
