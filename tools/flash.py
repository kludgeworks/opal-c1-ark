#!/usr/bin/env -S uv run python -P
# SPDX-License-Identifier: MIT
#MISE description="Flash the upgraded Luxonis v0.0.29 bootloader or archived Opal C1 images to SPI flash"
#USAGE flag "--target <target>" default="luxonis-bootloader" help="What to flash to SPI flash" {
#USAGE     long_help "Firmware image from firmware/ to flash to SPI flash:\n  - luxonis-bootloader: Upgraded Luxonis v0.0.29 USB bootloader (firmware/luxonis/bootloader/depthai-bootloader-usb.cmd), fixing the < 0.0.28 soft-reset hang while preserving the C1 application at 0x100000\n  - opal-bootloader: Stock v0.0.15 USB bootloader from Opal Composer (firmware/opal-c1/bootloader/depthai-bootloader-usb.cmd), preserving the C1 application at 0x100000\n  - opal-application: Stock 11.0 MiB Opal C1 standalone UVC+Mic SBR application (firmware/opal-c1/application/opal-c1-standalone.sbr) at 0x100000, preserving the bootloader"
#USAGE     choices "luxonis-bootloader" "opal-bootloader" "opal-application"
#USAGE }
#USAGE flag "--mxid <mxid>" help="Target Opal C1 Myriad X device ID (auto-detected if omitted)"
#USAGE flag "--bootloader-file <path>" help="Custom bootloader .cmd binary path (overrides --target)"

import hashlib
import os
import pathlib
import plistlib
import subprocess
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_BL_PATH = REPO_ROOT / "firmware" / "luxonis" / "bootloader" / "depthai-bootloader-usb.cmd"

os.environ.setdefault("DEPTHAI_LEVEL", "error")
if DEFAULT_BL_PATH.exists():
    os.environ.setdefault("DEPTHAI_BOOTLOADER_BINARY_USB", str(DEFAULT_BL_PATH))

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


MOVIDIUS_VID = 0x03E7
OPAL_PIDS = (0xF63D, 0xF63C)

OPAL_BL_PATH = REPO_ROOT / "firmware" / "opal-c1" / "bootloader" / "depthai-bootloader-usb.cmd"
OPAL_APP_PATH = REPO_ROOT / "firmware" / "opal-c1" / "application" / "opal-c1-standalone.sbr"
BACKUP_1MB_PATH = REPO_ROOT / "backups" / "bootloader_0.0.15_1MB.bin"
APPLICATION_OFFSET = 0x100000

console = Console()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inspect_usb_topology() -> dict | None:
    """Inspect macOS IOUSBHostDevice registry for the Opal C1 and detect intermediate hubs."""
    try:
        out = subprocess.check_output(
            ["ioreg", "-r", "-c", "IOUSBHostDevice", "-a"], timeout=5
        )
        items = plistlib.loads(out)
    except Exception:
        return None

    def walk(nodes: list[dict], chain: tuple[str, ...] = ()) -> dict | None:
        for node in nodes:
            vid = node.get("idVendor")
            pid = node.get("idProduct")
            name = (
                node.get("USB Product Name")
                or node.get("kUSBProductString")
                or node.get("IORegistryEntryName")
                or "USB Device"
            )
            loc = int(node.get("locationID", 0))
            cur_chain = (*chain, f"{name} (0x{loc:08x})") if vid is not None else chain

            if vid == MOVIDIUS_VID and pid in OPAL_PIDS:
                hub_depth = len(cur_chain) - 1
                is_behind_hub = hub_depth > 0 or (loc & 0x000FFFFF) != 0
                return {
                    "product_name": name,
                    "serial": str(node.get("USB Serial Number", "")),
                    "location_id": loc,
                    "link_speed_bps": int(node.get("UsbLinkSpeed", 0)),
                    "power_ma": int(node.get("UsbPowerSinkAllocation", 0)),
                    "is_behind_hub": is_behind_hub,
                    "chain": cur_chain,
                }

            children = node.get("IORegistryEntryChildren")
            if isinstance(children, list):
                found = walk(children, cur_chain)
                if found:
                    return found
        return None

    return walk(items) if isinstance(items, list) else None


