#!/usr/bin/env python3
"""
Packages the Opal C1 Companion and CMIOExtension into a complete macOS Application bundle:
build/OpalC1Ark.app/Contents/Library/SystemExtensions/com.kludgeworks.opalc1.extension.systemextension
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPANION_DIR = REPO_ROOT / "companion"
BUILD_DIR = REPO_ROOT / "build"
APP_DIR = BUILD_DIR / "OpalC1Ark.app"
SYS_EXT_DIR = APP_DIR / "Contents" / "Library" / "SystemExtensions" / "com.kludgeworks.opalc1.extension.systemextension"


def run_cmd(cmd: list[str], cwd: Path | None = None):
    print(f"[*] Running: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=cwd)
    if res.returncode != 0:
        print(f"[-] Command failed with exit code {res.returncode}")
        sys.exit(res.returncode)


def main():
    print("=" * 65)
    print("  OPAL C1 ARK — PACKAGING CMIO CAMERA EXTENSION & APP")
    print("=" * 65)

    # 1. Compile Swift Targets
    print("\n[1/4] Compiling Swift targets...")
    run_cmd(["swift", "build", "-c", "release"], cwd=COMPANION_DIR)

    swift_bin_dir = COMPANION_DIR / ".build" / "release"
    companion_bin = swift_bin_dir / "OpalC1Companion"
    extension_bin = swift_bin_dir / "OpalC1ExtensionService"

    if not companion_bin.exists() or not extension_bin.exists():
        print("[-] Binary artifacts not found in release build.")
        sys.exit(1)

    # 2. Construct Application Bundle Structure
    print("\n[2/4] Constructing App & System Extension bundles...")
    if APP_DIR.exists():
        shutil.rmtree(APP_DIR)

    (APP_DIR / "Contents" / "MacOS").mkdir(parents=True, exist_ok=True)
    (SYS_EXT_DIR / "Contents" / "MacOS").mkdir(parents=True, exist_ok=True)

    # Copy executables
    shutil.copy2(companion_bin, APP_DIR / "Contents" / "MacOS" / "OpalC1Ark")
    shutil.copy2(extension_bin, SYS_EXT_DIR / "Contents" / "MacOS" / "com.kludgeworks.opalc1.extension")

    # 3. Write Info.plist files
    print("\n[3/4] Writing bundle metadata & entitlements...")

    # Extension Info.plist
    ext_plist = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.kludgeworks.opalc1.extension</string>
    <key>CFBundleName</key>
    <string>OpalC1Extension</string>
    <key>CFBundlePackageType</key>
    <string>SYSX</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>CMIOExtension</key>
    <dict>
        <key>CMIOExtensionMachServiceName</key>
        <string>com.kludgeworks.opalc1.extension</string>
    </dict>
</dict>
</plist>
"""
    with open(SYS_EXT_DIR / "Contents" / "Info.plist", "w", encoding="utf-8") as f:
        f.write(ext_plist)

    # Container App Info.plist
    app_plist = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>OpalC1Ark</string>
    <key>CFBundleIdentifier</key>
    <string>com.kludgeworks.opalc1</string>
    <key>CFBundleName</key>
    <string>Opal C1 Ark</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSCameraUsageDescription</key>
    <string>Opal C1 Ark requires camera access to process and stream 4K video.</string>
</dict>
</plist>
"""
    with open(APP_DIR / "Contents" / "Info.plist", "w", encoding="utf-8") as f:
        f.write(app_plist)

    # 4. Code Signing
    print("\n[4/4] Ad-hoc code signing bundles...")
    # Sign inner system extension
    run_cmd(["codesign", "--force", "--deep", "--sign", "-", str(SYS_EXT_DIR)])
    # Sign outer container application
    run_cmd(["codesign", "--force", "--deep", "--sign", "-", str(APP_DIR)])

    print("\n" + "=" * 65)
    print(f"[✔] Successfully assembled bundle: {APP_DIR}")
    print(f"[✔] System Extension embedded: {SYS_EXT_DIR.name}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
