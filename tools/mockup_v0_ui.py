#!/usr/bin/env python3
"""
Opal C1 Ark — v0 UI Menu Bar Extra Mockup with Python-Swift Bindings
Demonstrates the v0 · Alive native menu bar extra, template silhouette lens glyphs,
and telemetry state updates.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
from pathlib import Path

# Camera States
STATE_IDLE = 0          # Connected, 0 clients streaming -> Open outline circle
STATE_LIVE = 1          # Actively streaming -> Filled solid circle
STATE_PAUSED = 2        # Video Paused -> Diagonal slash
STATE_DISCONNECTED = 3  # Disconnected -> 50% opacity dashed circle
STATE_ATTENTION = 4     # Needs attention -> Orange badge dot

STATE_NAMES = {
    STATE_IDLE: "Idle (Open circle)",
    STATE_LIVE: "Live (Filled circle)",
    STATE_PAUSED: "Paused (Diagonal slash)",
    STATE_DISCONNECTED: "Disconnected (Dashed circle)",
    STATE_ATTENTION: "Needs Attention (Orange badge)",
}

# User Actions from Menu
ACTION_TOGGLE_PAUSE = 1
ACTION_TOGGLE_LAUNCH_AT_LOGIN = 2
ACTION_PRESET_1 = 11
ACTION_PRESET_2 = 12
ACTION_PRESET_3 = 13
ACTION_QUIT = 99

ACTION_NAMES = {
    ACTION_TOGGLE_PAUSE: "Toggle Video Pause (⌃⌥V)",
    ACTION_TOGGLE_LAUNCH_AT_LOGIN: "Toggle Launch at Login",
    ACTION_PRESET_1: "Select Preset 1: Headshot (⌃⌥1)",
    ACTION_PRESET_2: "Select Preset 2: Desk View (⌃⌥2)",
    ACTION_PRESET_3: "Select Preset 3: Wide Studio (⌃⌥3)",
    ACTION_QUIT: "Quit Opal C1 Ark (⌘Q)",
}

ACTION_CALLBACK_TYPE = ctypes.CFUNCTYPE(None, ctypes.c_int32)


class OpalC1UIBridge:
    def __init__(self, dylib_path: Path | None = None):
        if dylib_path is None:
            # Search common build locations
            candidates = [
                Path(__file__).parent.parent / "companion" / ".build" / "arm64-apple-macosx" / "debug" / "libOpalC1UI.dylib",
                Path(__file__).parent.parent / "companion" / ".build" / "debug" / "libOpalC1UI.dylib",
                Path(__file__).parent.parent / "companion" / ".build" / "release" / "libOpalC1UI.dylib",
            ]
            for c in candidates:
                if c.exists():
                    dylib_path = c
                    break

        if dylib_path is None or not dylib_path.exists():
            raise FileNotFoundError(
                f"Could not locate libOpalC1UI.dylib. Please run 'cd companion && swift build' first. Checked: {candidates}"
            )

        self.dylib_path = dylib_path
        print(f"[*] Loading Swift UI dylib: {self.dylib_path}")
        self.lib = ctypes.CDLL(str(self.dylib_path))
        self._setup_signatures()
        self._callback_ref = None

    def _setup_signatures(self):
        # int opal_ui_init()
        self.lib.opal_ui_init.argtypes = []
        self.lib.opal_ui_init.restype = ctypes.c_int32

        # void opal_ui_set_state(int, const char*, const char*, double, double, double)
        self.lib.opal_ui_set_state.argtypes = [
            ctypes.c_int32,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_double,
        ]
        self.lib.opal_ui_set_state.restype = None

        # void opal_ui_register_callback(callback)
        self.lib.opal_ui_register_callback.argtypes = [ACTION_CALLBACK_TYPE]
        self.lib.opal_ui_register_callback.restype = None

        # int opal_ui_pump_events(double timeout)
        self.lib.opal_ui_pump_events.argtypes = [ctypes.c_double]
        self.lib.opal_ui_pump_events.restype = ctypes.c_int32

        # void opal_ui_terminate()
        self.lib.opal_ui_terminate.argtypes = []
        self.lib.opal_ui_terminate.restype = None

    def initialize(self):
        res = self.lib.opal_ui_init()
        if res != 0:
            raise RuntimeError(f"Failed to initialize Opal C1 UI: {res}")

    def register_callback(self, py_callback):
        def _c_callback(action_code: int):
            py_callback(action_code)

        self._callback_ref = ACTION_CALLBACK_TYPE(_c_callback)
        self.lib.opal_ui_register_callback(self._callback_ref)

    def set_state(
        self,
        state: int,
        status_line: str | None = None,
        client_name: str | None = None,
        fps: float = 30.0,
        bitrate_mbps: float = 25.0,
        temp_c: float = 41.5,
    ):
        status_bytes = status_line.encode("utf-8") if status_line else None
        client_bytes = client_name.encode("utf-8") if client_name else None
        self.lib.opal_ui_set_state(
            ctypes.c_int32(state),
            status_bytes,
            client_bytes,
            ctypes.c_double(fps),
            ctypes.c_double(bitrate_mbps),
            ctypes.c_double(temp_c),
        )

    def pump_events(self, timeout_seconds: float = 0.05) -> bool:
        ret = self.lib.opal_ui_pump_events(ctypes.c_double(timeout_seconds))
        return ret == 1

    def terminate(self):
        self.lib.opal_ui_terminate()


def on_menu_action(action_code: int):
    name = ACTION_NAMES.get(action_code, f"Unknown action ({action_code})")
    print(f"\n[⚡ UI Event from Menu Bar] {name}")


def run_demo_tour(bridge: OpalC1UIBridge, seconds_per_state: int = 4):
    """Cycles through all visual states so the developer can see the glyph and menu changes."""
    print("\n" + "=" * 65)
    print("  OPAL C1 ARK — v0 · ALIVE MENU BAR EXTRA DEMO TOUR")
    print("  Look at your macOS Menu Bar (top right) to see the icons change!")
    print("=" * 65 + "\n")

    steps = [
        (
            STATE_IDLE,
            "Idle · 4K Ready",
            None,
            0.0,
            0.0,
            39.2,
            "1. CAMERA IDLE — Open outline circle glyph. Connected, zero streaming clients.",
        ),
        (
            STATE_LIVE,
            "4K30 · HEVC 25.0 Mb/s · 41.5°C",
            "Google Meet",
            30.0,
            25.0,
            41.5,
            "2. LIVE STREAMING — Filled solid circle glyph. Streaming 4K to Google Meet.",
        ),
        (
            STATE_PAUSED,
            "Video Paused (Sensor Mute)",
            "Google Meet",
            0.0,
            0.0,
            41.2,
            "3. VIDEO PAUSED (⌃⌥V) — Diagonal slash glyph. Sensor streaming black frame.",
        ),
        (
            STATE_LIVE,
            "4K30 · HEVC 24.8 Mb/s · 42.1°C",
            "FaceTime",
            30.0,
            24.8,
            42.1,
            "4. RESUMED STREAMING — Filled solid circle glyph. Client switched to FaceTime.",
        ),
        (
            STATE_ATTENTION,
            "⚠️ Thermal Throttle: 66.4°C",
            "FaceTime",
            15.0,
            12.5,
            66.4,
            "5. NEEDS ATTENTION — Outline circle + orange badge dot. High temp warning.",
        ),
        (
            STATE_DISCONNECTED,
            "Camera Disconnected",
            None,
            0.0,
            0.0,
            0.0,
            "6. DISCONNECTED — Dashed circle at 50% opacity. USB disconnected.",
        ),
        (
            STATE_IDLE,
            "Idle · 4K Ready",
            None,
            0.0,
            0.0,
            40.1,
            "7. RESTORED IDLE — Reconnected, ready for streaming.",
        ),
    ]

    for state, status_line, client, fps, bitrate, temp, desc in steps:
        print(f"\n▶ {desc}")
        bridge.set_state(
            state=state,
            status_line=status_line,
            client_name=client,
            fps=fps,
            bitrate_mbps=bitrate,
            temp_c=temp,
        )

        # Pump events in small increments so UI remains fully responsive
        end_time = time.time() + seconds_per_state
        while time.time() < end_time:
            bridge.pump_events(0.05)
            time.sleep(0.01)

    print("\n[✔] Demo Tour complete. Menu bar remains active. Click icon to test menu.")
    print("Press Ctrl+C or select 'Quit Opal C1 Ark' in menu to exit.\n")
    try:
        while True:
            bridge.pump_events(0.05)
            time.sleep(0.02)
    except KeyboardInterrupt:
        print("\nExiting...")


def run_live_hardware(bridge: OpalC1UIBridge):
    """Wires the live Opal C1 camera hardware directly to the v0 Menu Bar Extra."""
    print("\n" + "=" * 65)
    print("  OPAL C1 ARK — v0 · LIVE HARDWARE INTEGRATION")
    print("  Streaming 4K H.265 from Sony IMX582 sensor to Menu Bar Extra")
    print("=" * 65 + "\n")

    try:
        import depthai as dai
        try:
            from tools.test_harness.pipeline import build_companion_pipeline
        except ImportError:
            from test_harness.pipeline import build_companion_pipeline
    except ImportError as e:
        print(f"[-] Missing dependency: {e}")
        return

    devices = dai.Device.getAllAvailableDevices()
    if not devices:
        print("[-] No DepthAI/Opal C1 device found on USB bus.")
        bridge.set_state(STATE_DISCONNECTED, "No Hardware Found")
        while True:
            bridge.pump_events(0.05)
            time.sleep(0.02)

    dev_info = devices[0]
    print(f"[+] Found device: {dev_info.getMxId()} (Status: {dev_info.state.name})")

    pipeline = build_companion_pipeline()

    print("[*] Booting Opal C1 companion pipeline on silicon...")
    try:
        with dai.Device(pipeline, dev_info) as device:
            print("[+] Silicon pipeline active! SuperSpeed XLink link established.")

            q_h265 = device.getOutputQueue("h265", maxSize=8, blocking=False)
            q_ctrl = device.getInputQueue("control")
            q_cfg = device.getInputQueue("config")

            is_paused = False
            active_preset = 1
            running = True

            def handle_hardware_action(action_code: int):
                nonlocal is_paused, active_preset, running
                on_menu_action(action_code)

                if action_code == ACTION_TOGGLE_PAUSE:
                    is_paused = not is_paused
                    ctrl = dai.CameraControl()
                    if is_paused:
                        ctrl.setStopStreaming()
                        print("[⚡ Hardware] Sensor stream STOPPED (mute)")
                    else:
                        ctrl.setStartStreaming()
                        print("[⚡ Hardware] Sensor stream RESUMED (unmute)")
                    q_ctrl.send(ctrl)

                elif action_code == ACTION_PRESET_1:
                    active_preset = 1
                    cfg = dai.ImageManipConfig()
                    cfg.setCropRect(0.15, 0.15, 0.85, 0.85)
                    q_cfg.send(cfg)
                    print("[⚡ Hardware] Applied Preset 1: Headshot (1.4x crop)")

                elif action_code == ACTION_PRESET_2:
                    active_preset = 2
                    cfg = dai.ImageManipConfig()
                    cfg.setCropRect(0.10, 0.35, 0.90, 0.95)
                    q_cfg.send(cfg)
                    print("[⚡ Hardware] Applied Preset 2: Desk View (tilt crop)")

                elif action_code == ACTION_PRESET_3:
                    active_preset = 3
                    cfg = dai.ImageManipConfig()
                    cfg.setCropRect(0.0, 0.0, 1.0, 1.0)
                    q_cfg.send(cfg)
                    print("[⚡ Hardware] Applied Preset 3: Wide Studio (full 4K)")

                elif action_code == ACTION_QUIT:
                    print("[⚡ Hardware] Quit requested. Shutting down...")
                    running = False

            bridge.register_callback(handle_hardware_action)

            # Rolling stats counters
            last_stats_time = time.time()
            frames_in_window = 0
            bytes_in_window = 0
            cur_fps = 0.0
            cur_mbps = 0.0
            cur_temp = 41.5

            print("\n[✔] Opal C1 Ark Menu Bar Extra is LIVE.")
            print("  • Look at the top right of your macOS screen for the live icon.")
            print("  • Click the icon to test: Pause Video (⌃⌥V) or Presets (⌃⌥1–3).")
            print("  • Select 'Quit Opal C1 Ark' in the menu or press Ctrl+C to stop.\n")

            while running:
                # Ingest available packets
                while True:
                    pkt = q_h265.tryGet()
                    if not pkt:
                        break
                    frames_in_window += 1
                    bytes_in_window += len(pkt.getData())

                now = time.time()
                elapsed = now - last_stats_time
                if elapsed >= 1.0:
                    cur_fps = frames_in_window / elapsed
                    cur_mbps = (bytes_in_window * 8) / (1_000_000 * elapsed)
                    frames_in_window = 0
                    bytes_in_window = 0
                    last_stats_time = now

                    try:
                        cur_temp = device.getChipTemperature().average
                    except Exception:
                        pass

                    # Determine UI state
                    if is_paused:
                        state = STATE_PAUSED
                        status_line = "Video Paused (Sensor Mute)"
                    elif cur_temp >= 65.0:
                        state = STATE_ATTENTION
                        status_line = f"⚠️ Thermal Warning: {cur_temp:.1f}°C"
                    else:
                        state = STATE_LIVE
                        status_line = f"4K30 · HEVC {cur_mbps:.1f} Mb/s · {cur_temp:.1f}°C"

                    preset_names = {1: "Headshot", 2: "Desk View", 3: "Wide Studio"}
                    client_desc = f"4K ({preset_names.get(active_preset, 'Live')})"

                    bridge.set_state(
                        state=state,
                        status_line=status_line,
                        client_name=client_desc if not is_paused else None,
                        fps=cur_fps,
                        bitrate_mbps=cur_mbps,
                        temp_c=cur_temp,
                    )

                    # Print rolling terminal telemetry
                    sys.stdout.write(
                        f"\r[Telemetry] State: {STATE_NAMES[state]:<24} | FPS: {cur_fps:4.1f} | Bitrate: {cur_mbps:4.1f} Mb/s | Temp: {cur_temp:4.1f}°C   "
                    )
                    sys.stdout.flush()

                # Pump Cocoa event loop
                bridge.pump_events(0.03)
                time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n[*] Interrupted by user. Exiting cleanly...")
    except Exception as e:
        print(f"\n[-] Hardware runtime error: {e}")
        bridge.set_state(STATE_DISCONNECTED, f"Hardware Error: {e}")
        bridge.pump_events(0.1)


def main():
    parser = argparse.ArgumentParser(description="Opal C1 Ark v0 Menu Bar Extra Mockup")
    parser.add_argument("--demo", action="store_true", help="Force animated demo tour of all states")
    parser.add_argument("--live", action="store_true", help="Force live connection to physical Opal C1 hardware")
    parser.add_argument("--seconds", type=int, default=3, help="Seconds per demo tour step (default: 3)")
    args = parser.parse_args()

    bridge = OpalC1UIBridge()
    bridge.initialize()

    if args.demo:
        bridge.register_callback(on_menu_action)
        run_demo_tour(bridge, seconds_per_state=args.seconds)
    elif args.live:
        run_live_hardware(bridge)
    else:
        # Auto-detect: if Opal C1 is connected, use Live Hardware mode; otherwise run Demo Tour
        try:
            import depthai as dai
            devices = dai.Device.getAllAvailableDevices()
        except Exception:
            devices = []

        if devices:
            print(f"[+] Opal C1 detected on USB ({devices[0].getMxId()}). Starting in Live Hardware mode.")
            run_live_hardware(bridge)
        else:
            print("[-] No Opal C1 hardware found on USB. Starting in Demo Tour mode.")
            bridge.register_callback(on_menu_action)
            run_demo_tour(bridge, seconds_per_state=args.seconds)


if __name__ == "__main__":
    main()
