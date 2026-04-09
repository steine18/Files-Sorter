from tkinterdnd2 import TkinterDnD
from src.gui import App


def main() -> None:
    root = TkinterDnD.Tk()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
