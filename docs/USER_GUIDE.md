# SaveSync-Bridge User Guide

SaveSync-Bridge is a desktop app for syncing game saves between the current machine and Google Drive by combining Ludusavi, rclone, and a small amount of sync metadata.

The important rule is simple: the app syncs one whole game snapshot at a time. It does not merge individual files inside a save.

## What The Main Window Shows

The current UI is a Sync Center with these main areas:

- `Refresh` rescans games visible to Ludusavi on the current machine
- `Sync All` runs smart sync for every non-excluded game
- each game card shows last sync time, last sync date, file created/modified dates, confidence score, current status, an exclusion checkbox, and one `Sync` button
- the left sidebar filters the list by `All Games`, `Local Newer`, `Conflicts`, `Synced`, and `Excluded`
- the `Backup Destination` panel summarizes the active Google Drive target
- the debug console shows exact CLI commands and output from Ludusavi and rclone

## Status Meanings

Each game ends up in one of these states:

- `Synced`: local and cloud hashes match
- `Local Newer`: local metadata is newer than the cloud copy
- `Cloud Newer`: cloud metadata is newer than the local copy
- `Conflict`: hashes differ and the app cannot safely pick a side automatically
- `Unknown`: the app does not have enough metadata yet, or a sync failed

## Confidence Scoring

When both local and cloud saves exist, the app computes a confidence score (0–100%) that indicates how certain it is about which side to keep.

The score is built from:

- how far apart the oldest file creation dates are
- whether the most-recently-modified side matches the recommended lineage
- how similar the file counts and total sizes are between both sides
- whether a full scan of ALL files in the save directory confirms the recommendation

The confidence label appears on each game card:

- **High** (green, ≥ 85%): the app is confident and will auto-resolve conflicts without asking
- **Medium** (yellow, 55–84%): the app has a suggestion but will always ask before replacing files
- **Low** (red, < 55%): the app is uncertain and will always ask

The conflict dialog shows the full confidence breakdown with individual reasoning bullets so you can make an informed decision.

## File Dates On Game Cards

Each game card now displays:

- **Created**: the oldest known file creation date from your local save files
- **Modified**: the most recent file modification date

These dates come from the actual save files on disk, not from when SaveSync-Bridge last synced.

## Setup

## 1. Connect Google Drive

Open `Backups` from the toolbar or the `Manage Backups` button.

The dialog controls:

- `Drive Remote Name`: rclone remote name, default `gdrive`
- `Drive Folder`: optional top-level folder in Google Drive
- `Backup Library`: folder under that Drive location where SaveSync-Bridge stores game snapshots
- `Google Client ID` and `Google Client Secret`: optional custom OAuth app credentials
- `Ludusavi Binary`: optional override path if you do not want the bundled binary
- `Rclone Binary`: optional override path if you do not want the bundled binary

The dialog actions are:

- `Authenticate Google Drive`: start browser-based sign-in and save the token
- `Check Connection`: verify the saved token and current path
- `Refresh Sign-In`: refresh an expired or revoked token
- `Remove Saved Token`: delete the token for the current remote

Most users do not need a `.env` file. If you created your own Google OAuth desktop app, you can provide its client ID and secret directly in the dialog.

Config storage:

- Windows: `%APPDATA%/savesync-bridge/config.toml`
- Linux or Steam Deck: `~/.config/savesync-bridge/config.toml`

Saved token storage:

- Windows: `%APPDATA%/savesync-bridge/rclone.conf`
- Linux or Steam Deck: `~/.config/savesync-bridge/rclone.conf`

## 2. Refresh Your Local Game List

`Refresh` scans only the current machine. It does not browse Google Drive for game names.

Command used:

```text
ludusavi backup --preview --api
```

Flow:

```mermaid
flowchart TD
    A[Click Refresh] --> B[Run Ludusavi preview scan]
    B --> C[Parse detected games and save paths]
    C --> D[Infer Steam app ID and Wine prefix metadata]
    D --> E[Attach local cached manifests when available]
    E --> F[Render game cards in the Sync Center]
```

## Daily Sync Workflow

The normal workflow is:

1. Refresh the local game list.
2. Review status badges and exclusions.
3. Click `Sync` on one game or `Sync All` for everything not excluded.
4. Resolve conflicts only when the app asks.

## How Smart Sync Works

This is the core flow used by both the per-game `Sync` button and `Sync All`.

```mermaid
flowchart TD
    A[Start sync for one game] --> B[Load local cached manifest]
    B --> C[Try cloud sync_meta.json]
    C --> D{sync_meta.json exists?}
    D -->|Yes| E[Compare local manifest with cloud metadata]
    D -->|No| F[Download cloud manifest.json]
    F --> G[Compare local and cloud manifests]
    E --> H{Result}
    G --> H
    H -->|Synced| I[No action]
    H -->|Local newer| J[Push local snapshot]
    H -->|Cloud newer| K[Pull cloud snapshot]
    H -->|Conflict| L[Open conflict dialog]
    H -->|Unknown| M[Default to push]
    L --> N{Choice}
    N -->|Keep Mine| J
    N -->|Keep Cloud| K
    N -->|Cancel| O[Stop without changes]
```

