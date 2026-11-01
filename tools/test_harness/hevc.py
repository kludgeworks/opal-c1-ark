# SPDX-License-Identifier: MIT
"""HEVC (ITU-T H.265) bitstream analysis and NAL unit parser."""

HEVC_NAL_NAMES: dict[int, str] = {
    0: "TRAIL_N (P-frame)",
    1: "TRAIL_R (P-frame ref)",
    2: "TSA_N",
    3: "TSA_R",
    4: "STSA_N",
    5: "STSA_R",
    6: "RADL_N",
    7: "RADL_R",
    8: "RASL_N",
    9: "RASL_R",
    19: "IDR_W_RADL (Keyframe)",
    20: "IDR_N_LP (Keyframe)",
    21: "CRA_NUT (Keyframe CRA)",
    32: "VPS (Video Parameter Set)",
    33: "SPS (Seq Parameter Set)",
    34: "PPS (Pic Parameter Set)",
    39: "PREFIX_SEI",
    40: "SUFFIX_SEI",
}

HEVC_KEYFRAME_TYPES: set[int] = {19, 20, 21}
HEVC_PARAM_SET_TYPES: set[int] = {32, 33, 34}


def parse_hevc_nal_units(data: bytes) -> list[tuple[int, str]]:
    """Parse ITU-T H.265 (HEVC) NAL units from a raw byte stream.

    Scans for 3-byte (0x000001) and 4-byte (0x00000001) start codes, extracts the
    HEVC NAL unit type from bits [6:1] of the first header byte, and returns
    a list of (nal_type, nal_name) tuples.
    """
    nal_units = []
    length = len(data)
    i = 0

    while i < length - 4:
        start_code_len = 0
        if data[i] == 0x00 and data[i + 1] == 0x00:
            if data[i + 2] == 0x01:
                start_code_len = 3
            elif i < length - 3 and data[i + 2] == 0x00 and data[i + 3] == 0x01:
                start_code_len = 4

        if start_code_len > 0:
            header_offset = i + start_code_len
            if header_offset < length:
                first_byte = data[header_offset]
                # HEVC NAL unit type is bits [6:1] of the first header byte
                nal_type = (first_byte >> 1) & 0x3F
                name = HEVC_NAL_NAMES.get(nal_type, f"TYPE_{nal_type}")
                nal_units.append((nal_type, name))
            i += start_code_len
        else:
            i += 1

    return nal_units


def is_hevc_keyframe(data: bytes) -> bool:
    """Return True if the bitstream slice contains an IDR or CRA keyframe NAL unit."""
    nals = parse_hevc_nal_units(data)
    return any(nal_type in HEVC_KEYFRAME_TYPES for nal_type, _ in nals)


def has_parameter_sets(data: bytes) -> bool:
    """Return True if the packet contains VPS, SPS, or PPS parameter sets."""
    nals = parse_hevc_nal_units(data)
    return any(nal_type in HEVC_PARAM_SET_TYPES for nal_type, _ in nals)
