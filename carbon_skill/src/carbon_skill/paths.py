"""Where runs live, and which labels are allowed."""

from __future__ import annotations

import os
import re
import shutil
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


def run_dir(label: str) -> Path:
    return data_root() / check_label(label)


def last_label() -> str | None:
    try:
        label = (data_root() / ".last").read_text().strip()
    except OSError:
        return None
    return label if valid_label(label) else None


def set_last(label: str) -> None:
    (data_root() / ".last").write_text(label + "\n")


def label_or_last(label: str | None) -> str:
    """The given label, else the most recently started run, else 'default'."""
    if label:
        return check_label(label)
    return last_label() or "default"


def all_labels() -> list[str]:
    root = data_root()
    return sorted(p.name for p in root.iterdir() if p.is_dir() and valid_label(p.name))


def empty_dir(path: Path) -> None:
    """Remove everything inside `path`, keeping the folder."""
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
