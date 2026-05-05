"""
Git utility functions.
"""

import subprocess
from pathlib import Path


def get_short_sha(repo_dir: str | Path = ".") -> str:
    """Return the short SHA of the current commit."""
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def get_branch(repo_dir: str | Path = ".") -> str:
    """Return the name of the current branch."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def has_uncommitted_changes(repo_dir: str | Path = ".") -> bool:
    """Return True if there are uncommitted changes in the working tree."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(result.stdout.strip())


def git_archive(output_path: str | Path, repo_dir: str | Path = ".") -> None:
    """Create a zip archive from committed files only."""
    subprocess.run(
        ["git", "archive", "--format=zip", "HEAD", "-o", str(output_path)],
        cwd=str(repo_dir),
        check=True,
    )
