import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from tkinterdnd2 import DND_FILES, TkinterDnD

from src.config import load_config, save_config
from src.file_router import parse_primary_xml, route_file, sort_files

# Column widths
_COL_FILE = 45
_COL_DEST = 16


class App(tk.Frame):
    def __init__(self, master: TkinterDnD.Tk):
        super().__init__(master)
        self.master = master
        master.title("Files Sorter")
        master.resizable(True, True)
        master.minsize(620, 480)
        self.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self._config = load_config()
        self._file_paths: list[str] = []  # absolute paths of dropped files

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # --- Output directory row ---
        out_frame = tk.Frame(self)
        out_frame.pack(fill=tk.X, pady=(0, 6))

        tk.Label(out_frame, text="Output folder:").pack(side=tk.LEFT)
        self._out_var = tk.StringVar(value=self._config.get("output_dir", ""))
        tk.Label(
            out_frame,
            textvariable=self._out_var,
            relief=tk.SUNKEN,
            anchor="w",
            width=48,
        ).pack(side=tk.LEFT, padx=6, fill=tk.X, expand=True)
        tk.Button(out_frame, text="Change Folder", command=self._change_output_folder).pack(
            side=tk.LEFT
        )

        # --- Drop zone ---
        drop_frame = tk.LabelFrame(self, text="Drop files here", padx=8, pady=8)
        drop_frame.pack(fill=tk.X, pady=(0, 6))

        self._drop_label = tk.Label(
            drop_frame,
            text="Drag and drop files onto this area\n(or use the Add Files button below)",
            height=4,
            relief=tk.RIDGE,
            bg="#f0f4f8",
            cursor="hand2",
        )
        self._drop_label.pack(fill=tk.X)
        self._drop_label.drop_target_register(DND_FILES)
        self._drop_label.dnd_bind("<<Drop>>", self._on_drop)

        # --- Status bar ---
        status_frame = tk.Frame(self)
        status_frame.pack(fill=tk.X, pady=(0, 4))

        self._primary_var = tk.StringVar(value="Primary XML: (none detected)")
        self._outdir_var = tk.StringVar(value="Output dir:  —")
        tk.Label(status_frame, textvariable=self._primary_var, anchor="w").pack(
            fill=tk.X, side=tk.TOP
        )
        tk.Label(status_frame, textvariable=self._outdir_var, anchor="w").pack(
            fill=tk.X, side=tk.TOP
        )

        # --- File list ---
        list_frame = tk.LabelFrame(self, text="Files to sort")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        header = tk.Frame(list_frame)
        header.pack(fill=tk.X)
        tk.Label(header, text=f"{'File':<{_COL_FILE}}  {'→ Folder'}", font=("Courier", 9, "bold")).pack(
            anchor="w", padx=4
        )
        ttk.Separator(list_frame, orient=tk.HORIZONTAL).pack(fill=tk.X)

        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self._listbox = tk.Listbox(
            list_frame,
            font=("Courier", 9),
            yscrollcommand=scrollbar.set,
            selectmode=tk.EXTENDED,
            activestyle="none",
        )
        scrollbar.config(command=self._listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._listbox.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # --- Buttons ---
        btn_frame = tk.Frame(self)
        btn_frame.pack(fill=tk.X)

        tk.Button(btn_frame, text="Add Files", width=12, command=self._add_files).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        tk.Button(btn_frame, text="Clear", width=10, command=self._clear).pack(side=tk.LEFT)
        tk.Button(
            btn_frame,
            text="Sort Files",
            width=14,
            bg="#2e7d32",
            fg="white",
            font=("TkDefaultFont", 10, "bold"),
            command=self._sort,
        ).pack(side=tk.RIGHT)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_drop(self, event) -> None:
        # tkinterdnd2 returns a space-separated string; brace-quoted paths handle spaces
        raw = event.data
        paths = self._parse_drop_data(raw)
        self._add_paths(paths)

    @staticmethod
    def _parse_drop_data(raw: str) -> list[str]:
        """Parse the tkinterdnd2 drop string (handles brace-quoted paths with spaces)."""
        paths: list[str] = []
        raw = raw.strip()
        i = 0
        while i < len(raw):
            if raw[i] == "{":
                end = raw.index("}", i)
                paths.append(raw[i + 1 : end])
                i = end + 1
            else:
                # Space-separated token
                end = raw.find(" ", i)
                if end == -1:
                    paths.append(raw[i:])
                    break
                paths.append(raw[i:end])
                i = end
            # Skip whitespace between tokens
            while i < len(raw) and raw[i] == " ":
                i += 1
        return [p for p in paths if p]

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(title="Select files to sort")
        if paths:
            self._add_paths(list(paths))

    def _add_paths(self, paths: list[str]) -> None:
        existing = set(self._file_paths)
        for p in paths:
            if p not in existing:
                self._file_paths.append(p)
                existing.add(p)
        self._refresh_list()

    def _clear(self) -> None:
        self._file_paths.clear()
        self._listbox.delete(0, tk.END)
        self._primary_var.set("Primary XML: (none detected)")
        self._outdir_var.set("Output dir:  —")

    def _change_output_folder(self) -> None:
        folder = filedialog.askdirectory(
            title="Select output folder",
            initialdir=self._config.get("output_dir", ""),
        )
        if folder:
            self._config["output_dir"] = folder
            self._out_var.set(folder)
            save_config(self._config)

    def _sort(self) -> None:
        if not self._file_paths:
            messagebox.showwarning("No files", "Please add files before sorting.")
            return
        output_base = self._config.get("output_dir", "")
        if not output_base:
            messagebox.showerror("No output folder", "Please set an output folder first.")
            return
        try:
            result = sort_files(self._file_paths, output_base)
        except ValueError as exc:
            messagebox.showerror("Cannot sort", str(exc))
            return

        errors = result.get("errors", [])
        routed = result.get("routed", {})
        out_dir = result.get("output_dir", "")

        summary_lines = [f"Sorted to: {out_dir}\n"]
        for folder, names in sorted(routed.items()):
            summary_lines.append(f"  {folder}/  ({len(names)} file{'s' if len(names) != 1 else ''})")

        if errors:
            summary_lines.append(f"\nErrors ({len(errors)}):")
            for name, reason in errors:
                summary_lines.append(f"  {name}: {reason}")
            messagebox.showwarning("Sort complete (with errors)", "\n".join(summary_lines))
        else:
            messagebox.showinfo("Sort complete", "\n".join(summary_lines))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _refresh_list(self) -> None:
        self._listbox.delete(0, tk.END)
        primary_name = None
        date_str = None

        for path in self._file_paths:
            name = Path(path).name
            folder = route_file(name)
            parsed = parse_primary_xml(name)
            if parsed is not None:
                primary_name = name
                date_str = parsed[1]
            display = f"{name[:_COL_FILE]:<{_COL_FILE}}  → {folder}"
            self._listbox.insert(tk.END, display)

        if primary_name:
            self._primary_var.set(f"Primary XML: {primary_name}")
            self._outdir_var.set(f"Output dir:  SV_{date_str}")
        else:
            self._primary_var.set("Primary XML: (none detected)")
            self._outdir_var.set("Output dir:  —")
