import copy
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from tkinterdnd2 import DND_FILES, TkinterDnD

from src.archive_sync import VisitSyncStatus, populate_remote, scan_local_visits, sync_visit
from src.config import load_config, save_config
from src.file_router import (
    DischargeGroup, load_routing, parse_discharge_groups, parse_primary_xml,
    reload_routing_cache, route_file, save_routing, sort_files,
)

# Column widths for the sort file list
_COL_FILE = 45

_DISCHARGE_TYPES = ("ADCP", "FT", "AA")
_ALL_CATEGORIES = ("VisitXML", "Discharge", "Photos", "RawData", "AncillaryFiles")

_SYNC_STATUS_COLORS = {
    "synced":  "#e8f5e9",
    "partial": "#fff9c4",
    "missing": "#ffebee",
}


class App(tk.Frame):
    def __init__(self, master: TkinterDnD.Tk):
        super().__init__(master)
        self.master = master
        master.title("File Sorter")
        master.resizable(True, True)
        master.minsize(680, 540)
        self.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self._config = load_config()

        # Sort tab state
        self._file_paths: list[str] = []
        self._discharge_groups: list[DischargeGroup] = []
        self._route_overrides: dict[str, str] = {}          # abs path -> manual category

        # Archive sync tab state
        self._visits: list[VisitSyncStatus] = []

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # --- Output directory row (shared, always visible) ---
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

        # --- Notebook ---
        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill=tk.BOTH, expand=True)

        sort_tab = tk.Frame(self._notebook)
        self._notebook.add(sort_tab, text="  Sort Files  ")

        sync_tab = tk.Frame(self._notebook)
        self._notebook.add(sync_tab, text="  Archive Sync  ")

        self._build_sort_tab(sort_tab)
        self._build_sync_tab(sync_tab)

    def _build_sort_tab(self, parent: tk.Frame) -> None:
        # --- Drop zone ---
        drop_frame = tk.LabelFrame(parent, text="Drop files here", padx=8, pady=8)
        drop_frame.pack(fill=tk.X, pady=(8, 6), padx=8)

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
        status_frame = tk.Frame(parent)
        status_frame.pack(fill=tk.X, padx=8, pady=(0, 4))

        self._primary_var = tk.StringVar(value="Primary XML: (none detected)")
        self._outdir_var = tk.StringVar(value="Output dir:  —")
        tk.Label(status_frame, textvariable=self._primary_var, anchor="w").pack(fill=tk.X)
        tk.Label(status_frame, textvariable=self._outdir_var, anchor="w").pack(fill=tk.X)

        # --- File list ---
        list_frame = tk.LabelFrame(parent, text="Files to sort")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))

        header = tk.Frame(list_frame)
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text=f"{'File':<{_COL_FILE}}  {'→ Folder'}",
            font=("Courier", 9, "bold"),
        ).pack(anchor="w", padx=4)
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
        self._listbox.bind("<Button-3>", self._on_right_click)

        # --- Buttons ---
        btn_frame = tk.Frame(parent)
        btn_frame.pack(fill=tk.X, padx=8, pady=(0, 8))

        tk.Button(btn_frame, text="Add Files", width=12, command=self._add_files).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        tk.Button(btn_frame, text="Clear", width=10, command=self._clear).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        tk.Button(
            btn_frame, text="Discharge Groups", width=16, command=self._manage_discharge
        ).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(
            btn_frame, text="Routing...", width=10, command=self._edit_routing
        ).pack(side=tk.LEFT)
        tk.Button(
            btn_frame,
            text="Sort Files",
            width=14,
            command=self._sort,
        ).pack(side=tk.RIGHT)

    def _build_sync_tab(self, parent: tk.Frame) -> None:
        # --- Archive destination root row ---
        dst_frame = tk.Frame(parent)
        dst_frame.pack(fill=tk.X, padx=8, pady=(8, 6))

        tk.Label(dst_frame, text="Archive destination root:").pack(side=tk.LEFT)
        self._dst_var = tk.StringVar(value=self._config.get("archive_dst_root", ""))
        tk.Label(
            dst_frame,
            textvariable=self._dst_var,
            relief=tk.SUNKEN,
            anchor="w",
            width=48,
        ).pack(side=tk.LEFT, padx=6, fill=tk.X, expand=True)
        tk.Button(dst_frame, text="Browse...", command=self._sync_browse_dst).pack(side=tk.LEFT)

        # --- Treeview ---
        tree_frame = tk.LabelFrame(parent, text="Local site visits")
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))

        cols = ("site", "date", "wy", "status", "local_n", "remote_n")
        vsb = tk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        self._sync_tree = ttk.Treeview(
            tree_frame,
            columns=cols,
            show="headings",
            selectmode="extended",
            yscrollcommand=vsb.set,
        )
        vsb.config(command=self._sync_tree.yview)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._sync_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        col_defs = [
            ("site",     "Site ID",      110),
            ("date",     "Visit Date",    95),
            ("wy",       "Water Year",    80),
            ("status",   "Status",        80),
            ("local_n",  "Local Files",   85),
            ("remote_n", "Remote Files",  90),
        ]
        for col, heading, width in col_defs:
            self._sync_tree.heading(col, text=heading, anchor="w")
            self._sync_tree.column(col, width=width, anchor="w", stretch=(col == "site"))

        for tag, color in _SYNC_STATUS_COLORS.items():
            self._sync_tree.tag_configure(tag, background=color)

        # --- Buttons ---
        btn_frame = tk.Frame(parent)
        btn_frame.pack(fill=tk.X, padx=8, pady=(0, 8))

        tk.Button(btn_frame, text="Scan", width=10, command=self._sync_scan).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        tk.Button(btn_frame, text="Sync Selected", width=14, command=self._sync_selected).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        tk.Button(
            btn_frame,
            text="Sync All",
            width=10,
            command=self._sync_all,
        ).pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    # Sort tab — event handlers
    # ------------------------------------------------------------------

    def _on_drop(self, event) -> None:
        paths = self._parse_drop_data(event.data)
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
                end = raw.find(" ", i)
                if end == -1:
                    paths.append(raw[i:])
                    break
                paths.append(raw[i:end])
                i = end
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
        self._auto_parse_discharge_groups()
        self._refresh_list()

    def _auto_parse_discharge_groups(self) -> None:
        """If no discharge groups exist yet, parse the primary XML and pre-populate them."""
        if self._discharge_groups:
            return
        primary = next(
            (p for p in self._file_paths if parse_primary_xml(Path(p).name) is not None),
            None,
        )
        if primary:
            self._discharge_groups = parse_discharge_groups(primary)

    def _clear(self) -> None:
        self._file_paths.clear()
        self._discharge_groups.clear()
        self._route_overrides.clear()
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
        discharge_files = [p for p in self._file_paths if self._effective_route(p) == "Discharge"]
        if not discharge_files:
            messagebox.showinfo("No discharge files", "No discharge files have been added yet.")
            return
        dlg = DischargeGroupDialog(self.master, discharge_files, self._discharge_groups)
        self.master.wait_window(dlg)
        if dlg.result is not None:
            self._discharge_groups = dlg.result
            self._refresh_list()

    def _on_right_click(self, event: tk.Event) -> None:
        idx = self._listbox.nearest(event.y)
        if idx < 0 or idx >= len(self._file_paths):
            return

        # If the clicked row isn't in the current selection, select only it
        if idx not in self._listbox.curselection():
            self._listbox.selection_clear(0, tk.END)
            self._listbox.selection_set(idx)

        selected_indices = list(self._listbox.curselection())
        selected_paths = [self._file_paths[i] for i in selected_indices]

        count = len(selected_paths)
        label = "Set category" if count == 1 else f"Set category  ({count} files)"

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label=label, state=tk.DISABLED)
        menu.add_separator()
        for cat in _ALL_CATEGORIES:
            menu.add_command(
                label=cat,
                command=lambda c=cat, pp=selected_paths: self._set_category(pp, c),
            )
        menu.add_separator()
        menu.add_command(
            label="Reset to auto",
            command=lambda pp=selected_paths: self._set_category(pp, None),
        )
        menu.tk_popup(event.x_root, event.y_root)

    def _set_category(self, paths: list[str], category: str | None) -> None:
        for p in paths:
            if category is None:
                self._route_overrides.pop(p, None)
                # If auto-route is no longer Discharge, drop from any group
                if route_file(Path(p).name) != "Discharge":
                    self._remove_from_discharge_groups(p)
            else:
                self._route_overrides[p] = category
                if category != "Discharge":
                    self._remove_from_discharge_groups(p)
        self._refresh_list()

    def _remove_from_discharge_groups(self, path: str) -> None:
        for g in self._discharge_groups:
            if path in g.files:
                g.files.remove(path)

    def _edit_routing(self) -> None:
        dlg = RoutingConfigDialog(self.master)
        self.master.wait_window(dlg)
        if dlg.saved:
            reload_routing_cache()
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
            result = sort_files(
                self._file_paths,
                output_base,
                self._discharge_groups or None,
                self._route_overrides or None,
            )
        except ValueError as exc:
            messagebox.showerror("Cannot sort", str(exc))
            return

        errors = result.get("errors", [])
        routed = result.get("routed", {})
        out_dir = result.get("output_dir", "")

        summary_lines = [f"Sorted to: {out_dir}\n"]
        for folder, names in sorted(routed.items()):
            summary_lines.append(
                f"  {folder}/  ({len(names)} file{'s' if len(names) != 1 else ''})"
            )

        if errors:
            summary_lines.append(f"\nErrors ({len(errors)}):")
            for name, reason in errors:
                summary_lines.append(f"  {name}: {reason}")
            messagebox.showwarning("Sort complete (with errors)", "\n".join(summary_lines))
        else:
            messagebox.showinfo("Sort complete", "\n".join(summary_lines))

    def _effective_route(self, path: str) -> str:
        """Return the active category for a file, respecting manual overrides."""
        if path in self._route_overrides:
            return self._route_overrides[path]
        return route_file(Path(path).name)


    def _refresh_list(self) -> None:
        self._listbox.delete(0, tk.END)
        primary_name = None
        site_number = None
        date_str = None

        # A file may be in multiple groups; track all assignments per path
        discharge_display: dict[str, list[str]] = {}
        for g in self._discharge_groups:
            for fp in g.files:
                discharge_display.setdefault(fp, []).append(g.folder_name)

        for idx, path in enumerate(self._file_paths):
            name = Path(path).name
            folder = self._effective_route(path)
            if folder == "Discharge" and path in discharge_display:
                groups = discharge_display[path]
                if len(groups) == 1:
                    folder = f"Discharge/{groups[0]}"
                else:
                    folder = f"Discharge/ ({len(groups)} groups)"
            parsed = parse_primary_xml(name)
            if parsed is not None:
                primary_name = name
                site_number, date_str = parsed

            manual = path in self._route_overrides
            suffix = " [*]" if manual else ""
            display = f"{name[:_COL_FILE]:<{_COL_FILE}}  → {folder}{suffix}"
            self._listbox.insert(tk.END, display)
            if manual:
                self._listbox.itemconfigure(idx, fg="#0055aa")

        if primary_name:
            self._primary_var.set(f"Primary XML: {primary_name}")
            self._outdir_var.set(f"Output dir:  {site_number}/SV_{date_str}")
        else:
            self._primary_var.set("Primary XML: (none detected)")
            self._outdir_var.set("Output dir:  —")

    # ------------------------------------------------------------------
    # Archive sync tab — event handlers
    # ------------------------------------------------------------------

    def _sync_browse_dst(self) -> None:
        folder = filedialog.askdirectory(
            title="Select archive destination root (DST folder)",
            initialdir=self._dst_var.get() or "",
        )
        if folder:
            self._dst_var.set(folder)
            self._config["archive_dst_root"] = folder
            save_config(self._config)

    def _sync_scan(self) -> None:
        output_dir = self._config.get("output_dir", "")
        dst_root = self._dst_var.get()
        if not output_dir:
            messagebox.showerror(
                "No output folder", "Set the output folder using Change Folder above.", parent=self.master
            )
            return
        if not dst_root:
            messagebox.showerror(
                "No destination", "Set the archive destination root first.", parent=self.master
            )
            return

        self.master.config(cursor="watch")
        self.master.update()
        try:
            self._visits = scan_local_visits(output_dir)
            populate_remote(self._visits, dst_root)
        finally:
            self.master.config(cursor="")

        self._sync_refresh_tree()
        if not self._visits:
            messagebox.showinfo(
                "No visits found",
                f"No SV_YYYYMMDD directories found under:\n{output_dir}",
                parent=self.master,
            )

    def _sync_refresh_tree(self) -> None:
        self._sync_tree.delete(*self._sync_tree.get_children())
        for i, v in enumerate(self._visits):
            date_display = f"{v.date_str[:4]}-{v.date_str[4:6]}-{v.date_str[6:]}"
            self._sync_tree.insert(
                "",
                tk.END,
                iid=str(i),
                values=(
                    v.site_id,
                    date_display,
                    v.water_year_str,
                    v.status.capitalize(),
                    len(v.local_files),
                    len(v.remote_files),
                ),
                tags=(v.status,),
            )

    def _sync_selected_visits(self) -> list[VisitSyncStatus]:
        return [self._visits[int(iid)] for iid in self._sync_tree.selection()]

    def _sync_selected(self) -> None:
        selected = self._sync_selected_visits()
        if not selected:
            messagebox.showwarning(
                "Nothing selected", "Select one or more visits to sync.", parent=self.master
            )
            return
        self._run_sync(selected)

    def _sync_all(self) -> None:
        if not self._visits:
            messagebox.showwarning("Not scanned", "Click Scan first.", parent=self.master)
            return
        to_sync = [v for v in self._visits if v.status != "synced"]
        if not to_sync:
            messagebox.showinfo(
                "Already synced", "All local visits are present on the remote.", parent=self.master
            )
            return
        self._run_sync(to_sync)

    def _run_sync(self, visits: list[VisitSyncStatus]) -> None:
        self.master.config(cursor="watch")
        self.master.update()
        total_copied = 0
        all_errors: list[str] = []
        try:
            for v in visits:
                copied, errors = sync_visit(v)
                total_copied += copied
                all_errors.extend(errors)
                if not errors:
                    v.remote_files = v.remote_files | v.local_files
        finally:
            self.master.config(cursor="")

        self._sync_refresh_tree()

        summary = f"Copied {total_copied} file(s) across {len(visits)} visit(s)."
        if all_errors:
            summary += f"\n\nErrors ({len(all_errors)}):\n" + "\n".join(all_errors[:20])
            messagebox.showwarning("Sync complete (with errors)", summary, parent=self.master)
        else:
            messagebox.showinfo("Sync complete", summary, parent=self.master)


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
        self._all_files: list[str] = list(discharge_files)  # always shows all files

        self.result: list[DischargeGroup] | None = None
        self._item_to_path: dict[str, str] = {}

        self._build_ui()
        self._refresh()

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

        left = tk.LabelFrame(main, text="Measurement Groups")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        vsb = tk.Scrollbar(left, orient=tk.VERTICAL)
        self._tree = ttk.Treeview(left, yscrollcommand=vsb.set, selectmode="browse")
        self._tree.heading("#0", text="Group / File", anchor="w")
        vsb.config(command=self._tree.yview)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        mid = tk.Frame(main)
        mid.grid(row=0, column=1, padx=6)
        tk.Frame(mid).pack(expand=True)
        tk.Button(mid, text="New Group...", width=16, command=self._new_group).pack(pady=3)
        tk.Button(mid, text="Delete Group", width=16, command=self._delete_group).pack(pady=3)
        ttk.Separator(mid, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
        tk.Button(mid, text="← Add to Group", width=16, command=self._assign_to_group).pack(pady=3)
        tk.Button(mid, text="Remove from Group", width=16, command=self._unassign_file).pack(pady=3)
        tk.Frame(mid).pack(expand=True)

        right = tk.LabelFrame(main, text="Discharge Files")
        right.grid(row=0, column=2, sticky="nsew", padx=(4, 0))

        vsb2 = tk.Scrollbar(right, orient=tk.VERTICAL)
        self._all_files_lb = tk.Listbox(
            right, yscrollcommand=vsb2.set, selectmode=tk.EXTENDED, font=("Courier", 9),
            exportselection=False,
        )
        vsb2.config(command=self._all_files_lb.yview)
        vsb2.pack(side=tk.RIGHT, fill=tk.Y)
        self._all_files_lb.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        bottom = tk.Frame(self, pady=6)
        bottom.pack(fill=tk.X, padx=8)
        tk.Button(bottom, text="Cancel", width=10, command=self.destroy).pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        tk.Button(
            bottom, text="OK", width=10, command=self._ok
        ).pack(side=tk.RIGHT)

    def _refresh(self) -> None:
        self._item_to_path.clear()
        self._tree.delete(*self._tree.get_children())
        for g in self._groups:
            gid = self._tree.insert("", tk.END, text=g.folder_name, open=True, tags=("group",))
            for fp in g.files:
                fid = self._tree.insert(gid, tk.END, text=Path(fp).name, tags=("file",))
                self._item_to_path[fid] = fp

        # Count how many groups each file is assigned to
        group_count: dict[str, int] = {}
        for g in self._groups:
            for fp in g.files:
                group_count[fp] = group_count.get(fp, 0) + 1

        self._all_files_lb.delete(0, tk.END)
        for fp in self._all_files:
            count = group_count.get(fp, 0)
            suffix = f"  [{count} group{'s' if count != 1 else ''}]" if count else ""
            self._all_files_lb.insert(tk.END, Path(fp).name + suffix)

    def _selected_group(self) -> DischargeGroup | None:
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

        selected_indices = self._all_files_lb.curselection()
        selected_files = [self._all_files[i] for i in selected_indices]

        g = DischargeGroup(
            number=self._next_number, time=time_val, type=type_val, files=selected_files
        )
        self._next_number += 1
        self._groups.append(g)
        self._refresh()

    def _delete_group(self) -> None:
        group = self._selected_group()
        if group is None:
            messagebox.showwarning("No group selected", "Select a group to delete.", parent=self)
            return
        self._groups.remove(group)
        self._refresh()

    def _assign_to_group(self) -> None:
        group = self._selected_group()
        if group is None:
            messagebox.showwarning(
                "No group selected", "Select a group in the left panel.", parent=self
            )
            return
        selected_indices = self._all_files_lb.curselection()
        if not selected_indices:
            messagebox.showwarning(
                "No files selected", "Select files from the right panel to add.", parent=self
            )
            return
        for i in selected_indices:
            fp = self._all_files[i]
            if fp not in group.files:
                group.files.append(fp)
        self._refresh()

    def _unassign_file(self) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        item = sel[0]
        if item not in self._item_to_path:
            messagebox.showwarning(
                "Select a file", "Select a file inside a group to remove it.", parent=self
            )
            return
        fp = self._item_to_path[item]
        group = self._selected_group()
        if group and fp in group.files:
            group.files.remove(fp)
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
            messagebox.showerror(
                "Invalid time", "Enter exactly 6 digits for hhmmss (e.g. 103045).", parent=self
            )
            return
        self.result = (t, self._type_var.get())
        self.destroy()


# ---------------------------------------------------------------------------
# Routing config dialog
# ---------------------------------------------------------------------------

# Internal IDs for the four editable routing sections shown in the treeview
_ROUTING_SECTIONS = [
    ("Discharge",      "Discharge",                   "extensions"),
    ("Discharge_qrev", "Discharge (requires _QRev suffix)", "qrev_extensions"),
    ("Photos",         "Photos",                      "extensions"),
    ("RawData",        "RawData",                     "extensions"),
]


class RoutingConfigDialog(tk.Toplevel):
    """Dialog for viewing and editing routing.json without touching any .py files."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Routing Configuration")
        self.grab_set()
        self.transient(parent)
        self.resizable(True, True)
        self.minsize(420, 380)
        self.saved = False

        self._routing = load_routing()
        self._build_ui()
        self._populate_tree()

        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        main = tk.Frame(self, padx=8, pady=8)
        main.pack(fill=tk.BOTH, expand=True)

        # Treeview
        tree_frame = tk.LabelFrame(main, text="Folder  →  Extensions")
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        vsb = tk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        self._tree = ttk.Treeview(
            tree_frame, yscrollcommand=vsb.set, selectmode="browse", show="tree"
        )
        vsb.config(command=self._tree.yview)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # Add extension row
        add_frame = tk.Frame(main)
        add_frame.pack(fill=tk.X, pady=(0, 6))
        tk.Label(add_frame, text="Extension:").pack(side=tk.LEFT)
        self._ext_var = tk.StringVar()
        tk.Entry(add_frame, textvariable=self._ext_var, width=10).pack(
            side=tk.LEFT, padx=6
        )
        tk.Button(add_frame, text="Add to selected folder", command=self._add_ext).pack(
            side=tk.LEFT
        )

        # Bottom buttons
        btn_frame = tk.Frame(main)
        btn_frame.pack(fill=tk.X)
        tk.Button(btn_frame, text="Remove Selected", width=16, command=self._remove_ext).pack(
            side=tk.LEFT
        )
        tk.Button(btn_frame, text="Cancel", width=10, command=self.destroy).pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        tk.Button(btn_frame, text="Save", width=10, command=self._save).pack(side=tk.RIGHT)

    # ------------------------------------------------------------------
    # Tree management
    # ------------------------------------------------------------------

    def _populate_tree(self) -> None:
        self._tree.delete(*self._tree.get_children())
        for iid, label, key in _ROUTING_SECTIONS:
            folder_key = "Discharge" if "Discharge" in iid else iid
            exts = self._routing.get(folder_key, {}).get(key, [])
            parent = self._tree.insert(
                "", tk.END, iid=iid, text=f"  {label}", open=True, tags=("folder",)
            )
            for ext in sorted(exts):
                self._tree.insert(parent, tk.END, text=f"    {ext}", tags=("ext",))
        self._tree.tag_configure("folder", font=("TkDefaultFont", 9, "bold"))

    def _section_for_item(self, iid: str) -> tuple[str, str, str] | None:
        """Return the _ROUTING_SECTIONS entry for a tree item (folder or child ext)."""
        parent = self._tree.parent(iid)
        section_iid = parent if parent else iid
        return next((s for s in _ROUTING_SECTIONS if s[0] == section_iid), None)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _add_ext(self) -> None:
        sel = self._tree.selection()
        if not sel:
            messagebox.showwarning(
                "No folder selected", "Select a folder (or extension within one) first.", parent=self
            )
            return
        section = self._section_for_item(sel[0])
        if section is None:
            return
        _, _, key = section
        folder_key = "Discharge" if "Discharge" in section[0] else section[0]

        raw = self._ext_var.get().strip().lower()
        if not raw:
            return
        ext = raw if raw.startswith(".") else f".{raw}"

        exts: list = self._routing.setdefault(folder_key, {}).setdefault(key, [])
        if ext not in exts:
            exts.append(ext)
            self._populate_tree()
        self._ext_var.set("")

    def _remove_ext(self) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        if "ext" not in self._tree.item(iid, "tags"):
            messagebox.showwarning(
                "Select an extension", "Select an individual extension to remove.", parent=self
            )
            return
        section = self._section_for_item(iid)
        if section is None:
            return
        _, _, key = section
        folder_key = "Discharge" if "Discharge" in section[0] else section[0]

        ext_text = self._tree.item(iid, "text").strip()
        exts: list = self._routing.get(folder_key, {}).get(key, [])
        if ext_text in exts:
            exts.remove(ext_text)
            self._populate_tree()

    def _save(self) -> None:
        save_routing(self._routing)
        self.saved = True
        self.destroy()
