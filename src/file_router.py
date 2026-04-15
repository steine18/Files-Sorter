import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

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

# When frozen by PyInstaller, routing.json lives next to the executable so
# users can edit it. In development, use the project root.
if getattr(sys, "frozen", False):
    ROUTING_PATH = Path(sys.executable).parent / "routing.json"
else:
    ROUTING_PATH = Path(__file__).parent.parent / "routing.json"

_ROUTING_DEFAULTS: dict = {
    "Discharge": {
        "extensions": [".rsqmb"],
        "qrev_extensions": [".xml", ".mat", ".pdf"],
    },
    "Photos": {"extensions": [".jpg", ".jpeg", ".png", ".tif"]},
    "RawData": {"extensions": [".csv", ".txt", ".dat"]},
}

_routing_cache: dict | None = None


def load_routing() -> dict:
    """Load routing.json, falling back to built-in defaults on any error."""
    if ROUTING_PATH.exists():
        try:
            with ROUTING_PATH.open() as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return json.loads(json.dumps(_ROUTING_DEFAULTS))  # deep copy of defaults


def save_routing(routing: dict) -> None:
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
    if ext in qrev_exts and stem.endswith("_QRev"):
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
) -> dict:
    """
    Validate, create the output directory tree, and copy files.

    discharge_groups: optional list of DischargeGroup instances; files assigned to a
    group are placed in Discharge/{group.folder_name}/ instead of Discharge/ directly.

    Returns:
        {
            "output_dir": str,           # full path to the created SV_{date} directory
            "routed": {folder: [names]}, # files successfully copied
            "errors": [(name, reason)],  # files that could not be processed
        }

    Raises ValueError if no primary XML is found in file_paths.
    """
    paths = [Path(p) for p in file_paths]

    # Find the primary XML
    primary = None
    for p in paths:
        if parse_primary_xml(p.name) is not None:
            primary = p
            break

    if primary is None:
        raise ValueError(
            "No primary visit XML found (expected filename: SV_{site}_{YYYYMMDD}_{HHMMSS}.xml)."
        )

    site_number, date_str = parse_primary_xml(primary.name)
    output_dir = Path(output_base_dir) / site_number / f"SV_{date_str}"

    # Build discharge routing: absolute path string -> list of subfolders within Discharge/
    # A file may be assigned to more than one group and will be copied to each.
    discharge_map: dict[str, list[str]] = {}
    if discharge_groups:
        for g in discharge_groups:
            for fp in g.files:
                discharge_map.setdefault(str(fp), []).append(g.folder_name)

    routed: dict[str, list[str]] = {}
    errors: list[tuple[str, str]] = []

    for p in paths:
        folder = route_file(p.name)
        if folder == "Discharge" and str(p) in discharge_map:
            for subfolder in discharge_map[str(p)]:
                dest_dir = output_dir / "Discharge" / subfolder
                dest_dir.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(p, dest_dir / p.name)
                    routed.setdefault(f"Discharge/{subfolder}", []).append(p.name)
                except OSError as exc:
                    errors.append((p.name, str(exc)))
        else:
            dest_dir = output_dir / folder
            dest_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(p, dest_dir / p.name)
                routed.setdefault(folder, []).append(p.name)
            except OSError as exc:
                errors.append((p.name, str(exc)))

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
        try:
            # Format: "2026-04-09T09:56:30-07:00" → "095630"
            time_str = dt_el.text.split("T")[1][:8].replace(":", "")
        except IndexError:
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
            vel_code = (vel_el.text if vel_el is not None else "").strip()
            mtype = _VELOCITY_TYPE_MAP.get(vel_code, "FT")

        groups.append(DischargeGroup(number=number, time=time_str, type=mtype))
        number += 1

    return groups
