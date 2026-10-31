#!/usr/bin/env -S uv run python -P
# SPDX-License-Identifier: MIT
#MISE description="Inspect the connected Opal C1 hardware, sensors, calibration EEPROM, and bootloader configuration (read-only)"
#USAGE flag "--mxid <mxid>" help="Target Opal C1 Myriad X device ID (auto-detected if omitted)"

import json
import os
import pathlib
import plistlib
import re
import subprocess
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_USB_BL = REPO_ROOT / "firmware" / "luxonis" / "bootloader" / "depthai-bootloader-usb.cmd"

# Prevent C++ spdlog warnings in libdepthai-core from colliding with Rich live spinners
os.environ.setdefault("DEPTHAI_LEVEL", "error")
if DEFAULT_USB_BL.exists():
    os.environ.setdefault("DEPTHAI_BOOTLOADER_BINARY_USB", str(DEFAULT_USB_BL))

import depthai as dai
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table


MOVIDIUS_VID = 0x03E7
OPAL_PIDS = (0xF63D, 0xF63C)

console = Console()


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
                f"Thunderbolt/USB-C port for reliable 5 Gbps SuperSpeed operation.[/dim]",
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


def fmt_mib(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.2f} MiB ({num_bytes:,} B)"


def inspect_discovery() -> list[dai.DeviceInfo]:
    all_xlink = dai.XLinkConnection.getAllConnectedDevices()

    table = Table(
        title="1. XLink / DepthAI Device Discovery",
        box=box.ROUNDED,
        header_style="bold cyan",
        title_style="bold white",
    )
    table.add_column("Port / Name", style="bold")
    table.add_column("MxID", style="green")
    table.add_column("State", style="yellow")
    table.add_column("Protocol", style="magenta")
    table.add_column("Status")

    for d in all_xlink:
        table.add_row(
            d.name,
            d.getMxId(),
            str(d.state).replace("XLinkDeviceState.", ""),
            str(d.protocol).replace("XLinkProtocol.", ""),
            str(d.status).replace("XLinkError_t.", ""),
        )

    if not all_xlink:
        table.add_row("—", "(none enumerated via XLink)", "—", "—", "—")

    console.print()
    console.print(table)
    return all_xlink


def inspect_device_runtime(mxid: str) -> None:
    dev_info = dai.DeviceInfo(mxid)
    pipeline = dai.Pipeline()

    with console.status(f"[bold cyan]Booting Myriad X runtime in RAM for MxID {mxid}..."):
        with dai.Device(pipeline, dev_info, dai.UsbSpeed.SUPER) as device:
            mem_ddr = device.getDdrMemoryUsage()
            mem_cmx = device.getCmxMemoryUsage()
            mem_leon_css = device.getLeonCssHeapUsage()
            mem_leon_mss = device.getLeonMssHeapUsage()
            temp = device.getChipTemperature()
            usb_speed = str(device.getUsbSpeed()).replace("UsbSpeed.", "")
            bl_ver = str(device.getBootloaderVersion())
            eeprom_avail = device.isEepromAvailable()
            features = device.getConnectedCameraFeatures()

            calib_info = "Unavailable"
            try:
                calib = device.readCalibration2()
                eeprom = calib.getEepromData()
                raw_calib = device.readCalibrationRaw()
                non_ff = sum(1 for b in raw_calib if b != 0xFF)
                calib_info = (
                    f"v{eeprom.version} | boardRev={eeprom.boardRev!r} | "
                    f"boardName={eeprom.boardName!r} | {non_ff}/{len(raw_calib)} non-0xFF bytes"
                )
            except Exception as exc:
                calib_info = f"Error: {exc}"

    hw_table = Table(
        title="2. Myriad X Runtime, Memory & Thermal Telemetry (RAM-Only)",
        box=box.ROUNDED,
        header_style="bold cyan",
        title_style="bold white",
    )
    hw_table.add_column("Property", style="bold")
    hw_table.add_column("Value")

    hw_table.add_row("MxID", f"[green]{mxid}[/green]")
    hw_table.add_row("Negotiated USB Speed", f"[bold green]{usb_speed}[/bold green]")
    hw_table.add_row("Active Bootloader", f"[yellow]{bl_ver}[/yellow]")
    hw_table.add_row(
        "Die Temperature",
        f"[bold]{temp.average:.1f} °C[/bold] "
        f"(CSS {temp.css:.1f} °C | MSS {temp.mss:.1f} °C | UPA {temp.upa:.1f} °C | DSS {temp.dss:.1f} °C)",
    )
    hw_table.add_row("DDR RAM", f"{fmt_mib(mem_ddr.used)} / {fmt_mib(mem_ddr.total)}")
    hw_table.add_row("CMX Memory", f"{fmt_mib(mem_cmx.used)} / {fmt_mib(mem_cmx.total)}")
    hw_table.add_row("LeonCSS Heap", f"{fmt_mib(mem_leon_css.used)} / {fmt_mib(mem_leon_css.total)}")
    hw_table.add_row("LeonMSS Heap", f"{fmt_mib(mem_leon_mss.used)} / {fmt_mib(mem_leon_mss.total)}")
    hw_table.add_row("Calibration EEPROM", f"available={eeprom_avail} ({calib_info})")

    console.print()
    console.print(hw_table)

    sensor_table = Table(
        title="Connected Camera Sensor & Native ISP Modes",
        box=box.ROUNDED,
        header_style="bold magenta",
        title_style="bold white",
    )
    sensor_table.add_column("Socket", style="bold")
    sensor_table.add_column("Sensor", style="green")
    sensor_table.add_column("Max Resolution")
    sensor_table.add_column("Autofocus")
    sensor_table.add_column("Supported ISP Configurations")

    for feat in features:
        cfgs = "\n".join(
            f"• {c.width}×{c.height} @ {c.minFps:.1f}–{c.maxFps:.1f} fps"
            for c in feat.configs
        )
        sensor_table.add_row(
            str(feat.socket).replace("CameraBoardSocket.", ""),
            feat.sensorName,
            f"{feat.width}×{feat.height}",
            "[green]Yes[/green]" if feat.hasAutofocus else "No",
            cfgs,
        )

    console.print()
    console.print(sensor_table)


