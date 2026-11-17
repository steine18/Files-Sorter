import json
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.config import BUNDLE_DIR, DATA_DIR

_AQ_NS = "http://water.usgs.gov/XML/AQ"

# MeasurementMethodCode → folder type (QZEROF intentionally omitted = no folder)
_METHOD_TYPE_MAP = {"QADCP": "ADCP"}
# VelocityMethodCode → folder type (used when method is QMIDSECTION etc.)
_VELOCITY_TYPE_MAP = {
    "WVADVM": "FT",   # FlowTracker / ADV
    "WVAA":   "AA",   # Price AA current meter
}

# Regex for the primary visit XML: SV_{site}_{YYYYMMDD}_{HHMMSS}.xml
_PRIMARY_XML_RE = re.compile(r"^SV_.+_(\d{8})_\d{6}\.xml$", re.IGNORECASE)

# User-editable routing (saved by the Routing dialog) and the copy shipped with the app.
ROUTING_PATH = DATA_DIR / "routing.json"
_BUNDLED_ROUTING_PATH = BUNDLE_DIR / "routing.json"

_ROUTING_DEFAULTS: dict = {
    "Discharge": {
        "extensions": [".rsqmb", ".ft"],
        "qrev_extensions": [".xml", ".mat", ".pdf"],
    },
    "Photos": {"extensions": [".jpg", ".jpeg", ".png", ".tif"]},
    "RawData": {"extensions": [".csv", ".txt", ".dat"]},
}

_routing_cache: dict | None = None


def _is_valid_routing(data) -> bool:
    """True if *data* has the shape route_file() expects: {folder: {key: [str, ...]}}."""
    if not isinstance(data, dict):
        return False
    for section in data.values():
        if not isinstance(section, dict):
            return False
        for exts in section.values():
            if not isinstance(exts, list) or not all(isinstance(e, str) for e in exts):
                return False
    return True


def load_routing() -> dict:
    """Load routing.json (user copy first, then the bundled copy), falling back to
    built-in defaults if neither exists or is malformed."""
    for path in (ROUTING_PATH, _BUNDLED_ROUTING_PATH):
        if not path.exists():
            continue
        try:
            with path.open() as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if _is_valid_routing(data):
            return data
    return json.loads(json.dumps(_ROUTING_DEFAULTS))  # deep copy of defaults


def save_routing(routing: dict) -> None:
    """Write routing.json. Raises OSError if the file cannot be written."""
    ROUTING_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ROUTING_PATH.open("w") as f:
        json.dump(routing, f, indent=2)


def reload_routing_cache() -> None:
    global _routing_cache
    _routing_cache = None


def _get_routing() -> dict:
    global _routing_cache
    if _routing_cache is None:
        _routing_cache = load_routing()
    return _routing_cache


@dataclass
class DischargeGroup:
    """A discharge measurement with its associated files."""
    number: int
    time: str         # hhmmss format
    type: str         # ADCP, FT, or AA
    files: list[str] = field(default_factory=list)  # absolute paths

    @property
    def folder_name(self) -> str:
        return f"Discharge{self.number}.T{self.time}.{self.type}"


def parse_primary_xml(filename: str) -> tuple[str, str] | None:
    """
    If *filename* matches the primary visit XML pattern, return (site_number, date_str).
    Otherwise return None.
    """
    m = _PRIMARY_XML_RE.match(filename)
    if m:
        # Extract site number: everything between first and last two underscore-delimited tokens
        # Pattern: SV_{site}_{date8}_{time6}.xml
        stem = Path(filename).stem  # e.g. SV_12345_20240315_103045
        parts = stem.split("_")
        # parts[0]="SV", parts[-1]=time, parts[-2]=date, parts[1:-2]=site tokens
        date_str = parts[-2]
        site_number = "_".join(parts[1:-2])
        return site_number, date_str
    return None


def find_primary_xmls(file_paths) -> list[str]:
    """Return every path in *file_paths* whose name matches the primary XML pattern,
    in input order. The first one is the one used for sorting."""
    return [p for p in file_paths if parse_primary_xml(Path(p).name) is not None]


def route_file(filename: str) -> str:
    """Return the destination subfolder name for a single file."""
    name = Path(filename).name
    ext = Path(filename).suffix.lower()
    stem = Path(filename).stem

    # 1. Primary visit XML (hardcoded — pattern-based, not extension-based)
    if parse_primary_xml(name) is not None:
        return "VisitXML"

    routing = _get_routing()

    # 2. Discharge
    discharge = routing.get("Discharge", {})
    discharge_exts = {e.lower() for e in discharge.get("extensions", [])}
    qrev_exts = {e.lower() for e in discharge.get("qrev_extensions", [])}
    if ext in discharge_exts:
        return "Discharge"
    if ext in qrev_exts and stem.lower().endswith("_qrev"):
        return "Discharge"

    # 3. Photos, 4. RawData (order matches routing.json key order)
    for folder in ("Photos", "RawData"):
        folder_exts = {e.lower() for e in routing.get(folder, {}).get("extensions", [])}
        if ext in folder_exts:
            return folder

    # 5. Catch-all
    return "AncillaryFiles"


