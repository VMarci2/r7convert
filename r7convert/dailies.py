"""Dailies: clips joined one after another into a single .mov with burn-ins.

The picture is passed through as recorded, with no tone mapping: Canon Log 3
stays log, so it looks flat, and the file is tagged Rec.709. Each clip is
encoded to its own segment with identical settings, then the segments are
joined with ffmpeg's concat demuxer without re-encoding.

Burn-in text goes to drawtext through text files in a work folder that is also
ffmpeg's working directory, so no file name, project name or font path ever
needs filtergraph escaping.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable

from .media import Clip, Tools, _NO_WINDOW

H264 = "H.264 (small, plays anywhere)"

# label -> (encoder args, pixel format, audio args). First entry is the default.
# H.264 has no fixed args: the encoder depends on the ffmpeg build (see _h264_args).
CODECS: dict[str, tuple[list[str], str, list[str]]] = {
    H264: ([], "yuv420p", ["-c:a", "aac", "-b:a", "192k"]),
    "ProRes 422 HQ": (["-c:v", "prores_ks", "-profile:v", "3", "-vendor", "apl0"],
                      "yuv422p10le", ["-c:a", "pcm_s16le"]),
    "ProRes 422": (["-c:v", "prores_ks", "-profile:v", "2", "-vendor", "apl0"],
                   "yuv422p10le", ["-c:a", "pcm_s16le"]),
    "ProRes 422 LT": (["-c:v", "prores_ks", "-profile:v", "1", "-vendor", "apl0"],
                      "yuv422p10le", ["-c:a", "pcm_s16le"]),
}

# label -> (width, height); None uses the first clip's size.
SIZES: dict[str, tuple[int, int] | None] = {
    "1920 x 1080": (1920, 1080),
    "Same as first clip": None,
}

# H.264 bitrate in bits per pixel per frame (about 20 Mb/s at 1080p25).
_H264_BITS_PER_PIXEL = 0.4

# Measured-ish bytes per pixel per frame for the size estimate.
_BYTES_PER_PIXEL = {
    H264: _H264_BITS_PER_PIXEL / 8,
    "ProRes 422 HQ": 0.443, "ProRes 422": 0.296, "ProRes 422 LT": 0.205,
}

_FONT = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf"


class Cancelled(Exception):
    pass


_encoders: dict[str, str] = {}


def h264_encoder(ffmpeg: str) -> str:
    """Best H.264 encoder in this ffmpeg build. The bundled one is LGPL, so it has
    no x264; it has OpenH264. Media Foundation is Windows' own fallback."""
    if ffmpeg not in _encoders:
        listing = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                                 text=True, errors="replace", **_NO_WINDOW).stdout
        names = {line.split()[1] for line in listing.splitlines() if len(line.split()) > 1}
        _encoders[ffmpeg] = next((e for e in ("libx264", "libopenh264", "h264_mf") if e in names), "")
    if not _encoders[ffmpeg]:
        raise RuntimeError("This ffmpeg has no H.264 encoder. Choose a ProRes format instead.")
    return _encoders[ffmpeg]


