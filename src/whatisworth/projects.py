"""Which project a working directory belongs to.

A project is the git repository a directory lies in. Git worktrees count
towards their main repository, and subdirectories towards their repository.
The mapping is resolved while the directory still exists and stored in the
ledger, so it survives worktrees that are deleted later.
"""

from __future__ import annotations

import json
from fnmatch import fnmatchcase
from pathlib import Path

from .i18n import t


def resolve_repo(cwd: str) -> str | None:
    """Main repository root of `cwd`, or None if `cwd` is gone or not in git."""
    path = Path(cwd)
    if not path.is_dir():
        return None
    for directory in (path, *path.parents):
        dot_git = directory / ".git"
        if dot_git.is_dir():
            return str(directory)
        if dot_git.is_file():
            return _worktree_main(dot_git) or str(directory)
        if directory == Path.home():
            break  # never treat a repository around $HOME as a project
    return None


def _worktree_main(dot_git_file: Path) -> str | None:
    """Main repository of a worktree, via `.git` -> gitdir -> commondir."""
    try:
        text = dot_git_file.read_text().strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    gitdir = (dot_git_file.parent / text.split(":", 1)[1].strip()).resolve()
    commondir_file = gitdir / "commondir"
    try:
        common = (gitdir / commondir_file.read_text().strip()).resolve()
    except OSError:
        return None
    return str(common.parent) if common.name == ".git" else None


def load_rules(path: Path) -> list[tuple[str, str]]:
    """Rules from projects.json, {"glob": "project"}, for folders git can no longer resolve."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    return [(str(Path(pattern).expanduser()), str(name)) for pattern, name in data.items()]


def known_repo(cwd: str | None, repos: dict[str, str | None]) -> str | None:
    """Repository of `cwd`, or of its nearest ancestor the ledger has resolved."""
    if not cwd:
        return None
    path = Path(cwd)
    for directory in (path, *path.parents):
        if repos.get(str(directory)):
            return repos[str(directory)]
        if directory == Path.home():
            break
    return None


def label(cwd: str | None, repo: str | None, rules: list[tuple[str, str]] = ()) -> str:
    if repo:
        return Path(repo).name
    if not cwd:
        return t("project.unknown")
    path = Path(cwd)
    for pattern, name in rules:
        if any(fnmatchcase(str(directory), pattern) for directory in (path, *path.parents)):
            return name
    if Path(cwd) == Path.home():
        return t("project.home")
    return Path(cwd).name or cwd
