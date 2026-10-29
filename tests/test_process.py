import sys
from pathlib import Path

from codexbench.process import run_logged


def test_process_captures_stdout_stderr_and_exit_code(tmp_path: Path) -> None:
    result = run_logged(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); raise SystemExit(3)"],
        cwd=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        timeout_seconds=5,
    )
    assert result.exit_code == 3
    assert result.timed_out is False
    assert (tmp_path / "stdout.log").read_text().strip() == "out"
    assert (tmp_path / "stderr.log").read_text().strip() == "err"


def test_process_timeout(tmp_path: Path) -> None:
    result = run_logged(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        cwd=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        timeout_seconds=1,
    )
    assert result.exit_code == 124
    assert result.timed_out is True


def test_missing_executable_is_127(tmp_path: Path) -> None:
    result = run_logged(
        ["definitely-not-installed-codexbench-command"],
        cwd=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        timeout_seconds=1,
    )
    assert result.exit_code == 127
    assert result.error

