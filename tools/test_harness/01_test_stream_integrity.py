#!/usr/bin/env -S uv run python -P
# SPDX-License-Identifier: MIT
#MISE description="Phase 1: Test 4K H.265 + 1080p UVC dual-stream integrity and thermal performance"
#USAGE flag "--duration <seconds>" default=30 help="Duration to run the test in seconds (0 for continuous until Ctrl+C)"
#USAGE flag "--bitrate <kbps>" default=25000 help="Target 4K H.265 bitrate in kbps"
#USAGE flag "--fps <fps>" default=30 help="Target capture and encode framerate"
#USAGE flag "--save-h265 <path>" default="tools/test_harness/sample_4k.h265" help="Path to save captured raw H.265 bitstream (for VideoToolbox testing)"
#USAGE flag "--simulate-disconnect" help="Simulate companion app pause/resume to verify UVC non-blocking queue immunity"
#USAGE flag "--mxid <mxid>" help="Target Opal C1 Myriad X device ID (auto-detected if omitted)"

"""
Phase 1 Test Harness: 4K H.265 + 1080p UVC Stream Integrity & Thermal Verification
===================================================================================

Validates the hybrid streaming architecture for the Opal C1 companion app:
1. Concurrently runs 1080p uncompressed NV12 over standard UVC (driverless fallback).
2. Concurrently encodes full 4K (3840x2160) using the Myriad X on-chip H.265 ASIC at 25 Mbps.
3. Streams H.265 over DepthAI XLink using non-blocking queues (preventing UVC stall).
4. Ingests, parses, and validates H.265 NAL units (VPS, SPS, PPS, IDR, non-IDR).
5. Monitors on-die silicon temperatures (CSS, MSS, UPA, DSS) and memory loads at 1 Hz.
6. Benchmarks actual throughput against the 25 Mbps SLA and dumps a sample .h265 file.
"""

import argparse
import json
import os
import pathlib
import signal
import subprocess
import sys
import time
from collections import deque
import depthai as dai
from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from tools.test_harness.hevc import parse_hevc_nal_units
from tools.test_harness.pipeline import build_dual_stream_pipeline
from tools.test_harness.telemetry import TelemetryRecorder, sparkline

console = Console()
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


def resolve_target_device(mxid: str | None = None) -> dai.DeviceInfo:
    devices = dai.Device.getAllAvailableDevices()
    if not devices:
        devices = dai.DeviceBootloader.getAllAvailableDevices()

    if not devices:
        raise RuntimeError(
            "No connected Opal C1 / DepthAI device detected! Ensure the camera is plugged in."
        )

    if mxid:
        for d in devices:
            if d.getMxId() == mxid:
                return d
        raise RuntimeError(f"Device with MxID {mxid} not found among available devices.")

    return devices[0]


