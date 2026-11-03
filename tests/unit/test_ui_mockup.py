"""Unit tests for the Opal C1 Ark v0 Menu Bar Extra Swift-Python bridge."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure tools/ is on path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

from mockup_v0_ui import (
    STATE_ATTENTION,
    STATE_DISCONNECTED,
    STATE_IDLE,
    STATE_LIVE,
    STATE_PAUSED,
    OpalC1UIBridge,
)


@pytest.fixture(scope="module")
def ui_bridge():
    """Initializes the Swift UI bridge once for testing."""
    bridge = OpalC1UIBridge()
    bridge.initialize()
    return bridge


def test_bridge_initialization(ui_bridge):
    """Verifies that the dylib loads and initializes without error."""
    assert ui_bridge is not None
    assert ui_bridge.lib is not None


def test_bridge_state_transitions(ui_bridge):
    """Verifies that all 5 v0 states transition and pump events cleanly."""
    states = [
        (STATE_IDLE, "Idle · 4K Ready", None, 0.0, 0.0, 39.5),
        (STATE_LIVE, "4K30 · HEVC 25 Mb/s · 41.5°C", "Google Meet", 30.0, 25.0, 41.5),
        (STATE_PAUSED, "Video Paused", "Google Meet", 0.0, 0.0, 41.5),
        (STATE_ATTENTION, "⚠️ Thermal Throttle: 66.2°C", "FaceTime", 15.0, 12.0, 66.2),
        (STATE_DISCONNECTED, "Camera Disconnected", None, 0.0, 0.0, 0.0),
    ]

    for state, status_line, client, fps, bitrate, temp in states:
        ui_bridge.set_state(
            state=state,
            status_line=status_line,
            client_name=client,
            fps=fps,
            bitrate_mbps=bitrate,
            temp_c=temp,
        )
        # Pump event loop for 10ms
        res = ui_bridge.pump_events(0.01)
        assert res is True


def test_action_callback_registration(ui_bridge):
    """Verifies action callback registration."""
    events = []

    def handle_action(code: int):
        events.append(code)

    ui_bridge.register_callback(handle_action)
    # Pumping events with no user click should not trigger callback
    ui_bridge.pump_events(0.01)
    assert len(events) == 0
