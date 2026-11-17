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
:: Output: %LOCALAPPDATA%\FileSorterBuild\dist\File Sorter\File Sorter.exe

:: Build output goes outside the project folder: when the project is in OneDrive,
:: sync locks freshly written files and PyInstaller fails with "Access is denied"
:: while replacing the previous build.
set "OUTROOT=%LOCALAPPDATA%\FileSorterBuild"

echo Building File Sorter...
pyinstaller "File Sorter.spec" --clean --noconfirm --workpath "%OUTROOT%\build" --distpath "%OUTROOT%\dist"

if %errorlevel% neq 0 (
    echo Build failed.
    exit /b %errorlevel%
)

echo.
echo Build complete. Output: %OUTROOT%\dist\File Sorter\File Sorter.exe