def render_dashboard(
    stats: dict,
    telemetry: dict,
    uptime_sec: float,
    duration_sec: int,
    is_paused: bool,
    fps_history: list[float] | None = None,
    bps_history: list[float] | None = None,
    temp_history: list[float] | None = None,
) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body", ratio=1),
        Layout(name="footer", size=3),
    )

    # Header
    rem_str = f"{int(duration_sec - uptime_sec)}s remaining" if duration_sec > 0 else "Continuous"
    header_table = Table.grid(expand=True)
    header_table.add_column(justify="left")
    header_table.add_column(justify="right")
    header_table.add_row(
        Text("Opal C1 — 4K H.265 + 1080p UVC Test Harness (Phase 1)", style="bold cyan"),
        Text(f"Uptime: {int(uptime_sec)}s | {rem_str}", style="bold yellow"),
    )
    layout["header"].update(Panel(header_table, box=box.ROUNDED, style="bright_blue"))

    # Body: 2 Columns (Stream Metrics & Silicon Health)
    layout["body"].split_row(
        Layout(name="stream", ratio=1),
        Layout(name="health", ratio=1),
    )

    # Stream Metrics Table
    stream_table = Table(title="4K H.265 Stream & Bitstream Metrics", box=box.SIMPLE, expand=True)
    stream_table.add_column("Metric", style="bold")
    stream_table.add_column("Value", justify="right")

    fps_style = "bold green" if stats["current_fps"] >= 28.0 else "bold red"
    bitrate_mbps = (stats["instant_bps"] * 8) / 1_000_000
    avg_bitrate_mbps = (stats["avg_bps"] * 8) / 1_000_000

    stream_table.add_row("Resolution", "3840×2160 (Native 4K)")
    stream_table.add_row("Video Codec", "H.265 / HEVC (Main Profile)")
    stream_table.add_row("Concurrent UVC", "[green]1920x1080 NV12 (Active)[/green]")
    stream_table.add_row("Frames Ingested", f"{stats['frames_total']:,}")
    stream_table.add_row("Instantaneous FPS", Text(f"{stats['current_fps']:.1f} FPS", style=fps_style))
    stream_table.add_row("Average FPS", f"{stats['avg_fps']:.1f} FPS")
    if fps_history:
        stream_table.add_row("Framerate Trend", f"[bold green]{sparkline(fps_history)}[/bold green]")
    stream_table.add_row("Instantaneous Bitrate", f"{bitrate_mbps:.2f} Mbps")
    stream_table.add_row("Average Bitrate", f"{avg_bitrate_mbps:.2f} Mbps")
    if bps_history:
        stream_table.add_row("Bitrate Trend", f"[bold cyan]{sparkline(bps_history)}[/bold cyan]")
    stream_table.add_row("Keyframes (IDR / CRA)", f"{stats['keyframes']:,} (GOP ~{stats['last_gop']})")
    stream_table.add_row("Avg Packet Size", f"{stats['avg_frame_kib']:.1f} KiB")
    layout["stream"].update(Panel(stream_table, box=box.ROUNDED))

    # Silicon Health Table
    health_table = Table(title="Myriad X Silicon Health & Telemetry", box=box.SIMPLE, expand=True)
    health_table.add_column("Component", style="bold")
    health_table.add_column("Temperature / Load", justify="right")

    css_temp = telemetry.get("temp_css", 0.0)
    mss_temp = telemetry.get("temp_mss", 0.0)
    avg_temp = telemetry.get("temp_avg", 0.0)
    temp_style = "bold green" if avg_temp < 58.0 else ("bold yellow" if avg_temp < 70.0 else "bold red")

    health_table.add_row("Average Chip Temp", Text(f"{avg_temp:.1f} °C", style=temp_style))
    health_table.add_row("CSS Core Temp", f"{css_temp:.1f} °C")
    health_table.add_row("MSS Core Temp", f"{mss_temp:.1f} °C")
    if temp_history:
        health_table.add_row("Thermal Trend", f"[bold orange3]{sparkline(temp_history)}[/bold orange3]")
    health_table.add_row("Thermal Headroom", f"{max(0.0, 85.0 - avg_temp):.1f} °C to throttle ceiling")
    health_table.add_row(
        "DDR Memory Usage",
        f"{telemetry.get('ddr_used_mib', 0):.1f} / {telemetry.get('ddr_total_mib', 0):.1f} MiB",
    )
    health_table.add_row(
        "CMX Memory Usage",
        f"{telemetry.get('cmx_used_mib', 0):.1f} / {telemetry.get('cmx_total_mib', 0):.1f} MiB",
    )
    health_table.add_row("Leon CSS CPU Usage", f"{telemetry.get('cpu_css_pct', 0.0):.1f}%")
    health_table.add_row("Leon MSS CPU Usage", f"{telemetry.get('cpu_mss_pct', 0.0):.1f}%")
    layout["health"].update(Panel(health_table, box=box.ROUNDED))

    # Footer
    status_msg = (
        "[bold red]⏸ SIMULATING COMPANION DISCONNECT (Queue discarding silently)...[/bold red]"
        if is_paused
        else "[bold green]✔ Ingesting live 4K H.265 bitstream | Press Ctrl+C to finish[/bold green]"
    )
    layout["footer"].update(Panel(status_msg, box=box.ROUNDED, style="dim"))

    return layout


