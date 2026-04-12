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
        - ``RCLONE_CONFIG_S3_TYPE``
        - ``RCLONE_CONFIG_S3_PROVIDER``
        - ``RCLONE_CONFIG_S3_ACCESS_KEY_ID``
        - ``RCLONE_CONFIG_S3_SECRET_ACCESS_KEY``
        - ``RCLONE_CONFIG_S3_REGION``
        - ``RCLONE_CONFIG_S3_ENDPOINT``
    """
    if env_file is None:
        env_file = Path.cwd() / ".env"
    load_dotenv(dotenv_path=env_file, override=True)
