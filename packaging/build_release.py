"""Build the shareable app folder and zip.

    python packaging/build_release.py --ffmpeg-bin DIR --exiftool-dir DIR [--manual PDF] [--force]
    python packaging/build_release.py --installer-only

The version comes from r7convert/__init__.py (__version__). It is stamped into the
folder name, the exe name and its file properties, the zip name, the installer
name and VERSION.txt.
An existing release with the same version is never overwritten unless --force is
given: bump __version__ instead.

Run with a Python environment that has requirements.txt plus a PyInstaller
installed from source (so its bootloader is compiled locally, not the stock one).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRODUCT = "Canon R7 EXR Converter"
FFMPEG_FILES = ["ffmpeg.exe", "ffprobe.exe"]
ISCC_PATHS = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
]


def read_version() -> str:
    text = (ROOT / "r7convert" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', text, re.M)
    if not match:
        raise SystemExit("r7convert/__init__.py: __version__ must look like \"2.1.0\"")
    return ".".join(match.groups())


def build_installer(app: Path, version: str, release: Path) -> Path | None:
    """Wrap the app folder in a single-file Inno Setup installer, if ISCC is installed."""
    iscc = shutil.which("iscc") or next((str(p) for p in ISCC_PATHS if p.is_file()), None)
    if not iscc:
        print("installer: skipped, Inno Setup 6 not found (winget install JRSoftware.InnoSetup)")
        return None
    subprocess.run(
        [iscc, "/Q", f"/DAppVersion={version}", f"/DSourceDir={app}", f"/DOutputDir={release}",
         str(ROOT / "packaging" / "installer.iss")],
        check=True,
    )
    return release / f"{PRODUCT} v{version} Setup.exe"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffmpeg-bin", type=Path)
    parser.add_argument("--exiftool-dir", type=Path)
    parser.add_argument("--manual", type=Path, default=ROOT / "docs" / "Canon_R7_EXR_Converter_Manual.pdf")
    parser.add_argument("--force", action="store_true", help="overwrite an existing release of this version")
    parser.add_argument("--installer-only", action="store_true",
                        help="only build the installer from the existing dist folder of this version")
    args = parser.parse_args()

    version = read_version()
    major, minor, patch = version.split(".")
    name = f"{PRODUCT} v{version}"
    release = ROOT / "release"
    dist = ROOT / "dist"
    if args.installer_only:
        if not (dist / name).is_dir():
            raise SystemExit(f"dist/{name} does not exist: run the full build first.")
        installer = build_installer(dist / name, version, release)
        return 0 if installer else 1
    if not (args.ffmpeg_bin and args.exiftool_dir):
        parser.error("--ffmpeg-bin and --exiftool-dir are required")
    archive = release / f"{name}.zip"
    if archive.exists() and not args.force:
        raise SystemExit(f"{archive.name} already exists. Bump __version__, or pass --force to rebuild it.")

    work = ROOT / "build"
    work.mkdir(exist_ok=True)
    version_file = work / "version_info.txt"
    template = (ROOT / "packaging" / "version_info.template.txt").read_text(encoding="utf-8")
    version_file.write_text(
        template.format(major=major, minor=minor, patch=patch, version=version, exe_name=f"{name}.exe"),
        encoding="utf-8",
    )

    env = dict(os.environ, R7_RELEASE_NAME=name, R7_VERSION_FILE=str(version_file))
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--workpath", str(work), "--distpath", str(dist),
         str(ROOT / "packaging" / "r7convert.spec")],
        check=True, env=env,
    )
    app = dist / name

    ffmpeg_out = app / "tools" / "ffmpeg"
    ffmpeg_out.mkdir(parents=True, exist_ok=True)
    for exe in FFMPEG_FILES:
        shutil.copy2(args.ffmpeg_bin / exe, ffmpeg_out / exe)
    for dll in args.ffmpeg_bin.glob("*.dll"):
        shutil.copy2(dll, ffmpeg_out / dll.name)
    licence = args.ffmpeg_bin.parent / "LICENSE.txt"
    if licence.is_file():
        shutil.copy2(licence, ffmpeg_out / "LICENSE.txt")
        (ffmpeg_out / "SOURCE.txt").write_text(
            "FFmpeg LGPL shared build from https://github.com/BtbN/FFmpeg-Builds\n"
            "Source code: https://ffmpeg.org/download.html\n",
            encoding="utf-8",
        )

    exif_out = app / "tools" / "exiftool"
    shutil.copytree(args.exiftool_dir, exif_out, dirs_exist_ok=True)
    launcher = next((p for p in exif_out.iterdir() if p.suffix.lower() == ".exe"), None)
    if launcher and launcher.name != "exiftool.exe":
        launcher.rename(exif_out / "exiftool.exe")

    if args.manual.is_file():
        shutil.copy2(args.manual, app / "Manual.pdf")
    changelog = ROOT / "CHANGELOG.md"
    (app / "VERSION.txt").write_text(
        f"{PRODUCT} - FVFX\nVersion {version}\n\n"
        + (changelog.read_text(encoding="utf-8") if changelog.is_file() else ""),
        encoding="utf-8",
    )

    release.mkdir(exist_ok=True)
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(app.rglob("*")):
            zf.write(path, Path(name) / path.relative_to(app))
    print(f"version: {version}")
    print(f"app:     {app}")
    print(f"archive: {archive}  ({archive.stat().st_size / 1e6:.0f} MB)")
    installer = build_installer(app, version, release)
    if installer:
        print(f"setup:   {installer}  ({installer.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