### Why `Unknown` pushes

If neither side has enough metadata to compare, SaveSync-Bridge currently treats the current machine as the source of truth and creates the first cloud snapshot by uploading it.

## What A Push Actually Does

Push means creating a fresh staged backup on the current machine and uploading that snapshot.

```mermaid
flowchart TD
    A[Run Ludusavi backup for one game] --> B[Stage backup in temp folder]
    B --> C[Hash staged files and build GameManifest]
    C --> D[Compress snapshot into save.tar.gz]
    D --> E[Write manifest.json]
    E --> F[Write sync_meta.json]
    F --> G[Upload archive and metadata with rclone]
    G --> H[Cache manifest locally]
    H --> I[Mark status as synced]
```

Important details:

- the app uploads Ludusavi's staged backup, not raw live files directly from their original folders
- cloud storage now prefers a compressed archive plus metadata
- `manifest.json` is still uploaded for backward compatibility and restore logic

## What A Pull Actually Does

Pull means downloading the saved cloud snapshot, adapting it if the platform changed, then restoring it through Ludusavi.

```mermaid
flowchart TD
    A[Fetch cloud data for one game] --> B{Compressed archive available?}
    B -->|Yes| C[Download save.tar.gz]
    B -->|No| D[Download legacy uncompressed backup]
    C --> E[Extract archive to temp folder]
    D --> F[Prepare legacy backup folder]
    E --> G[Rewrite paths for target platform if needed]
    F --> G
    G --> H[Run Ludusavi restore]
    H --> I[Cache cloud manifest locally]
    I --> J[Mark status as synced]
```

Cross-platform restore works when the save paths are inside a Wine-style `drive_c` prefix. That includes Steam compatdata prefixes and non-Steam launchers like Heroic or Lutris when Ludusavi reports their paths under `drive_c`.

## Conflict Handling

A conflict happens when local and cloud save contents differ (different hashes).

When a conflict is detected:

- If confidence is **High** (≥ 85%), the app auto-resolves by pushing or pulling the recommended side. No dialog is shown.
- If confidence is **Medium** or **Low**, the app opens a side-by-side comparison dialog.

The conflict dialog shows:

- snapshot times, oldest file creation dates, and latest modification dates for both sides
- per-file timestamps (created and modified) for up to 3 files on each side
- confidence score with label and reasoning
- a recommendation when one side clearly has the older-established save lineage
- the recommended action is preselected as the default button

```mermaid
flowchart TD
    A[Conflict detected] --> B{Confidence ≥ 85%?}
    B -->|Yes| C[Auto-resolve: push or pull recommended side]
    B -->|No| D[Show comparison dialog]
    D --> E{User choice}
    E -->|Keep Mine| F[Force push local snapshot]
    E -->|Keep Cloud| G[Fetch cloud manifest and force pull]
    E -->|Cancel| H[Leave both sides unchanged]
```

No automatic merge is attempted. The replacement unit is always the whole game backup.

## What “Newer” Means

“Newer” is manifest-level, not file-level.

That means:

- SaveSync-Bridge compares content hashes and timestamps at the snapshot level
- individual file modification times are used for confidence scoring and user guidance, not for choosing a winner
- if hashes differ, the result is always a conflict (never a silent overwrite)

## What Gets Replaced

This is the key behavior:

- the app never merges save files one-by-one
- a push replaces the cloud snapshot for that game
- a pull replaces the local snapshot for that game through Ludusavi restore
- the replacement unit is the whole staged backup for one game

## Excluding Games

Each game card has an exclusion checkbox.

- excluded games stay in the list
- excluded games appear under the `Excluded` filter
- excluded games are skipped by `Sync All`
- the exclusion list is saved in `config.toml` under `excluded_games`

## Debug Console

Use the debug console when:

- a game is missing from refresh results
- Google Drive authentication looks wrong
- cloud path settings are incorrect
- Ludusavi fails to back up or restore a title
- you need to inspect the exact CLI commands and stderr output

The panel shows the command, stdout, stderr, and exit code for Ludusavi and rclone operations.

## Cloud Layout

Each game is stored under:

```text
<backup_path>/<game_id>/
```

Current cloud format normally includes:

- `save.tar.gz`
- `sync_meta.json`
- `manifest.json`

Older snapshots may still contain an uncompressed Ludusavi backup layout instead of `save.tar.gz`.

## Local State Layout

The app keeps a cached manifest per game in:

- Windows: `%LOCALAPPDATA%/savesync-bridge/states/`
- Linux or Steam Deck: `~/.local/share/savesync-bridge/states/`

These files are sync metadata, not the actual game saves.

## Known Limits

- sync decisions are based on cached metadata, not a live three-way merge
- sync is game-level, not file-level
- native Linux save layouts outside Wine or Proton prefixes are not remapped into Windows paths
- `Unknown` currently defaults to upload on first sync

## Build And Run

```bash
uv sync
uv run savesync-bridge
```

Standalone build:

```bash
uv run build-exe
```

Windows output:

```text
dist/SaveSync-Bridge.exe
```