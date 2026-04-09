import copy
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from tkinterdnd2 import DND_FILES, TkinterDnD

from src.config import load_config, save_config
from src.file_router import DischargeGroup, parse_primary_xml, route_file, sort_files

# Column widths
_COL_FILE = 45
_COL_DEST = 16

_DISCHARGE_TYPES = ("ADCP", "FT", "AA")


class App(tk.Frame):
    def __init__(self, master: TkinterDnD.Tk):
        super().__init__(master)
        self.master = master
        master.title("Files Sorter")
        master.resizable(True, True)
        master.minsize(620, 480)
        self.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self._config = load_config()
        self._file_paths: list[str] = []          # absolute paths of dropped files
        self._discharge_groups: list[DischargeGroup] = []

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
        tk.Button(btn_frame, text="Clear", width=10, command=self._clear).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(
            btn_frame,
            text="Discharge Groups",
            width=16,
            command=self._manage_discharge,
        ).pack(side=tk.LEFT)
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
        self._discharge_groups.clear()
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

    def _manage_discharge(self) -> None:
        discharge_files = [p for p in self._file_paths if route_file(Path(p).name) == "Discharge"]
        if not discharge_files:
            messagebox.showinfo("No discharge files", "No discharge files have been added yet.")
            return
        dlg = DischargeGroupDialog(self.master, discharge_files, self._discharge_groups)
        self.master.wait_window(dlg)
        if dlg.result is not None:
            self._discharge_groups = dlg.result
            self._refresh_list()

    def _sort(self) -> None:
        if not self._file_paths:
            messagebox.showwarning("No files", "Please add files before sorting.")
            return
        output_base = self._config.get("output_dir", "")
        if not output_base:
            messagebox.showerror("No output folder", "Please set an output folder first.")
            return
        try:
            result = sort_files(self._file_paths, output_base, self._discharge_groups or None)
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
        site_number = None
        date_str = None

        # Build discharge display map: abs_path -> display destination
        discharge_display: dict[str, str] = {}
        for g in self._discharge_groups:
            for fp in g.files:
                discharge_display[fp] = f"Discharge/{g.folder_name}"

        for path in self._file_paths:
            name = Path(path).name
            folder = route_file(name)
            if folder == "Discharge" and path in discharge_display:
                folder = discharge_display[path]
            parsed = parse_primary_xml(name)
            if parsed is not None:
                primary_name = name
                site_number, date_str = parsed
            display = f"{name[:_COL_FILE]:<{_COL_FILE}}  → {folder}"
            self._listbox.insert(tk.END, display)

        if primary_name:
            self._primary_var.set(f"Primary XML: {primary_name}")
            self._outdir_var.set(f"Output dir:  {site_number}/SV_{date_str}")
        else:
            self._primary_var.set("Primary XML: (none detected)")
            self._outdir_var.set("Output dir:  —")


# ---------------------------------------------------------------------------
# Discharge group management dialog
# ---------------------------------------------------------------------------