def sort_files(
    file_paths: list[str],
    output_base_dir: str,
    discharge_groups: list[DischargeGroup] | None = None,
    overrides: dict[str, str] | None = None,
) -> dict:
    """
    Validate, create the output directory tree, and copy files.

    discharge_groups: optional list of DischargeGroup instances; files assigned to a
    group are placed in Discharge/{group.folder_name}/ instead of Discharge/ directly.
    overrides: optional dict mapping absolute path string -> folder name, applied before
    automatic routing rules.

    Returns:
        {
            "output_dir": str,           # full path to the created SV_{date} directory
            "routed": {folder: [names]}, # files successfully copied
            "errors": [(name, reason)],  # files that could not be processed
        }

    Raises ValueError if no primary XML is found in file_paths, or if primary XMLs
    for more than one site/date are present.
    """
    paths = [Path(p) for p in file_paths]

    # Find the primary XML (the first one wins; all must agree on site and date)
    primaries = [Path(p) for p in find_primary_xmls(file_paths)]
    if not primaries:
        raise ValueError(
            "No primary visit XML found (expected filename: SV_{site}_{YYYYMMDD}_{HHMMSS}.xml)."
        )
    primary = primaries[0]
    site_number, date_str = parse_primary_xml(primary.name)
    conflicting = [
        p.name for p in primaries[1:] if parse_primary_xml(p.name) != (site_number, date_str)
    ]
    if conflicting:
        raise ValueError(
            "Files from more than one site visit were added.\n"
            f"Using: {primary.name}\n"
            f"Conflicting: {', '.join(conflicting)}\n"
            "Sort one visit at a time."
        )

    output_dir = Path(output_base_dir) / site_number / f"SV_{date_str}"

    # Build discharge routing using Path objects as keys so separators are
    # normalised consistently on all platforms (avoids forward/back-slash mismatch).
    discharge_map: dict[Path, list[str]] = {}
    if discharge_groups:
        for g in discharge_groups:
            for fp in g.files:
                discharge_map.setdefault(Path(fp), []).append(g.folder_name)

    # Normalise overrides keys the same way
    overrides_map: dict[Path, str] = {}
    if overrides:
        for k, v in overrides.items():
            overrides_map[Path(k)] = v

    routed: dict[str, list[str]] = {}
    errors: list[tuple[str, str]] = []
    # Destination file (case-folded; Windows paths are case-insensitive) -> source that
    # claimed it in this run. Prevents a same-named file silently overwriting another.
    claimed: dict[str, Path] = {}

    def copy_to(src: Path, folder_label: str) -> None:
        dest = output_dir / folder_label / src.name
        key = str(dest).casefold()
        if key in claimed and claimed[key] != src:
            errors.append((
                src.name,
                f"same filename as {claimed[key]} in {folder_label}/ - not copied "
                "(rename one of them and sort again)",
            ))
            return
        claimed[key] = src
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            routed.setdefault(folder_label, []).append(src.name)
        except OSError as exc:
            errors.append((src.name, str(exc)))

    for p in paths:
        # Manual override takes priority over automatic routing
        if p in overrides_map:
            folder = overrides_map[p]
        else:
            folder = route_file(p.name)
        if folder == "Discharge" and p in discharge_map:
            for subfolder in discharge_map[p]:
                copy_to(p, f"Discharge/{subfolder}")
        else:
            copy_to(p, folder)

    return {
        "output_dir": str(output_dir),
        "routed": routed,
        "errors": errors,
    }


def parse_discharge_groups(xml_path: str) -> list[DischargeGroup]:
    """Parse a primary visit XML and return DischargeGroup objects with time and type
    pre-filled from the XML. QZEROF measurements are skipped (no files, no folder).
    Files lists are left empty — the user assigns those in the dialog.

    Returns an empty list if the file cannot be parsed.
    """
    try:
        tree = ET.parse(xml_path)
    except (ET.ParseError, OSError):
        return []

    root = tree.getroot()
    groups: list[DischargeGroup] = []
    number = 1

    for dm in root.findall(f".//{{{_AQ_NS}}}DischargeMeasurement"):
        # --- Extract time from DischargeDateTime ---
        dt_el = dm.find(f"{{{_AQ_NS}}}DischargeDateTime")
        if dt_el is None or not dt_el.text:
            continue
        dt_text = dt_el.text.strip()
        if "T" not in dt_text:
            continue  # date only — no time to name the folder with
        try:
            # Format: "2026-04-09T09:56:30-07:00" → "095630" (missing seconds → 00).
            # "Z" is only accepted by fromisoformat on Python 3.11+, so normalise it.
            if dt_text.endswith(("Z", "z")):
                dt_text = dt_text[:-1] + "+00:00"
            time_str = datetime.fromisoformat(dt_text).strftime("%H%M%S")
        except ValueError:
            continue

        # --- Determine type from method codes in first Channel ---
        channel = dm.find(f"{{{_AQ_NS}}}Channel")
        if channel is None:
            continue

        method_el = channel.find(f"{{{_AQ_NS}}}MeasurementMethodCode")
        if method_el is None:
            continue
        method_code = (method_el.text or "").strip()

        if method_code == "QZEROF":
            continue  # zero flow — no folder

        if method_code in _METHOD_TYPE_MAP:
            mtype = _METHOD_TYPE_MAP[method_code]
        else:
            # Fall back to velocity method code (distinguishes FT from AA)
            vel_el = channel.find(f"{{{_AQ_NS}}}VelocityMethodCode")
            vel_code = ((vel_el.text if vel_el is not None else None) or "").strip()
            mtype = _VELOCITY_TYPE_MAP.get(vel_code, "FT")

        groups.append(DischargeGroup(number=number, time=time_str, type=mtype))
        number += 1

    return groups
