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
    created: datetime | None = None
    file_hash: str | None = None  # per-file SHA-256 content hash


@dataclass(frozen=True)
class GameManifest:
    game_id: str
    host: Platform
    timestamp: datetime
    hash: str
    files: tuple[SaveFile, ...]
    machine_id: str = ""  # identifies the originating machine


@dataclass(frozen=True)
class SyncMeta:
    """Lightweight metadata for quick cloud status checks without downloading full manifest.
    
    IMPORTANT: The `game_id` field contains the ORIGINAL, unmodified Ludusavi game identifier,
    even if the game name contains special characters like colons. This is used to:
    - Map back to the actual game when displaying UI
    - Call ludusavi.restore_game() with the correct game identifier
    - Track sync history per actual game
    
    Temporary filesystem paths may use sanitized versions of game_id (colons → underscores),
    but this metadata always preserves the original.
    """

    game_id: str  # Original Ludusavi game identifier (e.g., "Mafia: Definitive Edition")
    hash: str
    timestamp: datetime
    compressed: bool = False
    archive_name: str = ""
    total_size: int = 0
    machine_id: str = ""  # identifies the originating machine


@dataclass(frozen=True)
class Game:
    id: str
    name: str
    steam_app_id: str | None = None
    wine_prefix: str | None = None
    wine_user: str | None = None
    save_paths: tuple[str, ...] = ()
    status: SyncStatus = SyncStatus.UNKNOWN
    excluded: bool = False
    local_manifest: GameManifest | None = None
    cloud_manifest: GameManifest | None = None
