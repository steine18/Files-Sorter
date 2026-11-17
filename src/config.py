import json
import os
import sys
from pathlib import Path

# Where bundled, read-only resources live (PyInstaller unpacks to sys._MEIPASS).
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def _user_data_dir() -> Path:
    """Directory for user-editable settings.

    Running from source: the project root (keeps the existing behaviour).
    Frozen by PyInstaller: %APPDATA%/FileSorter, because the bundle directory is a
    temporary folder that is deleted when the app exits.
    """
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "FileSorter"
    return Path(__file__).resolve().parent.parent


DATA_DIR = _user_data_dir()
CONFIG_PATH = DATA_DIR / "config.json"
_DEFAULTS = {"output_dir": str(Path.home())}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open() as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {**_DEFAULTS, **data}
        except (json.JSONDecodeError, OSError):
            pass
    return dict(_DEFAULTS)


def save_config(config: dict) -> None:
    """Write config.json. Raises OSError if the file cannot be written."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w") as f:
        json.dump(config, f, indent=2)
