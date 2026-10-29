from __future__ import annotations

from dataclasses import dataclass

from codexbench.process import CommandResult


@dataclass(frozen=True)
class Outcome:
    status: str
    kind: str
    resolved: bool | None


def classify_outcome(
    agent: CommandResult,
    *,
    patch_present: bool,
    evaluation_valid: bool | None = None,
    resolved: bool | None = None,
) -> Outcome:
    if agent.error or agent.exit_code == 127:
        return Outcome("failed", "installation_failure", None)
    if agent.timed_out:
        return Outcome("failed", "timeout", None)
    if agent.exit_code != 0:
        return Outcome("failed", "agent_failure", None)
    if not patch_present:
        return Outcome("completed", "normal_failure", False)
    if evaluation_valid is False:
        return Outcome("failed", "infrastructure_failure", None)
    if evaluation_valid is True and resolved is True:
        return Outcome("completed", "normal_success", True)
    if evaluation_valid is True and resolved is False:
        return Outcome("completed", "normal_failure", False)
    return Outcome("running", "pending_evaluation", None)

