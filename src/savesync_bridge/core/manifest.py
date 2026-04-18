from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from savesync_bridge.models.game import GameManifest, Platform, SaveFile, SyncMeta, SyncStatus

LineageRecommendation = Literal["local", "cloud"]

_IGNORED_MANIFEST_FILES = {"mapping.yaml", "registry.yaml"}


def _is_ignored_manifest_file(path: str) -> bool:
    return Path(path).name in _IGNORED_MANIFEST_FILES


def _filter_manifest_files(files: tuple[SaveFile, ...]) -> tuple[SaveFile, ...]:
    return tuple(f for f in files if not _is_ignored_manifest_file(f.path))


def _manifest_without_ignored_files(manifest: GameManifest) -> GameManifest:
    filtered_files = _filter_manifest_files(manifest.files)
    if len(filtered_files) == len(manifest.files):
        return manifest
    return GameManifest(
        game_id=manifest.game_id,
        host=manifest.host,
        timestamp=manifest.timestamp,
        hash=manifest.hash,
        files=filtered_files,
        machine_id=manifest.machine_id,
    )


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
        "machine_id": manifest.machine_id,
        "files": [
            {
                "path": f.path,
                "size": f.size,
                "modified": f.modified.isoformat(),
                "created": f.created.isoformat() if f.created is not None else None,
                "file_hash": f.file_hash,
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
            created=(
                datetime.fromisoformat(f["created"])
                if f.get("created") is not None
                else None
            ),
            file_hash=f.get("file_hash"),
        )
        for f in obj["files"]
    )
    return GameManifest(
        game_id=obj["game_id"],
        host=Platform(obj["host"]),
        timestamp=datetime.fromisoformat(obj["timestamp"]),
        hash=obj["hash"],
        files=files,
        machine_id=obj.get("machine_id", ""),
    )


def compare(local: GameManifest, cloud: GameManifest, runner_machine_id: str | None = None) -> SyncStatus:
    """Compare a local and cloud manifest to determine sync status.

    Args:
        local: Manifest from the local machine.
        cloud: Manifest from cloud storage.
        runner_machine_id: The current runner/machine ID. If provided and matches local's
            machine_id, and local.timestamp > cloud.timestamp, returns LOCAL_NEWER to skip
            conflict resolution.

    Returns:
        - :attr:`~SyncStatus.SYNCED` — hashes match; no action needed.
        - :attr:`~SyncStatus.LOCAL_NEWER` — local timestamp is newer and originated from same machine.
        - :attr:`~SyncStatus.CONFLICT` — hashes differ, so the saves contain
          different content and require user review.

    Note:
        Timestamp ordering alone is not safe for game saves because a fresh
        start or launcher touch can produce a newer file with less progress.
        Until the engine stores an explicit common base for three-way merge
        semantics, differing hashes are treated conservatively as conflicts.
        However, if per-file content hashes are available and all files have
        identical content (only metadata differs), treat as synced.
        
        The machine_id check optimizes the common case where the same machine
        has been actively playing: if the local version originated from the
        current machine and is newer, we can trust the local version without
        needing complex conflict resolution.
    """
    local = _manifest_without_ignored_files(local)
    cloud = _manifest_without_ignored_files(cloud)

    if local.hash == cloud.hash:
        return SyncStatus.SYNCED

    # Smart machine ID check: if this is the same machine that created the local
    # save and it's newer than cloud, just push without conflict resolution
    if (
        runner_machine_id
        and local.machine_id
        and runner_machine_id.lower() == local.machine_id.lower()
        and local.timestamp > cloud.timestamp
    ):
        return SyncStatus.LOCAL_NEWER

    diff = diff_manifests(local, cloud)
    if (
        diff.total_files > 0
        and diff.unchanged_count == diff.total_files
        and all(f.file_hash is not None for f in local.files)
        and all(f.file_hash is not None for f in cloud.files)
    ):
        return SyncStatus.SYNCED

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
        "machine_id": meta.machine_id,
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
        machine_id=obj.get("machine_id", ""),
    )


def compare_meta(local: GameManifest, cloud_meta: SyncMeta, runner_machine_id: str | None = None) -> SyncStatus:
    """Compare a local manifest with a lightweight cloud SyncMeta.
    
    Args:
        local: Local game manifest.
        cloud_meta: Lightweight cloud metadata.
        runner_machine_id: The current runner/machine ID. If provided and matches local's
            machine_id, and local.timestamp > cloud_meta.timestamp, returns LOCAL_NEWER to skip
            conflict resolution.
    
    Returns:
        - :attr:`~SyncStatus.SYNCED` — hashes match.
        - :attr:`~SyncStatus.LOCAL_NEWER` — local timestamp is newer and originated from same machine.
        - :attr:`~SyncStatus.CONFLICT` — hashes differ.
    """
    if local.hash == cloud_meta.hash:
        return SyncStatus.SYNCED
    
    # Smart machine ID check: if this is the same machine that created the local
    # save and it's newer than cloud, just push without conflict resolution
    if (
        runner_machine_id
        and local.machine_id
        and runner_machine_id.lower() == local.machine_id.lower()
        and local.timestamp > cloud_meta.timestamp
    ):
        return SyncStatus.LOCAL_NEWER
    
    return SyncStatus.CONFLICT


