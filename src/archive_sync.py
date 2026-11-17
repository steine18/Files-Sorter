import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.config import DATA_DIR

_SV_DIR_RE = re.compile(r"^SV_(\d{8})$")

SYNC_LOG_PATH = DATA_DIR / "sync_log.json"
_SYNC_LOG_VERSION = 1

# FAT/exFAT and some network shares store mtimes at 2-second resolution.
_MTIME_TOLERANCE_S = 2.0


def water_year(date_str: str) -> int:
    """Return the 2-digit US water year for a YYYYMMDD string.

    The US water year starts Oct 1. Examples:
      20241115 -> 25  (Oct 2024 falls in WY2025)
      20240315 -> 24  (Mar 2024 falls in WY2024)
    """
    year = int(date_str[:4])
    month = int(date_str[4:6])
    wy = year + 1 if month >= 10 else year
    return wy % 100


def remote_visit_path(dst_root: str, site_id: str, date_str: str) -> Path:
    """Build the remote path for a site visit.

    Structure: <dst_root>/wy{yy}/{site_id}/SiteVisits/SV_{date_str}
    """
    wy = water_year(date_str)
    return Path(dst_root) / f"wy{wy:02d}" / site_id / "SiteVisits" / f"SV_{date_str}"


def _collect_relative_files(root: Path) -> set[str]:
    """Return all files under root as forward-slash relative path strings."""
    if not root.is_dir():
        return set()
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _is_outdated(local: Path, remote: Path) -> bool:
    """True if the remote copy differs in size or is older than the local file."""
    try:
        ls, rs = local.stat(), remote.stat()
    except OSError:
        return False  # can't tell — don't force a copy
    return ls.st_size != rs.st_size or ls.st_mtime > rs.st_mtime + _MTIME_TOLERANCE_S


def _local_fingerprint(root: Path, rel_files: set[str]) -> str:
    """Hash of every local file's relative path, size and mtime.

    Only touches the local disk. Any added, removed, resized or re-saved file
    changes the fingerprint, which forces the visit to be re-checked on the remote.
    """
    h = hashlib.sha256()
    for rel in sorted(rel_files):
        try:
            st = (root / rel).stat()
            entry = f"{rel}\0{st.st_size}\0{st.st_mtime_ns}\n"
        except OSError:
            entry = f"{rel}\0?\n"
        h.update(entry.encode("utf-8"))
    return h.hexdigest()


