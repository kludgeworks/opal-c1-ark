#!/usr/bin/env -S uv run python -P
# /// script
# dependencies = [
#     "depthai>=2.33.0",
#     "rich>=13.0.0",
# ]
# ///
"""Run a standalone UVC webcam pipeline from RAM on the Opal C1."""

import signal
import sys
import time
import depthai as dai
from rich.console import Console

console = Console()

def main():
    console.print("\n[bold cyan]📷 Opal C1 — Custom Modern UVC Firmware (RAM Mode)[/bold cyan]")
    console.print("[dim]Building DepthAI 2025 pipeline with Sony IMX582 (LCM48)...[/dim]\n")

    pipeline = dai.Pipeline()

    # 1. Configure BoardConfig for native UVC descriptors
    board_config = dai.BoardConfig()
    uvc_config = dai.BoardConfig.UVC()
    uvc_config.enable = True
    uvc_config.width = 1920
    uvc_config.height = 1080
    uvc_config.cameraName = "Opal C1 (Ark Edition)"
    board_config.uvc = uvc_config
    pipeline.setBoardConfig(board_config)

    # 2. Configure 48 MP Sony IMX582 Sensor (CAM_A)
    cam = pipeline.create(dai.node.ColorCamera)
    cam.setBoardSocket(dai.CameraBoardSocket.CAM_A)
    cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_4_K)
    cam.setIspScale(1, 2)  # 3840x2160 -> 1920x1080 (1080p output)
    cam.setFps(30)
    cam.setImageOrientation(dai.CameraImageOrientation.ROTATE_180_DEG)
    cam.initialControl.setAutoFocusMode(dai.CameraControl.AutoFocusMode.CONTINUOUS_VIDEO)

    # 3. Create UVC Node
    uvc = pipeline.create(dai.node.UVC)
    cam.video.link(uvc.input)

    console.print("[yellow]⚡ Booting pipeline into Opal C1 RAM...[/yellow]")
    with dai.Device(pipeline) as device:
        usb_speed = device.getUsbSpeed()
        mxid = device.getMxId()

        console.print(f"[bold green]✔ Live in UVC mode![/bold green]")
        console.print(f"  • Device MxID  : [bold]{mxid}[/bold]")
        console.print(f"  • USB Speed    : [bold cyan]{usb_speed}[/bold cyan]")
        console.print(f"  • Resolution   : [bold]1920x1080 @ 30 FPS[/bold]")
        console.print(f"  • Camera Name  : [bold magenta]Opal C1 (Ark Edition)[/bold magenta]")
        console.print(f"  • Autofocus    : [green]Continuous Video AF enabled[/green]\n")
        console.print("[bold yellow]👉 You can now open Photo Booth, FaceTime, or QuickTime Player and select 'Opal C1 (Ark Edition)'.[/bold yellow]")
        console.print("[dim]Press Ctrl+C in this terminal to stop streaming.[/dim]\n")

        running = True
        def handle_signal(sig, frame):
            nonlocal running
            running = False
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        start_time = time.time()
        while running:
            uptime = int(time.time() - start_time)
            mins, secs = divmod(uptime, 60)
            sys.stdout.write(f"\r  Streaming active: {mins:02d}:{secs:02d} | Press Ctrl+C to stop...")
            sys.stdout.flush()
            time.sleep(1)

        sys.stdout.write("\n")
        console.print("\n[yellow]Stopping UVC pipeline and resetting device cleanly...[/yellow]")

    console.print("[bold green]✔ Clean shutdown complete.[/bold green]\n")

if __name__ == "__main__":
    main()
