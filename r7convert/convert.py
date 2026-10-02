"""Canon Log 3 HEVC -> scene-linear EXR sequences and/or ProRes."""

from __future__ import annotations

import contextlib
import queue
import subprocess
import sys
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import OpenImageIO as oiio

from . import colour
from .media import Clip, Tools, drain, pack_timecode, probe, _NO_WINDOW

# label -> target width, None keeps the source size
RESOLUTIONS: dict[str, int | None] = {
    "Full": None,
    "1920 wide": 1920,
}

BIT_DEPTHS: dict[str, str] = {
    "16-bit half": "half",
    "32-bit float": "float",
}

COMPRESSIONS: dict[str, str] = {
    "ZIP": "zip",
    "PIZ": "piz",
    "ZIPS": "zips",
    "DWAA (lossy)": "dwaa:45",
    "None": "none",
}

# label -> prores_ks profile. First entry is the default. prores_ks only takes
# 10-bit input, so 4444 is 10-bit too.
PRORES_PROFILES: dict[str, int] = {
    "422 HQ, 10-bit": 3,
    "422, 10-bit": 2,
    "422 LT, 10-bit": 1,
    "422 Proxy, 10-bit": 0,
    "4444, 10-bit": 4,
    "4444 XQ, 10-bit": 5,
}

# Apple's target rates at 1080p29.97 as bytes per pixel, for the size estimate.
_PRORES_BYTES_PER_PIXEL: dict[int, float] = {
    0: 0.091, 1: 0.205, 2: 0.296, 3: 0.443, 4: 0.664, 5: 1.006,
}

# ffmpeg primaries tag per gamut; gamuts without one are left untagged.
_FFMPEG_PRIMARIES: dict[str, str] = {"BT.709 / sRGB": "bt709", "BT.2020": "bt2020"}

# RGB -> legal-range Rec.709-matrix YCbCr for the ProRes encoder.
PRORES_FILTER = "scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int"

# Measured bytes per pixel for 16-bit half RGB on R7 footage, used for the size estimate.
_BYTES_PER_PIXEL: dict[str, float] = {
    "zip": 3.57, "piz": 3.30, "zips": 3.67, "dwaa:45": 0.93, "none": 6.00,
}
_FLOAT_MULTIPLIER = 2.74

# No level remapping: R'G'B' comes back as code/1023 for the decode LUT.
DECODE_FILTER = "scale=in_range=full:out_range=full:flags=bicubic+full_chroma_int+accurate_rnd"

# The ffmpeg pipe is the bottleneck; two workers is the measured optimum.
DEFAULT_WORKERS = 2


class Cancelled(Exception):
    pass


