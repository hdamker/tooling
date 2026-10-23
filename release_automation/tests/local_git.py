"""Local bare repositories standing in for GitHub remotes in git-level tests."""

import subprocess
from pathlib import Path
from typing import Dict, Optional

from release_automation.scripts.git_operations import GitOperations


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def make_remote(base: Path, name: str, files: Dict[str, str], tag: Optional[str] = None) -> Path:
    """Bare repository with one commit on main holding files (and an optional tag)."""
    seed = base / f"{name}-seed"
    seed.mkdir(parents=True)
    git(seed, "init", "-q", "-b", "main")
    git(seed, "config", "user.name", "seed")
    git(seed, "config", "user.email", "seed@example.com")
    write_files(seed, files)
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "seed")
    if tag:
        git(seed, "tag", tag)
    bare = base / f"{name}.git"
    git(base, "clone", "-q", "--bare", str(seed), str(bare))
    return bare


def write_files(root: Path, files: Dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def push_branch(bare: Path, base: Path, branch: str, files: Dict[str, str]) -> None:
    """Add a branch on the remote with one extra commit on top of main."""
    work = base / f"push-{branch.replace('/', '-')}"
    git(base, "clone", "-q", str(bare), str(work))
    git(work, "config", "user.name", "someone")
    git(work, "config", "user.email", "someone@example.com")
    git(work, "checkout", "-q", "-b", branch)
    write_files(work, files)
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "earlier run")
    git(work, "push", "-q", "origin", branch)


def git_ops(bare: Path, work_dir: Path, repo: str = "camaraproject/Example") -> GitOperations:
    """GitOperations bound to a local bare repository (file:// so --depth applies)."""
    return GitOperations(repo=repo, work_dir=str(work_dir), remote_url=bare.as_uri())
