#!/usr/bin/env -S uv run python -P
# SPDX-License-Identifier: MIT
#MISE description="Dump the Opal C1 16 MiB SPI flash backup and decode the embedded SBR sections, pipeline, and assets"
#USAGE flag "--mxid <mxid>" help="Target Opal C1 Myriad X device ID (auto-detected if omitted)"
#USAGE flag "--output-dir <dir>" default="backups" help="Directory to store flash backups and extracted sections"

import hashlib
import json
import os
import pathlib
import plistlib
import struct
import subprocess
import zlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_USB_BL = REPO_ROOT / "firmware" / "luxonis" / "bootloader" / "depthai-bootloader-usb.cmd"

# Prevent C++ spdlog warnings in libdepthai-core from colliding with Rich progress bars
os.environ.setdefault("DEPTHAI_LEVEL", "error")
if DEFAULT_USB_BL.exists():
    os.environ.setdefault("DEPTHAI_BOOTLOADER_BINARY_USB", str(DEFAULT_USB_BL))

import depthai as dai
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TransferSpeedColumn,
)
from rich.table import Table


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
APPLICATION_OFFSET = 0x100000
SBR_MAX_NUM_SECTIONS = 17
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
            f"({speed_str}, {topo['power_ma']} mA)\n"
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


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_nop(buf: bytes, pos: int = 0):
    b = buf[pos]
    pos += 1
    if b <= 0x7F:
        return b, pos
    elif b == 0x80:
        return buf[pos], pos + 1
    elif b == 0x81:
        return struct.unpack_from("<H", buf, pos)[0], pos + 2
    elif b == 0x82:
        return struct.unpack_from("<I", buf, pos)[0], pos + 4
    elif b == 0x83:
        return struct.unpack_from("<Q", buf, pos)[0], pos + 8
    elif b == 0x84:
        return struct.unpack_from("<b", buf, pos)[0], pos + 1
    elif b == 0x85:
        return struct.unpack_from("<h", buf, pos)[0], pos + 2
    elif b == 0x86:
        return struct.unpack_from("<i", buf, pos)[0], pos + 4
    elif b == 0x87:
        return struct.unpack_from("<q", buf, pos)[0], pos + 8
    elif b == 0x88:
        return round(struct.unpack_from("<f", buf, pos)[0], 5), pos + 4
    elif b == 0x89:
        return round(struct.unpack_from("<d", buf, pos)[0], 5), pos + 8
    elif b == 0xB7:
        return False, pos
    elif b == 0xB8:
        return True, pos
    elif b in (0xB9, 0xBA):
        cnt, pos = decode_nop(buf, pos)
        items = []
        for _ in range(cnt):
            v, pos = decode_nop(buf, pos)
            items.append(v)
        return items, pos
    elif b == 0xBB:
        cnt, pos = decode_nop(buf, pos)
        d = {}
        for _ in range(cnt):
            k, pos = decode_nop(buf, pos)
            v, pos = decode_nop(buf, pos)
            d[str(k)] = v
        return d, pos
    elif b == 0xBC:
        ln, pos = decode_nop(buf, pos)
        sub = buf[pos : pos + ln]
        try:
            inner, sub_pos = decode_nop(sub, 0)
            if sub_pos == len(sub):
                return {"_props": inner}, pos + ln
        except Exception:
            pass
        return {"_hex": sub.hex()}, pos + ln
    elif b == 0xBD:
        ln, pos = decode_nop(buf, pos)
        s = buf[pos : pos + ln].decode("utf-8", errors="replace")
        return s, pos + ln
    elif b == 0xBE:
        return None, pos
    elif b == 0xBF:
        return decode_nop(buf, pos)
    elif b >= 0xE0:
        return b - 256, pos
    else:
        raise ValueError(f"Unknown nop tag 0x{b:02x} at pos {pos - 1}")


