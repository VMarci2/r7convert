# Installing and updating

Runs on **64-bit Windows 10 or 11**. ffmpeg and exiftool come bundled; nothing
else needs installing.

## Install

Download from the [latest release](https://github.com/VMarci2/r7convert/releases/latest).

=== "Installer (recommended)"

    1. Download `Canon-R7-EXR-Converter-vX.Y.Z-Setup.exe`.
    2. Run it. No admin rights are needed, so it works on locked-down lab machines.
       It installs into `%LOCALAPPDATA%\Programs\Canon R7 EXR Converter`.
    3. Start it from the Start menu (or the desktop shortcut, if you ticked it).

    The installed version **updates itself** (see below).

=== "Zip"

    1. Download `Canon-R7-EXR-Converter-vX.Y.Z.zip`.
    2. Extract the **whole** zip to a normal folder, for example Documents. Keep
       all the files together: the `tools` and `_internal` folders are needed.
    3. Run `Canon R7 EXR Converter vX.Y.Z.exe`.

    The zip version tells you when there is an update, but you download and
    extract the new zip yourself.

!!! note "Windows protected your PC"
    The first time, Windows SmartScreen may block the app because it is not
    code-signed. Click **More info**, then **Run anyway**.

## Updates

When the app starts, it checks GitHub for a newer version. You can also check
any time with **Help → Check for updates…** or the button on the **Advanced** tab.

If there is one, it shows what's new and asks whether to install it:

- **Installed version:** click **Yes**. The app downloads the new installer,
  checks that it arrived intact, closes, updates and opens again by itself.
- **Zip version:** click **Yes** to open the download page, then replace your
  folder with the new zip.

The check never interrupts a running conversion. If you're offline, the
startup check fails silently.

!!! warning "Versions older than 2.3.0"
    Versions before 2.3.0 can't check for updates. Install 2.3.0 or later by hand
    once; after that, updates arrive automatically.

## Uninstall

Use **Settings → Apps → Installed apps → Canon R7 EXR Converter - FVFX →
Uninstall**. For the zip version, delete the folder.
