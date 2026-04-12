# SaveSync-Bridge Technical Documentation

This document describes the actual implementation in the current codebase, with emphasis on backup flow, sync decisions, replacement behavior, and version comparison.

## Architecture Overview

High-level layers:

- UI layer: PySide6 windows, dialogs, workers
- Orchestration layer: `SyncEngine`
- Tool adapters: `cli/ludusavi.py` and `cli/rclone.py`
- Persistence: config TOML, local manifest cache, remote `manifest.json`

Core modules:

- `src/savesync_bridge/core/sync_engine.py`
- `src/savesync_bridge/core/manifest.py`
- `src/savesync_bridge/cli/ludusavi.py`
- `src/savesync_bridge/cli/rclone.py`
- `src/savesync_bridge/models/game.py`

## Data Model

## `GameManifest`

Each snapshot is represented by:

- `game_id`: Ludusavi game identifier
- `host`: `windows`, `linux`, or `steam_deck`
- `timestamp`: UTC timestamp of when the manifest was created
- `hash`: SHA-256 digest across the staged backup content
- `files`: tuple of `SaveFile`

Each `SaveFile` contains:

- `path`: relative path inside the staged game backup
- `size`: file size in bytes
- `modified`: file modification time from the staged file

## Manifest Serialization

Implemented in `core/manifest.py`.

- `to_json(manifest)` writes pretty-printed JSON
- `from_json(data)` reconstructs `GameManifest`
- `compare(local, cloud)` returns `SyncStatus`

The manifest schema is intentionally small. It stores enough metadata for:

- snapshot equality checks via `hash`
- direction decisions via `timestamp`
- UI display via file counts and sizes

## Backup Logic

Implemented in `SyncEngine.push()`.

Sequence:

1. Create a temporary staging directory.
2. Create a per-game subdirectory inside staging.
3. Run Ludusavi backup for exactly one game into that directory.
4. Walk all staged files recursively.
5. Compute a combined SHA-256 hash across file contents.
6. Build a `GameManifest` with current UTC time.
7. Write `manifest.json` into the staging root.
8. Upload the game directory with rclone.
9. Upload `manifest.json` with rclone.
10. Save the same manifest into the local state cache.

Flow:

```mermaid
flowchart TD
    A[push(game_id)] --> B[TemporaryDirectory]
    B --> C[ludusavi.backup_game]
    C --> D[_build_manifest]
    D --> E[manifest_module.to_json]
    E --> F[rclone.upload game directory]
    F --> G[rclone.upload manifest.json]
    G --> H[_save_local_manifest]
    H --> I[SyncStatus.SYNCED]
```

### Exact Ludusavi command used for push

```text
ludusavi backup --api --force --path <staging_game_dir> <game_name>
```

`--force` is required because Ludusavi may otherwise request interactive confirmation, which breaks non-interactive GUI execution.

### Important implementation detail

The content hash is built from the staged backup files, not from the original live save locations. This is the correct thing to compare because those staged files are exactly what get uploaded.

## Pull Logic

Implemented in `SyncEngine.pull()`.

Sequence:

1. Create a temporary staging directory.
2. Create a per-game subdirectory.
3. Download the cloud snapshot into that directory using rclone.
4. Run Ludusavi restore for that game from the staging directory.
5. Save the cloud manifest into the local state cache.

Flow:

```mermaid
flowchart TD
    A[pull(game_id, manifest)] --> B[TemporaryDirectory]
    B --> C[rclone.download]
    C --> D[ludusavi.restore_game]
    D --> E[_save_local_manifest cloud manifest]
    E --> F[SyncStatus.SYNCED]
```

### Exact Ludusavi command used for pull

```text
ludusavi restore --api --force --path <staging_game_dir> <game_name>
```

## Which Files Get Replaced

This is the key design point.

The current implementation does not resolve replacement at file granularity.

What actually happens:

- `push()` uploads a full staged snapshot for a game
- `pull()` restores a full staged snapshot for a game
- conflict resolution chooses one of those two operations

