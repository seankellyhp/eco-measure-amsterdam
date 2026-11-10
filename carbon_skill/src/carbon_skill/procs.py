"""Process helpers: which agent we run under, is it alive, and detached spawn."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psutil

# Process names that are never the agent: shells, launchers and ourselves.
SKIP = {
    "bash", "sh", "zsh", "fish", "dash", "ksh", "tcsh", "csh", "cmd", "powershell",
    "pwsh", "conhost", "env", "timeout", "nohup", "script", "login", "sudo", "setsid",
    "uv", "uvx", "python", "python3", "carbon", "carbon_start",
}

# Process names of the coding agents themselves. An ancestor with one of these
# names means the command was run by an agent, not typed in a plain terminal.
KNOWN_AGENTS = {"claude", "codex", "pi"}


def _norm(name: str) -> str:
    name = (name or "").lower().lstrip("-")
    if name.endswith(".exe"):
        name = name[:-4]
    # python3.12 and the like
    if name.startswith("python"):
        return "python"
    return name


def create_time(pid: int) -> float | None:
    try:
        return psutil.Process(pid).create_time()
    except (psutil.Error, ValueError):
        return None


def name_of(pid: int) -> str:
    try:
        return psutil.Process(pid).name()
    except (psutil.Error, ValueError):
        return "?"


def alive(pid: int | None, created: float | None) -> bool:
    """True if `pid` exists and is the same process incarnation as recorded."""
    if not pid:
        return False
    try:
        if not psutil.pid_exists(pid):
            return False
        p = psutil.Process(pid)
        if p.status() == psutil.STATUS_ZOMBIE:
            return False
        return created is None or abs(p.create_time() - created) < 1.0
    except (psutil.Error, ValueError):
        return False


def detect_agent() -> dict:
    """The process this run belongs to: {pid, create_time, name, how}."""

    def rec(pid: int, how: str) -> dict:
        return {"pid": pid, "create_time": create_time(pid), "name": name_of(pid), "how": how}

    env = os.environ.get("CARBON_PARENT_PID", "").strip()
    if env.isdigit() and psutil.pid_exists(int(env)):
        return rec(int(env), "CARBON_PARENT_PID")

    env = os.environ.get("CLAUDE_PID", "").strip()
    if env.isdigit() and psutil.pid_exists(int(env)):
        return rec(int(env), "CLAUDE_PID")

    try:
        parents = psutil.Process().parents()
    except psutil.Error:
        parents = []
    last = None
    for p in parents:
        try:
            name = p.name()
        except psutil.Error:
            continue
        last = p
        if _norm(name) not in SKIP:
            return rec(p.pid, "first non-shell parent")
    if last is not None:
        return rec(last.pid, "top of the process tree")
    return rec(os.getppid(), "parent process")


def under_known_agent() -> bool:
    """True if a coding agent is among this process's ancestors."""
    try:
        parents = psutil.Process().parents()
    except psutil.Error:
        return False
    for p in parents:
        try:
            if _norm(p.name()) in KNOWN_AGENTS:
                return True
        except psutil.Error:
            continue
    return False


def spawn_detached(args: list[str], log: Path, cwd: Path) -> subprocess.Popen:
    """Start `args` fully detached; all three standard handles redirected.

    If the child inherited the tool call's output pipe, the agent's tool call
    would never return, so nothing is inherited.
    """
    kwargs: dict = {}
    if sys.platform == "win32":
        flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
        )
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    with open(log, "ab") as fh:
        return subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=fh,
            stderr=subprocess.STDOUT,
            close_fds=True,
            cwd=str(cwd),
            **kwargs,
        )


def stop_process(pid: int, created: float | None, wait: float = 5.0) -> None:
    """Terminate, then kill, a process we own."""
    if not alive(pid, created):
        return
    try:
        p = psutil.Process(pid)
        p.terminate()
        try:
            p.wait(wait)
        except psutil.TimeoutExpired:
            p.kill()
            p.wait(wait)
    except psutil.Error:
        pass