def inspect_bootloader(mxid: str) -> None:
    sdk_ver = str(dai.DeviceBootloader.getEmbeddedBootloaderVersion())

    with console.status("[bold cyan]Connecting to SPI Flash via RAM-booted v0.0.29 Bootloader..."):
        time.sleep(1.5)
        found, dev_info = dai.Device.getDeviceByMxId(mxid)
        if not found:
            dev_info = dai.DeviceInfo(mxid)

        with dai.DeviceBootloader(dev_info, allowFlashingBootloader=True) as bl:
            flashed_ver = str(bl.getFlashedVersion())
            active_ver = str(bl.getVersion())
            is_embedded = bl.isEmbeddedVersion()
            bl_type = str(bl.getType()).replace("Type.", "")
            mem_info = bl.getMemoryInfo(dai.DeviceBootloader.Memory.FLASH)
            cfg_data = bl.readConfigData()
            app_info = bl.readApplicationInfo(dai.DeviceBootloader.Memory.FLASH)

    bl_table = Table(
        title="3. SPI NOR Flash & Bootloader Inspection (Read-Only)",
        box=box.ROUNDED,
        header_style="bold yellow",
        title_style="bold white",
    )
    bl_table.add_column("Property", style="bold")
    bl_table.add_column("Value")

    ver_status = (
        f"[bold red]{flashed_ver}[/bold red] [dim](< 0.0.28: susceptible to soft-restart bug)[/dim]"
        if flashed_ver < "0.0.28"
        else f"[bold green]{flashed_ver}[/bold green]"
    )
    bl_table.add_row("Flashed SPI Bootloader", ver_status)
    bl_table.add_row(
        "Active RAM Bootloader",
        f"[green]{active_ver}[/green] (embedded={is_embedded}, latest SDK={sdk_ver})",
    )
    bl_table.add_row("Bootloader Type", bl_type)
    bl_table.add_row(
        "SPI Flash Chip",
        f"[bold]{fmt_mib(mem_info.size)}[/bold] [{mem_info.info}] (available={mem_info.available})",
    )
    bl_table.add_row(
        "Flashed Application @ 0x100000",
        f"hasApplication=[green]{app_info.hasApplication}[/green] "
        f"appName={app_info.applicationName!r} fwVersion={app_info.firmwareVersion!r}",
    )

    console.print()
    console.print(bl_table)
    compact_json = re.sub(
        r"\[\s+([^\[\]\{\}]+?)\s+\]",
        lambda m: "[" + ", ".join(x.strip() for x in m.group(1).split(",")) + "]",
        json.dumps(cfg_data, indent=2),
    )
    console.print()
    console.print(
        Panel(
            Syntax(compact_json, "json", theme="monokai", word_wrap=True),
            title="Bootloader Configuration (0x0FC000)",
            border_style="cyan",
            expand=False,
        )
    )


def main() -> None:
    console.print(
        Panel.fit(
            "[bold white]Opal C1 Hardware & Firmware Inspector[/bold white]\n"
            "[dim]Read-only DepthAI / Myriad X diagnostic utility[/dim]",
            border_style="bright_blue",
        )
    )
    topo = check_and_warn_topology()
    inspect_discovery()
    mxid = resolve_mxid(os.environ.get("usage_mxid"), topo)
    inspect_device_runtime(mxid)
    inspect_bootloader(mxid)


if __name__ == "__main__":
    main()
