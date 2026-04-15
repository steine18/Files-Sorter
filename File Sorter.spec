# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for File Sorter
#
# Build (Windows):  pyinstaller "File Sorter.spec"
# Build (macOS):    pyinstaller "File Sorter.spec"
#
# Output lands in dist/File Sorter/
#
# To add a code-signing certificate later (Windows):
#   signtool sign /fd SHA256 /tr http://timestamp.digicert.com
#             /td SHA256 /f cert.pfx /p <password>
#             "dist/File Sorter/File Sorter.exe"

from pathlib import Path
import tkinterdnd2

# Include tkinterdnd2's native drag-and-drop Tcl extension
tkdnd_dir = str(Path(tkinterdnd2.__file__).parent / "tkdnd")

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[
        # tkdnd native library — required for drag-and-drop
        (tkdnd_dir, "tkinterdnd2/tkdnd"),
        # Ship routing.json alongside the executable so users can edit it
        ("routing.json", "."),
    ],
    hiddenimports=["tkinterdnd2"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="File Sorter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX compression increases antivirus false-positive rate
    console=False,      # No console window
    icon="assets/icon.ico",  # Replace with real .ico path when available
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="File Sorter",
)
