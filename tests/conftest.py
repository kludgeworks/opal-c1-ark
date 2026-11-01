# SPDX-License-Identifier: MIT
"""Pytest fixtures and test configuration for Opal C1 test framework."""

import os
import pathlib
import sys
import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def pytest_addoption(parser):
    """Add CLI flags for hardware test selection."""
    parser.addoption(
        "--hardware",
        action="store_true",
        default=False,
        help="Run live hardware tests requiring a connected Opal C1 camera",
    )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "hardware: marks tests requiring physical Opal C1 / DepthAI hardware"
    )
    config.addinivalue_line(
        "markers", "offline: marks tests that execute purely in memory without USB hardware"
    )


def pytest_collection_modifyitems(config, items):
    """Skip hardware tests by default unless --hardware is passed or -m hardware is specified."""
    run_hardware = config.getoption("--hardware")
    keyword_expr = config.getoption("-k", default="")
    mark_expr = config.getoption("-m", default="")

    if not run_hardware and "hardware" not in mark_expr and "hardware" not in keyword_expr:
        skip_hw = pytest.mark.skip(
            reason="Hardware test skipped (pass --hardware or -m hardware to run live tests)"
        )
        for item in items:
            if "hardware" in item.keywords:
                item.add_marker(skip_hw)


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    """Return the absolute Path to the repository root."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def firmware_custom_dap(repo_root: pathlib.Path) -> pathlib.Path:
    """Path to the custom Opal C1 Ark Edition DAP package."""
    return repo_root / "firmware" / "custom" / "opal-c1-ark-edition.dap"


@pytest.fixture(scope="session")
def bootloader_v29_path(repo_root: pathlib.Path) -> pathlib.Path:
    """Path to the upgraded Luxonis v0.0.29 bootloader binary."""
    return repo_root / "firmware" / "luxonis" / "bootloader" / "depthai-bootloader-usb.cmd"


@pytest.fixture(scope="session")
def stock_opal_sbr_path(repo_root: pathlib.Path) -> pathlib.Path:
    """Path to the archived Opal C1 stock standalone SBR firmware."""
    return repo_root / "firmware" / "opal-c1" / "application" / "opal-c1-standalone.sbr"
