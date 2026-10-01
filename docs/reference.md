# Technical reference

## How the conversion works

For every frame, the converter:

| Step | What happens |
|---|---|
| 1. Decode | Reads the camera's 10-bit 4:2:2 HEVC video with ffmpeg. |
| 2. Linearise | Removes the Canon Log 3 curve, giving linear light (18% grey = 0.18). |
| 3. Colour | Converts from the camera's colour space (Cinema Gamut, read from the clip's metadata) to ACEScg. |
| 4. Write | Saves a 16-bit half-float EXR with ZIP compression, frame rate, timecode, camera and lens information. |

## Specifications

| Item | Value |
|---|---|
| Input | HEVC (H.265) Rext, 10-bit 4:2:2, Canon Log 3, as recorded by the EOS R7 |
| Log decode | Canon's published Canon Log 3 curve, on the legal-range code mapping: `(code − 64) / 876` |
| Linear scale | 18% grey card = 0.18 |
| Colour conversion | 3 × 3 matrix from the camera gamut to ACEScg by default, or to Rec.709, with Bradford adaptation where white points differ. Optionally none (camera primaries kept) |
| Resizing | Lanczos, applied in linear light |
| EXR | Written with OpenImageIO; half or float, RGB, with chromaticities, frame rate, SMPTE timecode, camera, lens and a comment |
| ProRes | `prores_ks`, 10-bit, linear values clipped to [0, 1], Rec.709 matrix, legal range, with timecode and source audio |
| Dailies | Each clip encoded separately, then joined without re-encoding. Picture passed through unchanged (Canon Log read as legal range, code values kept) and tagged Rec.709. H.264 uses x264, OpenH264 or Media Foundation, whichever the ffmpeg build has; the bundled build uses OpenH264 |
| Libraries | FFmpeg (decode and ProRes, LGPL), ExifTool (Canon metadata), numpy, OpenImageIO, tkinter. Built with PyInstaller |

## Why legal range?

R7 files are flagged *full range*, but Canon Log 3 is anchored on the legal
range. Black lands on 10-bit code 128, which is where the noise floor of real R7
footage sits, and Canon's three published anchors only line up on this scale:

| | This converter | Canon spec |
|---|---|---|
| Black, linear 0.0 | 7.3059 IRE (code 128) | 7.3 IRE |
| 18% grey, linear 0.2* | 32.7954 IRE | 32.8 IRE |
| 90% white, linear 1.0* | 58.6138 IRE | 58.6 IRE |

\* In Canon's own scale, where 0.2 is an 18% grey card. The converter rescales
by 0.9 so that 18% grey becomes 0.18.

## Verification

All three output colour spaces were compared against Nuke's own
`CanonLog3 CinemaGamut D55` OCIO transforms on real R7 footage. Median
difference: 0.017% for camera primaries, 0.09% for Rec.709, 0.08% for ACEScg.

## Source

The source code is at
[github.com/VMarci2/r7convert](https://github.com/VMarci2/r7convert).
