# SPDX-License-Identifier: MIT
"""Unit tests for the DepthAI dual-stream and standalone pipeline builders."""

import depthai as dai
import pytest
from tools.test_harness.pipeline import (
    build_dual_stream_pipeline,
    build_standalone_uvc_pipeline,
)


@pytest.mark.offline
def test_dual_stream_pipeline_nodes():
    """Dual-stream pipeline must instantiate all required nodes with exact bindings."""
    pipeline = build_dual_stream_pipeline(fps=30, bitrate_kbps=25000)
    nodes = pipeline.getAllNodes()
    node_types = {type(n).__name__ for n in nodes}

    assert "ColorCamera" in node_types, "Pipeline missing ColorCamera node"
    assert "UVC" in node_types, "Pipeline missing UVC node"
    assert "VideoEncoder" in node_types, "Pipeline missing VideoEncoder node"
    assert "XLinkOut" in node_types, "Pipeline missing XLinkOut nodes"
    assert "SystemLogger" in node_types, "Pipeline missing SystemLogger node"


@pytest.mark.offline
def test_camera_hardware_isp_configuration():
    """Camera node must configure CAM_A, 4K resolution, 1:2 ISP downscale, and 180 deg rotation."""
    pipeline = build_dual_stream_pipeline(fps=30, bitrate_kbps=25000)
    cam = next(n for n in pipeline.getAllNodes() if isinstance(n, dai.node.ColorCamera))

    assert cam.getBoardSocket() == dai.CameraBoardSocket.CAM_A
    assert cam.getResolution() == dai.ColorCameraProperties.SensorResolution.THE_4_K
    assert cam.getImageOrientation() == dai.CameraImageOrientation.ROTATE_180_DEG
    assert cam.getFps() == 30.0
    # ISP scale 1:2 scales 3840x2160 -> 1920x1080 in silicon with 0ms DSP latency
    assert cam.getIspSize() == (1920, 1080)
    # Native video output must remain 3840x2160 for 4K H.265 encoding
    assert cam.getVideoSize() == (3840, 2160)


@pytest.mark.offline
def test_h265_encoder_properties():
    """VideoEncoder must configure H.265 Main profile, CBR rate control, and GOP of 30."""
    pipeline = build_dual_stream_pipeline(fps=30, bitrate_kbps=25000)
    enc = next(n for n in pipeline.getAllNodes() if isinstance(n, dai.node.VideoEncoder))

    assert enc.getProfile() == dai.VideoEncoderProperties.Profile.H265_MAIN
    assert enc.getBitrateKbps() == 25000
    assert enc.getKeyframeFrequency() == 30
    assert enc.getRateControlMode() == dai.VideoEncoderProperties.RateControlMode.CBR


@pytest.mark.offline
def test_h265_xlink_queue_non_blocking_immunity():
    """CRITICAL: The h265 XLinkOut queue MUST be non-blocking to prevent UVC starvation."""
    pipeline = build_dual_stream_pipeline()
    xouts = [n for n in pipeline.getAllNodes() if isinstance(n, dai.node.XLinkOut)]
    h265_xout = next(x for x in xouts if x.getStreamName() == "h265")

    # If getBlocking() is True, an unread H.265 queue will stall VideoEncoder,
    # backpressure cam.video, and starve the UVC stream in Photo Booth/Zoom!
    assert h265_xout.input.getBlocking() is False, (
        "h265 XLinkOut queue is blocking! Must be False to guarantee UVC starvation immunity."
    )
    assert h265_xout.input.getQueueSize() == 30


@pytest.mark.offline
def test_standalone_uvc_pipeline_has_no_unread_xlinks():
    """Pure standalone UVC pipeline must contain zero unread XLink nodes."""
    pipeline = build_standalone_uvc_pipeline()
    nodes = pipeline.getAllNodes()
    xlinks = [n for n in nodes if isinstance(n, dai.node.XLinkOut)]

    assert len(xlinks) == 0, (
        f"Standalone UVC pipeline contains {len(xlinks)} XLinkOut nodes! "
        "Standalone boot pipelines must contain zero unread XLink nodes to prevent FIFO lockup."
    )
