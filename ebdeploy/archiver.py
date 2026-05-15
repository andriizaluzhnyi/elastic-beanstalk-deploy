"""
Deployment archive creation.
"""

import fnmatch
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional
from zipfile import ZIP_DEFLATED, ZipFile

from .exceptions import ArchiveError
from .git_utils import git_archive, has_uncommitted_changes

logger = logging.getLogger(__name__)


def build_archive(
    output_path: str | Path,
    source_dir: str | Path = ".",
    use_git_archive: bool = True,
    exclude_patterns: list[str] | None = None,
    client_name: Optional[str] = None,
    clients_dir: str = "clients",
) -> Path:
    """
    Create a zip archive of the application.

    Args:
        output_path: Path to the output .zip file.
        source_dir: Repository / project root.
        use_git_archive: Use `git archive` (committed files only).
                         Falls back to manual zip if there are uncommitted changes.
        exclude_patterns: Glob patterns to exclude (from ebdeploy.yml).
                          Automatically extended with patterns from .ebignore.
        client_name: When set, subdirs of ``clients_dir`` that do not match
                     this name (case-insensitive) are excluded from the archive.
        clients_dir: Name of the directory that holds per-client subdirs.

    Returns:
        Path to the created archive.
    """
    output_path = Path(output_path)
    source_dir = Path(source_dir).resolve()

    ebignore = _read_ebignore(source_dir)
    other_clients = _other_clients_patterns(source_dir, clients_dir, client_name)
    all_exclude = list(exclude_patterns or []) + ebignore + other_clients

    try:
        if use_git_archive:
            if has_uncommitted_changes(source_dir):
                logger.warning(
                    "Uncommitted changes detected — falling back to zip instead of git archive"
                )
                _zip_directory(output_path, source_dir, all_exclude)
            else:
                logger.info("Building archive via git archive ...")
                git_archive(output_path, source_dir)
                post_filter = ebignore + other_clients
                if post_filter:
                    _filter_zip(output_path, post_filter)
        else:
            logger.info("Building zip archive (including uncommitted changes) ...")
            _zip_directory(output_path, source_dir, all_exclude)

        size_kb = output_path.stat().st_size // 1024
        logger.info(f"Archive created: {output_path} ({size_kb} KB)")
        return output_path

    except subprocess.CalledProcessError as e:
        raise ArchiveError(f"git archive failed: {e.stderr}") from e
    except Exception as e:
        raise ArchiveError(f"Failed to create archive: {e}") from e


def _zip_directory(
    output_path: Path,
    source_dir: Path,
    exclude_patterns: list[str],
) -> None:
    """Pack a directory into a zip, skipping excluded files."""
    with ZipFile(output_path, "w", ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            # Filter directories in-place so os.walk won't descend into them
            dirs[:] = [
                d for d in dirs
                if not _is_excluded(
                    os.path.relpath(os.path.join(root, d), source_dir),
                    exclude_patterns,
                )
            ]
            for file in files:
                abs_path = Path(root) / file
                rel_path = abs_path.relative_to(source_dir)
                if _is_excluded(str(rel_path), exclude_patterns):
                    continue
                zf.write(abs_path, rel_path)


def _other_clients_patterns(
    source_dir: Path,
    clients_dir: str,
    client_name: Optional[str],
) -> list[str]:
    """Return exclusion patterns for client subdirs that don't match client_name.

    Comparison is case-insensitive. Returns an empty list when client_name is
    None or the clients directory does not exist.
    """
    if not client_name:
        return []
    clients_path = source_dir / clients_dir
    if not clients_path.is_dir():
        return []
    patterns: list[str] = []
    matched_dir: Optional[str] = None
    for entry in sorted(clients_path.iterdir()):
        if entry.is_dir():
            if entry.name.lower() == client_name.lower():
                matched_dir = entry.name
            else:
                base = f"{clients_dir}/{entry.name}"
                patterns += [base, f"{base}/*"]
    if matched_dir:
        logger.info(f"Client applied: {clients_dir}/{matched_dir}")
    if patterns:
        logger.debug(
            f"Excluding {len(patterns) // 2} other client dir(s) from {clients_dir}/"
        )
    return patterns


def _is_excluded(rel_path: str, patterns: list[str]) -> bool:
    """Return True if the path matches any of the glob patterns.

    Path separators are normalised to forward slashes before matching so that
    patterns written with '/' work correctly on Windows as well.
    """
    rel_path = rel_path.replace(os.sep, "/")
    for pat in patterns:
        if fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(
            os.path.basename(rel_path), pat
        ):
            return True
    return False


def _read_ebignore(source_dir: Path) -> list[str]:
    """Read patterns from .ebignore, skipping comments and blank lines."""
    path = source_dir / ".ebignore"
    if not path.exists():
        return []
    patterns = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if patterns:
        logger.info(f"Found .ebignore: {len(patterns)} pattern(s)")
    return patterns


def _filter_zip(zip_path: Path, patterns: list[str]) -> None:
    """Remove entries matching patterns from an existing zip in-place."""
    tmp = zip_path.with_suffix(".tmp.zip")
    with ZipFile(zip_path, "r") as src, ZipFile(tmp, "w", ZIP_DEFLATED) as dst:
        for item in src.infolist():
            if not _is_excluded(item.filename, patterns):
                dst.writestr(item, src.read(item.filename))
    zip_path.unlink()
    tmp.rename(zip_path)