class SyncLog:
    """Record of visits confirmed fully synced, so Scan can skip their remote check.

    Keyed by archive root + site + date, so results for one archive root are never
    reused for another. An entry only matches while the visit's local fingerprint is
    unchanged; adding or editing a local file makes the visit get re-checked.
    """

    def __init__(self, path: Path = SYNC_LOG_PATH):
        self.path = path
        self._entries: dict[str, dict] = {}
        self._load()

    @staticmethod
    def _key(dst_root: str, site_id: str, date_str: str) -> str:
        root = os.path.normcase(os.path.abspath(dst_root))
        return f"{root}|{site_id}|{date_str}"

    def _load(self) -> None:
        try:
            with self.path.open(encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return  # missing or unreadable log: everything just gets checked
        entries = data.get("visits") if isinstance(data, dict) else None
        if isinstance(entries, dict):
            self._entries = {
                k: v for k, v in entries.items()
                if isinstance(v, dict) and isinstance(v.get("fingerprint"), str)
            }

    def save(self) -> None:
        """Write the log atomically. Raises OSError on failure."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump({"version": _SYNC_LOG_VERSION, "visits": self._entries}, f, indent=1)
        os.replace(tmp, self.path)

    def is_synced(self, visit: "VisitSyncStatus", dst_root: str) -> bool:
        entry = self._entries.get(self._key(dst_root, visit.site_id, visit.date_str))
        return entry is not None and entry["fingerprint"] == visit.fingerprint

    def update_from(self, visits: list["VisitSyncStatus"], dst_root: str) -> None:
        """Record visits verified as synced against the remote; forget ones that aren't.
        Visits whose status came from the log are left as they are."""
        now = datetime.now().isoformat(timespec="seconds")
        for v in visits:
            if v.from_log or not v.local_files:
                continue
            key = self._key(dst_root, v.site_id, v.date_str)
            if v.status == "synced":
                self._entries[key] = {
                    "fingerprint": v.fingerprint,
                    "files": len(v.local_files),
                    "verified": now,
                }
            else:
                self._entries.pop(key, None)


@dataclass
class VisitSyncStatus:
    site_id: str
    date_str: str
    local_dir: Path
    remote_dir: Path
    local_files: set[str] = field(default_factory=set)
    remote_files: set[str] = field(default_factory=set)
    # Files present on both sides whose remote copy is stale (filled by populate_remote)
    outdated_on_remote: set[str] = field(default_factory=set)
    # Hash of local file names/sizes/mtimes, used to match against the sync log
    fingerprint: str = ""
    # True when the remote check was skipped because the sync log already confirms it
    from_log: bool = False

    @property
    def status(self) -> str:
        if not self.local_files:
            return "synced"
        if not self.remote_files:
            return "missing"
        if self.local_files <= self.remote_files and not self.outdated_on_remote:
            return "synced"
        return "partial"

    @property
    def missing_on_remote(self) -> set[str]:
        return self.local_files - self.remote_files

    @property
    def to_copy(self) -> set[str]:
        """Files that sync_visit() will copy: missing or outdated on the remote."""
        return self.missing_on_remote | self.outdated_on_remote

    @property
    def water_year_str(self) -> str:
        return f"WY{water_year(self.date_str):02d}"


def scan_local_visits(output_dir: str) -> list[VisitSyncStatus]:
    """Scan output_dir for all SV_YYYYMMDD visit folders.

    Returns a list of VisitSyncStatus with local_dir and local_files populated.
    remote_dir and remote_files are left empty; call populate_remote() to fill them.
    Raises OSError if output_dir (or a folder inside it) cannot be read.
    """
    base = Path(output_dir)
    results: list[VisitSyncStatus] = []
    if not base.is_dir():
        return results
    for site_dir in sorted(base.iterdir()):
        if not site_dir.is_dir():
            continue
        site_id = site_dir.name
        for sv_dir in sorted(site_dir.iterdir()):
            m = _SV_DIR_RE.match(sv_dir.name)
            if not m or not sv_dir.is_dir():
                continue
            date_str = m.group(1)
            local_files = _collect_relative_files(sv_dir)
            results.append(VisitSyncStatus(
                site_id=site_id,
                date_str=date_str,
                local_dir=sv_dir,
                remote_dir=Path(""),
                local_files=local_files,
                fingerprint=_local_fingerprint(sv_dir, local_files),
            ))
    return results


def populate_remote(
    visits: list[VisitSyncStatus], dst_root: str, log: SyncLog | None = None
) -> None:
    """Fill remote_dir, remote_files and outdated_on_remote on each VisitSyncStatus.

    If *log* is given, visits it already confirms as synced (unchanged locally since)
    skip the remote check entirely: they are marked from_log and their remote files are
    assumed to match the local ones. Pass log=None for a full rescan.
    Raises OSError if the destination cannot be read.
    """
    for v in visits:
        v.remote_dir = remote_visit_path(dst_root, v.site_id, v.date_str)
        v.from_log = False
        if log is not None and v.local_files and log.is_synced(v, dst_root):
            v.from_log = True
            v.remote_files = set(v.local_files)
            v.outdated_on_remote = set()
            continue
        v.remote_files = _collect_relative_files(v.remote_dir)
        v.outdated_on_remote = {
            rel for rel in v.local_files & v.remote_files
            if _is_outdated(v.local_dir / rel, v.remote_dir / rel)
        }


def sync_visit(visit: VisitSyncStatus) -> tuple[int, list[str]]:
    """Copy files missing from (or outdated on) the remote visit directory.

    Updates visit.remote_files / visit.outdated_on_remote for every file copied, so the
    status stays accurate even when some copies fail.
    Returns (number_copied, list_of_error_strings).
    """
    copied = 0
    errors: list[str] = []
    for rel in sorted(visit.to_copy):
        src = visit.local_dir / rel
        dst = visit.remote_dir / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
            visit.remote_files.add(rel)
            visit.outdated_on_remote.discard(rel)
        except OSError as exc:
            errors.append(f"{rel}: {exc}")
    return copied, errors
