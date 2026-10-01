---
hide:
  - navigation
---

# Canon R7 EXR Converter

![Canon R7 EXR Converter](assets/banner.png)

Converts video recorded on a **Canon EOS R7 in Canon Log 3** into **scene-linear
OpenEXR sequences** that load straight into Nuke. Each clip becomes a folder with
one EXR per frame, with an optional ProRes `.mov` for review.

[Download the latest version](https://github.com/VMarci2/r7convert/releases/latest){ .md-button .md-button--primary }
[Install guide](install.md){ .md-button }

## What it does

For every frame the converter:

| Step | What happens |
|---|---|
| 1. Decode | Reads the camera's 10-bit 4:2:2 HEVC video with ffmpeg. |
| 2. Linearise | Removes the Canon Log 3 curve, giving linear light (18% grey = 0.18). |
| 3. Colour | Converts from the camera's colour space (Cinema Gamut, read from the clip) to ACEScg. |
| 4. Write | Saves a 16-bit half-float EXR with ZIP compression, frame rate, timecode, camera and lens information. |

You don't need to know any of this to use it. Add clips, pick a folder, press
**Convert**.

## Where to go next

<div class="grid cards" markdown>

- **[Installing and updating](install.md)**: get it running on Windows, and how updates work.
- **[Converting clips](converting.md)**: the everyday workflow.
- **[Opening in Nuke](nuke.md)**: set Nuke up once so the colours are right.
- **[Advanced settings](advanced.md)**: colour spaces, size, EXR options and ProRes.
- **[Headless mode](headless.md)**: command-line use for batch jobs and pipeline scripts.
- **[Troubleshooting](troubleshooting.md)**: what the messages mean.

</div>

!!! tip "From inside the app"
    **Help → Documentation** opens this site, and **Help → Check for updates…**
    looks for a newer version.
