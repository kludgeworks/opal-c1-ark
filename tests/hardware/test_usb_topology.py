# SPDX-License-Identifier: MIT
"""Hardware integration test asserting Opal C1 USB link speed and dock negotiation."""

import plistlib
import subprocess
import pytest

MOVIDIUS_VID = 0x03E7
OPAL_PIDS = (0xF63D, 0xF63C)


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
            if vid == MOVIDIUS_VID and pid in OPAL_PIDS:
                return {
                    "product_name": (
                        node.get("USB Product Name")
                        or node.get("kUSBProductString")
                        or node.get("IORegistryEntryName")
                    ),
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
    assert len(info["serial"]) > 0


@pytest.mark.hardware
def test_opal_c1_superspeed_negotiation():
    """Opal C1 must negotiate SuperSpeed 5.0 Gbps (not fall back to 480 Mbps USB 2.0)."""
    info = get_connected_opal_usb_info()
    if not info:
        pytest.skip("Opal C1 hardware not detected on USB bus")

    speed_mbps = info["link_speed_bps"] // 1_000_000
    assert info["link_speed_bps"] >= 5_000_000_000, (
        f"Opal C1 link speed negotiated at only {speed_mbps} Mbps (USB 2.0 High-Speed fallback)! "
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