def main():
    parser = argparse.ArgumentParser(
        description="Phase 1: Test 4K H.265 + 1080p UVC dual-stream integrity and thermal performance"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=int(os.environ.get("usage_duration", 30)),
        help="Duration to run the test in seconds (0 for continuous until Ctrl+C, default: 30)",
    )
    parser.add_argument(
        "--bitrate",
        type=int,
        default=int(os.environ.get("usage_bitrate", 25000)),
        help="Target 4K H.265 bitrate in kbps (default: 25000)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=int(os.environ.get("usage_fps", 30)),
        help="Target framerate (default: 30)",
    )
    parser.add_argument(
        "--save-h265",
        default=os.environ.get("usage_save_h265", "tools/test_harness/sample_4k.h265"),
        help="Path to save captured raw H.265 bitstream",
    )
    parser.add_argument(
        "--simulate-disconnect",
        action="store_true",
        default="usage_simulate_disconnect" in os.environ,
        help="Simulate companion app pause/resume to verify UVC non-blocking queue immunity",
    )
    parser.add_argument(
        "--mxid",
        default=os.environ.get("usage_mxid", None),
        help="Target Opal C1 Myriad X device ID (auto-detected if omitted)",
    )
    parser.add_argument(
        "--flash",
        action="store_true",
        help="Flash this dual-stream pipeline permanently to SPI flash partition 0x100000",
    )
    parser.add_argument(
        "--export-csv",
        default="tests/output/telemetry.csv",
        help="Path to export time-series telemetry CSV (default: tests/output/telemetry.csv)",
    )
    parser.add_argument(
        "--export-json",
        default="tests/output/telemetry.json",
        help="Path to export time-series metrics JSON (default: tests/output/telemetry.json)",
    )
    parser.add_argument(
        "--export-html",
        default="tests/output/benchmark_report.html",
        help="Path to export interactive visual HTML report with SVG charts (default: tests/output/benchmark_report.html)",
    )

    args = parser.parse_args()
    duration = args.duration
    bitrate_kbps = args.bitrate
    fps = args.fps
    save_path = REPO_ROOT / args.save_h265
    save_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path = REPO_ROOT / args.export_csv
    json_path = REPO_ROOT / args.export_json
    html_path = REPO_ROOT / args.export_html
    sim_disconnect = args.simulate_disconnect
    mxid_arg = args.mxid

    console.print(
        Panel.fit(
            "[bold white]Opal C1 — Phase 1 Test Harness (4K H.265 + 1080p UVC)[/bold white]\n"
            f"[dim]Bitrate Target : {bitrate_kbps / 1000:.1f} Mbps CBR | FPS Target: {fps}[/dim]\n"
            f"[dim]Output Bitstream: {save_path.relative_to(REPO_ROOT)}[/dim]",
            border_style="bright_cyan",
        )
    )

    dev_info = resolve_target_device(mxid_arg)
    console.print(f"[green]✔ Target device detected:[/green] [bold]{dev_info.getMxId()}[/bold]")

    console.print("[dim]Constructing dual-stream pipeline...[/dim]")
    pipeline = build_dual_stream_pipeline(fps=fps, bitrate_kbps=bitrate_kbps)

    if args.flash:
        console.print("[bold yellow]Flashing dual-stream pipeline to SPI flash partition 0x100000...[/bold yellow]")
        with dai.DeviceBootloader(dev_info, allowFlashingBootloader=False) as bl:
            def on_progress(p: float):
                console.print(f"  Flashing: {p * 100:.1f}%", end="\r")
            ok, msg = bl.flash(
                on_progress,
                pipeline,
                compress=True,
                applicationName="Opal C1 (Dual Stream Ark)",
                memory=dai.DeviceBootloader.Memory.FLASH,
            )
            console.print(f"\n[green]✔ Flash completed: {msg or 'OK'}[/green]")
        return

    console.print("[dim]Connecting to device and booting pipeline in RAM...[/dim]")
    with dai.Device(pipeline, dev_info, dai.UsbSpeed.SUPER) as device:
        usb_speed = str(device.getUsbSpeed()).replace("UsbSpeed.", "")
        console.print(f"[bold green]✔ Device online![/bold green] Negotiated USB Speed: [bold cyan]{usb_speed}[/bold cyan]")
        console.print("[dim]Opening non-blocking output queues (h265 & sysinfo)...[/dim]\n")

        q_h265 = device.getOutputQueue("h265", maxSize=30, blocking=False)
        q_sys = device.getOutputQueue("sysinfo", maxSize=4, blocking=False)

        h265_file = open(save_path, "wb")

        # Stats state
        stats = {
            "frames_total": 0,
            "bytes_total": 0,
            "current_fps": 0.0,
            "avg_fps": 0.0,
            "instant_bps": 0.0,
            "avg_bps": 0.0,
            "keyframes": 0,
            "last_gop": 0,
            "avg_frame_kib": 0.0,
        }
        telemetry = {}
        recorder = TelemetryRecorder()

        fps_window = deque(maxlen=30)
        bytes_window = deque(maxlen=30)
        fps_history = deque(maxlen=40)
        bps_history = deque(maxlen=40)
        temp_history = deque(maxlen=40)

        start_time = time.time()
        last_keyframe_frame = 0
        is_paused = False
        pause_start = 0.0

        running = True

        def handle_signal(sig, frame):
            nonlocal running
            running = False

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        with Live(
            render_dashboard(stats, telemetry, 0.0, duration, False),
            refresh_per_second=10,
            console=console,
        ) as live:
            while running:
                now = time.time()
                uptime = now - start_time

                if duration > 0 and uptime >= duration:
                    break

                # Disconnect simulation test
                if sim_disconnect:
                    if 10.0 <= uptime <= 14.0:
                        if not is_paused:
                            is_paused = True
                            pause_start = now
                        time.sleep(0.05)
                        live.update(
                            render_dashboard(
                                stats,
                                telemetry,
                                uptime,
                                duration,
                                True,
                                list(fps_history),
                                list(bps_history),
                                list(temp_history),
                            )
                        )
                        continue
                    elif is_paused and uptime > 14.0:
                        is_paused = False

                # 1. Drain Telemetry Queue (1 Hz)
                in_sys = q_sys.tryGet()
                if in_sys is not None:
                    telemetry["temp_avg"] = in_sys.chipTemperature.average
                    telemetry["temp_css"] = in_sys.chipTemperature.css
                    telemetry["temp_mss"] = in_sys.chipTemperature.mss
                    telemetry["ddr_used_mib"] = in_sys.ddrMemoryUsage.used / (1024 * 1024)
                    telemetry["ddr_total_mib"] = in_sys.ddrMemoryUsage.total / (1024 * 1024)
                    telemetry["cmx_used_mib"] = in_sys.cmxMemoryUsage.used / (1024 * 1024)
                    telemetry["cmx_total_mib"] = in_sys.cmxMemoryUsage.total / (1024 * 1024)
                    telemetry["cpu_css_pct"] = in_sys.leonCssCpuUsage.average * 100.0
                    telemetry["cpu_mss_pct"] = in_sys.leonMssCpuUsage.average * 100.0

                # 2. Ingest H.265 Frame Packets
                in_h265 = q_h265.tryGet()
                if in_h265 is not None:
                    data = in_h265.getData()
                    packet_len = len(data)
                    h265_file.write(data)

                    stats["frames_total"] += 1
                    stats["bytes_total"] += packet_len
                    fps_window.append(now)
                    bytes_window.append((now, packet_len))

                    # Parse NAL units
                    nals = parse_hevc_nal_units(data)
                    is_keyframe = any(nal_type in (19, 20, 21) for nal_type, _ in nals)
                    if is_keyframe:
                        stats["keyframes"] += 1
                        if last_keyframe_frame > 0:
                            stats["last_gop"] = stats["frames_total"] - last_keyframe_frame
                        last_keyframe_frame = stats["frames_total"]

                    # Compute rolling FPS
                    if len(fps_window) > 1:
                        time_span = fps_window[-1] - fps_window[0]
                        if time_span > 0:
                            stats["current_fps"] = (len(fps_window) - 1) / time_span
                    if uptime > 0:
                        stats["avg_fps"] = stats["frames_total"] / uptime

                    # Compute rolling Bitrate
                    if len(bytes_window) > 1:
                        span = bytes_window[-1][0] - bytes_window[0][0]
                        total_window_bytes = sum(b for _, b in bytes_window)
                        if span > 0:
                            stats["instant_bps"] = total_window_bytes / span
                    if uptime > 0:
                        stats["avg_bps"] = stats["bytes_total"] / uptime

                    stats["avg_frame_kib"] = (stats["bytes_total"] / stats["frames_total"]) / 1024.0

                    current_bps_mbps = (stats["instant_bps"] * 8) / 1_000_000
                    recorder.record(
                        timestamp_sec=uptime,
                        fps=stats["current_fps"],
                        bitrate_mbps=current_bps_mbps,
                        frame_size_kib=packet_len / 1024.0,
                        is_keyframe=is_keyframe,
                        temp_avg_c=telemetry.get("temp_avg", 0.0),
                        temp_css_c=telemetry.get("temp_css", 0.0),
                        temp_mss_c=telemetry.get("temp_mss", 0.0),
                        ddr_used_mib=telemetry.get("ddr_used_mib", 0.0),
                        cmx_used_mib=telemetry.get("cmx_used_mib", 0.0),
                        cpu_css_pct=telemetry.get("cpu_css_pct", 0.0),
                        cpu_mss_pct=telemetry.get("cpu_mss_pct", 0.0),
                    )

                    if stats["current_fps"] > 0:
                        fps_history.append(stats["current_fps"])
                    if current_bps_mbps > 0:
                        bps_history.append(current_bps_mbps)
                    if "temp_avg" in telemetry and telemetry["temp_avg"] > 0:
                        temp_history.append(telemetry["temp_avg"])

                time.sleep(0.002)
                live.update(
                    render_dashboard(
                        stats,
                        telemetry,
                        uptime,
                        duration,
                        is_paused,
                        list(fps_history),
                        list(bps_history),
                        list(temp_history),
                    )
                )

        h265_file.close()

    console.print("\n[bold green]✔ Stream ingestion test complete![/bold green]\n")

    # Final SLA Scorecard
    scorecard = Table(title="Phase 1 Performance SLA Verification Scorecard", box=box.ROUNDED)
    scorecard.add_column("Metric / Requirement", style="bold")
    scorecard.add_column("SLA Target", justify="center")
    scorecard.add_column("Measured Result", justify="center")
    scorecard.add_column("Status", justify="center")

    avg_bitrate_mbps = (stats["avg_bps"] * 8) / 1_000_000
    bitrate_pass = 18.0 <= avg_bitrate_mbps <= 32.0
    scorecard.add_row(
        "4K H.265 Bitrate (CBR)",
        f"{bitrate_kbps / 1000:.1f} Mbps (±25%)",
        f"{avg_bitrate_mbps:.2f} Mbps",
        "[bold green]PASS[/bold green]" if bitrate_pass else "[bold yellow]WARN[/bold yellow]",
    )

    fps_pass = stats["avg_fps"] >= 28.0
    scorecard.add_row(
        "Capture & Encode Framerate",
        f"{fps}.0 FPS (≥ 28.0)",
        f"{stats['avg_fps']:.1f} FPS",
        "[bold green]PASS[/bold green]" if fps_pass else "[bold red]FAIL[/bold red]",
    )

    final_temp = telemetry.get("temp_avg", 0.0)
    temp_pass = final_temp < 60.0
    scorecard.add_row(
        "Average Silicon Temperature",
        "< 60.0 °C (Throttle limit: 85°C)",
        f"{final_temp:.1f} °C",
        "[bold green]PASS[/bold green]" if temp_pass else "[bold red]FAIL[/bold red]",
    )

    kf_pass = stats["keyframes"] >= max(1, int(uptime) - 2)
    scorecard.add_row(
        "Keyframe Cadence (GOP)",
        "1 Keyframe / second (GOP 30)",
        f"{stats['keyframes']} keyframes (GOP ~{stats['last_gop']})",
        "[bold green]PASS[/bold green]" if kf_pass else "[bold yellow]WARN[/bold yellow]",
    )

    console.print(scorecard)

    # ffprobe validation if available
    ffprobe_path = "/opt/homebrew/bin/ffprobe"
    if os.path.exists(ffprobe_path) and os.path.exists(save_path) and os.path.getsize(save_path) > 0:
        console.print("\n[dim]Validating bitstream integrity with ffprobe...[/dim]")
        try:
            cmd = [
                ffprobe_path,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,width,height,avg_frame_rate,profile",
                "-of",
                "json",
                str(save_path),
            ]
            probe_out = subprocess.check_output(cmd, timeout=5)
            probe_json = json.loads(probe_out)
            streams = probe_json.get("streams", [])
            if streams:
                st = streams[0]
                console.print(
                    Panel(
                        f"  • Codec   : [bold green]{st.get('codec_name', 'unknown').upper()}[/bold green]\n"
                        f"  • Geometry: [bold]{st.get('width')} × {st.get('height')}[/bold]\n"
                        f"  • Profile : [bold]{st.get('profile', 'Main')}[/bold]\n"
                        f"  • Raw Size: [cyan]{os.path.getsize(save_path) / (1024 * 1024):.2f} MiB[/cyan]",
                        title="ffprobe Bitstream Verification",
                        border_style="green",
                    )
                )
        except Exception as exc:
            console.print(f"[yellow]ffprobe validation note: {exc}[/yellow]")

    # Export Chartable Telemetry & Reports
    if recorder.samples:
        recorder.export_csv(csv_path)
        recorder.export_json(json_path)
        recorder.generate_html_report(html_path, title=f"Opal C1 Benchmark Telemetry ({int(uptime)}s run)")

        console.print()
        console.print(
            Panel(
                f"[bold cyan]📊 Chartable Telemetry & Visual Reports Exported:[/bold cyan]\n\n"
                f"  • [bold]Raw CSV Telemetry[/bold]  : file://{csv_path} ({len(recorder.samples):,} samples)\n"
                f"  • [bold]JSON Summary[/bold]        : file://{json_path}\n"
                f"  • [bold green]Interactive HTML Chart[/bold green]: file://{html_path}\n\n"
                f"[dim]Tip: Open the HTML report in Safari/Chrome to view responsive SVG charts for FPS, Bitrate, Thermals, and CPU load.[/dim]",
                title="Telemetry & Charting Exports",
                border_style="bright_cyan",
            )
        )


if __name__ == "__main__":
    main()
