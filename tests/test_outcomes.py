from codexbench.outcomes import classify_outcome
from codexbench.process import CommandResult


def command(exit_code=0, timed_out=False, error=None):
    return CommandResult([], exit_code, timed_out, 1.0, "stdout", "stderr", error)


def test_normal_success_path() -> None:
    outcome = classify_outcome(
        command(), patch_present=True, evaluation_valid=True, resolved=True
    )
    assert (outcome.status, outcome.kind, outcome.resolved) == (
        "completed",
        "normal_success",
        True,
    )


def test_normal_failure_path() -> None:
    outcome = classify_outcome(
        command(), patch_present=True, evaluation_valid=True, resolved=False
    )
    assert (outcome.status, outcome.kind, outcome.resolved) == (
        "completed",
        "normal_failure",
        False,
    )


def test_timeout_path() -> None:
    outcome = classify_outcome(command(124, timed_out=True), patch_present=False)
    assert (outcome.status, outcome.kind) == ("failed", "timeout")


def test_installation_failure_path() -> None:
    outcome = classify_outcome(
        command(127, error="No such file or directory"), patch_present=False
    )
    assert (outcome.status, outcome.kind) == ("failed", "installation_failure")