def check_and_warn_topology() -> dict | None:
    topo = inspect_usb_topology()
    if not topo:
        return None

    chain_str = " -> ".join(topo["chain"])
    speed_gbps = topo["link_speed_bps"] / 1_000_000_000
    speed_str = (
        f"{speed_gbps:.1f} Gbps"
        if topo["link_speed_bps"] >= 1_000_000_000
        else f"{topo['link_speed_bps'] // 1_000_000} Mbps"
    )

    if topo["is_behind_hub"]:
        console.print()
        console.print(
            Panel(
                f"[bold yellow]⚠ Camera is connected through an external USB hub/dock![/bold yellow]\n"
                f"  Topology : [bold]{chain_str}[/bold]\n"
                f"  Link     : {speed_str} ({topo['power_ma']} mA)\n\n"
                f"[dim]External hubs (such as Thunderbolt docks) can fail SuperSpeed link training during "
                f"the Myriad X bootloader's 150 ms USB re-enumeration. Connect directly to a MacBook "
                f"Thunderbolt/USB-C port for reliable flashing and 5 Gbps SuperSpeed operation.[/dim]",
                title="USB Topology Warning",
                border_style="yellow",
            )
        )
    else:
        console.print(
            f"\n[green]✔ Direct connection to Mac root USB port:[/green] [bold]{chain_str}[/bold] "
            f"({speed_str}, {topo['power_ma']} mA)"
        )
    return topo


def resolve_mxid(explicit_mxid: str | None, topo: dict | None) -> str:
    if explicit_mxid:
        return explicit_mxid

    connected = dai.XLinkConnection.getAllConnectedDevices()
    for dev in connected:
        if dev.getMxId():
            return dev.getMxId()

    if topo and topo.get("serial"):
        return topo["serial"]

    raise RuntimeError(
        "No connected Opal C1 / DepthAI device found. Plug in the camera or pass --mxid <mxid>."
    )


