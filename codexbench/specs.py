from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TaskSpec(StrictModel):
    id: str
    dataset: str = "verified"
    repo: str
    base_commit: str
    image: str
    image_platform: str = "linux/amd64"

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not ID_PATTERN.fullmatch(value):
            raise ValueError("task id contains unsafe characters")
        return value

    @field_validator("base_commit")
    @classmethod
    def valid_commit(cls, value: str) -> str:
        if not COMMIT_PATTERN.fullmatch(value):
            raise ValueError("base_commit must be a 40-character lowercase SHA-1")
        return value


class DocumentSpec(StrictModel):
    source: str
    destination: str

    @field_validator("destination")
    @classmethod
    def safe_destination(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or value in {"", "."}:
            raise ValueError("document destination must remain inside the workspace")
        return value


class ConditionSpec(StrictModel):
    id: str
    label: str
    documents: tuple[DocumentSpec, ...] = ()

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not ID_PATTERN.fullmatch(value):
            raise ValueError("condition id contains unsafe characters")
        return value


class RuntimeSpec(StrictModel):
    model: str
    reasoning_effort: Literal["minimal", "low", "medium", "high", "xhigh", "max", "ultra"]
    token_budget: int = Field(gt=0)
    agent_timeout_seconds: int = Field(default=1800, gt=0)
    evaluator_timeout_seconds: int = Field(default=1800, gt=0)
    codex_cli: str = "codex"
    swebench_cli: str = ".venv/bin/swebench"
    task_repo: str = "swe-bench-tasks"
    results_dir: str = "runs"
    database: str = "runs/results.sqlite3"
    billing_mode: Literal["chatgpt_subscription", "api"] = "chatgpt_subscription"


class ExperimentSpec(StrictModel):
    schema_version: Literal[1]
    experiment_id: str
    prompt_version: str
    repetitions: int = Field(default=1, gt=0)
    seed: int = 0
    runtime: RuntimeSpec
    tasks: tuple[TaskSpec, ...]
    conditions: tuple[ConditionSpec, ...]

    @model_validator(mode="after")
    def unique_ids(self) -> "ExperimentSpec":
        for label, values in (("task", self.tasks), ("condition", self.conditions)):
            ids = [item.id for item in values]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {label} ids")
        if not self.tasks or not self.conditions:
            raise ValueError("at least one task and condition are required")
        return self

    def task(self, task_id: str) -> TaskSpec:
        for item in self.tasks:
            if item.id == task_id:
                return item
        return _missing("task", task_id)

    def condition(self, condition_id: str) -> ConditionSpec:
        for item in self.conditions:
            if item.id == condition_id:
                return item
        return _missing("condition", condition_id)


def _missing(kind: str, item_id: str):
    raise KeyError(f"unknown {kind}: {item_id}")


class RunSpec(StrictModel):
    experiment_id: str
    prompt_version: str
    task: TaskSpec
    condition: ConditionSpec
    runtime: RuntimeSpec
    repetition: int = Field(gt=0)
    condition_digest: str

    @property
    def run_id(self) -> str:
        identity = {
            "experiment_id": self.experiment_id,
            "prompt_version": self.prompt_version,
            "task_id": self.task.id,
            "base_commit": self.task.base_commit,
            "condition_id": self.condition.id,
            "condition_digest": self.condition_digest,
            "model": self.runtime.model,
            "reasoning_effort": self.runtime.reasoning_effort,
            "token_budget": self.runtime.token_budget,
            "repetition": self.repetition,
        }
        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:12]
        return f"{self.task.id}--{self.condition.id}--r{self.repetition}--{digest}"


def load_experiment(path: Path) -> ExperimentSpec:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ExperimentSpec.model_validate(raw)


def condition_digest(condition: ConditionSpec, manifest: Path) -> str:
    digest = hashlib.sha256(condition.id.encode())
    for document in condition.documents:
        source = (manifest.parent / document.source).resolve()
        digest.update(document.destination.encode())
        digest.update(source.read_bytes())
    return digest.hexdigest()


def build_run_spec(
    experiment: ExperimentSpec,
    manifest: Path,
    task_id: str,
    condition_id: str,
    repetition: int,
) -> RunSpec:
    condition = experiment.condition(condition_id)
    return RunSpec(
        experiment_id=experiment.experiment_id,
        prompt_version=experiment.prompt_version,
        task=experiment.task(task_id),
        condition=condition,
        runtime=experiment.runtime,
        repetition=repetition,
        condition_digest=condition_digest(condition, manifest),
    )
