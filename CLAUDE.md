# CLAUDE.md — Files-Sorter

## Project Overview

**Files-Sorter** is a Python desktop GUI application that organizes field survey files into a
standardized directory structure. The user drops a batch of related files onto the interface; the
app detects the primary XML visit file, derives the output folder name from it, and copies every
file into the correct subfolder.

---

## Architecture

```
Files-Sorter/
├── main.py              # Entry point — creates TkinterDnD root, launches App
├── requirements.txt     # Python dependencies (tkinterdnd2)
├── config.json          # Persisted user config (output_dir); auto-created on first run
└── src/
    ├── __init__.py
    ├── config.py        # load_config() / save_config() around config.json
    ├── file_router.py   # File classification and copy logic
    └── gui.py           # tkinter + tkinterdnd2 main window
```

---

## File Routing Rules

Files are classified in the following **priority order** (first match wins):

| Destination       | Rule |
|-------------------|------|
| `VisitXML/`       | Filename matches `SV_<site>_<YYYYMMDD>_<HHMMSS>.xml` |
| `Discharge/`      | Filename ends with `_QRev.xml`, `_QRev.mat`, `_QRev.pdf`, OR extension is `.rsqmb` |
| `Photos/`         | Extension is `.jpg`, `.jpeg`, `.png`, or `.tif` |
| `RawData/`        | Extension is `.csv`, `.txt`, or `.dat` |
| `AncillaryFiles/` | Everything else (catch-all) |

The primary XML rule is checked **before** the Discharge rule so that the visit XML is never
misrouted despite also being a `.xml` file.

---

## Output Directory Structure

Given a primary file `SV_12345_20240315_103045.xml`, the app creates:

```
<output_dir>/
└── SV_20240315/
    ├── VisitXML/
    │   └── SV_12345_20240315_103045.xml
    ├── Discharge/
    ├── Photos/
    ├── RawData/
    └── AncillaryFiles/
```

Only subfolders that will receive at least one file are created.

---

## Key Modules

### `src/file_router.py`

- `parse_primary_xml(filename) -> tuple[str, str] | None`  
  Regex-matches `SV_*_YYYYMMDD_HHMMSS.xml`. Returns `(site_number, date_str)` or `None`.

- `route_file(filename) -> str`  
  Returns the destination subfolder name for a single file (applies rules above).

- `sort_files(file_paths, output_base_dir) -> dict`  
  Validates that exactly one primary XML is present, creates the output tree, copies files, and
  returns a summary dict `{folder: [filenames]}`.

### `src/config.py`

- `load_config() -> dict` — reads `config.json`; defaults `output_dir` to the user's home dir.
- `save_config(config: dict)` — writes updated config back to `config.json`.

### `src/gui.py`

Main `App` class (inherits from `tkinter.Frame`):

- Drop zone accepts `DND_FILES` events via tkinterdnd2.
- File list (scrollable `Listbox`) shows each file and its routed destination.
- Status bar shows the detected primary XML and derived output folder name.
- "Change Output Folder" button opens a directory picker and persists the choice.
- "Sort Files" button calls `sort_files()` and shows a result dialog.
- "Clear" button resets the file list.

---

## Development Setup

```bash
# Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the app
python main.py
```

**Python version:** 3.10+

**Dependencies:**
- `tkinterdnd2` — adds drag-and-drop support to tkinter

---

## Conventions

- All source code lives in `src/`; `main.py` is only an entry point.
- Routing rules live exclusively in `src/file_router.py`. Add new rules there.
- Config persistence uses `config.json` at the project root (not the user's home dir).
- Files are **copied**, not moved, to avoid data loss.
- Subfolders are only created when at least one file is routed to them.
- Error messages are surfaced to the user via `messagebox` dialogs, never silently swallowed.

---

## Testing Checklist

1. Drop a valid batch (includes primary XML) — verify correct routing in the file list.
2. Click "Sort Files" — verify output directory and subfolders are created correctly.
3. Drop a batch with **no** primary XML — verify an error dialog is shown.
4. Drop files with ambiguous types (e.g., a `.pdf` that is not a QRev file) — verify they land in `AncillaryFiles/`.
5. Change output folder — verify the new path persists after restarting the app.
