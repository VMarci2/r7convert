"""ffmpeg/exiftool discovery and clip probing."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable

if sys.platform == "win32":
    _NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _NO_WINDOW = {}


def drain(stream) -> Callable[[], str]:
    """Read a child's pipe on a thread for as long as it runs; returns a function that
    waits for the end and gives the text.

    A Windows pipe holds only a few KB: a child that writes more than that to a
    pipe nobody is reading blocks forever, and the whole conversion hangs with it.
    Every ffmpeg stderr=PIPE must go through this.
    """
    chunks: list = []

    def read() -> None:
        while chunk := stream.read(4096):
            chunks.append(chunk)

    thread = threading.Thread(target=read, daemon=True)
    thread.start()

    def result() -> str:
        thread.join()
        text = "".join(c if isinstance(c, str) else c.decode("utf-8", "replace") for c in chunks)
        return text.strip()

    return result

VIDEO_SUFFIXES = {".mp4", ".mov", ".mxf", ".m4v"}


class ToolsMissing(RuntimeError):
    pass


@dataclass(frozen=True)
class Tools:
    ffmpeg: str
    ffprobe: str
    exiftool: str | None

    @classmethod
    def discover(cls) -> "Tools":
        """Bundled tools next to the exe first, then PATH."""
        ffmpeg = _bundled("ffmpeg", "ffmpeg.exe") or shutil.which("ffmpeg")
        ffprobe = _bundled("ffmpeg", "ffprobe.exe") or shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            raise ToolsMissing(
                "ffmpeg was not found.\n\n"
                "If you are using the shared app, extract the whole zip again."
            )
        exiftool = (_bundled("exiftool", "exiftool.exe")
                    or shutil.which("exiftool") or shutil.which("ExifTool"))
        return cls(ffmpeg, ffprobe, exiftool)


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _bundled(folder: str, name: str) -> str | None:
    path = app_dir() / "tools" / folder / name
    return str(path) if path.is_file() else None


@dataclass
class Clip:
    path: Path
    width: int
    height: int
    frames: int
    fps: Fraction
    pix_fmt: str
    codec: str
    colour_range: str
    timecode: str | None = None
    has_audio: bool = False
    log_version: str | None = None
    camera_model: str | None = None
    lens_model: str | None = None
    colour_space_tag: str | None = None

    @property
    def name(self) -> str:
        return self.path.stem

    @property
    def is_canon_log3(self) -> bool:
        return (self.log_version or "").upper().replace(" ", "") in {"CLOGV3", "CANONLOG3"}

    def summary(self) -> str:
        bits = [f"{self.width}x{self.height}", f"{float(self.fps):g}p",
                f"{self.frames} frames", self.codec, self.pix_fmt]
        if self.log_version:
            bits.append(self.log_version)
        if self.colour_space_tag:
            bits.append(self.colour_space_tag)
        return "  ".join(bits)


def _run(cmd: list[str]) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True, errors="replace", **_NO_WINDOW)
    if out.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name} failed:\n{out.stderr.strip()[:800]}")
    return out.stdout


def probe(path: Path, tools: Tools) -> Clip:
    data = json.loads(_run([
        tools.ffprobe, "-v", "error", "-of", "json", "-show_streams", "-show_format", str(path),
    ]))
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise RuntimeError(f"No video stream in {path.name}")

    fps = Fraction(video.get("avg_frame_rate") or video.get("r_frame_rate") or "25/1")
    if fps == 0:
        fps = Fraction(25, 1)

    frames = int(video.get("nb_frames") or 0)
    if frames <= 0:
        duration = float(video.get("duration") or data.get("format", {}).get("duration") or 0)
        frames = int(round(duration * float(fps)))

    timecode = None
    for source in (data.get("format", {}).get("tags", {}), *(s.get("tags", {}) for s in streams)):
        if source.get("timecode"):
            timecode = source["timecode"]
            break

    clip = Clip(
        path=path,
        width=int(video["width"]),
        height=int(video["height"]),
        frames=frames,
        fps=fps,
        pix_fmt=video.get("pix_fmt", "?"),
        codec=video.get("codec_name", "?"),
        colour_range=video.get("color_range", "unknown"),
        timecode=timecode,
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )
    if tools.exiftool:
        _attach_canon_tags(clip, tools)
    return clip


def _attach_canon_tags(clip: Clip, tools: Tools) -> None:
    try:
        raw = _run([
            tools.exiftool, "-json", "-CanonLogVersion", "-ColorSpace2", "-Model", "-LensModel",
            str(clip.path),
        ])
        tags = json.loads(raw)[0]
    except Exception:
        return

    def text(key: str) -> str | None:
        value = tags.get(key)
        return None if value is None else str(value)

    clip.log_version = text("CanonLogVersion")
    clip.colour_space_tag = text("ColorSpace2")
    clip.camera_model = text("Model")
    clip.lens_model = text("LensModel")


def pack_timecode(timecode: str, frame_offset: int, fps: int) -> tuple[int, int]:
    """SMPTE timecode -> OpenEXR (timeAndFlags, userData). Non-drop-frame."""
    hours, minutes, seconds, frames = (int(p) for p in timecode.replace(";", ":").split(":"))
    total = ((hours * 60 + minutes) * 60 + seconds) * fps + frames + frame_offset
    total %= 24 * 60 * 60 * fps
    frames = total % fps
    seconds = (total // fps) % 60
    minutes = (total // (fps * 60)) % 60
    hours = (total // (fps * 3600)) % 24

    def bcd(value: int, shift: int) -> int:
        return ((value % 10) << shift) | ((value // 10) << (shift + 4))

    packed = bcd(frames, 0) | bcd(seconds, 8) | bcd(minutes, 16) | bcd(hours, 24)
    return packed & 0xFFFFFFFF, 0
