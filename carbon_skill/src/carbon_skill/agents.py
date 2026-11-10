"""Coding agents we install the skill into, and `carbon install-skill`.

Add an agent by adding an entry to AGENTS.
"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from importlib import resources
from pathlib import Path

from . import paths, runs

MARKER = ".installed-by-carbon-skill"
PLACEHOLDER = "{{CARBON_CMD}}"
OLD_LAYOUT = ("scripts", ".venv", "pyproject.toml", "uv.lock", ".python-version")


def _claude_config() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def _codex_config() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


# name -> (config folder whose existence means "installed", skill folder)
AGENTS = {
    "claude-code": lambda: (_claude_config(), _claude_config() / "skills" / "carbon"),
    # Codex reads user skills from ~/.agents/skills (developers.openai.com/codex/skills).
    "codex": lambda: (_codex_config(), Path.home() / ".agents" / "skills" / "carbon"),
}


def detected() -> list[str]:
    return [name for name, loc in AGENTS.items() if loc()[0].is_dir()]


def _project_dir() -> Path | None:
    """The source project when running from `uv run --project <dir>` (its .venv)."""
    prefix = Path(sys.prefix)
    if prefix.name != ".venv":
        return None
    proj = prefix.parent
    try:
        text = (proj / "pyproject.toml").read_text()
    except OSError:
        return None
    return proj if 'name = "carbon-skill"' in text else None


def _quote(path: str) -> str:
    return f'"{path}"' if " " in path else path


def carbon_cmd() -> str:
    """How an agent should call this program on this machine."""
    proj = _project_dir()
    if proj is not None:
        return f'uv run --project "{proj.resolve().as_posix()}" carbon'
    bindir = Path(sys.executable).parent
    exe = bindir / ("carbon.exe" if sys.platform == "win32" else "carbon")
    found = shutil.which("carbon")
    if found:
        f = Path(found)
        if f.resolve().parent == bindir.resolve() or f.resolve() == exe.resolve():
            return "carbon"
    if exe.exists():
        return _quote(exe.as_posix())
    return "carbon"


def _template() -> resources.abc.Traversable:
    return resources.files("carbon_skill") / "skill"


def _copy_tree(src, dest: Path, cmd: str) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.is_dir():
            _copy_tree(item, dest / item.name, cmd)
        elif item.name.endswith(".md"):
            (dest / item.name).write_text(item.read_text(encoding="utf-8").replace(PLACEHOLDER, cmd), encoding="utf-8")


def _migrate_old(folder: Path) -> list[str]:
    """Move runs out of a bash-era install and remove its program files."""
    notes = []
    old_runs = folder / "runs"
    if old_runs.is_dir():
        root = paths.data_root()
        for d in sorted(old_runs.iterdir()):
            if not d.is_dir() or not paths.valid_label(d.name):
                continue
            if (root / d.name).exists():
                notes.append(f"  kept old run '{d.name}' in place: a run with that name already exists")
                continue
            shutil.move(str(d), str(root / d.name))
            _convert_old_run(root / d.name)
            notes.append(f"  moved old run '{d.name}' to {root / d.name}")
        if not any(old_runs.iterdir()):
            old_runs.rmdir()
    for name in OLD_LAYOUT:
        p = folder / name
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()
    return notes


def _convert_old_run(rundir: Path) -> None:
    """Give a bash-era run a status.json so the report can find its window."""
    if (rundir / "status.json").exists():
        return

    def read(name: str) -> str | None:
        try:
            return (rundir / name).read_text().strip() or None
        except OSError:
            return None

    runs.write_json(rundir / "status.json", {
        "state": "stopped",
        "started_at": read("started_at"),
        "ended_at": read("ended_at"),
        "stopped_by": (read("stopped_by") or "carbon end").replace("carbon_end", "carbon end"),
    })


def install(name: str, force: bool = False) -> list[str]:
    config, folder = AGENTS[name]()
    out = []
    if folder.exists() and not (folder / MARKER).exists():
        if not force:
            raise paths.Failure(
                f"{folder} exists and was not installed by carbon-skill; left it alone.\n"
                "Pass --force to move it to a backup and install anyway."
            )
        backup = folder.parent.parent / f"carbon-skill-backup-{datetime.now():%Y%m%d-%H%M%S}"
        shutil.move(str(folder), str(backup))
        out.append(f"  moved the existing folder to {backup}")
    if (folder / MARKER).exists():
        out += _migrate_old(folder)
        for child in ("SKILL.md", "reference"):
            p = folder / child
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
    cmd = carbon_cmd()
    _copy_tree(_template(), folder, cmd)
    (folder / MARKER).write_text(f"carbon-skill\ncommand: {cmd}\n")
    return [f"Installed the carbon skill for {name} at {folder}", f"  command: {cmd}"] + out


def remove(name: str) -> str:
    _, folder = AGENTS[name]()
    if not folder.exists():
        return f"Nothing installed for {name} at {folder}"
    if not (folder / MARKER).exists():
        return f"{folder} was not installed by carbon-skill; left it alone."
    shutil.rmtree(folder)
    return f"Removed {folder}"


def command(agent: str, do_remove: bool, force: bool) -> int:
    if agent == "all":
        names = detected()
        if not names and not do_remove:
            print("No agent config folder found; installing for claude-code.")
            names = ["claude-code"]
        elif do_remove:
            names = list(AGENTS)
    else:
        names = [agent]

    if do_remove:
        for name in names:
            print(remove(name))
        print(f"Your measurements are kept in {paths.data_root()}")
        return 0

    for name in names:
        print("\n".join(install(name, force)))
    print("Restart your agent if /carbon is not listed.")
    return 0
