import pytest
from pydantic import ValidationError

from codexbench.specs import DocumentSpec, RunSpec, TaskSpec


def test_task_requires_full_commit() -> None:
    with pytest.raises(ValidationError):
        TaskSpec(
            id="task",
            repo="org/repo",
            base_commit="abc",
            image="image:latest",
        )


def test_document_rejects_path_escape() -> None:
    with pytest.raises(ValidationError):
        DocumentSpec(source="AGENTS.md", destination="../AGENTS.md")


def test_run_id_is_deterministic(run_spec: RunSpec) -> None:
    assert run_spec.run_id == RunSpec.model_validate(run_spec.model_dump()).run_id
    assert run_spec.run_id.startswith("sympy__sympy-1--control--r1--")


def test_run_id_changes_with_repetition(run_spec: RunSpec) -> None:
    second = run_spec.model_copy(update={"repetition": 2})
    assert run_spec.run_id != second.run_id