What does not happen:

- no per-file "newest file wins" rule
- no merge of local and cloud file sets
- no selective restore of a subset of files based on timestamps or hashes

So the replacement unit is the whole game snapshot.

## How “Newer” Is Determined

Implemented in `core/manifest.py::compare()` and used by `SyncEngine.check_status()`.

Decision rules:

1. If hashes are equal, return `SYNCED`.
2. If hashes differ and `local.timestamp > cloud.timestamp`, return `LOCAL_NEWER`.
3. If hashes differ and `cloud.timestamp > local.timestamp`, return `CLOUD_NEWER`.
4. If hashes differ and timestamps are equal, return `CONFLICT`.

Flow:

```mermaid
flowchart TD
    A[compare(local, cloud)] --> B{local.hash == cloud.hash?}
    B -->|Yes| C[SYNCED]
    B -->|No| D{local.timestamp > cloud.timestamp?}
    D -->|Yes| E[LOCAL_NEWER]
    D -->|No| F{cloud.timestamp > local.timestamp?}
    F -->|Yes| G[CLOUD_NEWER]
    F -->|No| H[CONFLICT]
```

### Important nuance

“Newer” is manifest-level, not file-level.

The engine does not compare individual `SaveFile.modified` values to decide the winner. Those per-file timestamps are stored for metadata and display, but the winner is chosen by the top-level manifest timestamp.

## How `check_status()` Works

`SyncEngine.check_status(game_id)` performs a two-source comparison:

- local cached manifest: loaded from the per-game state file
- cloud manifest: downloaded from `<prefix>/<game_id>/manifest.json`

Rules before manifest comparison:

- both missing -> `UNKNOWN`
- cloud missing, local exists -> `LOCAL_NEWER`
- local missing, cloud exists -> `CLOUD_NEWER`

Only when both exist does the engine call `manifest.compare(local, cloud)`.

## How `sync()` Decides What To Do

`SyncEngine.sync(game_id)` is a thin coordinator over `check_status()`.

Rules:

- `SYNCED` -> no-op
- `CONFLICT` -> return conflict; caller must resolve in UI
- `LOCAL_NEWER` -> call `push(game_id)`
- `UNKNOWN` -> also call `push(game_id)`
- `CLOUD_NEWER` -> fetch cloud manifest and call `pull(game_id, manifest)`

Flow:

```mermaid
flowchart TD
    A[sync(game_id)] --> B[check_status]
    B --> C{status}
    C -->|SYNCED| D[Return synced]
    C -->|CONFLICT| E[Return conflict]
    C -->|LOCAL_NEWER| F[push]
    C -->|UNKNOWN| F
    C -->|CLOUD_NEWER| G[get_cloud_manifest]
    G --> H{manifest found?}
    H -->|No| I[Return unknown error]
    H -->|Yes| J[pull]
```

### Why `UNKNOWN` currently pushes

This is a product decision embedded in the current implementation: when the app has no local or cloud metadata to compare, it treats the current machine as the source of truth and creates the first cloud snapshot by pushing.

That behavior is simple, but it is important to document because it means first sync is biased toward upload.

## Conflict Resolution Logic

The engine itself does not resolve conflicts. It reports `SyncStatus.CONFLICT`.

The UI then opens `ConflictDialog` and maps the choice to one of two full operations:

- `KEEP_LOCAL` -> invoke `_on_push_game()`
- `KEEP_CLOUD` -> invoke `_on_pull_game()`
- `KEEP_NEITHER` -> do nothing

This means conflict resolution is still snapshot-level. The dialog helps the user choose a side, but it does not perform a merge.

## Manifest Hash Construction

Implemented in `_build_manifest()`.

Algorithm:

1. Recursively walk every file under the staged game directory.
2. Sort paths deterministically using `sorted(game_dir.rglob("*"))`.
3. For each file:
4. Read the full file bytes.
5. Feed bytes into a single SHA-256 hasher.
6. Record file metadata relative to the staged game directory.

