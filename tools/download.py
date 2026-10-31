#!/usr/bin/env -S uv run python -P
# SPDX-License-Identifier: MIT
#MISE description="Fetch and verify the latest Luxonis DepthAI firmware packages or extract the Opal C1 firmware from Opal Composer"
#USAGE flag "--source <source>" default="luxonis" help="Source to download" {
#USAGE     long_help "Firmware source to download and verify:\n  - luxonis: Latest upstream Luxonis DepthAI USB bootloader (v0.0.29) and universal OpenVINO vision firmware\n  - opal: Stock Opal C1 bootloader (v0.0.15), C1 firmware, and tuning blobs extracted from the official Opal Composer macOS DMG"
#USAGE     choices "luxonis" "opal"
#USAGE }
#USAGE flag "--output-dir <dir>" default="firmware" help="Directory to store downloaded artifacts and manifest"
#USAGE flag "--ref <ref>" default="v2.33.0" help="Git ref in luxonis/depthai-core to query when --source=luxonis"

import hashlib
import io
import json
import lzma
import os
import pathlib
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import xml.etree.ElementTree as ET

os.environ.setdefault("DEPTHAI_LEVEL", "error")

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
ARTIFACTORY_BASE = "https://artifacts.luxonis.com/artifactory"
OPAL_APPCAST_URL = "https://updates.opal.camera/release/appcast.xml"
OPAL_RELEASE_BASE = "https://updates.opal.camera/release"

console = Console()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "opalc1-firmware-fetcher/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def stream_download(url: str, dest: pathlib.Path, label: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "opalc1-firmware-fetcher/1.0"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        total = int(resp.headers.get("Content-Length", 0)) or None
        buf = bytearray()
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=36),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"Downloading {label}", total=total)
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                buf.extend(chunk)
                progress.update(task, completed=len(buf))

    data = bytes(buf)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return data


def download_and_verify(url: str, sha256_url: str, dest: pathlib.Path) -> str:
    expected_sha256 = fetch_text(sha256_url).strip().split()[0].lower()

    if dest.exists():
        existing_sha256 = sha256_hex(dest.read_bytes())
        if existing_sha256 == expected_sha256:
            console.print(
                f"  [green]✔ Cached[/green] [bold]{dest.name}[/bold] [dim](sha256={existing_sha256[:16]}…)[/dim]"
            )
            return existing_sha256

    data = stream_download(url, dest, dest.name)
    actual_sha256 = sha256_hex(data)
    if actual_sha256 != expected_sha256:
        dest.unlink(missing_ok=True)
        raise RuntimeError(
            f"SHA-256 mismatch for {dest.name}: expected {expected_sha256}, got {actual_sha256}"
        )

    console.print(
        f"  [green]✔ Verified[/green] [bold]{dest.name}[/bold] ({len(data):,} B, [dim]sha256={actual_sha256[:16]}…[/dim])"
    )
    return actual_sha256


def parse_cmake_var(text: str, var_name: str) -> str:
    m = re.search(rf'set\(\s*{ re.escape(var_name) }\s+"([^"]*)"\s*\)', text)
    if not m:
        raise ValueError(f"Could not find {var_name} in CMake config")
    return m.group(1)


