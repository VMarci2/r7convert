# Changelog

## 2.3.0

- Optional ProRes .mov output, alongside the EXRs or instead of them (Advanced
  tab, Format). Quality defaults to 422 HQ 10-bit; 422, LT, Proxy, 4444 and
  4444 XQ are also available. Carries the clip's timecode and audio.
- ProRes follows the Output colour space, so it is scene-linear like the EXRs.
  Being integer, it clips everything above 1.0: use the EXRs for compositing.
- Advanced tab split into Colour and Format groups. EXR settings only show when
  EXR is ticked, and ProRes quality only when ProRes is ticked.
- Headless mode takes `--prores` and `--no-exr`.
- Updates: the app checks GitHub for a newer version when it starts, and on
  demand from Advanced → Check for updates. The installed version downloads the
  new installer, checks it, and updates and reopens by itself; the zip version
  opens the download page. Copies older than 2.3.0 can't check, so install
  2.3.0 by hand once.

## 2.2.0

- Default output is now ACEScg: Canon Log 3 is linearised and converted from the
  camera's colour space to ACEScg (AP1). Read it in Nuke as `ACEScg`.
- Linear with camera primaries and Linear Rec.709 remain available under Advanced.
- Manual and README now explain setting Nuke to OCIO with an ACES 1.3 config,
  and no longer recommend Rec.709 / nuke-default.
- Optional single-file Windows installer (`... Setup.exe`) alongside the zip:
  installs per user, no admin rights needed, with Start menu shortcut and
  uninstaller.

## 2.1.0

- Default output is now linear with the camera's own primaries (Cinema Gamut for
  R7 footage): the Canon Log 3 curve is removed and no colour matrix is applied.
- Linear Rec.709 and ACEScg remain available under Advanced.
- Version number shown in the window title, the exe, the folder and the zip.

## 2.0.0

- First shared release: standalone Windows app with ffmpeg and exiftool bundled.
- Canon Log 3 to linear EXR, camera colour space read from the clip's metadata.
- ProRes output removed.
