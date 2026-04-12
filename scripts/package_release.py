"""Package built executables into release archives.

Examples:
    uv run build-exe
    uv run package-release --version v0.1.0
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).parent.parent
DIST = ROOT / "dist"
RELEASE = ROOT / "release"


def _platform_name() -> str:
    return "windows" if sys.platform == "win32" else "linux"


def _archive_suffix(platform: str) -> str:
    return ".zip" if platform == "windows" else ".tar.gz"


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def _built_target(platform: str) -> Path:
    name = "SaveSync-Bridge.exe" if platform == "windows" else "SaveSync-Bridge"
    return DIST / name


def _stage_release_tree(version: str, platform: str) -> tuple[Path, str]:
    target = _built_target(platform)
    if not target.exists():
        raise FileNotFoundError(
            f"Built artifact not found: {target}. Run 'uv run build-exe' first."
        )

    package_name = f"savesync-bridge-{version}-{platform}-x64"
    stage_dir = RELEASE / package_name
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)

    if target.is_dir():
        shutil.copytree(target, stage_dir / target.name)
    else:
        shutil.copy2(target, stage_dir / target.name)

    for extra in ["README.md", "LICENSE", "THIRD_PARTY_LICENSES.md", ".env.example"]:
        shutil.copy2(ROOT / extra, stage_dir / extra)

    return stage_dir, package_name


def _write_zip(source_dir: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(source_dir.parent))


def _write_tar_gz(source_dir: Path, archive_path: Path) -> None:
    with tarfile.open(archive_path, "w:gz") as tf:
        tf.add(source_dir, arcname=source_dir.name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Package SaveSync-Bridge release archives")
    parser.add_argument("--version", required=True, help="Release version or tag, e.g. v0.1.0")
    parser.add_argument(
        "--platform",
        choices=["windows", "linux"],
        default=None,
        help="Target platform (default: current host platform)",
    )
    args = parser.parse_args()

    platform = args.platform or _platform_name()
    RELEASE.mkdir(parents=True, exist_ok=True)

    stage_dir, package_name = _stage_release_tree(args.version, platform)
    archive_path = RELEASE / f"{package_name}{_archive_suffix(platform)}"
    if archive_path.exists():
        archive_path.unlink()

    if platform == "windows":
        _write_zip(stage_dir, archive_path)
    else:
        _write_tar_gz(stage_dir, archive_path)

    checksum_path = RELEASE / f"{package_name}.sha256"
    checksum_path.write_text(f"{_sha256(archive_path)}  {archive_path.name}\n", encoding="utf-8")

    print(f"Created: {archive_path}")
    print(f"Checksum: {checksum_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())