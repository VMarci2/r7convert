# Opening in Nuke

The frames are **scene-linear ACEScg**. Set Nuke up for ACES once per script:

1. Open **Edit → Project Settings** (or press ++s++ in the Node Graph) and go to
   the **Color** tab.
2. Set **color management** to **OCIO**.
3. For **OCIO config**, choose an **ACES 1.3** config. The working space becomes
   `scene_linear` (ACEScg).
4. Read the EXRs in, and set the Read node's **colorspace** to **ACEScg**.

!!! danger "Don't use nuke-default or Linear Rec.709"
    Don't use Nuke's legacy colour management (`nuke-default`) with this
    footage, and don't convert to Linear Rec.709. Much of the R7's wide gamut
    falls outside Rec.709 and would be clipped or shifted.

If you chose a different **Output colour space** on the
[Advanced tab](advanced.md#colour), set the Read node to match:

| Output colour space | Read node colorspace |
|---|---|
| ACEScg (default) | `ACEScg` |
| Linear, camera primaries | `Linear CinemaGamut D55` |
| Linear Rec.709 | `Linear Rec.709 (sRGB)` |

*Linear, camera primaries* is only for pipelines that want Cinema Gamut
untouched.

For a ProRes `.mov`, use the same colorspace as the EXRs: it is the same
scene-linear image, just clipped above 1.0 (see [ProRes](advanced.md#prores)).

More detail: Foundry's *OCIO Color Management* page in the Nuke online help.
