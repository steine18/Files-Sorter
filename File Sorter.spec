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
        # Default routing; user edits are saved to %APPDATA%/FileSorter/routing.json
        ("routing.json", "."),
        # Window icon, loaded at runtime by main.py (the exe icon is set below)
        ("assets/icon.ico", "assets"),
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
    icon="assets/icon.ico",  # Replace assets/icon.ico to change both exe and window icon
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
