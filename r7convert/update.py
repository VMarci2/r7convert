"""Update check and install from GitHub releases.

Every release carries a `latest.json` asset (written by packaging/publish_release.py).
`releases/latest/download/latest.json` is served from GitHub's download CDN, not
the REST API, so a whole lab on one campus IP never hits the API's 60
requests/hour limit.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import __version__

REPO = "VMarci2/r7convert"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
# The documentation site (MkDocs, built from docs/ by .github/workflows/docs.yml).
DOCS_URL = "https://vmarci2.github.io/r7convert/"
NUKE_URL = DOCS_URL + "nuke/"
DAILIES_URL = DOCS_URL + "dailies/"
HEADLESS_URL = DOCS_URL + "headless/"
TROUBLESHOOTING_URL = DOCS_URL + "troubleshooting/"
# R7_UPDATE_URL points the check at another manifest, for testing a release.
MANIFEST_URL = os.environ.get("R7_UPDATE_URL") or f"{RELEASES_PAGE}/download/latest.json"
DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "r7convert-update"
TIMEOUT = 8
_HEADERS = {"User-Agent": f"r7convert/{__version__}"}


@dataclass
class Release:
    version: str
    notes: str
    installer_url: str
    sha256: str
    size: int


def parse_version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.strip().lstrip("v").split("."))


def fetch_latest() -> Release:
    request = urllib.request.Request(MANIFEST_URL, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8"))
    return Release(
        version=data["version"],
        notes=data.get("notes", ""),
        installer_url=data["installer_url"],
        sha256=data["sha256"].lower(),
        size=int(data.get("size", 0)),
    )


def is_newer(release: Release) -> bool:
    return parse_version(release.version) > parse_version(__version__)


def is_installed() -> bool:
    """True for the Setup.exe install, which can update itself; False for the zip and source."""
    if not getattr(sys, "frozen", False):
        return False
    return any(Path(sys.executable).parent.glob("unins*.exe"))


def clean_downloads() -> None:
    """Remove installers left by an earlier update; the installer cannot delete itself."""
    shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)


def download(
    release: Release, on_progress: Callable[[float], None], cancelled: Callable[[], bool],
) -> Path | None:
    """Download and verify the installer. Returns None if cancelled."""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = DOWNLOAD_DIR / f"Canon-R7-EXR-Converter-v{release.version}-Setup.exe"
    partial = target.with_suffix(".part")
    digest = hashlib.sha256()
    done = 0

    request = urllib.request.Request(release.installer_url, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response, open(partial, "wb") as out:
        total = int(response.headers.get("Content-Length") or release.size or 0)
        while chunk := response.read(1 << 20):
            if cancelled():
                out.close()
                partial.unlink(missing_ok=True)
                return None
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if total:
                on_progress(done / total)

    if digest.hexdigest() != release.sha256:
        partial.unlink(missing_ok=True)
        raise RuntimeError("The download was damaged (checksum mismatch). Try again.")
    partial.replace(target)
    return target


def launch_installer(installer: Path) -> None:
    """Run the installer silently; the app must exit straight after so its files can be replaced.

    /UPDATE=1 makes installer.iss reopen the app when it finishes.
    """
    subprocess.Popen(
        [str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/UPDATE=1"],
        close_fds=True,
    )
