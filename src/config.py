import json
import os
import sys
from pathlib import Path

# When frozen by PyInstaller, store config next to the executable so it
# persists across updates. In development, use the project root.
if getattr(sys, "frozen", False):
    CONFIG_PATH = Path(sys.executable).parent / "config.json"
else:
    CONFIG_PATH = Path(__file__).parent.parent / "config.json"
_DEFAULTS = {"output_dir": str(Path.home())}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open() as f:
                data = json.load(f)
            return {**_DEFAULTS, **data}
        except (json.JSONDecodeError, OSError):
            pass
    return dict(_DEFAULTS)


def save_config(config: dict) -> None:
    with CONFIG_PATH.open("w") as f:
        json.dump(config, f, indent=2)