def oldest_known_created(manifest: GameManifest) -> datetime | None:
    """Return the earliest creation timestamp known for a manifest.

    Falls back to the earliest modification time when creation times are not
    available from the host filesystem.
    """
    manifest = _manifest_without_ignored_files(manifest)
    created_values = [f.created for f in manifest.files if f.created is not None]
    if created_values:
        return min(created_values)
    if manifest.files:
        return min(f.modified for f in manifest.files)
    return None


def latest_modified(manifest: GameManifest) -> datetime | None:
    """Return the most recent file modification time in a manifest."""
    manifest = _manifest_without_ignored_files(manifest)
    if not manifest.files:
        return None
    return max(f.modified for f in manifest.files)


def recommend_lineage(
    local_manifest: GameManifest,
    cloud_manifest: GameManifest,
) -> LineageRecommendation | None:
    """Recommend which side appears to be the older-established save lineage."""
    local_manifest = _manifest_without_ignored_files(local_manifest)
    cloud_manifest = _manifest_without_ignored_files(cloud_manifest)
    local_created = oldest_known_created(local_manifest)
    cloud_created = oldest_known_created(cloud_manifest)
    local_modified = latest_modified(local_manifest)
    cloud_modified = latest_modified(cloud_manifest)

    if local_created is None or cloud_created is None:
        return None

    if local_created < cloud_created and (
        local_modified is None or cloud_modified is None or local_modified >= cloud_modified
    ):
        return "local"

    if cloud_created < local_created and (
        local_modified is None or cloud_modified is None or cloud_modified >= local_modified
    ):
        return "cloud"

    return None


# ---------------------------------------------------------------------------
# Per-file diff
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileDiffEntry:
    """One file's diff status between local and cloud manifests."""

    path: str
    status: str  # "unchanged", "modified", "added_local", "added_cloud", "removed_local", "removed_cloud"
    local_file: SaveFile | None = None
    cloud_file: SaveFile | None = None


@dataclass(frozen=True)
class ManifestDiff:
    """Result of comparing two manifests at the per-file level."""

    entries: tuple[FileDiffEntry, ...]
    unchanged_count: int
    modified_count: int
    added_local_count: int  # files only on local side
    added_cloud_count: int  # files only on cloud side
    total_files: int  # union of both sides


def diff_manifests(
    local_manifest: GameManifest,
    cloud_manifest: GameManifest,
) -> ManifestDiff:
    """Compare two manifests file-by-file using per-file content hashes.

    When per-file hashes are available, uses them to determine if file content
    is identical even when metadata (size/timestamps) may differ.  Falls back
    to size comparison when hashes are absent.
    """
    local_manifest = _manifest_without_ignored_files(local_manifest)
    cloud_manifest = _manifest_without_ignored_files(cloud_manifest)

    local_by_path = {f.path: f for f in local_manifest.files}
    cloud_by_path = {f.path: f for f in cloud_manifest.files}
    all_paths = sorted(set(local_by_path) | set(cloud_by_path))

    entries: list[FileDiffEntry] = []
    unchanged = modified = added_local = added_cloud = 0

    for path in all_paths:
        local_f = local_by_path.get(path)
        cloud_f = cloud_by_path.get(path)

        if local_f is not None and cloud_f is not None:
            # Both sides have this file — check content
            if local_f.file_hash and cloud_f.file_hash:
                same = local_f.file_hash == cloud_f.file_hash
            else:
                # Fallback: compare size as rough proxy
                same = local_f.size == cloud_f.size
            if same:
                entries.append(FileDiffEntry(path, "unchanged", local_f, cloud_f))
                unchanged += 1
            else:
                entries.append(FileDiffEntry(path, "modified", local_f, cloud_f))
                modified += 1
        elif local_f is not None:
            entries.append(FileDiffEntry(path, "added_local", local_f, None))
            added_local += 1
        else:
            entries.append(FileDiffEntry(path, "added_cloud", None, cloud_f))
            added_cloud += 1

    total = len(all_paths)
    return ManifestDiff(
        entries=tuple(entries),
        unchanged_count=unchanged,
        modified_count=modified,
        added_local_count=added_local,
        added_cloud_count=added_cloud,
        total_files=total,
    )


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

# Threshold above which automatic sync is considered safe.
AUTO_SYNC_CONFIDENCE_THRESHOLD = 0.85


