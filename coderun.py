"""Run user Python code locally, offline, with a hard timeout.

The Code Studio never touches the network itself; it launches a child Python
process with ``-B -E`` (no bytecode files, ignored PYTHON* environment) in the
user's workspace, so local sibling imports still work.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT = 40_000
DEFAULT_TIMEOUT = 15.0


@dataclass
class RunResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int | None
    duration: float
    note: str = ""

    def as_text(self, source_name: str = "program.py") -> str:
        lines = [f"Program : {source_name}", f"Exit code: {self.exit_code}", f"Runtime : {self.duration * 1000:.0f} ms"]
        if self.note:
            lines.append(f"Note    : {self.note}")
        lines.append("")
        lines.append("--- STDOUT " + "-" * 46)
        lines.append(self.stdout.rstrip() if self.stdout.strip() else "(no output)")
        lines.append("")
        lines.append("--- STDERR " + "-" * 46)
        lines.append(self.stderr.rstrip() if self.stderr.strip() else "(nothing)")
        return "\n".join(lines)


def _trim(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + f"\n... output truncated ({len(text) - MAX_OUTPUT} more characters)"


def syntax_error(source: str) -> str | None:
    """Return a readable syntax error, or None when the source compiles."""
    try:
        compile(source, "<nova>", "exec")
    except SyntaxError as exc:
        return f"{exc.msg} (line {exc.lineno}, column {exc.offset})"
    except (ValueError, TypeError) as exc:
        return str(exc)
    return None


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTHONSTARTUP", None)
    return env


def run_file(path: Path | str, timeout: float = DEFAULT_TIMEOUT, cwd: Path | str | None = None) -> RunResult:
    path = Path(path)
    workdir = Path(cwd) if cwd else path.parent
    if not path.is_file():
        return RunResult(False, "", f"File not found: {path}", None, 0.0)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            [sys.executable, "-B", "-E", "-X", "utf8", str(path)],
            cwd=str(workdir),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_child_env(),
        )
    except subprocess.TimeoutExpired:
        return RunResult(
            False,
            "",
            "",
            None,
            time.monotonic() - started,
            note=f"Stopped after {timeout:.0f}s — check for infinite loops or blocking input()",
        )
    except OSError as exc:
        return RunResult(False, "", f"Could not start Python: {exc}", None, time.monotonic() - started)
    duration = time.monotonic() - started
    return RunResult(
        ok=completed.returncode == 0,
        stdout=_trim(completed.stdout),
        stderr=_trim(completed.stderr),
        exit_code=completed.returncode,
        duration=duration,
    )


def run_source(source: str, workdir: Path | str, timeout: float = DEFAULT_TIMEOUT, name: str = "snippet.py") -> RunResult:
    """Write a temporary script inside ``workdir`` and run it."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    handle, temp_path = tempfile.mkstemp(prefix=".nova_run_", suffix=".py", dir=str(workdir), text=True)
    os.close(handle)
    try:
        Path(temp_path).write_text(source, encoding="utf-8")
        return run_file(temp_path, timeout=timeout, cwd=workdir)
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