def _h264_args(encoder: str, bitrate: int) -> list[str]:
    if encoder == "libx264":
        return ["-c:v", "libx264", "-preset", "medium", "-b:v", str(bitrate),
                "-maxrate", str(bitrate * 3 // 2), "-bufsize", str(bitrate * 2)]
    if encoder == "libopenh264":
        return ["-c:v", "libopenh264", "-rc_mode", "bitrate", "-b:v", str(bitrate)]
    return ["-c:v", encoder, "-b:v", str(bitrate)]


@dataclass
class DailiesSettings:
    output: Path
    codec: str = next(iter(CODECS))
    size: str = next(iter(SIZES))
    project: str = ""
    # what to burn in; the project name also needs text to show
    burn_project: bool = True
    burn_name: bool = True
    burn_frame: bool = True


def output_format(clips: list[Clip], settings: DailiesSettings) -> tuple[int, int, Fraction]:
    """Width, height and frame rate of the dailies: the first clip sets the frame rate."""
    size = SIZES[settings.size]
    width, height = size if size else (clips[0].width, clips[0].height)
    return width - width % 2, height - height % 2, clips[0].fps


def frames_at(clip: Clip, fps: Fraction) -> int:
    if clip.fps == fps:
        return clip.frames
    return int(round(clip.frames * fps / clip.fps))


def estimate_bytes(clips: list[Clip], settings: DailiesSettings) -> int:
    if not clips:
        return 0
    width, height, fps = output_format(clips, settings)
    frames = sum(frames_at(c, fps) for c in clips)
    return int(width * height * frames * _BYTES_PER_PIXEL[settings.codec])


class DailiesMaker:
    def __init__(
        self,
        tools: Tools,
        settings: DailiesSettings,
        log: Callable[[str], None] = lambda m: None,
        on_progress: Callable[[float], None] = lambda f: None,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        self.tools = tools
        self.settings = settings
        self.log = log
        self.on_progress = on_progress
        self.cancelled = cancelled

    def run(self, clips: list[Clip]) -> Path:
        if not clips:
            raise ValueError("No clips.")
        output = self.settings.output.with_suffix(".mov")
        output.parent.mkdir(parents=True, exist_ok=True)
        work = output.parent / f".{output.stem}-dailies-parts"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir()
        try:
            return self._run(clips, output, work)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _run(self, clips: list[Clip], output: Path, work: Path) -> Path:
        width, height, fps = output_format(clips, self.settings)
        counts = [frames_at(c, fps) for c in clips]
        total = max(1, sum(counts))
        codec = self.settings.codec
        if codec == H264:
            codec = f"H.264 ({h264_encoder(self.tools.ffmpeg)})"
        self.log(f"Dailies: {len(clips)} clip(s), {width}x{height} at {float(fps):g} fps, {codec}")

        font = "fontfile=arial.ttf"
        if _FONT.is_file():
            shutil.copy2(_FONT, work / "arial.ttf")
        else:
            font = "font=Arial"
        project = self.settings.project.strip() if self.settings.burn_project else ""
        if project:
            (work / "project.txt").write_text(project, encoding="utf-8")

        parts: list[str] = []
        done = 0
        for index, (clip, count) in enumerate(zip(clips, counts)):
            if self.cancelled():
                raise Cancelled()
            if clip.fps != fps:
                self.log(f"  {clip.path.name}: {float(clip.fps):g} fps, converted to {float(fps):g} fps")
            if clip.log_version and not clip.is_canon_log3:
                self.log(f"  {clip.path.name}: {clip.log_version}, not Canon Log 3")
            (work / f"name{index}.txt").write_text(clip.path.name, encoding="utf-8")
            digits = len(str(count))
            (work / f"frame{index}.txt").write_text(f"%{{eif:n+1:d:{digits}}} / {count}", encoding="utf-8")

            part = f"part{index:04d}.mov"
            self._encode(clip, index, part, work, width, height, fps, font, bool(project),
                         lambda frame: self.on_progress((done + min(frame, count)) / total))
            parts.append(part)
            done += count
            self.on_progress(done / total)
            self.log(f"  {clip.path.name}: {count} frames")

        (work / "parts.txt").write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        self._ffmpeg(["-f", "concat", "-safe", "0", "-i", "parts.txt", "-c", "copy",
                      "-movflags", "+faststart", str(output)], work)
        self.log(f"  written {output.name}")
        return output

    def _filter(self, clip: Clip, index: int, width: int, height: int, fps: Fraction,
                font: str, project: bool) -> str:
        pix_fmt = CODECS[self.settings.codec][1]
        # Canon Log sits on legal-range code values although R7 files are flagged
        # full range: read them as legal range so every code value passes through.
        levels = "in_range=tv:out_range=tv:" if clip.log_version else "out_range=tv:"
        size = round(height * 0.028)
        margin = round(height * 0.025)
        text = (f"{font}:fontsize={size}:fontcolor=white:box=1:boxcolor=black@0.5:"
                f"boxborderw={max(2, round(size * 0.3))}:y=h-lh-{margin}")
        steps = [
            f"fps={fps.numerator}/{fps.denominator}",
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2:"
            f"{levels}in_color_matrix=bt709:out_color_matrix=bt709:flags=lanczos",
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
            "setsar=1",
            f"format={pix_fmt}",
        ]
        if self.settings.burn_name:
            steps.append(f"drawtext={text}:textfile=name{index}.txt:expansion=none:x=(w-tw)/2")
        if self.settings.burn_frame:
            steps.append(f"drawtext={text}:textfile=frame{index}.txt:expansion=normal:x=w-tw-{margin}")
        if project:
            steps.append(f"drawtext={text}:textfile=project.txt:expansion=none:x={margin}")
        steps.append("setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709")
        return ",".join(steps)

    def _encode(self, clip: Clip, index: int, part: str, work: Path, width: int, height: int,
                fps: Fraction, font: str, project: bool, on_frame: Callable[[int], None]) -> None:
        video, _, audio = CODECS[self.settings.codec]
        command = ["-i", str(clip.path)]
        if clip.has_audio:
            command += ["-map", "0:v:0", "-map", "0:a:0"]
        else:  # every segment needs an audio track for the join
            command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                        "-map", "0:v:0", "-map", "1:a:0", "-shortest"]
        command += ["-vf", self._filter(clip, index, width, height, fps, font, project), *video]
        if self.settings.codec == H264:
            bitrate = int(width * height * float(fps) * _H264_BITS_PER_PIXEL)
            # a keyframe every second, so the reel scrubs well
            command += [*_h264_args(h264_encoder(self.tools.ffmpeg), bitrate),
                        "-g", str(max(1, round(float(fps))))]
        # No timecode track: the first clip's timecode would be wrong for the joined reel.
        command += [*audio, "-ar", "48000", "-ac", "2", "-write_tmcd", "0",
                    "-progress", "pipe:1", "-nostats", part]
        self._ffmpeg(command, work, on_frame)

    def _ffmpeg(self, args: list[str], cwd: Path, on_frame: Callable[[int], None] | None = None) -> None:
        proc = subprocess.Popen(
            [self.tools.ffmpeg, "-v", "error", "-nostdin", "-y", *args], cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", **_NO_WINDOW,
        )
        for line in proc.stdout:
            if self.cancelled():
                proc.kill()
                proc.wait()
                raise Cancelled()
            if on_frame and line.startswith("frame="):
                try:
                    on_frame(int(line[6:].strip()))
                except ValueError:
                    pass
        stderr = proc.stderr.read().strip()
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed: {stderr[:400]}")