def fetch_luxonis_bootloader(firmware_dir: pathlib.Path, github_raw_base: str) -> dict:
    cfg_text = fetch_text(f"{github_raw_base}/DepthaiBootloaderConfig.cmake")
    maturity = parse_cmake_var(cfg_text, "DEPTHAI_BOOTLOADER_MATURITY").lower()
    version = parse_cmake_var(cfg_text, "DEPTHAI_BOOTLOADER_VERSION")

    repo = (
        "luxonis-myriad-release-local"
        if maturity == "release"
        else "luxonis-myriad-snapshot-local"
    )
    archive_name = f"depthai-bootloader-fwp-{version}.tar.xz"
    base_url = f"{ARTIFACTORY_BASE}/{repo}/depthai-bootloader/{version}"
    archive_path = firmware_dir / "archives" / archive_name

    digest = download_and_verify(
        f"{base_url}/{archive_name}",
        f"{base_url}/{archive_name}.sha256",
        archive_path,
    )

    extract_dir = firmware_dir / "luxonis" / "bootloader"
    extract_dir.mkdir(parents=True, exist_ok=True)
    extracted_files = []
    with tarfile.open(archive_path, mode="r:xz") as tf:
        for member in tf.getmembers():
            if member.isfile() and member.name == "depthai-bootloader-usb.cmd":
                tf.extract(member, path=extract_dir, filter="data")
                p = extract_dir / member.name
                extracted_files.append(
                    {
                        "name": member.name,
                        "path": str(p.relative_to(firmware_dir)),
                        "size": p.stat().st_size,
                        "sha256": sha256_hex(p.read_bytes()),
                    }
                )

    sdk_usb_bl = bytes(dai.DeviceBootloader.getEmbeddedBootloaderBinary(dai.DeviceBootloader.Type.USB))
    sdk_ver = str(dai.DeviceBootloader.getEmbeddedBootloaderVersion())
    sdk_sha = sha256_hex(sdk_usb_bl)

    return {
        "version": version,
        "maturity": maturity,
        "archive": str(archive_path.relative_to(firmware_dir)),
        "archive_sha256": digest,
        "sdk_embedded_version": sdk_ver,
        "sdk_embedded_usb_sha256": sdk_sha,
        "files": extracted_files,
    }


def fetch_luxonis_device_firmware(firmware_dir: pathlib.Path, github_raw_base: str) -> dict:
    cfg_text = fetch_text(f"{github_raw_base}/DepthaiDeviceSideConfig.cmake")
    maturity = parse_cmake_var(cfg_text, "DEPTHAI_DEVICE_SIDE_MATURITY").lower()
    commit = parse_cmake_var(cfg_text, "DEPTHAI_DEVICE_SIDE_COMMIT")

    repo = (
        "luxonis-myriad-release-local"
        if maturity == "release"
        else "luxonis-myriad-snapshot-local"
    )
    archive_name = f"depthai-device-fwp-{commit}.tar.xz"
    base_url = f"{ARTIFACTORY_BASE}/{repo}/depthai-device-side/{commit}"
    extract_dir = firmware_dir / "luxonis" / "device"
    extract_dir.mkdir(parents=True, exist_ok=True)
    archive_path = extract_dir / archive_name

    digest = download_and_verify(
        f"{base_url}/{archive_name}",
        f"{base_url}/{archive_name}.sha256",
        archive_path,
    )

    extracted_files = []
    with tarfile.open(archive_path, mode="r:xz") as tf:
        tf.extractall(path=extract_dir, filter="data")
        for member in tf.getmembers():
            if member.isfile():
                p = extract_dir / member.name
                extracted_files.append(
                    {
                        "name": member.name,
                        "path": str(p.relative_to(firmware_dir)),
                        "size": p.stat().st_size,
                        "sha256": sha256_hex(p.read_bytes()),
                    }
                )

    return {
        "commit": commit,
        "maturity": maturity,
        "archive": str(archive_path.relative_to(firmware_dir)),
        "archive_sha256": digest,
        "files": extracted_files,
    }