Consequences:

- identical staged content produces the same manifest hash
- the hash is based on file content, not on filenames alone
- the algorithm reads all staged files fully into memory one by one

The code does not currently include file paths in the digest input. In practice, staged backups are still deterministic enough for current use, but this is worth noting if stronger manifest semantics are needed later.

## Local Persistence

### Config

Stored as TOML:

- Windows: `%APPDATA%/savesync-bridge/config.toml`
- Linux / Steam Deck: `$XDG_CONFIG_HOME/savesync-bridge/config.toml` or `~/.config/savesync-bridge/config.toml`

Fields:

- `rclone_remote`
- `s3_bucket`
- `s3_prefix`
- `ludusavi_path`
- `rclone_path`
- `known_games`

### Local state cache

Stored as per-game JSON manifests:

- Windows: `%LOCALAPPDATA%/savesync-bridge/states/<game_id>.json`
- Linux / Steam Deck: `$XDG_DATA_HOME/savesync-bridge/states/<game_id>.json` or `~/.local/share/savesync-bridge/states/<game_id>.json`

These files are not saves. They are comparison metadata.

## Cloud Persistence

Remote layout for each game:

```text
<s3_prefix>/<game_id>/
```

Contents:

- Ludusavi-produced backup files
- `manifest.json`

`manifest.json` is the cloud-side source used by `get_cloud_manifest()` and `check_status()`.

## CLI Adapter Behavior

### Ludusavi adapter

Implemented in `cli/ludusavi.py`.

- `list_games()` -> `backup --preview --api`
- `backup_game()` -> `backup --api --force --path ...`
- `restore_game()` -> `restore --api --force --path ...`

`list_games()` uses preview mode because `manifest show --api` is too broad for this app and can hang while processing the entire global manifest.

### rclone adapter

Implemented in `cli/rclone.py`.

- `upload()` -> `rclone copy <local> <remote>:<bucket>/<prefix>`
- `download()` -> `rclone copy <remote>:<bucket>/<prefix> <local>`
- `read_file()` -> `rclone cat <remote>:<bucket>/<key>`
- `list_files()` -> `rclone lsjson <remote>:<bucket>/<prefix>`

The wrapper can merge extra environment variables into the subprocess environment so credentials loaded from `.env` are inherited by rclone.

## Debug Bus And Console

All CLI wrappers emit best-effort events to `cli_bus`:

- command string
- stdout
- stderr
- exit code

`DebugPanel` subscribes to those events and renders a collapsible execution log in the main window. This is diagnostic only; it does not affect sync decisions.

## Path Translation Module

`core/path_translator.py` contains translation helpers for Windows environment-variable paths and Proton compatdata paths.

Current status:

- available as utility code
- not part of the active push/pull decision pipeline in `SyncEngine`

That distinction matters. The current synchronization logic depends on Ludusavi backup/restore behavior, not on direct path rewriting inside the engine.

## Current Constraints And Risks

## 1. No true three-way merge

The code comments mention that full three-way conflict detection would require a stored base hash. That does not exist yet.

Current behavior is simpler:

- same hash -> synced
- differing hashes + newer timestamp -> choose newer side
- differing hashes + equal timestamp -> conflict

## 2. Snapshot-level replacement only

This is the biggest product constraint. The app replaces one whole snapshot with another.

## 3. Timestamp semantics are app-generated

Manifest timestamps are generated when SaveSync-Bridge writes a manifest, not copied from a cloud provider clock. That is correct for the current design, but it means decision quality depends on when manifests were last written.

## 4. `UNKNOWN` prefers push

First-sync or missing-metadata situations currently resolve toward upload.

## Packaging Notes

The project includes PyInstaller packaging support:

- spec file: `savesync_bridge.spec`
- build command: `uv run build-exe`

The packaged binary includes bundled `ludusavi` and `rclone` executables. `core/binaries.py` detects frozen execution via `sys._MEIPASS` so the app can still locate those tools from inside the packaged bundle.