"""Commit Keeper core: deterministic git checkpointing.

Pure subprocess + stdlib, no Hermes imports. Given a repo path, the keeper:

  1. Refuses anything that is not a git work tree.
  2. Refuses a repo with unmerged (conflicted) paths; a human resolves
     conflicts, never an automatic checkpoint.
  3. Lists changed paths (tracked modifications and untracked files).
  4. Drops credential-shaped paths by name (.env, *.key, *.pem,
     *secret*, *credential*, keystore files) even when .gitignore forgot
     them. Dropped paths are reported, never staged.
  5. Stages the rest, commits with a checkpoint message, and pushes
     when asked.

Every step reports a plain dict so the plugin layer can ledger it.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

_SENSITIVE_MARKERS = (
    ".env",
    "secret",
    "credential",
    "keystore",
    "private",
)
_SENSITIVE_SUFFIXES = (".key", ".pem", ".p12", ".pfx")


def is_sensitive_path(path: str) -> bool:
    low = path.replace("\\", "/").lower()
    name = low.rsplit("/", 1)[-1]
    if name == ".env" or name.startswith(".env."):
        return True
    if any(marker in name for marker in _SENSITIVE_MARKERS):
        return True
    return name.endswith(_SENSITIVE_SUFFIXES)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def changed_paths(repo: Path) -> List[str]:
    out = _git(repo, "status", "--porcelain")
    paths: List[str] = []
    for line in out.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:  # rename: keep the destination path
            path = path.split(" -> ", 1)[1]
        paths.append(path.strip('"'))
    return paths


def has_conflicts(repo: Path) -> bool:
    out = _git(repo, "status", "--porcelain")
    for line in out.stdout.splitlines():
        code = line[:2]
        if code in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}:
            return True
    return False


def checkpoint(repo_path: str, push: bool = False, message: str = "") -> Dict[str, Any]:
    repo = Path(os.path.expanduser(repo_path)).resolve()
    result: Dict[str, Any] = {"repo": str(repo), "ts": time.time(), "push": push}
    probe = _git(repo, "rev-parse", "--is-inside-work-tree") if repo.exists() else None
    if probe is None or probe.returncode != 0 or probe.stdout.strip() != "true":
        result.update(action="skipped", reason="not a git work tree")
        return result
    if has_conflicts(repo):
        result.update(action="refused", reason="unmerged paths present")
        return result
    paths = changed_paths(repo)
    if not paths:
        result.update(action="skipped", reason="working tree clean")
        return result
    safe = [p for p in paths if not is_sensitive_path(p)]
    dropped = [p for p in paths if is_sensitive_path(p)]
    result["dropped_sensitive"] = dropped
    if not safe:
        result.update(action="skipped", reason="only credential-shaped paths changed")
        return result
    add = _git(repo, "add", "--", *safe)
    if add.returncode != 0:
        result.update(action="failed", reason="git add failed: " + add.stderr.strip()[:300])
        return result
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    msg = message or f"commit-keeper: checkpoint {stamp} ({len(safe)} files)"
    commit = _git(
        repo,
        "-c", "user.name=commit-keeper",
        "-c", "user.email=commit-keeper@localhost",
        "commit", "-m", msg,
    )
    if commit.returncode != 0:
        result.update(action="failed", reason="git commit failed: " + (commit.stderr or commit.stdout).strip()[:300])
        return result
    head = _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    result.update(action="committed", commit=head, files=len(safe))
    if push:
        pushed = _git(repo, "push")
        if pushed.returncode != 0:
            result.update(pushed=False, push_error=pushed.stderr.strip()[:300])
        else:
            result.update(pushed=True)
    return result
