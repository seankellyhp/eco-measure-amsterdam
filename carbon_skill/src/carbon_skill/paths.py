"""Where runs live, and which labels are allowed."""

from __future__ import annotations

import os
import re
from pathlib import Path

LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class UsageError(Exception):
    """A bad argument: printed to stderr, exit code 2."""


class Failure(Exception):
    """An expected failure: printed to stderr, exit code 1."""


def data_root() -> Path:
    """The folder holding every run: CARBON_RUN_ROOT, else the user data dir."""
    env = os.environ.get("CARBON_RUN_ROOT")
    if env:
        root = Path(env).expanduser()
    else:
        import platformdirs

        root = platformdirs.user_data_path("carbon-skill") / "runs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def valid_label(label: str) -> bool:
    return bool(LABEL_RE.match(label or ""))


def check_label(label: str) -> str:
    if not valid_label(label):
        raise UsageError(
            f"Invalid label {label!r}. A label is 1 to 64 characters: letters, digits, '.', '_' or '-', "
            "starting with a letter or digit."
        )
    return label


def run_dir(run_id: int) -> Path:
    """The folder holding a run's monitor.log and stop sentinel."""
    return data_root() / str(int(run_id))


def parse_ref(ref: str) -> tuple[str | None, int | None]:
    """(label, None) for a label, (None, id) for '@<id>'. '@' is never part of a label."""
    if ref.startswith("@"):
        if ref[1:].isdigit():
            return None, int(ref[1:])
        raise UsageError(f"Invalid run id {ref!r}: write @ followed by the number shown by carbon list.")
    return check_label(ref), None
