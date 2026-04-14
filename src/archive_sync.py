import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

_SV_DIR_RE = re.compile(r"^SV_(\d{8})$")


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


@dataclass
class VisitSyncStatus:
    site_id: str
    date_str: str
    local_dir: Path
    remote_dir: Path
    local_files: set[str] = field(default_factory=set)
    remote_files: set[str] = field(default_factory=set)

    @property
    def status(self) -> str:
        if not self.local_files:
            return "synced"
        if not self.remote_files:
            return "missing"
        if self.local_files <= self.remote_files:
            return "synced"
        return "partial"

    @property
    def missing_on_remote(self) -> set[str]:
        return self.local_files - self.remote_files

    @property
    def water_year_str(self) -> str:
        return f"WY{water_year(self.date_str):02d}"


def scan_local_visits(output_dir: str) -> list[VisitSyncStatus]:
    """Scan output_dir for all SV_YYYYMMDD visit folders.

    Returns a list of VisitSyncStatus with local_dir and local_files populated.
    remote_dir and remote_files are left empty; call populate_remote() to fill them.
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
            results.append(VisitSyncStatus(
                site_id=site_id,
                date_str=date_str,
                local_dir=sv_dir,
                remote_dir=Path(""),
                local_files=_collect_relative_files(sv_dir),
            ))
    return results


def populate_remote(visits: list[VisitSyncStatus], dst_root: str) -> None:
    """Fill remote_dir and remote_files on each VisitSyncStatus."""
    for v in visits:
        v.remote_dir = remote_visit_path(dst_root, v.site_id, v.date_str)
        v.remote_files = _collect_relative_files(v.remote_dir)


def sync_visit(visit: VisitSyncStatus) -> tuple[int, list[str]]:
    """Copy files missing from remote to the remote visit directory.

    Returns (number_copied, list_of_error_strings).
    """
    copied = 0
    errors: list[str] = []
    for rel in sorted(visit.missing_on_remote):
        src = visit.local_dir / rel
        dst = visit.remote_dir / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
        except OSError as exc:
            errors.append(f"{rel}: {exc}")
    return copied, errors