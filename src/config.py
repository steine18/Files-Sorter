import json
import os
from pathlib import Path

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
