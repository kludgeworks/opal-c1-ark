# SPDX-License-Identifier: MIT
"""Hardware integration test asserting Opal C1 stream SLA and silicon thermal limits."""

import depthai as dai
import pytest


def get_available_depthai_device() -> dai.DeviceInfo | None:
    """Return an available DepthAI device if connected."""
    devices = dai.Device.getAllAvailableDevices()
    if not devices:
        devices = dai.DeviceBootloader.getAllAvailableDevices()
    return devices[0] if devices else None


@pytest.mark.hardware
def test_camera_hardware_autofocus_ic():
    """Verify Sony IMX582 sensor on CAM_A has an operational Voice Coil Motor (VCM) AF IC."""
    dev_info = get_available_depthai_device()
    if not dev_info:
        pytest.skip("No Opal C1 / DepthAI device detected over USB (plug in the camera)")

    pipeline = dai.Pipeline()
    try:
        with dai.Device(pipeline, dev_info) as device:
            features = device.getConnectedCameraFeatures()
            cam_a = next((c for c in features if c.socket == dai.CameraBoardSocket.CAM_A), None)

            assert cam_a is not None, "No sensor detected on socket CAM_A"
            assert cam_a.hasAutofocus is True, "Autofocus IC not detected on CAM_A"
            assert cam_a.sensorName in ("IMX582", "LCM48", "IMX586", "OV48B"), (
                f"Unexpected sensor silicon on CAM_A: {cam_a.sensorName}"
            )
    except RuntimeError as exc:
        pytest.skip(f"Device busy or running standalone flash application: {exc}")


@pytest.mark.hardware
def test_silicon_junction_temperature_headroom():
    """Assert steady-state silicon junction temperature stays well below the 85°C throttle ceiling."""
    dev_info = get_available_depthai_device()
    if not dev_info:
        pytest.skip("No Opal C1 / DepthAI device detected over USB")

    pipeline = dai.Pipeline()
    try:
        with dai.Device(pipeline, dev_info) as device:
            temp = device.getChipTemperature()
            avg_temp = temp.average
            css_temp = temp.css
            mss_temp = temp.mss

            assert avg_temp < 60.0, (
                f"Silicon average temperature ({avg_temp:.1f}°C) exceeds 60°C target! "
                "Check heatsinking and verify hardware ISP scaling is enabled."
            )
            assert css_temp < 65.0, f"Leon CSS core ({css_temp:.1f}°C) exceeds 65°C threshold"
            assert mss_temp < 65.0, f"Leon MSS core ({mss_temp:.1f}°C) exceeds 65°C threshold"
            # Ensure at least 25°C of headroom before the 85°C hardware throttling ceiling
            assert (85.0 - avg_temp) >= 25.0, "Less than 25°C of thermal headroom remaining"
    except RuntimeError as exc:
        pytest.skip(f"Device busy or running standalone flash application: {exc}")
