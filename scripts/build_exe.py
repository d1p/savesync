"""Build SaveSync-Bridge into a standalone executable via PyInstaller.

Usage:
    uv run build-exe            # standard release build
    uv run build-exe --debug    # keep console window for debugging
    uv run build-exe --dir      # one-folder build (faster startup, easier debugging)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SPEC = ROOT / "savesync_bridge.spec"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build SaveSync-Bridge executable")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable console window and debug mode",
    )
    parser.add_argument(
        "--dir",
        action="store_true",
        dest="onedir",
        help="Produce a one-folder build instead of a single-file EXE",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        default=True,
        help="Remove build/ and dist/ before building (default: True)",
    )
    args = parser.parse_args()

    if args.clean:
        for d in (DIST, BUILD):
            if d.exists():
                print(f"Removing {d} …")
                shutil.rmtree(d)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(SPEC),
        "--noconfirm",
        "--workpath", str(BUILD),
        "--distpath", str(DIST),
    ]

    if args.onedir:
        cmd.append("--onedir")
    else:
        cmd.append("--onefile")

    if args.debug:
        cmd += ["--debug", "all", "--console"]

    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, check=False)

    if result.returncode == 0:
        exe_path = DIST / ("SaveSync-Bridge" + (".exe" if sys.platform == "win32" else ""))
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / 1_048_576
            print(f"\nBuild successful: {exe_path}  ({size_mb:.1f} MB)")
        else:
            # one-dir build
            print(f"\nBuild successful — output in {DIST}/")
    else:
        print("\nBuild FAILED", file=sys.stderr)

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