class OutOfMemory(RuntimeError):
    """Windows refused memory: almost always other programs, not this one."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            "Your computer ran out of memory.\n\n"
            "Close programs that use a lot of it (Nuke, SynthEyes, other 3D or video apps, "
            "browsers with many tabs) and convert again.\n\n"
            "Frames already written stay on disk and are replaced when you convert again."
        )
        self.detail = detail


@dataclass
class Settings:
    output_dir: Path
    source_gamut: str = colour.AUTO_GAMUT
    workspace: str = colour.ACESCG
    resolution: str = "Full"
    bit_depth: str = "16-bit half"
    compression: str = "ZIP"
    start_frame: int = 1
    workers: int = DEFAULT_WORKERS
    write_exr: bool = True
    write_prores: bool = False
    prores_quality: str = next(iter(PRORES_PROFILES))


@dataclass
class Progress:
    clip_index: int = 0
    clip_count: int = 0
    clip_name: str = ""
    frames_done: int = 0
    frames_total: int = 1

    @property
    def fraction(self) -> float:
        return min(1.0, self.frames_done / max(1, self.frames_total))


LogFn = Callable[[str], None]
ProgressFn = Callable[[Progress], None]
CancelFn = Callable[[], bool]

_local = threading.local()


def _scratch(shape: tuple, dtype) -> np.ndarray:
    """Per-thread reusable buffer."""
    cache = getattr(_local, "cache", None)
    if cache is None:
        cache = _local.cache = {}
    key = (shape, np.dtype(dtype).str)
    buffer = cache.get(key)
    if buffer is None:
        buffer = cache[key] = np.empty(shape, dtype)
    return buffer


def target_size(clip: Clip, resolution: str) -> tuple[int, int]:
    width = RESOLUTIONS[resolution]
    if width is None or width >= clip.width:
        return clip.width, clip.height
    height = int(round(clip.height * width / clip.width))
    return width, height - (height % 2)


def estimate_bytes(clips: list[Clip], settings: Settings) -> int:
    per_pixel = 0.0
    if settings.write_exr:
        exr = _BYTES_PER_PIXEL.get(COMPRESSIONS[settings.compression], 3.6)
        if BIT_DEPTHS[settings.bit_depth] == "float":
            exr *= _FLOAT_MULTIPLIER
        per_pixel += exr
    if settings.write_prores:
        per_pixel += _PRORES_BYTES_PER_PIXEL[PRORES_PROFILES[settings.prores_quality]]
    total = 0.0
    for clip in clips:
        width, height = target_size(clip, settings.resolution)
        total += width * height * per_pixel * max(clip.frames, 0)
    return int(total)


def human_bytes(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if count < 1024 or unit == "TB":
            return f"{count:.1f} {unit}"
        count /= 1024
    return "unknown"


def probe_clips(paths: list[Path], tools: Tools) -> list[Clip]:
    return [probe(path, tools) for path in paths]


class Converter:
    def __init__(
        self,
        tools: Tools,
        settings: Settings,
        log: LogFn = lambda m: None,
        on_progress: ProgressFn = lambda p: None,
        cancelled: CancelFn = lambda: False,
    ) -> None:
        self.tools = tools
        self.settings = settings
        self.log = log
        self.on_progress = on_progress
        self.cancelled = cancelled
        self._lut = colour.build_decode_lut()

    def _check_cancelled(self) -> None:
        if self.cancelled():
            raise Cancelled()

    def _resolve_gamut(self, clip: Clip) -> tuple[str, bool]:
        if self.settings.source_gamut != colour.AUTO_GAMUT:
            return self.settings.source_gamut, True
        return colour.gamut_from_tag(clip.colour_space_tag)

    def _matrix(self, clip: Clip) -> np.ndarray | None:
        source, _ = self._resolve_gamut(clip)
        target, _ = colour.output_space(self.settings.workspace, source)
        matrix = colour.gamut_matrix(source, target)
        if np.allclose(matrix, np.eye(3), atol=1e-9):
            return None
        return matrix.astype(np.float32)

    def _transform(
        self, codes: np.ndarray, matrix: np.ndarray | None, resize_to: tuple[int, int] | None
    ) -> np.ndarray:
        """Returns a thread-local buffer, valid until this thread's next call."""
        linear = self._lut[codes]
        if matrix is not None:
            flat = linear.reshape(-1, 3)
            out = _scratch(flat.shape, np.float32)
            np.dot(flat, matrix.T, out=out)
            linear = out.reshape(linear.shape)
        if resize_to is not None:
            linear = _resize_linear(linear, *resize_to)
        return linear

    def _pipeline(
        self,
        clip: Clip,
        resize_to: tuple[int, int] | None,
        consume: Callable[[int, np.ndarray], None],
        bump: Callable[[int], None],
        on_error: Callable[[], None] = lambda: None,
    ) -> int:
        """Decode a clip and call consume(index, linear) per frame, possibly out of order.

        on_error runs as soon as any frame fails, so a consumer waiting for a
        frame that will now never arrive can give up.
        """
        frame_bytes = clip.width * clip.height * 3 * 2
        matrix = self._matrix(clip)
        workers = max(1, self.settings.workers)

        proc = subprocess.Popen(
            [self.tools.ffmpeg, "-v", "error", "-nostdin", "-i", str(clip.path),
             "-vf", DECODE_FILTER, "-f", "rawvideo", "-pix_fmt", "rgb48le", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_NO_WINDOW,
        )
        decoder_stderr = drain(proc.stderr)

        free: queue.Queue = queue.Queue()
        for _ in range(workers + 2):
            free.put(bytearray(frame_bytes))
        pending: queue.Queue = queue.Queue()

        errors: list[str] = []
        lock = threading.Lock()
        completed = 0
        produced = 0

        out_of_memory = False

        def fail() -> None:
            nonlocal out_of_memory
            out_of_memory |= isinstance(sys.exc_info()[1], MemoryError)
            errors.append(traceback.format_exc())
            on_error()

        def reader() -> None:
            nonlocal produced
            try:
                while not self.cancelled() and not errors:
                    buffer = free.get()
                    view = memoryview(buffer)
                    filled = 0
                    while filled < frame_bytes:
                        got = proc.stdout.readinto(view[filled:])
                        if not got:
                            break
                        filled += got
                    if filled < frame_bytes:
                        free.put(buffer)
                        break
                    pending.put((produced, buffer))
                    produced += 1
            except Exception:
                fail()
            finally:
                for _ in range(workers):
                    pending.put(None)

        def worker() -> None:
            nonlocal completed
            while True:
                item = pending.get()
                if item is None:
                    return
                index, buffer = item
                if errors or self.cancelled():
                    free.put(buffer)
                    continue
                try:
                    codes = np.frombuffer(buffer, dtype="<u2").reshape(clip.height, clip.width, 3)
                    consume(index, self._transform(codes, matrix, resize_to))
                except Exception:
                    fail()
                finally:
                    free.put(buffer)
                with lock:
                    completed += 1
                    count = completed
                bump(count)

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
        reader_thread = threading.Thread(target=reader, daemon=True)
        for thread in threads:
            thread.start()
        reader_thread.start()
        reader_thread.join()
        for thread in threads:
            thread.join()

        if proc.poll() is None:
            proc.kill()
        proc.wait()
        stderr = decoder_stderr()
        proc.stdout.close()
        proc.stderr.close()

        if out_of_memory:
            raise OutOfMemory(errors[0])
        if errors:
            raise RuntimeError(errors[0])
        self._check_cancelled()
        if stderr:
            self.log(f"  ffmpeg: {stderr[:400]}")
        return produced

    def run(self, clips: list[Clip]) -> list[Path]:
        total_frames = sum(c.frames for c in clips) or 1
        progress = Progress(clip_count=len(clips), frames_total=total_frames)
        done_frames = 0
        outputs: list[Path] = []

        for index, clip in enumerate(clips, start=1):
            self._check_cancelled()
            progress.clip_index = index
            progress.clip_name = clip.path.name

            def bump(frame_number: int) -> None:
                progress.frames_done = done_frames + frame_number
                self.on_progress(progress)

            outputs.extend(self._write_clip(clip, bump))
            done_frames += clip.frames
            progress.frames_done = done_frames
            self.on_progress(progress)

        return outputs

    def _write_clip(self, clip: Clip, bump: Callable[[int], None]) -> list[Path]:
        settings = self.settings
        width, height = target_size(clip, settings.resolution)
        resize = (width, height) if (width, height) != (clip.width, clip.height) else None

        gamut, detected = self._resolve_gamut(clip)
        workspace_gamut, colour_space = colour.output_space(settings.workspace, gamut)
        comment = f"Canon R7 EXR Converter: {clip.path.name} | Canon Log 3 | {gamut} -> {workspace_gamut}"

        self.log(f"{clip.name}: {width}x{height}, {clip.frames} frames")
        if not detected and settings.source_gamut == colour.AUTO_GAMUT:
            self.log(f"  Colour space not found in clip, using {gamut}.")
        if clip.log_version and not clip.is_canon_log3:
            self.log(f"  Warning: clip is {clip.log_version}, not Canon Log 3.")

        settings.output_dir.mkdir(parents=True, exist_ok=True)
        outputs: list[Path] = []
        writers: list[Callable[[int, np.ndarray], None]] = []
        prores: _ProResWriter | None = None

        if settings.write_exr:
            folder = settings.output_dir / clip.name
            folder.mkdir(parents=True, exist_ok=True)
            writers.append(self._exr_writer(clip, folder, width, height,
                                            workspace_gamut, colour_space, comment))
            outputs.append(folder)

        if settings.write_prores:
            movie = settings.output_dir / f"{clip.name}.mov"
            prores = _ProResWriter(
                self._prores_command(clip, movie, width, height, workspace_gamut, comment),
                (height, width, 3), self.cancelled,
            )
            writers.append(prores.put)
            outputs.append(movie)

        def consume(index: int, linear: np.ndarray) -> None:
            for write in writers:
                write(index, linear)

        try:
            written = self._pipeline(clip, resize, consume, bump,
                                     on_error=prores.abort if prores else lambda: None)
        except BaseException:
            if prores:
                prores.abort()
                with contextlib.suppress(Exception):
                    prores.finish()
                if prores.broken:
                    raise RuntimeError(f"ProRes encoding failed: {prores.stderr[:400]}") from None
            raise
        if prores:
            stderr = prores.finish()
            if stderr:
                self.log(f"  ffmpeg (ProRes): {stderr[:400]}")
        self.log(f"  {written} frames written")
        return outputs

    def _exr_writer(
        self, clip: Clip, folder: Path, width: int, height: int,
        workspace_gamut: str, colour_space: str | None, comment: str,
    ) -> Callable[[int, np.ndarray], None]:
        settings = self.settings
        pixel_type = BIT_DEPTHS[settings.bit_depth]
        compression = COMPRESSIONS[settings.compression]
        chroma = colour.chromaticities(workspace_gamut)
        fps = int(round(float(clip.fps)))

        def write(index: int, linear: np.ndarray) -> None:
            path = folder / f"{clip.name}.{settings.start_frame + index:04d}.exr"

            spec = oiio.ImageSpec(width, height, 3, pixel_type)
            spec.attribute("compression", compression)
            spec.attribute("oiio:ColorSpace", colour_space)
            spec.attribute("chromaticities", oiio.TypeDesc("float[8]"), chroma)
            spec.attribute("framesPerSecond", oiio.TypeDesc("rational"),
                           (clip.fps.numerator, clip.fps.denominator))
            spec.attribute("comment", comment)
            if clip.camera_model:
                spec.attribute("Make", "Canon")
                spec.attribute("Model", clip.camera_model)
            if clip.lens_model:
                spec.attribute("Lens", clip.lens_model)
            if clip.timecode:
                spec.attribute("smpte:TimeCode", oiio.TypeDesc("timecode"),
                               pack_timecode(clip.timecode, index, fps))

            if pixel_type == "half":
                pixels = _scratch(linear.shape, np.float16)
                np.copyto(pixels, linear)
            else:
                pixels = linear

            out = oiio.ImageOutput.create(str(path))
            if out is None:
                raise RuntimeError(f"Cannot write EXR: {oiio.geterror()}")
            if not out.open(str(path), spec):
                raise RuntimeError(f"Cannot open {path}: {out.geterror()}")
            ok = out.write_image(pixels)
            error = out.geterror()
            out.close()
            if not ok:
                raise RuntimeError(f"Write failed for {path}: {error}")

        return write

    def _prores_command(
        self, clip: Clip, movie: Path, width: int, height: int, workspace_gamut: str, comment: str,
    ) -> list[str]:
        """ffmpeg reading linear rgb48le frames on stdin and writing ProRes."""
        profile = PRORES_PROFILES[self.settings.prores_quality]
        pix_fmt = "yuv444p10le" if profile >= 4 else "yuv422p10le"
        command = [
            self.tools.ffmpeg, "-v", "error", "-nostdin", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb48le", "-video_size", f"{width}x{height}",
            "-framerate", f"{clip.fps.numerator}/{clip.fps.denominator}", "-i", "-",
        ]
        if clip.has_audio:
            command += ["-i", str(clip.path), "-map", "0:v:0", "-map", "1:a:0", "-c:a", "copy"]
        # Tags go on the frames; ffmpeg ignores -color_* output flags after a filter.
        tags = "setparams=range=tv:colorspace=bt709:color_trc=linear"
        if workspace_gamut in _FFMPEG_PRIMARIES:
            tags += f":color_primaries={_FFMPEG_PRIMARIES[workspace_gamut]}"
        command += [
            "-vf", f"{PRORES_FILTER},{tags}", "-c:v", "prores_ks", "-profile:v", str(profile),
            "-vendor", "apl0", "-pix_fmt", pix_fmt,
        ]
        if clip.timecode:
            command += ["-timecode", clip.timecode]
        command += ["-metadata", f"comment={comment}", str(movie)]
        return command


class _ProResWriter:
    """Feeds frames to an ffmpeg ProRes encoder in order, whatever order they arrive in.

    put() only accepts frames within `window` of the next one to write, so memory
    stays bounded and the frame the encoder is waiting for always gets in.
    ProRes is integer, so linear values are clipped to [0, 1].
    """

    def __init__(self, command: list[str], shape: tuple, cancelled: CancelFn, window: int = 6) -> None:
        self.shape = shape
        self.cancelled = cancelled
        self.window = window
        self.cond = threading.Condition()
        self.ready: dict[int, np.ndarray] = {}
        self.free: list[np.ndarray] = []
        self.next = 0
        self.done = False
        self.failed = False
        self.broken = False  # the encoder itself died
        self.stderr = ""
        self.proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, **_NO_WINDOW,
        )
        self._stderr = drain(self.proc.stderr)
        self.thread = threading.Thread(target=self._feed, daemon=True)
        self.thread.start()

    def put(self, index: int, linear: np.ndarray) -> None:
        with self.cond:
            while index >= self.next + self.window and not self.failed:
                if self.cancelled():
                    return  # the pipeline raises Cancelled itself
                self.cond.wait(0.2)
            if self.failed:
                raise RuntimeError("ProRes encoder stopped")
            frame = self.free.pop() if self.free else np.empty(self.shape, np.uint16)

        scaled = _scratch(linear.shape, np.float32)
        np.clip(linear, 0.0, 1.0, out=scaled)
        np.multiply(scaled, 65535.0, out=scaled)
        np.rint(scaled, out=scaled)
        np.copyto(frame, scaled, casting="unsafe")

        with self.cond:
            self.ready[index] = frame
            self.cond.notify_all()

    def _feed(self) -> None:
        while True:
            with self.cond:
                self.cond.wait_for(lambda: self.next in self.ready or self.done or self.failed)
                if self.failed or self.next not in self.ready:
                    break
                frame = self.ready.pop(self.next)
            try:
                self.proc.stdin.write(frame.data)
            except OSError:
                self.broken = True
                self.abort()
                break
            with self.cond:
                self.next += 1
                self.free.append(frame)
                self.cond.notify_all()
        with contextlib.suppress(OSError):
            self.proc.stdin.close()

    def abort(self) -> None:
        with self.cond:
            self.failed = True
            self.cond.notify_all()

    def finish(self) -> str:
        """Flush the remaining frames, wait for the encoder and return its stderr."""
        with self.cond:
            self.done = True
            self.cond.notify_all()
        if self.failed and self.proc.poll() is None:
            self.proc.kill()  # before the join: it unblocks a write stuck on a dead encoder
        self.thread.join()
        code = self.proc.wait()
        self.stderr = stderr = self._stderr()
        self.proc.stderr.close()
        if self.cancelled():
            return stderr
        if self.failed or code != 0:
            raise RuntimeError(f"ProRes encoding failed: {stderr[:400] or 'encoder stopped'}")
        return stderr


def _resize_linear(image: np.ndarray, width: int, height: int) -> np.ndarray:
    buf = oiio.ImageBuf(np.ascontiguousarray(image))
    roi = oiio.ROI(0, width, 0, height, 0, 1, 0, image.shape[2])
    return oiio.ImageBufAlgo.resize(buf, "lanczos3", roi=roi).get_pixels("float")
