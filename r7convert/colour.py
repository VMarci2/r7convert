"""Canon Log 3 decoding and gamut conversion."""

from __future__ import annotations

import numpy as np

CLOG3_THRESHOLD_LOW = 0.04076162
CLOG3_THRESHOLD_HIGH = 0.105357102

# Canon Log 3 uses the legal-range code mapping even though R7 files are flagged full range.
LEGAL_BLACK_10BIT = 64.0
LEGAL_SCALE_10BIT = 876.0


def clog3_to_linear(ire: np.ndarray) -> np.ndarray:
    """Canon Log 3 (legal-range normalised) -> scene linear, 18% grey = 0.18."""
    ire = np.asarray(ire, dtype=np.float64)
    low = -(np.power(10.0, (0.07623209 - ire) / 0.42889912) - 1.0) / 14.98325
    mid = (ire - 0.073059361) / 2.3069815
    high = (np.power(10.0, (ire - 0.069886632) / 0.42889912) - 1.0) / 14.98325
    x = np.where(ire < CLOG3_THRESHOLD_LOW, low, np.where(ire <= CLOG3_THRESHOLD_HIGH, mid, high))
    return x * 0.9


def linear_to_clog3(linear: np.ndarray) -> np.ndarray:
    """Scene linear -> Canon Log 3 (legal-range normalised)."""
    x = np.asarray(linear, dtype=np.float64) / 0.9
    low = -0.42889912 * np.log10(-14.98325 * x + 1.0) + 0.07623209
    mid = 2.3069815 * x + 0.073059361
    high = 0.42889912 * np.log10(14.98325 * x + 1.0) + 0.069886632
    return np.where(x < -0.014, low, np.where(x <= 0.014, mid, high))


def build_decode_lut() -> np.ndarray:
    """16-bit code value -> scene linear. Exact, since the source is 10-bit."""
    code = np.arange(65536, dtype=np.float64) / 65535.0 * 1023.0
    ire = (code - LEGAL_BLACK_10BIT) / LEGAL_SCALE_10BIT
    return clog3_to_linear(ire).astype(np.float32)


D65 = (0.3127, 0.3290)
ACES_WHITE = (0.32168, 0.33767)

# name -> (red xy, green xy, blue xy, white xy)
GAMUTS: dict[str, tuple] = {
    "Canon Cinema Gamut": ((0.7400, 0.2700), (0.1700, 1.1400), (0.0800, -0.1000), D65),
    "BT.709 / sRGB": ((0.640, 0.330), (0.300, 0.600), (0.150, 0.060), D65),
    "BT.2020": ((0.708, 0.292), (0.170, 0.797), (0.131, 0.046), D65),
    "ACEScg (AP1)": ((0.713, 0.293), (0.165, 0.830), (0.128, 0.044), ACES_WHITE),
}

CAMERA_PRIMARIES = "Linear, camera primaries"
ACESCG = "ACEScg"

# label -> (gamut, colour space name written to the EXR header)
# First entry is the default. A gamut of None keeps the clip's own primaries:
# the log curve is removed and no matrix is applied.
WORKSPACES: dict[str, tuple[str | None, str | None]] = {
    ACESCG: ("ACEScg (AP1)", "ACEScg"),
    CAMERA_PRIMARIES: (None, None),
    "Linear Rec.709": ("BT.709 / sRGB", "lin_rec709"),
}

# colour space name for linear data left in a camera gamut
_LINEAR_NAMES: dict[str, str] = {
    "Canon Cinema Gamut": "lin_cinemagamut",
    "BT.709 / sRGB": "lin_rec709",
    "BT.2020": "lin_rec2020",
    "ACEScg (AP1)": "ACEScg",
}


def output_space(workspace: str, source_gamut: str) -> tuple[str, str]:
    """(gamut, colour space name) of the output for a workspace and a clip's gamut."""
    gamut, name = WORKSPACES[workspace]
    if gamut is None:
        return source_gamut, _LINEAR_NAMES[source_gamut]
    return gamut, name

_BRADFORD = np.array(
    [
        [0.8951, 0.2664, -0.1614],
        [-0.7502, 1.7135, 0.0367],
        [0.0389, -0.0685, 1.0296],
    ]
)


def _xyz(xy: tuple[float, float]) -> np.ndarray:
    x, y = xy
    return np.array([x / y, 1.0, (1.0 - x - y) / y])


def normalised_primary_matrix(gamut: tuple) -> np.ndarray:
    red, green, blue, white = gamut
    m = np.array([_xyz(red), _xyz(green), _xyz(blue)]).T
    return m @ np.diag(np.linalg.inv(m) @ _xyz(white))


def chromatic_adaptation(src_white: tuple, dst_white: tuple) -> np.ndarray:
    src = _BRADFORD @ _xyz(src_white)
    dst = _BRADFORD @ _xyz(dst_white)
    return np.linalg.inv(_BRADFORD) @ np.diag(dst / src) @ _BRADFORD


def gamut_matrix(src_name: str, dst_name: str) -> np.ndarray:
    """Linear RGB matrix between two gamuts in GAMUTS."""
    src, dst = GAMUTS[src_name], GAMUTS[dst_name]
    adapt = chromatic_adaptation(src[3], dst[3])
    return np.linalg.inv(normalised_primary_matrix(dst)) @ adapt @ normalised_primary_matrix(src)


def chromaticities(gamut_name: str) -> tuple[float, ...]:
    red, green, blue, white = GAMUTS[gamut_name]
    return (*red, *green, *blue, *white)


AUTO_GAMUT = "Detect from clip"
FALLBACK_GAMUT = "Canon Cinema Gamut"

# Canon ColorSpace2 maker note -> GAMUTS key
_GAMUT_BY_TAG: dict[str, str] = {
    "cinemagamut": "Canon Cinema Gamut",
    "cinema gamut": "Canon Cinema Gamut",
    "bt.2020": "BT.2020",
    "bt2020": "BT.2020",
    "rec.2020": "BT.2020",
    "rec2020": "BT.2020",
    "srgb": "BT.709 / sRGB",
    "bt.709": "BT.709 / sRGB",
    "bt709": "BT.709 / sRGB",
    "rec.709": "BT.709 / sRGB",
    "rec709": "BT.709 / sRGB",
}


def gamut_from_tag(tag: str | None) -> tuple[str, bool]:
    """Returns (gamut, detected). Falls back to Cinema Gamut when the tag is unknown."""
    if tag:
        match = _GAMUT_BY_TAG.get(tag.strip().lower())
        if match:
            return match, True
    return FALLBACK_GAMUT, False
