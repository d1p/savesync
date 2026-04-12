from __future__ import annotations

import json
from datetime import datetime

from savesync_bridge.models.game import GameManifest, Platform, SaveFile, SyncMeta, SyncStatus


def to_json(manifest: GameManifest) -> str:
    """Serialise a GameManifest to a JSON string.

    Args:
        manifest: The manifest to serialise.

    Returns:
        Pretty-printed JSON string.
    """
    data: dict = {
        "game_id": manifest.game_id,
        "host": manifest.host.value,
        "timestamp": manifest.timestamp.isoformat(),
        "hash": manifest.hash,
        "files": [
            {
                "path": f.path,
                "size": f.size,
                "modified": f.modified.isoformat(),
            }
            for f in manifest.files
        ],
    }
    return json.dumps(data, indent=2)


def from_json(data: str) -> GameManifest:
    """Deserialise a GameManifest from a JSON string.

    Args:
        data: JSON string produced by :func:`to_json`.

    Returns:
        Reconstructed :class:`~savesync_bridge.models.game.GameManifest`.

    Raises:
        json.JSONDecodeError: If ``data`` is not valid JSON.
        KeyError: If required fields are missing.
        ValueError: If enum values or datetime strings are invalid.
    """
    obj = json.loads(data)
    files = tuple(
        SaveFile(
            path=f["path"],
            size=f["size"],
            modified=datetime.fromisoformat(f["modified"]),
        )
        for f in obj["files"]
    )
    return GameManifest(
        game_id=obj["game_id"],
        host=Platform(obj["host"]),
        timestamp=datetime.fromisoformat(obj["timestamp"]),
        hash=obj["hash"],
        files=files,
    )


def compare(local: GameManifest, cloud: GameManifest) -> SyncStatus:
    """Compare a local and cloud manifest to determine sync status.

    Args:
        local: Manifest from the local machine.
        cloud: Manifest from cloud storage.

    Returns:
        - :attr:`~SyncStatus.SYNCED` — hashes match; no action needed.
        - :attr:`~SyncStatus.LOCAL_NEWER` — local timestamp is ahead of cloud.
        - :attr:`~SyncStatus.CLOUD_NEWER` — cloud timestamp is ahead of local.
        - :attr:`~SyncStatus.CONFLICT` — timestamps are equal but hashes differ,
          indicating independent modifications.

    Note:
        Full three-way conflict detection (e.g. both sides modified since last
        common base) is handled at the sync-engine level and requires a stored
        base hash.
    """
    if local.hash == cloud.hash:
        return SyncStatus.SYNCED
    if local.timestamp > cloud.timestamp:
        return SyncStatus.LOCAL_NEWER
    if cloud.timestamp > local.timestamp:
        return SyncStatus.CLOUD_NEWER
    # Equal timestamps but different hashes — independent modification
    return SyncStatus.CONFLICT


# ---------------------------------------------------------------------------
# SyncMeta — lightweight metadata for quick cloud checks
# ---------------------------------------------------------------------------


def sync_meta_to_json(meta: SyncMeta) -> str:
    """Serialise a SyncMeta to a JSON string."""
    data: dict = {
        "version": 2,
        "game_id": meta.game_id,
        "hash": meta.hash,
        "timestamp": meta.timestamp.isoformat(),
        "compressed": meta.compressed,
        "archive_name": meta.archive_name,
        "total_size": meta.total_size,
    }
    return json.dumps(data, indent=2)


def sync_meta_from_json(data: str) -> SyncMeta:
    """Deserialise a SyncMeta from a JSON string."""
    obj = json.loads(data)
    return SyncMeta(
        game_id=obj["game_id"],
        hash=obj["hash"],
        timestamp=datetime.fromisoformat(obj["timestamp"]),
        compressed=obj.get("compressed", False),
        archive_name=obj.get("archive_name", ""),
        total_size=obj.get("total_size", 0),
    )


def compare_meta(local: GameManifest, cloud_meta: SyncMeta) -> SyncStatus:
    """Compare a local manifest with a lightweight cloud SyncMeta."""
    if local.hash == cloud_meta.hash:
        return SyncStatus.SYNCED
    if local.timestamp > cloud_meta.timestamp:
        return SyncStatus.LOCAL_NEWER
    if cloud_meta.timestamp > local.timestamp:
        return SyncStatus.CLOUD_NEWER
    return SyncStatus.CONFLICT
