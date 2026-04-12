# SaveSync-Bridge

A PySide6 GUI that acts as a smart manager for [Ludusavi](https://github.com/mtkennerly/ludusavi), enabling seamless game save synchronization between Windows PCs and Steam Deck via rclone-backed S3 storage.

## Documentation

- User guide: [docs/USER_GUIDE.md](docs/USER_GUIDE.md)
- Technical documentation: [docs/TECHNICAL.md](docs/TECHNICAL.md)

## Features

- **Path Translation**: Automatically maps save paths between Windows and Steam Deck (Proton/Wine compatdata)
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
```

## License

MIT — see [LICENSE](LICENSE).