def dump_flash_and_decode(mxid: str, backup_dir: pathlib.Path) -> None:
    extracted_dir = backup_dir / "extracted"
    backup_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)

    dev_info = dai.DeviceInfo(mxid)

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=36),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        connect_task = progress.add_task(
            f"Connecting to {mxid} via RAM-booted v0.0.29 Bootloader...", total=None
        )
        with dai.DeviceBootloader(dev_info, allowFlashingBootloader=True) as bl:
            mem = bl.getMemoryInfo(dai.DeviceBootloader.Memory.FLASH)
            flash_size = mem.size
            progress.remove_task(connect_task)

            read_task = progress.add_task(
                f"Reading SPI Flash [{mem.info}]", total=flash_size
            )

            def on_progress(p: float) -> None:
                progress.update(read_task, completed=int(p * flash_size))

            ok, err, full_flash = bl.readCustom(
                dai.DeviceBootloader.Memory.FLASH, 0, flash_size, on_progress
            )
            progress.update(read_task, completed=flash_size)
            if not ok or len(full_flash) != flash_size:
                raise RuntimeError(
                    f"Failed reading flash: ok={ok}, err={err!r}, got={len(full_flash)}"
                )

    full_bytes = bytes(full_flash)
    bl_1mb_bytes = full_bytes[:APPLICATION_OFFSET]
    app_dap_bytes = full_bytes[APPLICATION_OFFSET:]

    bl_path = backup_dir / "bootloader_0.0.15_1MB.bin"
    bl_path.write_bytes(bl_1mb_bytes)

    full_path = backup_dir / "opal_c1_full_16MB.bin"
    full_path.write_bytes(full_bytes)

    img_table = Table(
        title="Saved SPI Flash Backups",
        box=box.ROUNDED,
        header_style="bold green",
        title_style="bold white",
    )
    img_table.add_column("File", style="bold")
    img_table.add_column("Region", style="cyan")
    img_table.add_column("Size", justify="right")
    img_table.add_column("SHA-256", style="dim")

    img_table.add_row(
        str(bl_path.relative_to(REPO_ROOT)),
        "0x000000–0x0FFFFF (Bootloader + Config)",
        f"{len(bl_1mb_bytes):,} B",
        sha256_hex(bl_1mb_bytes),
    )
    img_table.add_row(
        str(full_path.relative_to(REPO_ROOT)),
        "0x000000–0xFFFFFF (Full 16 MiB Flash)",
        f"{len(full_bytes):,} B",
        sha256_hex(full_bytes),
    )
    console.print()
    console.print(img_table)

    magic = app_dap_bytes[:2]
    if magic != b"BR":
        raise RuntimeError(f"Unexpected SBR magic at 0x100000: {magic!r}")

    sbr_table = Table(
        title="Opal C1 Application SBR Partition Table @ 0x100000",
        box=box.ROUNDED,
        header_style="bold cyan",
        title_style="bold white",
    )
    sbr_table.add_column("#", justify="right")
    sbr_table.add_column("Section", style="bold")
    sbr_table.add_column("Flash Offset", style="yellow")
    sbr_table.add_column("Size", justify="right")
    sbr_table.add_column("CRC32", style="magenta")
    sbr_table.add_column("Compression")
    sbr_table.add_column("Extracted Output", style="green")

    pos = 2
    sections: dict[str, bytes] = {}
    for idx in range(SBR_MAX_NUM_SECTIONS):
        raw_sec = app_dap_bytes[pos : pos + 30]
        pos += 30
        raw_name, size, offset, checksum, _sec_type, flags = struct.unpack("<16sIIIBB", raw_sec)
        name = raw_name.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        if not name and size == 0 and offset == 0:
            continue

        comp = (flags >> 2) & 0x07
        comp_names = {0: "NONE", 1: "ZLIB", 2: "GZIP", 3: "XZ"}
        sec_data = app_dap_bytes[offset : offset + size]

        clean_name = name.lstrip("_") or f"section_{idx}"
        sec_path = extracted_dir / f"{idx:02d}_{clean_name}.raw"
        sec_path.write_bytes(sec_data)
        sections[clean_name] = sec_data

        out_desc = sec_path.name
        if comp == 1:
            decomp_data = zlib.decompress(sec_data)
            decomp_path = extracted_dir / f"{idx:02d}_{clean_name}.decompressed.bin"
            decomp_path.write_bytes(decomp_data)
            out_desc += f" -> {decomp_path.name} ({len(decomp_data) / (1024*1024):.2f} MiB)"

        sbr_table.add_row(
            str(idx),
            name,
            f"0x{APPLICATION_OFFSET + offset:06x}",
            f"{size:,} B",
            f"0x{checksum:08x}",
            comp_names.get(comp, str(comp)),
            out_desc,
        )

    console.print()
    console.print(sbr_table)

    decoded_assets = None
    for clean_name in ("pipeline", "assets"):
        if clean_name in sections:
            sec_data = sections[clean_name]
            unpacked, _ = decode_nop(sec_data, 0)
            json_path = extracted_dir / f"{clean_name}_decoded.json"
            json_str = json.dumps(unpacked, indent=2, default=str)
            json_path.write_text(json_str)
            if clean_name == "assets":
                decoded_assets = unpacked

    if decoded_assets and "asset_storage" in sections and isinstance(decoded_assets, list):
        storage = sections["asset_storage"]
        asset_map = decoded_assets[0] if decoded_assets else {}
        if isinstance(asset_map, dict):
            asset_table = Table(
                title="Extracted Embedded Assets from asset_storage",
                box=box.ROUNDED,
                header_style="bold magenta",
                title_style="bold white",
            )
            asset_table.add_column("Asset Key", style="bold")
            asset_table.add_column("Offset", style="yellow")
            asset_table.add_column("Size", justify="right")
            asset_table.add_column("Saved File", style="green")
            asset_table.add_column("SHA-256 (first 16)", style="dim")

            for idx, (asset_key, meta) in enumerate(asset_map.items()):
                offset, size, _align = meta
                blob = storage[offset : offset + size]
                safe_key = asset_key.strip("/").replace("/", "_")
                ext = ".py" if "script" in safe_key else (".blob" if "blob" in safe_key else ".bin")
                out_file = extracted_dir / f"asset_{idx}_{safe_key}{ext}"
                out_file.write_bytes(blob)
                asset_table.add_row(
                    asset_key,
                    f"0x{offset:06x}",
                    f"{size:,} B",
                    out_file.name,
                    sha256_hex(blob)[:16],
                )

            console.print()
            console.print(asset_table)


def main() -> None:
    console.print(
        Panel.fit(
            "[bold white]Opal C1 SPI Flash Backup & SBR Decoder[/bold white]\n"
            "[dim]Dumps 16 MiB SPI NOR flash and unpacks firmware, pipeline, and assets[/dim]",
            border_style="bright_green",
        )
    )
    topo = check_and_warn_topology()
    mxid = resolve_mxid(os.environ.get("usage_mxid"), topo)
    out_arg = pathlib.Path(os.environ["usage_output_dir"])
    backup_dir = out_arg if out_arg.is_absolute() else (REPO_ROOT / out_arg)
    dump_flash_and_decode(mxid, backup_dir)


if __name__ == "__main__":
    main()
