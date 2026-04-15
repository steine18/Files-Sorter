import os
import sys

from tkinterdnd2 import TkinterDnD

from src.gui import App


def _resource(relative: str) -> str:
    """Return absolute path to a bundled resource.

    Works both when running from source and when frozen by PyInstaller
    (sys._MEIPASS points to the temp folder where assets are unpacked).
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def main() -> None:
    root = TkinterDnD.Tk()
    try:
        root.iconbitmap(_resource(os.path.join("assets", "app.ico")))
    except Exception:
        pass  # icon is cosmetic — never crash over it
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
