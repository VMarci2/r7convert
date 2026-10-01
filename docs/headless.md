# Headless mode

Headless mode runs the same converter without a window, for batch jobs, render
farm scripts and pipeline tools. It starts whenever `--convert` is on the
command line, and the output is identical to pressing **Convert** with the
Advanced tab at its defaults.

```text
"Canon R7 EXR Converter vX.Y.Z.exe" --convert CLIP [CLIP ...] --out DIR [--log FILE] [--prores] [--no-exr]
```

## Options

| Option | Meaning |
|---|---|
| `--convert CLIP ...` | One or more clip files. Every argument after it that doesn't start with `--` is a clip. Folders and wildcards are **not** expanded: list the files (see [batching](#batch-a-folder)). |
| `--out DIR` | **Required.** Output folder; created if missing. |
| `--log FILE` | Write progress and errors to FILE (overwritten each run). **Essential with the exe**: it is a windowed program and has no console. The folder must already exist. |
| `--prores` | Also write a ProRes `.mov` (422 HQ, 10-bit). |
| `--no-exr` | Skip the EXR sequence. With `--prores`, writes ProRes only. |

## Fixed settings

There are no flags for the Advanced-tab options. Headless mode always uses:

| Setting | Value |
|---|---|
| Camera colour space | Detected from the clip (Canon Cinema Gamut if exiftool is missing) |
| Output colour space | ACEScg (AP1), scene linear |
| Size | Full (source resolution) |
| EXR | 16-bit half, ZIP, frames numbered from `0001` |
| ProRes | 422 HQ, 10-bit, with the clip's timecode and audio |

For anything else, use the app. Output goes where the app puts it
([Output](converting.md#output)), and existing files are **overwritten without
asking**.

## Running the exe

The exe is a windowed program, so a shell that starts it neither waits for it
nor sees any output. Make the shell wait, and read the result from the log and
the exit code. The installer puts the exe in
`%LOCALAPPDATA%\Programs\Canon R7 EXR Converter\`; a zip copy runs from wherever
it was extracted.

=== "PowerShell"

    ```powershell
    $exe = "$env:LOCALAPPDATA\Programs\Canon R7 EXR Converter\Canon R7 EXR Converter v2.3.0.exe"
    $p = Start-Process $exe -Wait -PassThru -ArgumentList `
         '--convert "D:\Shoot\A001.MP4" --out "D:\Shoot\EXR" --log "D:\Shoot\convert.log" --prores'
    $p.ExitCode
    ```

=== "Command Prompt / .bat"

    ```bat
    start "" /wait "Canon R7 EXR Converter v2.3.0.exe" ^
          --convert "D:\Shoot\A001.MP4" --out "D:\Shoot\EXR" --log "D:\Shoot\convert.log"
    echo exit code %ERRORLEVEL%
    ```

=== "From source"

    In a development checkout, output goes to the console, so `--log` is optional:

    ```text
    .venv\Scripts\python.exe -m r7convert --convert A001.MP4 A002.MP4 --out EXR
    ```

!!! note "The exe name includes the version"
    After an update the exe is called `... vX.Y.Z.exe` with the new number.
    Scripts that should survive updates can look it up instead:
    `(Get-ChildItem "$env:LOCALAPPDATA\Programs\Canon R7 EXR Converter\Canon R7 EXR Converter v*.exe").FullName`

## Batch a folder

A run stops at the first clip that fails, and all clips are read before any are
converted. Running one clip per invocation keeps one bad file from stopping the
rest, and gives each clip its own log:

```powershell
$exe  = (Get-ChildItem "$env:LOCALAPPDATA\Programs\Canon R7 EXR Converter\Canon R7 EXR Converter v*.exe").FullName
$out  = "D:\Shoot\EXR"
$logs = New-Item -ItemType Directory -Force "D:\Shoot\logs"
Get-ChildItem "D:\Shoot\*.MP4" | ForEach-Object {
    $log = Join-Path $logs "$($_.BaseName).log"
    $a   = "--convert `"$($_.FullName)`" --out `"$out`" --log `"$log`" --prores"
    $p   = Start-Process $exe -ArgumentList $a -Wait -PassThru
    if ($p.ExitCode -ne 0) { Write-Warning "$($_.Name) failed - see $log" }
}
```

## Log and exit codes

Exit code `0` means every clip converted; `1` means something failed, and the
last log line starts with `error:`. A successful log:

```text
Canon R7 EXR Converter v2.3.0
ffmpeg: C:\...\tools\ffmpeg\ffmpeg.exe
exiftool: C:\...\tools\exiftool\exiftool.exe
9O4A4288: 3840x2160, 135 frames
  135 frames written
```

Watch for `exiftool: None` (gamut can't be detected, so Cinema Gamut is used),
`Colour space not found in clip` and `Warning: clip is ..., not Canon Log 3`.
None of these stop the run, so a script should check for them.

## Gotchas

| Situation | What happens |
|---|---|
| `--out` missing, or the `--log` folder missing | Unhandled error before logging starts: nothing reaches the log, and the exe may show an error dialog. Always pass `--out`, and create the log folder first. |
| Stopping a run | There is no cancel flag. Ending the process leaves partial output: the frames written so far and an unplayable `.mov`. |
| Trimmed test clips | Clips cut with `ffmpeg -c copy` lose Canon's metadata, so the gamut falls back to Cinema Gamut. Test with camera originals. |
| Speed | About 0.35 s per 4K frame (about 3 fps), so a 5 s clip takes about 45 s. Running several instances at once rarely helps: the bottleneck is moving frames between processes, not the CPU. |
| Updates | Headless runs never check for or install updates. |
