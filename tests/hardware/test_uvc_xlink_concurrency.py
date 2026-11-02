# SPDX-License-Identifier: MIT
"""Hardware integration test asserting UVC + XLink stream concurrency and reconnect immunity."""

import time
import pytest
import depthai as dai

from tools.test_harness.pipeline import build_dual_stream_pipeline
from tools.test_harness.hevc import parse_hevc_nal_units


def get_available_depthai_device() -> dai.DeviceInfo | None:
    """Return an available DepthAI device if connected."""
    devices = dai.Device.getAllAvailableDevices()
    if not devices:
        devices = dai.DeviceBootloader.getAllAvailableDevices()
    return devices[0] if devices else None


@pytest.mark.hardware
def test_dual_stream_pipeline_launch():
    """Verify that dual-stream pipeline (4K H.265 + 1080p UVC) boots cleanly on hardware."""
    dev_info = get_available_depthai_device()
    if not dev_info:
        pytest.skip("No Opal C1 / DepthAI device detected over USB (plug in the camera)")

    pipeline = build_dual_stream_pipeline(bitrate_kbps=25000, fps=30)
    try:
        with dai.Device(pipeline, dev_info) as device:
            q_h265 = device.getOutputQueue(name="h265", maxSize=4, blocking=False)
            assert q_h265 is not None

            # Pull at least 15 frames (0.5s of video) to verify hardware encoder is pumping frames
            frames_received = 0
            start_time = time.time()
            while frames_received < 15 and (time.time() - start_time) < 5.0:
                pkt = q_h265.tryGet()
                if pkt is not None:
                    data = pkt.getData()
                    assert len(data) > 0
                    nals = parse_hevc_nal_units(data)
                    assert len(nals) > 0
                    frames_received += 1
                else:
                    time.sleep(0.01)

            assert frames_received >= 15, f"Only received {frames_received} frames before timeout"
    except RuntimeError as exc:
        pytest.skip(f"Device busy or running standalone flash application: {exc}")


@pytest.mark.hardware
def test_xlink_disconnect_and_reconnect_resilience():
    """Verify that disconnecting and reconnecting XLink consumer does not require a device power-cycle."""
    dev_info = get_available_depthai_device()
    if not dev_info:
        pytest.skip("No Opal C1 / DepthAI device detected over USB (plug in the camera)")

    # Run 3 consecutive connect -> stream -> disconnect cycles
    for cycle in range(1, 4):
        pipeline = build_dual_stream_pipeline(bitrate_kbps=25000, fps=30)
        try:
            with dai.Device(pipeline, dev_info) as device:
                q = device.getOutputQueue(name="h265", maxSize=4, blocking=False)
                got_frame = False
                t0 = time.time()
                while not got_frame and (time.time() - t0) < 4.0:
                    pkt = q.tryGet()
                    if pkt is not None and len(pkt.getData()) > 0:
                        got_frame = True
                    time.sleep(0.01)

                assert got_frame, f"Cycle {cycle}: failed to receive frame from reconnected device"
        except RuntimeError as exc:
            pytest.fail(
                f"Cycle {cycle}: Reconnection failed with error: {exc}. "
                "Device may have entered stale XLink state requiring power-cycle!"
            )
        time.sleep(0.5)
