# SaveSync-Bridge

A PySide6 GUI that acts as a smart manager for [Ludusavi](https://github.com/mtkennerly/ludusavi), enabling seamless game save synchronization between Windows PCs and Steam Deck via rclone-backed S3 storage.

## Documentation

- User guide: [docs/USER_GUIDE.md](docs/USER_GUIDE.md)
- Technical documentation: [docs/TECHNICAL.md](docs/TECHNICAL.md)

## Cloud Builds And Releases

This repository includes GitHub Actions workflows for prepackaged Windows and Linux builds.

- `Cloud Build`: builds Windows and Linux artifacts in GitHub Actions and uploads them as workflow artifacts
- `Release`: runs on version tags like `v0.1.0` and publishes downloadable release archives for both platforms

Each release archive contains:

- the packaged SaveSync-Bridge app binary
- bundled Ludusavi binary for that platform
- bundled rclone binary for that platform
- `.env.example`
- `LICENSE`
- `THIRD_PARTY_LICENSES.md`

To create a GitHub release with both platform builds:

```bash
git tag v0.1.0
git push origin v0.1.0
```

To run an on-demand cloud build without publishing a release, use the `Cloud Build` workflow from the Actions tab.

## Features

- **Path Translation**: Automatically maps save paths between Windows and Wine/Proton prefixes, including non-Steam launchers that Ludusavi detects under `drive_c`
- **Conflict Resolution**: Metadata-driven sync with a visual conflict resolution dialog
- **Sync Center**: Unified view of all games regardless of which machine they were last played on
- **Ludusavi Integration**: Uses Ludusavi's `--api` mode for save discovery and backup/restore
- **rclone Transport**: Leverages rclone CLI for S3 storage operations

## Requirements

- Python 3.13+
- [Ludusavi](https://github.com/mtkennerly/ludusavi) CLI installed and on PATH
- [rclone](https://rclone.org/) CLI installed and configured with your S3 remote

## Setup

```bash
# Install Python 3.13 via pyenv
pyenv install 3.13
pyenv local 3.13

# Install dependencies with uv
uv sync

# Run the app
uv run savesync-bridge
```

## Development

```bash
# Install dev dependencies
uv sync

# Run tests
uv run pytest

# Lint & format
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# Build a standalone executable
uv run build-exe

# Package the built executable into a release archive
uv run package-release --version v0.1.0
```

## License

MIT — see [LICENSE](LICENSE).
