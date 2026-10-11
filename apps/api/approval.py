"""Approval rules for cards (operator decision 4, 2026-10-09).

A card needs the operator's approval before it can run when it:
  - edits a git repo whose current branch is main or master, or
  - asks for something that leaves this Mac: pushing, merging, deploying, publishing, or
    contacting a person (email, text, call, posting to a channel).
Working directories outside the allowed roots are rejected outright (not approvable).

The prompt check is a keyword screen, not a guarantee; agent sandboxes and blocked tools are
the second line of defence.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

OUTWARD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pushes or merges code", re.compile(r"\b(git\s+push|push\s+(to|the|this|it)|merge\s+(to|into|the|this|pr)|force[- ]push)\b", re.I)),
    ("deploys or releases", re.compile(r"\b(deploy|release|roll\s+(to\s+)?prod|terraform\s+apply|publish)\w*\b", re.I)),
    ("contacts a person", re.compile(r"\b(send\s+(an?\s+)?(email|e-mail|text|sms|message|invite)|e-?mail\s+(to|the)|text\s+(him|her|them|me)|call\s+(him|her|them|me|the)|post\s+(to|on|in)\s+\w+|tweet|reply\s+to\s+(the\s+)?(email|customer|user))\b", re.I)),
)

PROTECTED_BRANCHES = {"main", "master"}


def resolve_workdir(path: str, roots: tuple[Path, ...]) -> Path | None:
    """The real path when it is an existing directory inside an allowed root, else None."""
    try:
        real = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not real.is_dir():
        return None
    for root in roots:
        try:
            root_real = root.expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if real == root_real or root_real in real.parents:
            return real
    return None


def current_branch(workdir: Path) -> str | None:
    """The checked-out branch, or None outside a repo or on a detached HEAD.

    `symbolic-ref` works in a new repo before its first commit, where `rev-parse
    --abbrev-ref HEAD` fails; that gap would have let edits to a fresh main branch skip approval.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(workdir), "symbolic-ref", "-q", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def reasons_for(prompt: str, mode: str, branch: str | None) -> list[str]:
    reasons: list[str] = []
    if mode == "edit" and branch in PROTECTED_BRANCHES:
        reasons.append(f"edits a repo on its {branch} branch")
    text = prompt or ""
    for label, pattern in OUTWARD_PATTERNS:
        if pattern.search(text):
            reasons.append(f"prompt {label}")
    return reasons