def extract_opal_c1_firmware_from_dmg(dmg_path: pathlib.Path, firmware_dir: pathlib.Path) -> dict:
    """Mount Opal Composer DMG read-only and extract all embedded Opal C1 firmware & tuning blobs."""
    opal_c1_dir = firmware_dir / "opal-c1"
    bl_dir = opal_c1_dir / "bootloader"
    dev_dir = opal_c1_dir / "device"
    res_dir = opal_c1_dir / "resources"
    bl_dir.mkdir(parents=True, exist_ok=True)
    dev_dir.mkdir(parents=True, exist_ok=True)
    res_dir.mkdir(parents=True, exist_ok=True)

    mnt_dir = pathlib.Path(tempfile.mkdtemp(prefix="opal_dmg_"))
    extracted_summary: dict[str, list[dict]] = {
        "bootloader": [],
        "device": [],
        "resources": [],
    }

    with console.status("[bold cyan]Mounting Opal Composer DMG read-only and extracting C1 firmware..."):
        try:
            subprocess.run(
                [
                    "hdiutil",
                    "attach",
                    "-nobrowse",
                    "-readonly",
                    str(dmg_path),
                    "-mountpoint",
                    str(mnt_dir),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            app_contents = mnt_dir / "Opal Composer.app" / "Contents"
            dylib_path = app_contents / "Frameworks" / "libdepthai-core.dylib"
            dylib_bytes = dylib_path.read_bytes()

            xz_magic = b"\xfd7zXZ\x00"
            pos = 0
            seen_members: set[str] = set()

            while True:
                idx = dylib_bytes.find(xz_magic, pos)
                if idx == -1:
                    break
                pos = idx + 6
                try:
                    dec = lzma.LZMADecompressor(lzma.FORMAT_XZ)
                    max_window = 15_000_000
                    chunk = dylib_bytes[idx : idx + max_window]
                    tar_bytes = dec.decompress(chunk)
                    comp_len = len(chunk) - len(dec.unused_data)
                    raw_xz = dylib_bytes[idx : idx + comp_len]

                    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tf:
                        names = [m.name for m in tf.getmembers() if m.isfile()]
                        if not names or names[0] in seen_members:
                            continue
                        seen_members.update(names)

                        if any("bootloader" in n for n in names):
                            usb_member = tf.extractfile("depthai-bootloader-usb.cmd")
                            if usb_member:
                                usb_data = usb_member.read()
                                out_p = bl_dir / "depthai-bootloader-usb.cmd"
                                out_p.write_bytes(usb_data)
                                digest = sha256_hex(usb_data)
                                extracted_summary["bootloader"].append(
                                    {
                                        "name": out_p.name,
                                        "path": str(out_p.relative_to(firmware_dir)),
                                        "size": len(usb_data),
                                        "sha256": digest,
                                    }
                                )
                        elif any("depthai-device" in n for n in names):
                            xz_out = (
                                dev_dir
                                / "depthai-device-fwp-e2929eb3993d759114d7084074a0eec845c12b45.tar.xz"
                            )
                            xz_out.write_bytes(raw_xz)
                            digest = sha256_hex(raw_xz)
                            extracted_summary["device"].append(
                                {
                                    "name": xz_out.name,
                                    "path": str(xz_out.relative_to(firmware_dir)),
                                    "size": len(raw_xz),
                                    "sha256": digest,
                                    "members": names,
                                }
                            )
                except Exception:
                    continue

            xpc_res = (
                app_contents
                / "XPCServices"
                / "OpalCameraDeviceService.xpc"
                / "Contents"
                / "Resources"
            )
            main_res = app_contents / "Resources"

            c1_files = [
                xpc_res / "Opal582_v2.bin",
                xpc_res / "Opal_v0.12.bin",
                xpc_res / "dd0bad95b2.tlv",
                xpc_res / "cf422ae69a.sfo",
                xpc_res / "2684560952.tlv",
                xpc_res / "49559974de.tlv",
                xpc_res / "6127be7a1f.tlv",
                xpc_res / "6f153dffab.evn",
                xpc_res / "bd45062c37.evn",
                xpc_res / "237530fe13.evn",
                xpc_res / "0a8bf313b1.evn",
                main_res / "142359x2f4.evn",
            ]
            c1_files.extend(sorted(main_res.glob("*_pipeline.json")))

            for src in c1_files:
                if src.exists():
                    dst = res_dir / src.name
                    shutil.copy2(src, dst)
                    data = dst.read_bytes()
                    digest = sha256_hex(data)
                    extracted_summary["resources"].append(
                        {
                            "name": dst.name,
                            "path": str(dst.relative_to(firmware_dir)),
                            "size": len(data),
                            "sha256": digest,
                        }
                    )
        finally:
            subprocess.run(
                ["hdiutil", "detach", str(mnt_dir)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            shutil.rmtree(mnt_dir, ignore_errors=True)

    table = Table(
        title="Extracted Opal C1 Firmware & Assets (firmware/opal-c1/)",
        box=box.ROUNDED,
        header_style="bold magenta",
        title_style="bold white",
    )
    table.add_column("Category", style="cyan")
    table.add_column("File", style="bold", overflow="fold")
    table.add_column("Size", justify="right", no_wrap=True)
    table.add_column("SHA-256 (first 16)", style="dim", no_wrap=True)

    for cat in ("bootloader", "device", "resources"):
        for item in extracted_summary[cat]:
            table.add_row(
                cat,
                item["path"],
                f"{item['size']:,} B",
                item["sha256"][:16],
            )

    console.print()
    console.print(table)
    return extracted_summary


def fetch_opal_release(firmware_dir: pathlib.Path) -> dict:
    xml_text = fetch_text(OPAL_APPCAST_URL)
    root = ET.fromstring(xml_text)
    ns = {"sparkle": "http://www.andymatuschak.org/xml-namespaces/sparkle"}

    releases = []
    for item in root.findall("./channel/item"):
        title = item.findtext("title", "")
        pub_date = item.findtext("pubDate", "")
        version = item.findtext("sparkle:version", "", ns)
        short_ver = item.findtext("sparkle:shortVersionString", "", ns)
        enclosure = item.find("enclosure")
        if enclosure is not None:
            rel_url = enclosure.attrib.get("url", "")
            full_url = f"{OPAL_RELEASE_BASE}/{rel_url.lstrip('/')}"
            length = int(enclosure.attrib.get("length", "0"))
            ed_sig = enclosure.attrib.get(
                "{http://www.andymatuschak.org/xml-namespaces/sparkle}edSignature", ""
            )
            releases.append(
                {
                    "title": title,
                    "short_version": short_ver,
                    "build": version,
                    "pub_date": pub_date,
                    "filename": rel_url,
                    "url": full_url,
                    "size": length,
                    "ed_signature": ed_sig,
                }
            )

    extracted = {}
    if releases:
        latest = releases[0]
        dmg_dest = firmware_dir / "opal" / latest["filename"]
        dmg_dest.parent.mkdir(parents=True, exist_ok=True)
        if dmg_dest.exists() and dmg_dest.stat().st_size == latest["size"]:
            console.print(
                f"  [green]✔ Cached[/green] [bold]{latest['filename']}[/bold] ({latest['size'] / (1024*1024):.2f} MiB)"
            )
        else:
            stream_download(latest["url"], dmg_dest, latest["filename"])

        extracted = extract_opal_c1_firmware_from_dmg(dmg_dest, firmware_dir)

    return {
        "releases": releases,
        "extracted_opal_c1": extracted,
    }


def main() -> None:
    source = os.environ["usage_source"]
    out_arg = pathlib.Path(os.environ["usage_output_dir"])
    firmware_dir = out_arg if out_arg.is_absolute() else (REPO_ROOT / out_arg)
    ref = os.environ["usage_ref"]

    console.print(
        Panel.fit(
            f"[bold white]Opal C1 Firmware Downloader[/bold white]\n"
            f"[dim]Source: [bold cyan]{source}[/bold cyan] | Output: {firmware_dir.relative_to(REPO_ROOT)}[/dim]",
            border_style="bright_cyan",
        )
    )

    firmware_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = firmware_dir / "manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
        except Exception:
            manifest = {}

    if source == "luxonis":
        github_raw_base = (
            f"https://raw.githubusercontent.com/luxonis/depthai-core/{ref}/cmake/Depthai"
        )
        bl_info = fetch_luxonis_bootloader(firmware_dir, github_raw_base)
        dev_info = fetch_luxonis_device_firmware(firmware_dir, github_raw_base)
        manifest["luxonis_bootloader"] = bl_info
        manifest["luxonis_device_firmware"] = dev_info

        table = Table(
            title=f"Luxonis DepthAI Firmware Packages (ref={ref})",
            box=box.ROUNDED,
            header_style="bold cyan",
            title_style="bold white",
        )
        table.add_column("Package", style="yellow", no_wrap=True)
        table.add_column("Extracted File", style="bold", overflow="fold")
        table.add_column("Size", justify="right", no_wrap=True)
        table.add_column("SHA-256 (first 16)", style="dim", no_wrap=True)

        for f in bl_info["files"]:
            table.add_row(
                f"Bootloader v{bl_info['version']}",
                f["path"],
                f"{f['size']:,} B",
                f["sha256"][:16],
            )
        for f in dev_info["files"]:
            table.add_row(
                f"Device {dev_info['commit'][:10]}",
                f["path"],
                f"{f['size']:,} B",
                f["sha256"][:16],
            )
        console.print()
        console.print(table)
    elif source == "opal":
        manifest["opal_composer"] = fetch_opal_release(firmware_dir)
    else:
        raise ValueError(f"Unsupported --source: {source!r}")

    manifest_path.write_text(json.dumps(manifest, indent=2))
    console.print(f"\n[green]✔[/green] Updated manifest: [bold]{manifest_path}[/bold]")


if __name__ == "__main__":
    main()
