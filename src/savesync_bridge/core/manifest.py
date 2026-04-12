from __future__ import annotations

import json
from datetime import datetime, timezone

from savesync_bridge.models.game import GameManifest, Platform, SaveFile, SyncStatus


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