@dataclass(frozen=True)
class ConfidenceResult:
    """Result of a confidence assessment for a sync decision."""

    score: float  # 0.0 – 1.0
    recommendation: LineageRecommendation | None
    reasons: tuple[str, ...]
    safe_to_auto_sync: bool

    @property
    def label(self) -> str:
        if self.score >= 0.85:
            return "High"
        if self.score >= 0.55:
            return "Medium"
        return "Low"


def compute_confidence(
    local_manifest: GameManifest,
    cloud_manifest: GameManifest,
    *,
    local_dir_oldest_created: datetime | None = None,
    local_dir_newest_modified: datetime | None = None,
    local_dir_file_count: int | None = None,
) -> ConfidenceResult:
    """Compute a confidence score for recommending which side to keep.

    The score is built from multiple independent signals.  Each signal
    contributes a weighted factor.  When combined they produce a 0-1 score
    that indicates how confident we are in the recommendation.

    Extra ``local_dir_*`` parameters come from scanning ALL files in the
    save directory (not just the Ludusavi-mapped subset).  They strengthen
    or weaken the signal from the manifest-level heuristics.

    Returns a :class:`ConfidenceResult` with the computed score, recommendation,
    human-readable reasons, and whether automatic sync is safe.
    """
    reasons: list[str] = []
    weights: list[tuple[float, float]] = []  # (weight, value 0-1)

    recommendation = recommend_lineage(local_manifest, cloud_manifest)

    local_created = oldest_known_created(local_manifest)
    cloud_created = oldest_known_created(cloud_manifest)
    local_modified = latest_modified(local_manifest)
    cloud_modified = latest_modified(cloud_manifest)
    diff = diff_manifests(local_manifest, cloud_manifest)

    # --- Signal 1: Creation date gap (weight 0.25) ---
    local_manifest = _manifest_without_ignored_files(local_manifest)
    cloud_manifest = _manifest_without_ignored_files(cloud_manifest)

    if local_created is not None and cloud_created is not None:
        gap = abs((local_created - cloud_created).total_seconds())
        if gap > 86400 * 7:  # >7 days apart → very clear
            weights.append((0.25, 1.0))
            reasons.append(f"Creation dates differ by {gap / 86400:.0f} days")
        elif gap > 86400:  # >1 day
            weights.append((0.25, 0.8))
            reasons.append(f"Creation dates differ by {gap / 3600:.0f} hours")
        elif gap > 3600:  # >1 hour
            weights.append((0.25, 0.5))
            reasons.append(f"Creation dates differ by {gap / 60:.0f} minutes")
        else:
            weights.append((0.25, 0.1))
            reasons.append("Creation dates are very close — ambiguous")
    else:
        weights.append((0.25, 0.0))
        reasons.append("Missing creation date info — cannot compare origins")

    # --- Signal 2: Unchanged save files despite manifest/hash differences (weight 0.20) ---
    if diff.total_files > 0 and diff.unchanged_count == diff.total_files:
        weights.append((0.20, 1.0))
        reasons.append(
            "All tracked save files are unchanged; remaining differences appear limited to metadata."
        )
    else:
        weights.append((0.20, 0.0))

    # --- Signal 3: Modification recency agreement (weight 0.20) ---
    if local_modified is not None and cloud_modified is not None and recommendation is not None:
        newer_is_recommended = (
            (recommendation == "local" and local_modified >= cloud_modified)
            or (recommendation == "cloud" and cloud_modified >= local_modified)
        )
        if newer_is_recommended:
            weights.append((0.20, 1.0))
            reasons.append("Most-recently-modified side matches recommended lineage")
        else:
            weights.append((0.20, 0.3))
            reasons.append("Most-recently-modified side contradicts lineage recommendation")
    else:
        weights.append((0.20, 0.0))

    # --- Signal 4: Per-file content match ratio (weight 0.15) ---
    diff = diff_manifests(local_manifest, cloud_manifest)
    if diff.total_files > 0:
        unchanged_ratio = diff.unchanged_count / diff.total_files
        if unchanged_ratio >= 0.8:
            weights.append((0.15, 0.9))
            reasons.append(
                f"{diff.unchanged_count}/{diff.total_files} files have identical content"
            )
        elif unchanged_ratio >= 0.5:
            weights.append((0.15, 0.6))
            reasons.append(
                f"{diff.unchanged_count}/{diff.total_files} files have identical content"
            )
        else:
            weights.append((0.15, 0.3))
            reasons.append(
                f"Only {diff.unchanged_count}/{diff.total_files} files match — significant divergence"
            )
    else:
        weights.append((0.15, 0.0))

    # --- Signal 4: File count similarity (weight 0.10) ---
    local_count = len(local_manifest.files)
    cloud_count = len(cloud_manifest.files)
    if local_count > 0 and cloud_count > 0:
        ratio = min(local_count, cloud_count) / max(local_count, cloud_count)
        if ratio >= 0.8:
            weights.append((0.10, 0.9))
            reasons.append(f"File counts similar ({local_count} local vs {cloud_count} cloud)")
        elif ratio >= 0.5:
            weights.append((0.10, 0.5))
            reasons.append(f"File counts differ ({local_count} local vs {cloud_count} cloud)")
        else:
            weights.append((0.10, 0.2))
            reasons.append(f"File counts very different ({local_count} local vs {cloud_count} cloud)")
    else:
        weights.append((0.10, 0.0))
        reasons.append("One or both sides have no files")

    # --- Signal 5: Size similarity (weight 0.10) ---
    local_size = sum(f.size for f in local_manifest.files)
    cloud_size = sum(f.size for f in cloud_manifest.files)
    if local_size > 0 and cloud_size > 0:
        size_ratio = min(local_size, cloud_size) / max(local_size, cloud_size)
        if size_ratio >= 0.8:
            weights.append((0.10, 0.9))
        elif size_ratio >= 0.5:
            weights.append((0.10, 0.5))
        else:
            weights.append((0.10, 0.2))
            reasons.append("Save sizes differ significantly — possible data loss risk")
    else:
        weights.append((0.10, 0.0))

    # --- Signal 6: Directory-level creation date corroboration (weight 0.20) ---
    if local_dir_oldest_created is not None and cloud_created is not None and recommendation is not None:
        if recommendation == "local":
            if local_dir_oldest_created < cloud_created:
                weights.append((0.20, 1.0))
                reasons.append("Full directory scan confirms local files predate cloud")
            else:
                weights.append((0.20, 0.2))
                reasons.append("Directory scan does NOT confirm local is the older lineage")
        elif recommendation == "cloud":
            if local_dir_oldest_created > cloud_created:
                weights.append((0.20, 0.9))
                reasons.append("Full directory scan confirms local files are newer than cloud origin")
            else:
                weights.append((0.20, 0.3))
                reasons.append("Directory scan partially contradicts cloud lineage recommendation")
    elif local_dir_oldest_created is not None:
        weights.append((0.20, 0.3))
        reasons.append("Directory scan available but no cloud creation date to compare")
    else:
        weights.append((0.20, 0.0))
        if local_dir_file_count is None:
            reasons.append("No directory scan data available")

    # Compute weighted score
    total_weight = sum(w for w, _ in weights)
    if total_weight > 0:
        score = sum(w * v for w, v in weights) / total_weight
    else:
        score = 0.0

    # If no recommendation at all, score is capped low unless all files are unchanged.
    if recommendation is None:
        if diff.total_files == 0 or diff.unchanged_count != diff.total_files:
            score = min(score, 0.3)
            reasons.append("No clear lineage recommendation — manual review required")

    score = round(min(max(score, 0.0), 1.0), 2)
    safe = score >= AUTO_SYNC_CONFIDENCE_THRESHOLD and recommendation is not None

    return ConfidenceResult(
        score=score,
        recommendation=recommendation,
        reasons=tuple(reasons),
        safe_to_auto_sync=safe,
    )


