# SPDX-License-Identifier: MIT
"""Unit tests for the ITU-T H.265 (HEVC) NAL unit parser and bitstream analyzer."""

import pathlib
import pytest
from tools.test_harness.hevc import (
    HEVC_KEYFRAME_TYPES,
    HEVC_NAL_NAMES,
    has_parameter_sets,
    is_hevc_keyframe,
    parse_hevc_nal_units,
)


@pytest.mark.offline
def test_parse_empty_and_garbage_data():
    """Parser must gracefully return an empty list for empty or non-NAL bytes."""
    assert parse_hevc_nal_units(b"") == []
    assert parse_hevc_nal_units(b"hello world") == []
    assert parse_hevc_nal_units(b"\x00\x00\x00") == []
    assert parse_hevc_nal_units(b"\xff\xff\xff\xff\xff") == []


@pytest.mark.offline
def test_parse_hevc_parameter_sets_3byte_start_code():
    """Parser must correctly extract VPS (32), SPS (33), and PPS (34) with 3-byte start codes."""
    # Start code: 0x00 0x00 0x01
    # HEVC NAL header: (nal_type << 1) & 0x7E
    # VPS = (32 << 1) = 0x40
    # SPS = (33 << 1) = 0x42
    # PPS = (34 << 1) = 0x44
    data = (
        b"\x00\x00\x01\x40\x01\x0c\x01\xff"  # VPS
        b"\x00\x00\x01\x42\x01\x01\x02\xff"  # SPS
        b"\x00\x00\x01\x44\x01\x00\xff"      # PPS
    )
    nals = parse_hevc_nal_units(data)
    assert len(nals) == 3
    assert nals[0] == (32, "VPS (Video Parameter Set)")
    assert nals[1] == (33, "SPS (Seq Parameter Set)")
    assert nals[2] == (34, "PPS (Pic Parameter Set)")
    assert has_parameter_sets(data) is True
    assert is_hevc_keyframe(data) is False


@pytest.mark.offline
def test_parse_hevc_keyframes_4byte_start_code():
    """Parser must identify IDR_W_RADL (19), IDR_N_LP (20), and CRA_NUT (21) keyframes."""
    # 4-byte start code: 0x00 0x00 0x00 0x01
    # IDR_W_RADL = (19 << 1) = 0x26
    # IDR_N_LP   = (20 << 1) = 0x28
    # CRA_NUT    = (21 << 1) = 0x2A
    idr_w = b"\x00\x00\x00\x01\x26\x01\xaf\xfe"
    idr_n = b"\x00\x00\x00\x01\x28\x01\xaf\xfe"
    cra   = b"\x00\x00\x00\x01\x2A\x01\xaf\xfe"

    assert is_hevc_keyframe(idr_w) is True
    assert is_hevc_keyframe(idr_n) is True
    assert is_hevc_keyframe(cra) is True

    nals_idr = parse_hevc_nal_units(idr_w)
    assert len(nals_idr) == 1
    assert nals_idr[0][0] == 19
    assert "Keyframe" in nals_idr[0][1]


@pytest.mark.offline
def test_parse_hevc_trailing_p_frames():
    """Parser must recognize non-keyframe trailing slices (P-frames)."""
    # TRAIL_R = (1 << 1) = 0x02
    # TRAIL_N = (0 << 1) = 0x00
    p_frame = b"\x00\x00\x01\x02\x01\xd0\xba\xbe"
    nals = parse_hevc_nal_units(p_frame)
    assert len(nals) == 1
    assert nals[0][0] == 1
    assert "P-frame" in nals[0][1]
    assert is_hevc_keyframe(p_frame) is False


@pytest.mark.offline
def test_concatenated_access_unit():
    """A single H.265 access unit packet typically concatenates VPS+SPS+PPS+IDR."""
    packet = (
        b"\x00\x00\x00\x01\x40\x01\x0c"  # VPS (32)
        b"\x00\x00\x00\x01\x42\x01\x01"  # SPS (33)
        b"\x00\x00\x00\x01\x44\x01\x00"  # PPS (34)
        b"\x00\x00\x00\x01\x26\x01\xaa"  # IDR_W_RADL (19)
    )
    nals = parse_hevc_nal_units(packet)
    assert [n[0] for n in nals] == [32, 33, 34, 19]
    assert has_parameter_sets(packet) is True
    assert is_hevc_keyframe(packet) is True


@pytest.mark.offline
def test_real_sample_bitstream_if_present(repo_root: pathlib.Path):
    """If sample_4k.h265 was dumped by Phase 1, verify that its real NAL headers are valid."""
    sample_file = repo_root / "tools" / "test_harness" / "sample_4k.h265"
    if not sample_file.exists() or sample_file.stat().st_size == 0:
        pytest.skip("sample_4k.h265 not yet captured on hardware")

    with open(sample_file, "rb") as f:
        head_chunk = f.read(65536)  # Read first 64 KiB

    nals = parse_hevc_nal_units(head_chunk)
    assert len(nals) > 0, "Failed to parse any NAL units from sample_4k.h265"

    nal_types = {n[0] for n in nals}
    # A valid HEVC stream must begin with VPS, SPS, or PPS parameter sets
    assert nal_types.intersection({32, 33, 34}), "Sample stream missing VPS/SPS/PPS parameter sets"
    # And must contain at least one IDR/CRA keyframe
    assert nal_types.intersection(HEVC_KEYFRAME_TYPES), "Sample stream missing IDR/CRA keyframe"
