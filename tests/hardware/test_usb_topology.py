# SPDX-License-Identifier: MIT
"""Hardware integration test asserting Opal C1 USB link speed and dock negotiation."""

import plistlib
import subprocess
import pytest

MOVIDIUS_VID = 0x03E7

# Known Movidius Myriad X USB Product IDs across lifecycle states
PID_UNBOOTED = 0x2485       # ROM bootloader waiting for firmware (USB 2.0 480 Mbps)
PID_DEPTHAI_APP = 0xF63B    # Active DepthAI custom pipeline/application (SuperSpeed 5 Gbps)
PID_BOOTLOADER = 0xF63C     # DepthAI flash bootloader mode (SuperSpeed 5 Gbps)
PID_UVC = 0xF63D            # UVC composite video class device (SuperSpeed 5 Gbps)

ALL_OPAL_PIDS = (PID_UNBOOTED, PID_DEPTHAI_APP, PID_BOOTLOADER, PID_UVC)
SUPERSPEED_PIDS = (PID_DEPTHAI_APP, PID_BOOTLOADER, PID_UVC)


def get_connected_opal_usb_info() -> dict | None:
    """Query the macOS IOUSBHostDevice registry for the Opal C1."""
    try:
        out = subprocess.check_output(
            ["ioreg", "-r", "-c", "IOUSBHostDevice", "-a"], timeout=5
        )
        if not out or not out.strip():
            return None
        items = plistlib.loads(out)
    except Exception:
        return None

    def walk(nodes: list[dict]) -> dict | None:
        for node in nodes:
            vid = node.get("idVendor")
            pid = node.get("idProduct")
            if vid == MOVIDIUS_VID and pid in ALL_OPAL_PIDS:
                return {
                    "product_name": (
                        node.get("USB Product Name")
                        or node.get("kUSBProductString")
                        or node.get("IORegistryEntryName")
                    ),
                    "pid": int(pid),
                    "serial": str(node.get("USB Serial Number", "")),
                    "location_id": int(node.get("locationID", 0)),
                    "link_speed_bps": int(node.get("UsbLinkSpeed", 0)),
                    "power_ma": int(node.get("UsbPowerSinkAllocation", 0)),
                }
            children = node.get("IORegistryEntryChildren")
            if isinstance(children, list):
                res = walk(children)
                if res:
                    return res
        return None

    return walk(items) if isinstance(items, list) else None


@pytest.mark.hardware
def test_opal_c1_enumerated_on_usb():
    """Opal C1 must be physically enumerated on the USB bus."""
    info = get_connected_opal_usb_info()
    if not info:
        pytest.skip("Opal C1 hardware not detected on USB bus (plug in the camera)")

    assert info["product_name"] is not None
    assert info["pid"] in ALL_OPAL_PIDS


@pytest.mark.hardware
def test_opal_c1_superspeed_negotiation():
    """Opal C1 in active/bootloader states must negotiate SuperSpeed 5.0 Gbps."""
    info = get_connected_opal_usb_info()
    if not info:
        pytest.skip("Opal C1 hardware not detected on USB bus")

    pid = info["pid"]
    speed_mbps = info["link_speed_bps"] // 1_000_000

    if pid == PID_UNBOOTED:
        # ROM bootloader is USB 2.0 High-Speed only (480 Mbps)
        assert info["link_speed_bps"] >= 480_000_000, (
            f"Unbooted Opal C1 (0x2485) speed is {speed_mbps} Mbps (expected 480 Mbps)"
        )
    elif pid in SUPERSPEED_PIDS:
        # Booted DepthAI app, bootloader, or UVC device must negotiate 5.0 Gbps SuperSpeed
        assert info["link_speed_bps"] >= 5_000_000_000, (
            f"Opal C1 (PID 0x{pid:04X}) link speed negotiated at only {speed_mbps} Mbps! "
            "Must negotiate 5.0 Gbps SuperSpeed. Check cable or move to rear Thunderbolt 5 port."
        )


@pytest.mark.hardware
def test_opal_c1_power_sink_allocation():
    """Opal C1 must be allocated full 896 mA SuperSpeed power budget (not 500 mA ceiling)."""
    info = get_connected_opal_usb_info()
    if not info:
        pytest.skip("Opal C1 hardware not detected on USB bus")

    assert info["power_ma"] >= 896, (
        f"Opal C1 allocated only {info['power_ma']} mA! "
        "Must receive 896 mA to power IMX582 sensor, VCM autofocus coil, and Myriad X."
    )
