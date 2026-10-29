from pathlib import Path

import pytest

from codexbench.specs import ConditionSpec, RunSpec, RuntimeSpec, TaskSpec


@pytest.fixture
def run_spec() -> RunSpec:
    return RunSpec(
        experiment_id="test-experiment",
        prompt_version="v1",
        task=TaskSpec(
            id="sympy__sympy-1",
            repo="sympy/sympy",
            base_commit="a" * 40,
            image="example/image:latest",
        ),
        condition=ConditionSpec(id="control", label="Control"),
        runtime=RuntimeSpec(
            model="test-model",
            reasoning_effort="high",
            token_budget=100,
        ),
        repetition=1,
        condition_digest="b" * 64,
    )


@pytest.fixture
def fake_result_paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "stdout.log", tmp_path / "stderr.log"

