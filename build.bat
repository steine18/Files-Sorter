@echo off
:: Build script for File Sorter (Windows)
:: Run this from the project root with your venv active.
::
:: First-time setup:
::   pip install -r requirements.txt
::   pip install -r requirements-dev.txt
::
:: Then build:
::   build.bat
::
:: Output: dist\File Sorter\File Sorter.exe

echo Building File Sorter...
pyinstaller "File Sorter.spec" --clean --noconfirm

if %errorlevel% neq 0 (
    echo Build failed.
    exit /b %errorlevel%
)

echo.
echo Build complete. Output: dist\File Sorter\File Sorter.exe
