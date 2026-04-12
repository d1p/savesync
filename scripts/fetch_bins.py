"""
Download and verify bundled third-party binaries for SaveSync-Bridge.

Fetches:
  - Ludusavi v0.31.0  (MIT) — https://github.com/mtkennerly/ludusavi
  - rclone   v1.73.4  (MIT) — https://github.com/rclone/rclone

Run once before building or distributing:
    uv run python scripts/fetch_bins.py
    uv run python scripts/fetch_bins.py --platform windows
    uv run python scripts/fetch_bins.py --platform linux
"""

from __future__ import annotations

import argparse
import hashlib
import io
import stat
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Manifest: all artefacts to fetch
# ---------------------------------------------------------------------------

MANIFEST: dict[str, dict] = {
    "windows": {
        "ludusavi": {
            "url": "https://github.com/mtkennerly/ludusavi/releases/download/v0.31.0/ludusavi-v0.31.0-win64.zip",
            "sha256": "f47a8ad8c708f01d2eb124704973beffab205e292f5287a10fc4a101f8d68706",
            "archive_type": "zip",
            # Search for any file matching this name inside the archive
            "binary_name": "ludusavi.exe",
            "output_name": "ludusavi.exe",
        },
        "rclone": {
            "url": "https://github.com/rclone/rclone/releases/download/v1.73.4/rclone-v1.73.4-windows-amd64.zip",
            "sha256": "4ad32977eec7f77aef98c035865c333f2005be2478dd6b04c9456d1df7b326bf",
            "archive_type": "zip",
            "binary_name": "rclone.exe",
            "output_name": "rclone.exe",
        },
    },
    "linux": {
        "ludusavi": {
            "url": "https://github.com/mtkennerly/ludusavi/releases/download/v0.31.0/ludusavi-v0.31.0-linux.tar.gz",
            "sha256": "7322ff45d41eae7ae064a80d8c9ecccc5b8fb6fc090a603a66369cd4b054068d",
            "archive_type": "tar.gz",
            "binary_name": "ludusavi",
            "output_name": "ludusavi",
        },
        "rclone": {
            "url": "https://github.com/rclone/rclone/releases/download/v1.73.4/rclone-v1.73.4-linux-amd64.zip",
            "sha256": "abc0e6e0f275a469d94645f7ef92c7c7673eed20b6558acec5ff48b74641213c",
            "archive_type": "zip",
            "binary_name": "rclone",
            "output_name": "rclone",
        },
    },
}

BIN_ROOT = Path(__file__).parent.parent / "src" / "savesync_bridge" / "bin"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _download(url: str) -> bytes:
    print(f"  Downloading {url} …", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "savesync-bridge/fetch_bins"})
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 — URL is a hardcoded constant
        return resp.read()


def _extract_from_zip(data: bytes, binary_name: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if Path(name).name == binary_name:
                return zf.read(name)
    raise FileNotFoundError(f"{binary_name!r} not found inside archive")


def _extract_from_tar(data: bytes, binary_name: str) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for member in tf.getmembers():
            if Path(member.name).name == binary_name:
                f = tf.extractfile(member)
                if f is None:
                    continue
                return f.read()
    raise FileNotFoundError(f"{binary_name!r} not found inside archive")


def _make_executable(path: Path) -> None:
    """Set owner/group execute bits on non-Windows systems."""
    if sys.platform != "win32":
        current = path.stat().st_mode
        path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# ---------------------------------------------------------------------------
# Core fetch logic
# ---------------------------------------------------------------------------


def fetch(platform: str) -> None:
    entries = MANIFEST.get(platform)
    if entries is None:
        print(f"Unknown platform {platform!r}. Choose: {list(MANIFEST)}", file=sys.stderr)
        sys.exit(1)

    out_dir = BIN_ROOT / platform
    out_dir.mkdir(parents=True, exist_ok=True)

    for tool, spec in entries.items():
        out_path = out_dir / spec["output_name"]
        if out_path.exists():
            print(f"  [{platform}/{tool}] already present — skip (delete to re-fetch)")
            continue

        print(f"\n[{platform}/{tool}]")
        archive_bytes = _download(spec["url"])

        actual = _sha256(archive_bytes)
        expected = spec["sha256"]
        if actual != expected:
            print(
                f"  SHA-256 MISMATCH for {spec['url']}\n"
                f"    expected: {expected}\n"
                f"    got:      {actual}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"  SHA-256 verified ✓")

        if spec["archive_type"] == "zip":
            binary_bytes = _extract_from_zip(archive_bytes, spec["binary_name"])
        else:
            binary_bytes = _extract_from_tar(archive_bytes, spec["binary_name"])

        out_path.write_bytes(binary_bytes)
        _make_executable(out_path)
        size_mb = out_path.stat().st_size / 1_048_576
        print(f"  Written → {out_path.relative_to(BIN_ROOT.parent.parent.parent)} ({size_mb:.1f} MB)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch bundled binaries for SaveSync-Bridge")
    parser.add_argument(
        "--platform",
        choices=list(MANIFEST),
        default=None,
        help="Fetch only for this platform (default: current host platform)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Fetch for ALL platforms (use when building a distribution)",
    )
    args = parser.parse_args()

    if args.all:
        platforms = list(MANIFEST)
    elif args.platform:
        platforms = [args.platform]
    else:
        platforms = ["windows" if sys.platform == "win32" else "linux"]

    for platform in platforms:
        print(f"\n=== {platform} ===")
        fetch(platform)

    print("\nDone.")


if __name__ == "__main__":
    main()