class DischargeGroupDialog(tk.Toplevel):
    """Modal dialog for organizing discharge files into measurement subfolders."""

    def __init__(self, parent, discharge_files: list[str], existing_groups: list[DischargeGroup]):
        super().__init__(parent)
        self.title("Manage Discharge Measurements")
        self.grab_set()
        self.transient(parent)
        self.resizable(True, True)
        self.minsize(700, 440)

        self._groups: list[DischargeGroup] = copy.deepcopy(existing_groups)
        self._next_number: int = max((g.number for g in self._groups), default=0) + 1

        assigned = {fp for g in self._groups for fp in g.files}
        self._unassigned: list[str] = [fp for fp in discharge_files if fp not in assigned]

        self.result: list[DischargeGroup] | None = None
        self._item_to_path: dict[str, str] = {}  # treeview iid -> absolute path

        self._build_ui()
        self._refresh()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _build_ui(self) -> None:
        main = tk.Frame(self, padx=8, pady=8)
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=3)
        main.columnconfigure(2, weight=3)
        main.rowconfigure(0, weight=1)

        # Left: groups treeview
        left = tk.LabelFrame(main, text="Measurement Groups")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        vsb = tk.Scrollbar(left, orient=tk.VERTICAL)
        self._tree = ttk.Treeview(left, yscrollcommand=vsb.set, selectmode="browse")
        self._tree.heading("#0", text="Group / File", anchor="w")
        vsb.config(command=self._tree.yview)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # Middle: action buttons
        mid = tk.Frame(main)
        mid.grid(row=0, column=1, padx=6)
        tk.Frame(mid).pack(expand=True)  # spacer
        tk.Button(mid, text="New Group...", width=16, command=self._new_group).pack(pady=3)
        tk.Button(mid, text="Delete Group", width=16, command=self._delete_group).pack(pady=3)
        ttk.Separator(mid, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
        tk.Button(mid, text="← Assign Files", width=16, command=self._assign_to_group).pack(pady=3)
        tk.Button(mid, text="Unassign →", width=16, command=self._unassign_file).pack(pady=3)
        tk.Frame(mid).pack(expand=True)  # spacer

        # Right: unassigned files listbox
        right = tk.LabelFrame(main, text="Unassigned Discharge Files")
        right.grid(row=0, column=2, sticky="nsew", padx=(4, 0))

        vsb2 = tk.Scrollbar(right, orient=tk.VERTICAL)
        self._unassigned_lb = tk.Listbox(
            right, yscrollcommand=vsb2.set, selectmode=tk.EXTENDED, font=("Courier", 9)
        )
        vsb2.config(command=self._unassigned_lb.yview)
        vsb2.pack(side=tk.RIGHT, fill=tk.Y)
        self._unassigned_lb.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # Bottom: OK / Cancel
        bottom = tk.Frame(self, pady=6)
        bottom.pack(fill=tk.X, padx=8)
        tk.Button(bottom, text="Cancel", width=10, command=self.destroy).pack(side=tk.RIGHT, padx=(4, 0))
        tk.Button(
            bottom, text="OK", width=10, bg="#2e7d32", fg="white", command=self._ok
        ).pack(side=tk.RIGHT)

    def _refresh(self) -> None:
        self._item_to_path.clear()
        self._tree.delete(*self._tree.get_children())
        for g in self._groups:
            gid = self._tree.insert("", tk.END, text=g.folder_name, open=True, tags=("group",))
            for fp in g.files:
                fid = self._tree.insert(gid, tk.END, text=Path(fp).name, tags=("file",))
                self._item_to_path[fid] = fp

        self._unassigned_lb.delete(0, tk.END)
        for fp in self._unassigned:
            self._unassigned_lb.insert(tk.END, Path(fp).name)

    def _selected_group(self) -> DischargeGroup | None:
        """Return the DischargeGroup for the currently selected tree item (group or file)."""
        sel = self._tree.selection()
        if not sel:
            return None
        item = sel[0]
        parent = self._tree.parent(item)
        group_iid = parent if parent else item
        folder_name = self._tree.item(group_iid, "text")
        return next((g for g in self._groups if g.folder_name == folder_name), None)

    def _new_group(self) -> None:
        dlg = _GroupPropertiesDialog(self)
        self.wait_window(dlg)
        if dlg.result is None:
            return
        time_val, type_val = dlg.result

        selected_indices = sorted(self._unassigned_lb.curselection())
        selected_files = [self._unassigned[i] for i in selected_indices]

        g = DischargeGroup(number=self._next_number, time=time_val, type=type_val, files=selected_files)
        self._next_number += 1
        self._groups.append(g)

        for i in reversed(selected_indices):
            self._unassigned.pop(i)

        self._refresh()

    def _delete_group(self) -> None:
        group = self._selected_group()
        if group is None:
            messagebox.showwarning("No group selected", "Select a group to delete.", parent=self)
            return
        self._unassigned.extend(group.files)
        self._groups.remove(group)
        self._refresh()

    def _assign_to_group(self) -> None:
        group = self._selected_group()
        if group is None:
            messagebox.showwarning("No group selected", "Select a group in the left panel.", parent=self)
            return
        selected_indices = sorted(self._unassigned_lb.curselection())
        if not selected_indices:
            messagebox.showwarning(
                "No files selected", "Select files from the right panel to assign.", parent=self
            )
            return
        selected_files = [self._unassigned[i] for i in selected_indices]
        group.files.extend(selected_files)
        for i in reversed(selected_indices):
            self._unassigned.pop(i)
        self._refresh()

    def _unassign_file(self) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        item = sel[0]
        if item not in self._item_to_path:
            messagebox.showwarning(
                "Select a file", "Select a file inside a group to unassign it.", parent=self
            )
            return
        fp = self._item_to_path[item]
        group = self._selected_group()
        if group and fp in group.files:
            group.files.remove(fp)
            self._unassigned.append(fp)
        self._refresh()

    def _ok(self) -> None:
        self.result = self._groups
        self.destroy()


class _GroupPropertiesDialog(tk.Toplevel):
    """Small dialog to collect time and measurement type for a new discharge group."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("New Discharge Measurement")
        self.grab_set()
        self.transient(parent)
        self.resizable(False, False)
        self.result: tuple[str, str] | None = None

        f = tk.Frame(self, padx=14, pady=14)
        f.pack()

        tk.Label(f, text="Time (hhmmss):").grid(row=0, column=0, sticky="e", padx=4, pady=5)
        self._time_var = tk.StringVar()
        time_entry = tk.Entry(f, textvariable=self._time_var, width=10)
        time_entry.grid(row=0, column=1, padx=4, pady=5)
        time_entry.focus_set()

        tk.Label(f, text="Type:").grid(row=1, column=0, sticky="e", padx=4, pady=5)
        self._type_var = tk.StringVar(value="ADCP")
        ttk.Combobox(
            f, textvariable=self._type_var, values=_DISCHARGE_TYPES, state="readonly", width=8
        ).grid(row=1, column=1, padx=4, pady=5)

        btn = tk.Frame(f)
        btn.grid(row=2, columnspan=2, pady=(10, 0))
        tk.Button(btn, text="Cancel", width=8, command=self.destroy).pack(side=tk.RIGHT, padx=3)
        tk.Button(btn, text="OK", width=8, command=self._on_ok).pack(side=tk.RIGHT, padx=3)

        self.bind("<Return>", lambda _: self._on_ok())

    def _on_ok(self) -> None:
        t = self._time_var.get().strip()
        if not re.fullmatch(r"\d{6}", t):
            messagebox.showerror("Invalid time", "Enter exactly 6 digits for hhmmss (e.g. 103045).", parent=self)
            return
        self.result = (t, self._type_var.get())
        self.destroy()
