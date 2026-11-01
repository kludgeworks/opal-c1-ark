# SPDX-License-Identifier: MIT
"""Hardware integration test asserting zero macOS kernel USB pipe stalls or dock drops."""

import subprocess
import pytest


@pytest.mark.hardware
def test_zero_kernel_pipe_stalls():
    """Assert zero 0xe0005000 (pipe stalled) control endpoint failures in macOS kernel logs."""
    try:
        # Check last 60 seconds of kernel logs for USB pipe stalls
        out = subprocess.check_output(
            [
                "/usr/bin/log",
                "show",
                "--last",
                "1m",
                "--style",
                "compact",
                "--predicate",
                'senderImagePath CONTAINS "IOUSBHostFamily"',
            ],
            timeout=10,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pytest.skip("Unable to query macOS system log (requires standard permissions)")

    stall_lines = [
        line for line in out.splitlines()
        if "0xe0005000" in line or "pipe stalled" in line
    ]

    assert len(stall_lines) == 0, (
        f"Detected {len(stall_lines)} USB pipe stalls in macOS kernel logs:\n"
        + "\n".join(stall_lines[:5])
    )


@pytest.mark.hardware
def test_zero_dock_hub_brownouts():
    """Assert zero dock root hub crashes (link change interrupt) in macOS kernel logs."""
    try:
        out = subprocess.check_output(
            [
                "/usr/bin/log",
                "show",
                "--last",
                "1m",
                "--style",
                "compact",
                "--predicate",
                'senderImagePath CONTAINS "IOUSBHostFamily"',
            ],
            timeout=10,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pytest.skip("Unable to query macOS system log")

    # Catch Intel Barlow Ridge USB 3 hub collapse
    hub_crashes = [
        line for line in out.splitlines()
        if "5787/0000 (USB3 HUB): link change interrupt" in line
        or "5801/0101 (USB2.0 Hub): hardware connection lost" in line
    ]

    assert len(hub_crashes) == 0, (
        f"Detected {len(hub_crashes)} Thunderbolt dock hub crashes in kernel logs:\n"
        + "\n".join(hub_crashes[:5])
    )
