from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True)
class CommandResult:
    argv: list[str]
    exit_code: int
    timed_out: bool
    duration_seconds: float
    stdout_path: str
    stderr_path: str
    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def run_logged(
    argv: Sequence[str],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
    env: Mapping[str, str] | None = None,
) -> CommandResult:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    command = [str(item) for item in argv]
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=stdout,
                stderr=stderr,
                env=dict(env) if env else None,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            stderr.write((str(exc) + "\n").encode())
            return CommandResult(
                command,
                127,
                False,
                time.monotonic() - started,
                str(stdout_path),
                str(stderr_path),
                error=str(exc),
            )
        try:
            exit_code = process.wait(timeout=timeout_seconds)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            exit_code = 124
    return CommandResult(
        command,
        exit_code,
        timed_out,
        time.monotonic() - started,
        str(stdout_path),
        str(stderr_path),
    )