def flash_image(target: str, mxid: str, custom_file: str | None) -> None:
    if not BACKUP_1MB_PATH.exists():
        console.print(
            Panel(
                f"[bold yellow]⚠ Note:[/bold yellow] Local SPI bootloader backup ({BACKUP_1MB_PATH.relative_to(REPO_ROOT)}) "
                f"was not found, though the stock Opal v0.0.15 bootloader is archived in "
                f"[bold]firmware/opal-c1/bootloader/[/bold].\n"
                f"Run [bold cyan]mise run backup[/bold cyan] first if you want a full 16 MiB dump of your unit's flash.",
                border_style="yellow",
            )
        )

    use_flash_bootloader = True
    flash_offset = 0
    if custom_file:
        raw_path = pathlib.Path(custom_file)
        target_path = raw_path if raw_path.is_absolute() else (REPO_ROOT / raw_path).resolve()
        target_desc = f"Custom USB Bootloader ({target_path.name})"
    elif target == "luxonis-bootloader":
        target_path = DEFAULT_BL_PATH
        target_desc = "Luxonis USB Bootloader v0.0.29"
    elif target == "opal-bootloader":
        target_path = OPAL_BL_PATH
        target_desc = "Opal Composer Stock USB Bootloader (v0.0.15)"
    elif target == "opal-application":
        target_path = OPAL_APP_PATH
        target_desc = "Opal C1 Standalone SBR Application Image (0x100000)"
        use_flash_bootloader = False
        flash_offset = APPLICATION_OFFSET
    else:
        raise ValueError(f"Unsupported flash target: {target!r}")

    if not target_path.exists():
        raise RuntimeError(
            f"Target binary {target_path} not found. Run 'mise run download' first."
        )

    target_bytes = target_path.read_bytes()
    target_sha = sha256_hex(target_bytes)
    dev_info = dai.DeviceInfo(mxid)

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=36),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        conn_task = progress.add_task(
            f"Connecting to {mxid} via RAM-booted v0.0.29 Bootloader...", total=None
        )
        with dai.DeviceBootloader(dev_info, allowFlashingBootloader=True) as bl:
            before_ver = str(bl.getFlashedVersion())
            progress.remove_task(conn_task)

            flash_task = progress.add_task(
                f"Flashing {target_desc} ({len(target_bytes):,} B)...", total=100.0
            )

            def on_progress(p: float) -> None:
                progress.update(flash_task, completed=p * 100.0)

            if use_flash_bootloader:
                ok, msg = bl.flashBootloader(
                    dai.DeviceBootloader.Memory.FLASH,
                    dai.DeviceBootloader.Type.USB,
                    on_progress,
                    str(target_path),
                )
            else:
                ok, msg = bl.flashCustom(
                    dai.DeviceBootloader.Memory.FLASH,
                    flash_offset,
                    target_bytes,
                    on_progress,
                )
            progress.update(flash_task, completed=100.0)

            if not ok:
                raise RuntimeError(f"Flashing failed: {msg}")

    with console.status("[bold cyan]Waiting for camera to reboot and verifying SPI flash..."):
        time.sleep(2.5)
        found, verify_info = dai.Device.getDeviceByMxId(mxid)
        if not found:
            verify_info = dai.DeviceInfo(mxid)

        with dai.DeviceBootloader(verify_info, allowFlashingBootloader=True) as bl:
            after_ver = str(bl.getFlashedVersion())
            app_info = bl.readApplicationInfo(dai.DeviceBootloader.Memory.FLASH)
            cfg_data = bl.readConfigData()

    try:
        rel_path = str(target_path.relative_to(REPO_ROOT))
    except ValueError:
        rel_path = str(target_path)

    summary = Table(
        title="SPI Flash Summary",
        box=box.ROUNDED,
        header_style="bold green",
        title_style="bold white",
    )
    summary.add_column("Field", style="bold")
    summary.add_column("Value")

    summary.add_row("Target", f"[cyan]{target}[/cyan] ({target_desc})")
    summary.add_row("Source Binary", f"{rel_path} ({len(target_bytes):,} B)")
    summary.add_row("Source SHA-256", f"[dim]{target_sha}[/dim]")
    summary.add_row("Previous SPI Bootloader", f"[yellow]{before_ver}[/yellow]")
    summary.add_row("Verified SPI Bootloader", f"[bold green]{after_ver}[/bold green]")
    summary.add_row(
        "Application Partition @ 0x100000",
        f"hasApplication=[bold green]{app_info.hasApplication}[/bold green]",
    )
    summary.add_row(
        "USB Bootloader Config",
        f"vid=0x{cfg_data.get('usb', {}).get('vid', 0):04x} "
        f"pid=0x{cfg_data.get('usb', {}).get('pid', 0):04x} "
        f"maxUsbSpeed={cfg_data.get('usb', {}).get('maxUsbSpeed')} "
        f"timeoutMs={cfg_data.get('usb', {}).get('timeoutMs')}",
    )

    console.print()
    console.print(summary)


def main() -> None:
    target = os.environ["usage_target"]
    custom_file = os.environ.get("usage_bootloader_file")

    console.print(
        Panel.fit(
            f"[bold white]Opal C1 SPI Flasher[/bold white]\n"
            f"[dim]Target: [bold cyan]{target}[/bold cyan][/dim]",
            border_style="bright_yellow",
        )
    )
    topo = check_and_warn_topology()
    mxid = resolve_mxid(os.environ.get("usage_mxid"), topo)
    flash_image(target, mxid, custom_file)


if __name__ == "__main__":
    main()
