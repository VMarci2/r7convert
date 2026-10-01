"""Publish the built release to GitHub, which is what the app's update check reads.

    python packaging/build_release.py --ffmpeg-bin DIR --exiftool-dir DIR
    python packaging/publish_release.py [--draft]

Uploads the Setup.exe, the zip and a latest.json manifest to a GitHub release
tagged vX.Y.Z, using the gh CLI (gh auth login once). Release notes are the
version's CHANGELOG.md section. The working tree must be committed and pushed,
so the tag matches the source the release was built from.

Installed copies update from latest.json; zip copies are pointed at the release
page. A --draft release is invisible to the app until published on GitHub.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_release import PRODUCT, ROOT, read_version  # noqa: E402

sys.path.insert(0, str(ROOT))
from r7convert.update import REPO  # noqa: E402


def run(*command: str, capture: bool = False) -> str:
    result = subprocess.run(command, cwd=ROOT, check=True, text=True,
                            capture_output=capture)
    return result.stdout.strip() if capture else ""


def changelog_section(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(version)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match or not match.group(1).strip():
        raise SystemExit(f"CHANGELOG.md has no '## {version}' section: add one first.")
    return match.group(1).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft", action="store_true", help="create a draft release to check first")
    args = parser.parse_args()

    version = read_version()
    tag = f"v{version}"
    release = ROOT / "release" / tag
    setup = release / f"{PRODUCT} v{version} Setup.exe"
    archive = release / f"{PRODUCT} v{version}.zip"
    for path in (setup, archive):
        if not path.is_file():
            raise SystemExit(f"{path.name} not found: run build_release.py first (with Inno Setup installed).")

    if run("git", "status", "--porcelain", capture=True):
        raise SystemExit("Uncommitted changes: commit them first, so the tag matches the build.")
    if run("git", "tag", "--list", tag, capture=True) or \
            subprocess.run(["gh", "release", "view", tag, "--repo", REPO],
                           cwd=ROOT, capture_output=True).returncode == 0:
        raise SystemExit(f"{tag} already exists: bump __version__ for a new release.")
    notes = changelog_section(version)

    # GitHub turns spaces in asset names into dots; upload under predictable names instead.
    upload = ROOT / "build" / "upload" / tag
    shutil.rmtree(upload, ignore_errors=True)
    upload.mkdir(parents=True)
    setup_name = f"Canon-R7-EXR-Converter-{tag}-Setup.exe"
    zip_name = f"Canon-R7-EXR-Converter-{tag}.zip"
    shutil.copy2(setup, upload / setup_name)
    shutil.copy2(archive, upload / zip_name)
    manifest = {
        "version": version,
        "notes": notes,
        "installer_url": f"https://github.com/{REPO}/releases/download/{tag}/{setup_name}",
        "sha256": sha256(setup),
        "size": setup.stat().st_size,
    }
    (upload / "latest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (upload / "notes.md").write_text(notes, encoding="utf-8")

    run("git", "push", "origin", "HEAD")
    run("git", "tag", tag)
    run("git", "push", "origin", tag)
    command = ["gh", "release", "create", tag, "--repo", REPO, "--title", f"{PRODUCT} {tag}",
               "--notes-file", str(upload / "notes.md"), "--verify-tag",
               str(upload / setup_name), str(upload / zip_name), str(upload / "latest.json")]
    if args.draft:
        command.append("--draft")
    run(*command)
    shutil.rmtree(upload, ignore_errors=True)
    print(f"published {tag}{' (draft)' if args.draft else ''}: https://github.com/{REPO}/releases/tag/{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
