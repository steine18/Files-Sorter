import re
import shutil
from pathlib import Path

# Regex for the primary visit XML: SV_{site}_{YYYYMMDD}_{HHMMSS}.xml
_PRIMARY_XML_RE = re.compile(r"^SV_.+_(\d{8})_\d{6}\.xml$", re.IGNORECASE)

# Discharge: files whose stem ends with _QRev (any of these extensions) or .rsqmb
_QREV_EXTENSIONS = {".xml", ".mat", ".pdf"}
_DISCHARGE_EXTENSIONS = {".rsqmb"}

# Photos
_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif"}

# Rawdata
_RAWDATA_EXTENSIONS = {".csv", ".txt", ".dat"}


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

    # 1. Primary visit XML
    if parse_primary_xml(name) is not None:
        return "VisitXml"

    # 2. Discharge: *_QRev.{xml,mat,pdf}  OR  *.rsqmb
    if ext in _DISCHARGE_EXTENSIONS:
        return "Discharge"
    if ext in _QREV_EXTENSIONS and stem.endswith("_QRev"):
        return "Discharge"

    # 3. Photos
    if ext in _PHOTO_EXTENSIONS:
        return "Photos"

    # 4. Rawdata
    if ext in _RAWDATA_EXTENSIONS:
        return "Rawdata"

    # 5. Catch-all
    return "AncillaryFiles"


def sort_files(file_paths: list[str], output_base_dir: str) -> dict:
    """
    Validate, create the output directory tree, and copy files.

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

    _, date_str = parse_primary_xml(primary.name)
    output_dir = Path(output_base_dir) / f"SV_{date_str}"

    routed: dict[str, list[str]] = {}
    errors: list[tuple[str, str]] = []

    for p in paths:
        folder = route_file(p.name)
        dest_dir = output_dir / folder
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / p.name
        try:
            shutil.copy2(p, dest)
            routed.setdefault(folder, []).append(p.name)
        except OSError as exc:
            errors.append((p.name, str(exc)))

    return {
        "output_dir": str(output_dir),
        "routed": routed,
        "errors": errors,
    }
