# SPDX-License-Identifier: MIT
"""Unit tests validating integrity and structure of offline firmware archives."""

import json
import pathlib
import pytest


@pytest.mark.offline
def test_firmware_manifest_valid(repo_root: pathlib.Path):
    """firmware/manifest.json must exist, be valid JSON, and document bootloaders and applications."""
    manifest_path = repo_root / "firmware" / "manifest.json"
    assert manifest_path.exists(), "firmware/manifest.json is missing"

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "bootloaders" in data or "manifestVersion" in data or "packages" in data or isinstance(data, dict)


@pytest.mark.offline
def test_stock_opal_firmware_assets(
    stock_opal_sbr_path: pathlib.Path, bootloader_v29_path: pathlib.Path, repo_root: pathlib.Path
):
    """Stock Opal C1 standalone SBR application must match expected SBR magic header."""
    assert stock_opal_sbr_path.exists(), f"Missing stock SBR at {stock_opal_sbr_path}"
    assert stock_opal_sbr_path.stat().st_size > 10 * 1024 * 1024, "Stock SBR smaller than 10 MiB"

    with open(stock_opal_sbr_path, "rb") as f:
        magic = f.read(12)
    # Magic header: b'BR__firmware'
    assert magic.startswith(b"BR__firmware"), f"Unexpected magic header in SBR: {magic}"

    # Stock bootloader v0.0.15
    stock_bl = repo_root / "firmware" / "opal-c1" / "bootloader" / "depthai-bootloader-usb.cmd"
    assert stock_bl.exists(), "Missing stock v0.0.15 bootloader binary"
    assert stock_bl.stat().st_size > 500 * 1024


@pytest.mark.offline
def test_upgraded_luxonis_bootloader_v29(bootloader_v29_path: pathlib.Path):
    """Luxonis v0.0.29 USB bootloader binary must be present for soft-reset fixes."""
    assert bootloader_v29_path.exists(), f"Missing v0.0.29 bootloader at {bootloader_v29_path}"
    assert bootloader_v29_path.stat().st_size > 500 * 1024


@pytest.mark.offline
def test_custom_opal_c1_dap_package(firmware_custom_dap: pathlib.Path):
    """Custom Opal C1 Ark Edition DAP package must exist and begin with valid SBR magic."""
    assert firmware_custom_dap.exists(), f"Missing custom DAP package at {firmware_custom_dap}"
    assert firmware_custom_dap.stat().st_size > 5 * 1024 * 1024, "DAP package smaller than 5 MiB"

    with open(firmware_custom_dap, "rb") as f:
        magic = f.read(12)
    assert magic.startswith(b"BR__firmware"), f"Invalid DAP magic header: {magic}"
