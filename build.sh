#!/bin/bash
# Build script for File Sorter (macOS)
# Run from the project root with your venv active.
#
# First-time setup:
#   pip install -r requirements.txt
#   pip install -r requirements-dev.txt
#
# Then build:
#   chmod +x build.sh && ./build.sh
#
# Output: dist/File Sorter/File Sorter

set -e

echo "Building File Sorter..."
pyinstaller "File Sorter.spec" --clean --noconfirm

echo ""
echo "Build complete. Output: dist/File Sorter/File Sorter"
