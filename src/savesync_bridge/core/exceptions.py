from __future__ import annotations


class SaveSyncError(Exception):
    """Base exception for all SaveSync-Bridge errors."""


class LudusaviError(SaveSyncError):
    """Raised when a Ludusavi CLI invocation fails."""

    def __init__(self, message: str, returncode: int, stderr: str) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


class RcloneError(SaveSyncError):
    """Raised when an rclone CLI invocation fails."""

    def __init__(self, message: str, returncode: int, stderr: str) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


class SyncError(SaveSyncError):
    """Raised when the sync orchestration layer encounters a logic error."""
