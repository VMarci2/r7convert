"""Tkinter front end."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import colour, update
from .convert import (
    BIT_DEPTHS,
    COMPRESSIONS,
    PRORES_PROFILES,
    RESOLUTIONS,
    Cancelled,
    Converter,
    Progress,
    Settings,
    estimate_bytes,
    human_bytes,
    probe_clips,
)
from . import __version__
from .media import VIDEO_SUFFIXES, Clip, Tools, ToolsMissing

APP_NAME = "Canon R7 EXR Converter - FVFX"
WINDOW_TITLE = f"{APP_NAME}  v{__version__}"
PAD = 4


class App(ttk.Frame):
    def __init__(self, root: tk.Tk, tools: Tools) -> None:
        super().__init__(root, padding=PAD)
        self.root = root
        self.tools = tools
        self.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.paths: list[Path] = []
        self.probed: dict[Path, Clip] = {}
        self.messages: queue.Queue = queue.Queue()
        self.cancel_flag = threading.Event()
        self.last_output: Path | None = None

        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=0, column=0, sticky="nsew")
        self.convert_tab = ttk.Frame(self.notebook, padding=PAD)
        self.advanced_tab = ttk.Frame(self.notebook, padding=PAD)
        self.notebook.add(self.convert_tab, text="Convert")
        self.notebook.add(self.advanced_tab, text="Advanced")

        self._build_convert()
        self._build_advanced()
        self._build_menu()
        self._poll()

        self.update_window: tk.Toplevel | None = None
        self.update_cancel = threading.Event()
        if getattr(sys, "frozen", False):
            update.clean_downloads()
            self.root.after(1500, lambda: self.check_updates(manual=False))

    def _build_convert(self) -> None:
        tab = self.convert_tab
        tab.columnconfigure(0, weight=1)

        clips = ttk.LabelFrame(tab, text="Clips", padding=PAD)
        clips.grid(row=0, column=0, sticky="nsew")
        clips.columnconfigure(0, weight=1)
        clips.rowconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        self.listbox = tk.Listbox(clips, height=6, selectmode="extended", activestyle="none")
        self.listbox.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(clips, orient="vertical", command=self.listbox.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=bar.set)

        buttons = ttk.Frame(clips)
        buttons.grid(row=0, column=2, sticky="n", padx=(PAD, 0))
        for text, command in (("Add clips…", self.add_files), ("Add folder…", self.add_folder),
                              ("Remove", self.remove_selected), ("Clear", self.clear_clips)):
            ttk.Button(buttons, text=text, command=command, width=12).pack(fill="x", pady=(0, 2))

        where = ttk.LabelFrame(tab, text="Save to", padding=PAD)
        where.grid(row=1, column=0, sticky="ew", pady=(PAD, 0))
        where.columnconfigure(0, weight=1)
        self.output_var = tk.StringVar()
        ttk.Entry(where, textvariable=self.output_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(where, text="Choose…", command=self.pick_output, width=10).grid(
            row=0, column=1, padx=(PAD, 0)
        )

        self.summary_var = tk.StringVar(value="No clips added.")
        ttk.Label(tab, textvariable=self.summary_var).grid(row=2, column=0, sticky="w", pady=(PAD, 0))
        self.warning_var = tk.StringVar(value="")
        ttk.Label(tab, textvariable=self.warning_var, foreground="#b45309").grid(
            row=3, column=0, sticky="w"
        )

        self.progress = ttk.Progressbar(tab, mode="determinate", maximum=1000)
        self.progress.grid(row=4, column=0, sticky="ew", pady=(PAD, 0))

        actions = ttk.Frame(tab)
        actions.grid(row=5, column=0, sticky="ew", pady=(PAD, 0))
        actions.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(actions, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.convert_button = ttk.Button(actions, text="Convert", command=self.start, width=12)
        self.convert_button.grid(row=0, column=1)
        self.cancel_button = ttk.Button(
            actions, text="Cancel", command=self.cancel, width=10, state="disabled"
        )
        self.cancel_button.grid(row=0, column=2, padx=(PAD, 0))

        details = ttk.LabelFrame(tab, text="Log", padding=2)
        details.grid(row=6, column=0, sticky="nsew", pady=(PAD, 0))
        details.columnconfigure(0, weight=1)
        details.rowconfigure(0, weight=1)
        tab.rowconfigure(6, weight=1)
        self.log_text = tk.Text(
            details, height=5, wrap="word", state="disabled",
            font=("Consolas", 9), background="#1e1e1e", foreground="#d4d4d4",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_bar = ttk.Scrollbar(details, orient="vertical", command=self.log_text.yview)
        log_bar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_bar.set)

        if not self.tools.exiftool:
            self.write_log("exiftool not found: colour space can't be read from clips, "
                           "Canon Cinema Gamut will be used.")

    def _build_advanced(self) -> None:
        tab = self.advanced_tab
        tab.columnconfigure(0, weight=1)

        # Colour applies to every format; the format group only decides how it is stored.
        look = ttk.LabelFrame(tab, text="Colour", padding=PAD)
        look.grid(row=0, column=0, sticky="ew")
        gamuts = [colour.AUTO_GAMUT] + [g for g in colour.GAMUTS if g != "ACEScg (AP1)"]
        self.gamut_var = self._combo(look, 0, "Camera colour space", gamuts)
        self.workspace_var = self._combo(look, 1, "Output colour space", list(colour.WORKSPACES))

        fmt = ttk.LabelFrame(tab, text="Format", padding=PAD)
        fmt.grid(row=1, column=0, sticky="ew", pady=(PAD, 0))
        self.resolution_var = self._combo(fmt, 0, "Size", list(RESOLUTIONS))

        self.exr_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(fmt, text="EXR sequence", variable=self.exr_var).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(PAD, 0)
        )
        self.bitdepth_var = self._combo(fmt, 2, "    Bit depth", list(BIT_DEPTHS))
        self.compression_var = self._combo(fmt, 3, "    Compression", list(COMPRESSIONS))
        ttk.Label(fmt, text="    First frame").grid(row=4, column=0, sticky="w", pady=2)
        self.start_var = tk.StringVar(value="1")
        ttk.Spinbox(fmt, from_=0, to=9999999, textvariable=self.start_var, width=10).grid(
            row=4, column=1, sticky="w", padx=(PAD, 0), pady=2
        )

        self.prores_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(fmt, text="ProRes .mov", variable=self.prores_var).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(PAD, 0)
        )
        self.prores_quality_var = self._combo(fmt, 6, "    Quality", list(PRORES_PROFILES))
        ttk.Label(
            fmt, foreground="#b45309", wraplength=380, justify="left",
            text="ProRes can't hold values above 1.0, so bright highlights clip. "
                 "Use the EXRs for compositing.",
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 2))

        self.exr_rows = [w for r in (2, 3, 4) for w in fmt.grid_slaves(row=r)]
        self.prores_rows = [w for r in (6, 7) for w in fmt.grid_slaves(row=r)]

        ttk.Button(tab, text="Reset to defaults", command=self.reset_defaults).grid(
            row=2, column=0, sticky="w", pady=(PAD * 2, 0)
        )

        updates = ttk.LabelFrame(tab, text="Updates", padding=PAD)
        updates.grid(row=3, column=0, sticky="ew", pady=(PAD * 2, 0))
        updates.columnconfigure(0, weight=1)
        ttk.Label(updates, text=f"Version {__version__}").grid(row=0, column=0, sticky="w")
        self.update_button = ttk.Button(updates, text="Check for updates",
                                        command=lambda: self.check_updates(manual=True))
        self.update_button.grid(row=0, column=1)

        for var in (self.exr_var, self.prores_var):
            var.trace_add("write", lambda *_: self._show_format_rows())
        for var in (self.gamut_var, self.workspace_var, self.resolution_var,
                    self.bitdepth_var, self.compression_var, self.exr_var,
                    self.prores_var, self.prores_quality_var):
            var.trace_add("write", lambda *_: self.refresh_summary())
        self._show_format_rows()

    def _show_format_rows(self) -> None:
        for rows, on in ((self.exr_rows, self.exr_var.get()), (self.prores_rows, self.prores_var.get())):
            for widget in rows:
                widget.grid() if on else widget.grid_remove()

    def _combo(self, parent, row: int, label: str, values: list[str]) -> tk.StringVar:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        var = tk.StringVar(value=values[0])
        ttk.Combobox(parent, textvariable=var, values=values, state="readonly", width=28).grid(
            row=row, column=1, sticky="w", padx=(PAD, 0), pady=2
        )
        return var

    def reset_defaults(self) -> None:
        self.gamut_var.set(colour.AUTO_GAMUT)
        self.workspace_var.set(next(iter(colour.WORKSPACES)))
        self.resolution_var.set(next(iter(RESOLUTIONS)))
        self.bitdepth_var.set(next(iter(BIT_DEPTHS)))
        self.compression_var.set(next(iter(COMPRESSIONS)))
        self.start_var.set("1")
        self.exr_var.set(True)
        self.prores_var.set(False)
        self.prores_quality_var.set(next(iter(PRORES_PROFILES)))

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="Manual (online)", command=lambda: webbrowser.open(update.MANUAL_URL))
        help_menu.add_command(label="Headless mode (online)",
                              command=lambda: webbrowser.open(update.HEADLESS_URL))
        offline = _app_dir() / "Manual.pdf"
        if offline.is_file():
            help_menu.add_command(label="Manual (offline copy)", command=lambda: os.startfile(offline))
        help_menu.add_command(label="Documentation website", command=lambda: webbrowser.open(update.DOCS_URL))
        help_menu.add_separator()
        help_menu.add_command(label="Check for updates…", command=lambda: self.check_updates(manual=True))
        help_menu.add_command(label="Release notes", command=lambda: webbrowser.open(update.RELEASES_PAGE))
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.configure(menu=menubar)

    def _converting(self) -> bool:
        return str(self.cancel_button.cget("state")) == "normal"

    def check_updates(self, manual: bool) -> None:
        if manual:
            self.update_button.configure(state="disabled", text="Checking…")

        def work() -> None:
            try:
                self.messages.put(("update", (update.fetch_latest(), None, manual)))
            except Exception as error:
                self.messages.put(("update", (None, error, manual)))

        threading.Thread(target=work, daemon=True).start()

    def _on_update_checked(self, release, error, manual: bool) -> None:
        if manual:
            self.update_button.configure(state="normal", text="Check for updates")
        if error is not None:
            if manual and getattr(error, "code", None) == 404:
                messagebox.showinfo("Up to date", "No update has been published yet.")
            elif manual:
                messagebox.showerror("Update check failed",
                                     f"Couldn't reach GitHub. Check the internet connection.\n\n{error}")
            return
        if not update.is_newer(release):
            if manual:
                messagebox.showinfo("Up to date", f"You have the latest version ({__version__}).")
            return
        if self._converting():
            if manual:
                messagebox.showinfo("Update available",
                                    f"Version {release.version} is available. Finish or cancel the "
                                    "conversion, then check again.")
            return
        notes = release.notes.strip()
        if len(notes) > 700:
            notes = notes[:700].rsplit("\n", 1)[0] + "\n…"
        header = f"Version {release.version} is available (you have {__version__}).\n\n{notes}\n\n"
        if update.is_installed():
            if messagebox.askyesno("Update available", header + "Install it now? The app closes, "
                                   "updates and opens again by itself."):
                self._download_update(release)
        elif messagebox.askyesno("Update available", header + "Open the download page?"):
            webbrowser.open(update.RELEASES_PAGE)

    def _download_update(self, release) -> None:
        window = self.update_window = tk.Toplevel(self.root)
        window.title("Updating")
        window.resizable(False, False)
        window.transient(self.root)
        window.grab_set()
        frame = ttk.Frame(window, padding=PAD * 3)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=f"Downloading version {release.version}…").pack(anchor="w")
        self.update_progress = ttk.Progressbar(frame, mode="determinate", maximum=1000, length=320)
        self.update_progress.pack(fill="x", pady=PAD * 2)
        ttk.Button(frame, text="Cancel", command=self.update_cancel.set).pack(anchor="e")
        window.protocol("WM_DELETE_WINDOW", self.update_cancel.set)
        self.update_cancel.clear()

        def work() -> None:
            try:
                path = update.download(
                    release, lambda f: self.messages.put(("update_progress", f)), self.update_cancel.is_set,
                )
                self.messages.put(("update_ready", path))
            except Exception as error:
                self.messages.put(("update_failed", str(error)))

        threading.Thread(target=work, daemon=True).start()

    def _on_update_downloaded(self, path: Path | None) -> None:
        if self.update_window:
            self.update_window.destroy()
            self.update_window = None
        if path is None:
            return
        try:
            update.launch_installer(path)
        except OSError as error:
            messagebox.showerror("Update failed", f"Couldn't start the installer.\n\n{error}")
            return
        self.root.destroy()

    def add_files(self) -> None:
        picked = filedialog.askopenfilenames(
            title="Choose clips",
            filetypes=[("Video", "*.mp4 *.MP4 *.mov *.MOV *.mxf *.MXF"), ("All files", "*.*")],
        )
        self._add([Path(p) for p in picked])

    def add_folder(self) -> None:
        folder = filedialog.askdirectory(title="Choose a folder of clips")
        if not folder:
            return
        found = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in VIDEO_SUFFIXES)
        if not found:
            messagebox.showinfo("No clips", "No video files in that folder.")
            return
        self._add(found)

    def _add(self, paths: list[Path]) -> None:
        added = [p for p in paths if p not in self.paths]
        for path in added:
            self.paths.append(path)
            self.listbox.insert("end", path.name)
        if not added:
            return
        if not self.output_var.get():
            self.output_var.set(str(self.paths[0].parent / "EXR"))
        self.summary_var.set("Reading clips…")
        threading.Thread(target=self._probe_worker, args=(added,), daemon=True).start()

    def _probe_worker(self, paths: list[Path]) -> None:
        for path in paths:
            try:
                clip = probe_clips([path], self.tools)[0]
            except Exception as error:
                self.messages.put(("log", f"Could not read {path.name}: {error}"))
                continue
            self.messages.put(("probed", (path, clip)))
        self.messages.put(("summary", None))

    def remove_selected(self) -> None:
        for index in sorted(self.listbox.curselection(), reverse=True):
            self.probed.pop(self.paths[index], None)
            self.listbox.delete(index)
            del self.paths[index]
        self.refresh_summary()

    def clear_clips(self) -> None:
        self.listbox.delete(0, "end")
        self.paths.clear()
        self.probed.clear()
        self.refresh_summary()

    def pick_output(self) -> None:
        folder = filedialog.askdirectory(title="Save to")
        if folder:
            self.output_var.set(folder)

    def refresh_summary(self) -> None:
        if not self.paths:
            self.summary_var.set("No clips added.")
            self.warning_var.set("")
            return
        clips = [self.probed[p] for p in self.paths if p in self.probed]
        if not clips:
            self.summary_var.set(f"{len(self.paths)} clip(s)")
            return
        frames = sum(c.frames for c in clips)
        sizes = {f"{c.width}x{c.height}" for c in clips}
        size = sizes.pop() if len(sizes) == 1 else "mixed sizes"
        total = human_bytes(estimate_bytes(clips, self._settings()))
        self.summary_var.set(f"{len(clips)} clip(s)  ·  {size}  ·  {frames} frames  ·  ~{total}")
        odd = [c.path.name for c in clips if c.log_version and not c.is_canon_log3]
        self.warning_var.set(f"{len(odd)} clip(s) are not Canon Log 3 ({odd[0]})" if odd else "")

    def _settings(self) -> Settings:
        try:
            start = int(self.start_var.get())
        except (ValueError, AttributeError):
            start = 1
        return Settings(
            output_dir=Path(self.output_var.get()),
            source_gamut=self.gamut_var.get(),
            workspace=self.workspace_var.get(),
            resolution=self.resolution_var.get(),
            bit_depth=self.bitdepth_var.get(),
            compression=self.compression_var.get(),
            start_frame=start,
            write_exr=self.exr_var.get(),
            write_prores=self.prores_var.get(),
            prores_quality=self.prores_quality_var.get(),
        )

    def start(self) -> None:
        if not self.paths:
            messagebox.showwarning("No clips", "Add at least one clip.")
            return
        if not self.output_var.get().strip():
            messagebox.showwarning("No folder", "Choose where to save.")
            return
        settings = self._settings()
        if not (settings.write_exr or settings.write_prores):
            messagebox.showwarning("No format", "Tick EXR or ProRes on the Advanced tab.")
            return
        self.cancel_flag.clear()
        self.convert_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress.configure(value=0)
        self.status_var.set("Starting…")
        threading.Thread(target=self._work, args=(list(self.paths), settings), daemon=True).start()

    def cancel(self) -> None:
        self.cancel_flag.set()
        self.status_var.set("Stopping…")

    def _work(self, paths: list[Path], settings: Settings) -> None:
        def log(message: str) -> None:
            self.messages.put(("log", message))

        def on_progress(progress: Progress) -> None:
            self.messages.put(("progress", (progress.fraction, progress.clip_index, progress.clip_count)))

        try:
            missing = [p for p in paths if p not in self.probed]
            for path, clip in zip(missing, probe_clips(missing, self.tools)):
                self.probed[path] = clip
            clips = [self.probed[p] for p in paths]
            outputs = Converter(self.tools, settings, log, on_progress, self.cancel_flag.is_set).run(clips)
            self.messages.put(("done", (len(clips), settings, outputs)))
        except Cancelled:
            self.messages.put(("cancelled", None))
        except Exception as error:
            self.messages.put(("log", traceback.format_exc()))
            self.messages.put(("error", str(error)))

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "log":
                    self.write_log(payload)
                elif kind == "probed":
                    path, clip = payload
                    self.probed[path] = clip
                elif kind == "summary":
                    self.refresh_summary()
                elif kind == "progress":
                    fraction, index, count = payload
                    self.progress.configure(value=fraction * 1000)
                    self.status_var.set(f"Clip {index}/{count}  —  {fraction * 100:.0f}%")
                elif kind == "done":
                    self._finished(*payload)
                elif kind == "cancelled":
                    self._reset("Stopped")
                elif kind == "error":
                    self._reset("Failed")
                    messagebox.showerror("Conversion failed", payload)
                elif kind == "update":
                    self._on_update_checked(*payload)
                elif kind == "update_progress":
                    if self.update_window:
                        self.update_progress.configure(value=payload * 1000)
                elif kind == "update_ready":
                    self._on_update_downloaded(payload)
                    if payload is not None:
                        return  # the window is gone
                elif kind == "update_failed":
                    self._on_update_downloaded(None)
                    messagebox.showerror("Update failed", payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _finished(self, count: int, settings: Settings, outputs: list[Path]) -> None:
        self.progress.configure(value=1000)
        self._reset("Done")
        self.last_output = settings.output_dir
        total = human_bytes(_size_of(outputs))
        self.write_log(f"Done: {count} clip(s), {total}.")
        if messagebox.askyesno(
            "Done",
            f"Converted {count} clip(s), {total}.\n\n{settings.output_dir}\n\nOpen the folder?",
        ):
            self.open_output()

    def open_output(self) -> None:
        if not self.last_output or not self.last_output.exists():
            return
        if sys.platform == "win32":
            os.startfile(self.last_output)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(self.last_output)])
        else:
            subprocess.Popen(["xdg-open", str(self.last_output)])

    def _reset(self, status: str) -> None:
        self.convert_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.status_var.set(status)

    def write_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


def _app_dir() -> Path:
    """Folder of the exe in a build, the repo root when run from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _size_of(outputs: list[Path]) -> int:
    """Bytes written by this run only, not the whole output folder."""
    total = 0
    try:
        for path in outputs:
            if path.is_dir():
                total += sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            elif path.is_file():
                total += path.stat().st_size
    except OSError:
        pass
    return total


def main() -> int:
    root = tk.Tk()
    root.title(WINDOW_TITLE)
    icon = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "assets" / "icon.ico"
    if icon.is_file():
        try:
            root.iconbitmap(default=str(icon))
        except tk.TclError:
            pass
    root.geometry("620x520")
    root.minsize(520, 440)
    try:
        tools = Tools.discover()
    except ToolsMissing as error:
        root.withdraw()
        messagebox.showerror("ffmpeg missing", str(error))
        return 1
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(root, tools)
    root.mainloop()
    return 0
