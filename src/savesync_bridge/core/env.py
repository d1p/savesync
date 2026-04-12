from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


def load_env(env_file: Path | None = None) -> None:
    """Load a ``.env`` file and merge its contents into :data:`os.environ`.

    The loaded variables are inherited by child processes (e.g. rclone) without
    any additional configuration.

    Args:
        env_file: Path to the ``.env`` file.  When *None*, defaults to
            ``<cwd>/.env``.  A missing file is silently ignored.

    Expected keys (all optional):
        - ``RCLONE_DRIVE_CLIENT_ID``
        - ``RCLONE_DRIVE_CLIENT_SECRET``
        - ``RCLONE_DRIVE_SCOPE``
    """
    if env_file is None:
        env_file = Path.cwd() / ".env"
    load_dotenv(dotenv_path=env_file, override=True)