# ---------------------------------------------------------------------------
# Sync history
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SyncHistoryEntry:
    """A single entry in the sync activity log."""

    timestamp: str  # ISO format
    game_id: str
    action: str  # "push", "pull", "auto_push", "auto_pull", "conflict_resolved"
    machine_id: str = ""
    confidence: float | None = None
    error: str | None = None


def _history_file(state_dir: Path) -> Path:
    return state_dir / "sync_history.json"


def load_sync_history(state_dir: Path, limit: int = 200) -> list[SyncHistoryEntry]:
    """Load the most recent *limit* sync history entries."""
    path = _history_file(state_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = [
            SyncHistoryEntry(
                timestamp=e["timestamp"],
                game_id=e["game_id"],
                action=e["action"],
                machine_id=e.get("machine_id", ""),
                confidence=e.get("confidence"),
                error=e.get("error"),
            )
            for e in data[-limit:]
        ]
        return entries
    except (json.JSONDecodeError, KeyError):
        return []


def append_sync_history(
    state_dir: Path,
    entry: SyncHistoryEntry,
    max_entries: int = 500,
) -> None:
    """Append a history entry, keeping at most *max_entries*."""
    path = _history_file(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    entries: list[dict] = []
    if path.exists():
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            entries = []

    entries.append({
        "timestamp": entry.timestamp,
        "game_id": entry.game_id,
        "action": entry.action,
        "machine_id": entry.machine_id,
        "confidence": entry.confidence,
        "error": entry.error,
    })

    # Trim old entries
    if len(entries) > max_entries:
        entries = entries[-max_entries:]

    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
