# Troubleshooting

## Messages

| Message | Meaning |
|---|---|
| ffmpeg was not found | Files are missing from the program folder. Reinstall, or extract the whole zip again. |
| exiftool not found | Files are missing from the program folder. Canon Cinema Gamut is used until you reinstall or extract the zip again. |
| Colour space not found in clip | The clip has no Canon colour space tag (often because it was trimmed or re-exported). Canon Cinema Gamut is used. Set **Camera colour space** on the Advanced tab if that's wrong. |
| N clip(s) are not Canon Log 3 | The clip was recorded with a different picture profile. The output colours will be wrong: the converter only understands Canon Log 3. |
| Your computer ran out of memory | Other programs are using almost all of the PC's memory. Close Nuke, SynthEyes, other 3D or video apps and browser tabs you don't need, then convert again. The converter itself needs about 1 GB. |
| Could not read … | The file isn't a readable video file. |
| ProRes encoding failed | The `.mov` couldn't be written, often because the drive is full or the file is open in another program. The message includes ffmpeg's reason. |
| Tick EXR or ProRes on the Advanced tab | Both formats are switched off. Tick at least one. |
| Dailies failed: ffmpeg failed … | A clip couldn't be read or the file couldn't be written, often because the drive is full or the file is open in a player. The message includes ffmpeg's reason. |
| This ffmpeg has no H.264 encoder | Rare; the bundled ffmpeg always has one. Choose a ProRes format on the Dailies tab instead. |
| Wait for the … to finish first | Converting and making dailies can't run at the same time. |
| Update check failed | GitHub couldn't be reached. Check the internet connection, or try again later. |

## Common problems

??? question "The colours look washed out or too saturated in Nuke"
    Nuke isn't set up for ACES, or the Read node's colorspace doesn't match the
    files. Follow [Opening in Nuke](nuke.md).

??? question "The ProRes looks different from the EXRs in the highlights"
    That's expected: ProRes can't store values above 1.0, so bright areas are
    clipped. See [ProRes](advanced.md#prores).

??? question "Windows says 'Windows protected your PC'"
    The app isn't code-signed. Click **More info**, then **Run anyway**. This
    only happens the first time.

??? question "Conversion failed: out of memory"
    Converting 4K needs about 1 GB of memory, but Windows can only give it
    that if other programs leave room. Nuke, SynthEyes and browsers with lots of
    tabs can use 5–10 GB each. Close what you don't need and convert again;
    frames already written are simply replaced.

??? question "The disk filled up"
    4K EXRs take about 30 MB per frame. Check the estimate under the
    **Save to** folder before converting, and use a smaller size or DWAA
    compression on the Advanced tab if space is tight.

??? question "The update was offered but nothing happened"
    The installer runs silently and reopens the app when it's done, which can
    take up to a minute. If the app doesn't come back, start it from the Start
    menu, or download the installer from the
    [releases page](https://github.com/VMarci2/r7convert/releases/latest).
