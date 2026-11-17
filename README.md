# File Sorter

A Python desktop application for organizing USGS field survey files into a standardized directory structure.

## Overview

Field visits generate a variety of files — visit XMLs, ADCP raw data, QRev outputs, photos, and more. File Sorter lets you drag and drop a batch of files, automatically detects the primary visit XML, previews where each file will go, and copies everything into the correct subfolder with one click.

It also includes an **Archive Sync** tool to compare your local archive against a network drive and copy any missing visit folders across.

## Features

- **Drag-and-drop** or file-picker to add files
- **Automatic routing** based on file extension and name pattern
- **Primary XML detection** — derives the output folder name (`SV_YYYYMMDD`) and site ID from the visit XML filename
- **Discharge group management** — discharge files are organized into numbered subfolders (`Discharge1.T{time}.{type}`); groups are auto-populated by parsing measurement time and method (ADCP, FT, AA) directly from the visit XML
- **Multi-group assignment** — a single discharge file can be copied into multiple measurement subfolders
- **Configurable routing** — edit `routing.json` or use the in-app Routing dialog to change which extensions go to which folder, no Python editing required
- **Archive Sync tab** — scans your local archive, computes the correct water-year remote path (`wy{yy}/{site_id}/SiteVisits/`), and syncs missing files to a network drive

## File Routing Rules

Rules are applied in priority order (first match wins):

| Destination | Rule |
|---|---|
| `VisitXML/` | Filename matches `SV_{site}_{YYYYMMDD}_{HHMMSS}.xml` |
| `Discharge/` | Extension in `routing.json` discharge list (e.g. `.rsqmb`, `.ft`), or stem ends with `_QRev` and extension in the QRev list |
| `Photos/` | `.jpg`, `.jpeg`, `.png`, `.tif`, `.mov` (configurable) |
| `RawData/` | `.csv`, `.txt`, `.dat` (configurable) |
| `AncillaryFiles/` | Everything else |

Extensions can be added or removed at any time via the **Routing...** button without restarting the app.

## Output Directory Structure

```
<output_dir>/
└── <site_id>/
    └── SV_<YYYYMMDD>/
        ├── VisitXML/
        ├── Discharge/
        │   ├── Discharge1.T<hhmmss>.ADCP/
        │   └── Discharge2.T<hhmmss>.FT/
        ├── Photos/
        ├── RawData/
        └── AncillaryFiles/
```

Only subfolders that receive at least one file are created. Files are **copied**, not moved.

## Archive Sync

The remote network drive is expected to follow this structure:

```
<archive_root>/
└── wy<yy>/
    └── <site_id>/
        └── SiteVisits/
            └── SV_<YYYYMMDD>/
```

Water year follows the US standard (Oct 1 start). The Archive Sync tab compares every local visit against the remote, color-codes the status (synced / partial / missing), and copies missing or outdated files on demand.

**Sync log.** Once a visit is confirmed fully synced, it is recorded in `sync_log.json` together with a fingerprint of its local files (names, sizes, modification times). Later scans skip the network check for those visits as long as nothing changed locally — adding or editing a file in a visit makes it get re-checked. Synced visits are hidden unless **Show synced** is ticked. Use **Full Rescan** to ignore the log and check every visit on the archive (e.g. if files may have been removed from the archive directly).

## Setup

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

**Requirements:** Python 3.10+, `tkinterdnd2`
