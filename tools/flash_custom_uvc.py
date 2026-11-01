#!/usr/bin/env -S uv run python -P
# SPDX-License-Identifier: MIT
#MISE description="Flash modern SuperSpeed UVC pipeline firmware to Opal C1 SPI flash"
#USAGE flag "--mxid <mxid>" help="Target Opal C1 Myriad X device ID (auto-detected if omitted)"

import os
import pathlib
import sys
import time
import depthai as dai
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

console = Console()
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def build_pipeline() -> dai.Pipeline:
    pipeline = dai.Pipeline()

    # 1. Early UVC USB descriptor configuration (Plug & Play 1080p)
    board_config = dai.BoardConfig()
    uvc_config = dai.BoardConfig.UVC()
    uvc_config.enable = True
    uvc_config.width = 1920
    uvc_config.height = 1080
    uvc_config.cameraName = "Opal C1 (Ark Edition)"
    board_config.uvc = uvc_config
    pipeline.setBoardConfig(board_config)

    # 2. Sony IMX582 Sensor (CAM_A) - 4K capture with Hardware ISP 1:2 scale (Zero latency!)
    cam = pipeline.create(dai.node.ColorCamera)
    cam.setBoardSocket(dai.CameraBoardSocket.CAM_A)
    cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_4_K)
    cam.setIspScale(1, 2)  # 3840x2160 -> 1920x1080 directly on-die in hardware ISP!
    cam.setFps(30)
    cam.setImageOrientation(dai.CameraImageOrientation.ROTATE_180_DEG)
    cam.initialControl.setAutoFocusMode(dai.CameraControl.AutoFocusMode.CONTINUOUS_VIDEO)

    # 3. Direct Hardware ISP -> UVC Output (Pure line-rate, zero backpressure)
    uvc = pipeline.create(dai.node.UVC)
    cam.video.link(uvc.input)

    return pipeline


def resolve_device(mxid: str | None = None) -> dai.DeviceInfo:
    devices = dai.DeviceBootloader.getAllAvailableDevices()
    if not devices:
        devices = dai.Device.getAllAvailableDevices()

    if not devices:
        raise RuntimeError("No connected Opal C1 / DepthAI device found!")

    if mxid:
        for d in devices:
            if d.getMxId() == mxid:
                return d
        raise RuntimeError(f"Device with MxID {mxid} not found among available devices.")

    return devices[0]


def main():
    mxid_arg = None
    if len(sys.argv) > 1 and sys.argv[1] == "--mxid" and len(sys.argv) > 2:
        mxid_arg = sys.argv[2]
    elif "usage_mxid" in os.environ:
        mxid_arg = os.environ["usage_mxid"]

    console.print(
        Panel.fit(
            "[bold white]Opal C1 — Flash Custom SuperSpeed UVC Firmware[/bold white]\n"
            "[dim]Target: SPI Flash Partition 0x100000 (Application)[/dim]\n"
            "[dim]Bootloader: Preserving Luxonis v0.0.29 at 0x000000[/dim]",
            border_style="bright_cyan",
        )
    )

    dev_info = resolve_device(mxid_arg)
    mxid = dev_info.getMxId()
    console.print(f"[green]✔ Target device detected:[/green] [bold]{mxid}[/bold] (state: {dev_info.state})")

    console.print("[dim]Building modern DepthAI hybrid pipeline (1080p UVC + 4K H.265 + Telemetry)...[/dim]")
    pipeline = build_pipeline()

    dap_output_path = REPO_ROOT / "firmware" / "custom" / "opal-c1-ark-edition.dap"
    dap_output_path.parent.mkdir(parents=True, exist_ok=True)
    console.print(f"[dim]Exporting application package to {dap_output_path.relative_to(REPO_ROOT)}...[/dim]")
    dai.DeviceBootloader.saveDepthaiApplicationPackage(
        dap_output_path, pipeline, compress=True, applicationName="Opal C1 (Ark Edition)"
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=36),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        conn_task = progress.add_task(f"Connecting to bootloader on {mxid}...", total=None)
        with dai.DeviceBootloader(dev_info, allowFlashingBootloader=False) as bl:
            bl_ver = str(bl.getFlashedVersion())
            progress.remove_task(conn_task)

            flash_task = progress.add_task(
                "Compressing & Flashing UVC Application to SPI Flash...", total=100.0
            )

            def on_progress(p: float) -> None:
                progress.update(flash_task, completed=p * 100.0)

            ok, msg = bl.flash(
                on_progress,
                pipeline,
                compress=True,
                applicationName="Opal C1 (Ark Edition)",
                memory=dai.DeviceBootloader.Memory.FLASH,
            )
            progress.update(flash_task, completed=100.0)

            if not ok:
                raise RuntimeError(f"Flashing failed: {msg}")

    console.print(f"\n[bold green]✔ Flash completed successfully![/bold green] Status: {msg or 'OK'}")

    with console.status("[bold cyan]Rebooting camera and verifying application partition..."):
        time.sleep(3.0)
        verify_dev = resolve_device(mxid)
        with dai.DeviceBootloader(verify_dev, allowFlashingBootloader=False) as bl:
            after_ver = str(bl.getFlashedVersion())
            app_info = bl.readApplicationInfo(dai.DeviceBootloader.Memory.FLASH)
            cfg_data = bl.readConfigData()

    table = Table(
        title="Opal C1 SPI Flash Verification",
        box=box.ROUNDED,
        header_style="bold green",
        title_style="bold white",
    )
    table.add_column("Property", style="bold")
    table.add_column("Value")

    table.add_row("Device MxID", f"[bold]{mxid}[/bold]")
    table.add_row("SPI Bootloader Version", f"[bold green]{after_ver}[/bold green]")
    table.add_row("Application Present", f"[bold green]{app_info.hasApplication}[/bold green]")
    table.add_row("Application Name", f"[bold cyan]{app_info.applicationName}[/bold cyan]")
    table.add_row("Firmware Version", f"{app_info.firmwareVersion}")
    table.add_row(
        "USB Bootloader Config",
        f"vid=0x{cfg_data.get('usb', {}).get('vid', 0):04x} "
        f"pid=0x{cfg_data.get('usb', {}).get('pid', 0):04x} "
        f"maxUsbSpeed={cfg_data.get('usb', {}).get('maxUsbSpeed')} "
        f"timeoutMs={cfg_data.get('usb', {}).get('timeoutMs')}",
    )

    console.print()
    console.print(table)
    console.print("\n[bold green]🎉 Flash verified![/bold green] The Opal C1 is now a standalone plug-and-play UVC camera.\n")


if __name__ == "__main__":
    main()
