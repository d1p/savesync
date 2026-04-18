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
    """Complete game manifest with all metadata for fast comparison and restore.
    
    IMPORTANT: The `game_id` field contains the ORIGINAL, unmodified Ludusavi game identifier,
    even if the game name contains special characters like colons. This is used to:
    - Map back to the actual game when displaying UI
    - Call ludusavi.restore_game() with the correct game identifier
    - Track sync history per actual game
    
    Temporary filesystem paths may use sanitized versions of game_id (colons → underscores),
    but this manifest always preserves the original.
    
    Combined manifest design:
    - All metadata needed for status checks (hash comparison) is here
    - All metadata needed for detailed diffs is here
    - Only the actual save.tar.gz is downloaded separately when pulling
    """
    game_id: str  # Original Ludusavi game identifier (e.g., "Mafia: Definitive Edition")
    host: Platform
    timestamp: datetime
    hash: str
    files: tuple[SaveFile, ...]
    machine_id: str = ""  # identifies the originating machine
    compressed: bool = False  # whether save archive is compressed (tar.gz)
    archive_name: str = "save.tar.gz"  # name of the save archive file
    total_size: int = 0  # total size of compressed archive (0 if uncompressed)


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
