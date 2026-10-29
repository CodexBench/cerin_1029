from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from codexbench.evaluator import SwebenchEvaluator
from codexbench.outcomes import Outcome, classify_outcome
from codexbench.process import CommandResult, run_logged
from codexbench.specs import ExperimentSpec, RunSpec
from codexbench.store import EventJournal, ResultStore, utc_now


class HarnessError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimePaths:
    project_root: Path
    manifest: Path
    codex_cli: Path
    swebench_cli: Path
    task_repo: Path
    results_dir: Path
    database: Path


def _resolve_tool(value: str, root: Path) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute() or "/" in value:
        return (candidate if candidate.is_absolute() else root / candidate).resolve()
    found = shutil.which(value)
    return Path(found) if found else root / value


def resolve_paths(experiment: ExperimentSpec, manifest: Path) -> RuntimePaths:
    root = manifest.resolve().parent.parent
    runtime = experiment.runtime
    codex_value = os.environ.get("CODEXBENCH_CODEX_CLI", runtime.codex_cli)
    swebench_value = os.environ.get("CODEXBENCH_SWEBENCH_CLI", runtime.swebench_cli)
    task_repo_value = os.environ.get("CODEXBENCH_TASK_REPO", runtime.task_repo)
    results_value = os.environ.get("CODEXBENCH_RESULTS_DIR", runtime.results_dir)
    database_value = os.environ.get("CODEXBENCH_DATABASE", runtime.database)

    def resolve_path(value: str) -> Path:
        path = Path(value).expanduser()
        return (path if path.is_absolute() else root / path).resolve()

    return RuntimePaths(
        project_root=root,
        manifest=manifest.resolve(),
        codex_cli=_resolve_tool(codex_value, root),
        swebench_cli=_resolve_tool(swebench_value, root),
        task_repo=resolve_path(task_repo_value),
        results_dir=resolve_path(results_value),
        database=resolve_path(database_value),
    )


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_token_usage(event_path: Path) -> dict[str, int] | None:
    latest: dict[str, int] | None = None

    def mappings(value: Any) -> Iterable[dict[str, Any]]:
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from mappings(child)
        elif isinstance(value, list):
            for child in value:
                yield from mappings(child)

    if not event_path.exists():
        return None
    for line in event_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        for value in mappings(event):
            input_tokens = value.get("input_tokens")
            output_tokens = value.get("output_tokens")
            if isinstance(input_tokens, int) and isinstance(output_tokens, int):
                cached = value.get("cached_input_tokens", 0)
                cached = cached if isinstance(cached, int) else 0
                reasoning = value.get("reasoning_output_tokens", 0)
                reasoning = reasoning if isinstance(reasoning, int) else 0
                uncached = max(0, input_tokens - cached)
                latest = {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached,
                    "uncached_input_tokens": uncached,
                    "output_tokens": output_tokens,
                    "reasoning_output_tokens": reasoning,
                    "raw_total_tokens": input_tokens + output_tokens,
                    "budget_tokens": uncached + output_tokens,
                }
    return latest


def validate_environment(
    experiment: ExperimentSpec,
    paths: RuntimePaths,
    *,
    pull_images: bool = False,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not paths.codex_cli.is_file():
        errors.append(f"Codex CLI not found: {paths.codex_cli}")
    if not paths.swebench_cli.is_file():
        errors.append(f"SWE-bench CLI not found: {paths.swebench_cli}")
    if not paths.task_repo.is_dir():
        errors.append(f"task repository not found: {paths.task_repo}")

    for condition in experiment.conditions:
        for document in condition.documents:
            source = (paths.manifest.parent / document.source).resolve()
            if not source.is_file():
                errors.append(f"condition document not found: {source}")

    for task in experiment.tasks:
        task_dir = paths.task_repo / "tasks" / task.id
        metadata_path = task_dir / "task.yaml"
        if not metadata_path.is_file():
            errors.append(f"task metadata not found: {metadata_path}")
            continue
        raw = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
        checks = {
            "instance_id": task.id,
            "repo": task.repo,
            "base_commit": task.base_commit,
            "image": task.image,
        }
        for key, expected in checks.items():
            if raw.get(key) != expected:
                errors.append(
                    f"{task.id}: {key} mismatch, manifest={expected!r}, task={raw.get(key)!r}"
                )
        for required in ("problem_statement.md", "tests.json"):
            if not (task_dir / required).is_file():
                errors.append(f"{task.id}: missing {required}")

    docker = subprocess.run(
        ["docker", "info", "--format", "{{json .}}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if docker.returncode != 0:
        errors.append("Docker daemon is unavailable: " + docker.stderr.strip())
    else:
        try:
            info = json.loads(docker.stdout)
            memory = int(info.get("MemTotal", 0))
            if memory < 12 * 1024**3:
                warnings.append("Docker memory is below 12 GiB; prebuilt images are required")
        except (json.JSONDecodeError, ValueError):
            warnings.append("Docker info could not be parsed")

    image_results = []
    if not errors:
        for task in experiment.tasks:
            inspect = subprocess.run(
                ["docker", "image", "inspect", task.image],
                text=True,
                capture_output=True,
                check=False,
            )
            if inspect.returncode != 0 and pull_images:
                pulled = subprocess.run(
                    ["docker", "pull", "--platform", task.image_platform, task.image],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if pulled.returncode != 0:
                    errors.append(f"failed to pull {task.image}: {pulled.stderr.strip()}")
                inspect = subprocess.run(
                    ["docker", "image", "inspect", task.image],
                    text=True,
                    capture_output=True,
                    check=False,
                )
            if inspect.returncode != 0:
                errors.append(f"Docker image missing: {task.image}; use validate --pull-images")
                continue
            image = json.loads(inspect.stdout)[0]
            image_results.append(
                {
                    "task_id": task.id,
                    "image": task.image,
                    "id": image.get("Id"),
                    "architecture": image.get("Architecture"),
                }
            )

    report = {
        "status": "ready" if not errors else "failed",
        "timestamp": utc_now(),
        "errors": errors,
        "warnings": warnings,
        "paths": {key: str(value) for key, value in asdict(paths).items()},
        "images": image_results,
    }
    paths.results_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(paths.results_dir / "validation.json", report)
    return report


class Runner:
    def __init__(
        self,
        spec: RunSpec,
        paths: RuntimePaths,
        store: ResultStore,
        *,
        resume: bool = False,
    ):
        self.spec = spec
        self.paths = paths
        self.store = store
        self.resume = resume
        self.run_dir = paths.results_dir / spec.run_id
        self.workspace = self.run_dir / "workspace"
        self.checkpoints_path = self.run_dir / "checkpoints.json"
        self.summary_path = self.run_dir / "result.json"
        self.patch_path = self.run_dir / "agent.patch"
        self.agent_events = self.run_dir / "agent.events.jsonl"
        self.started = time.monotonic()
        self.journal: EventJournal | None = None

    def _load_checkpoints(self) -> dict[str, Any]:
        if self.checkpoints_path.exists():
            return json.loads(self.checkpoints_path.read_text(encoding="utf-8"))
        return {}

    def _checkpoint(self, name: str, value: Any = True) -> None:
        checkpoints = self._load_checkpoints()
        checkpoints[name] = value
        atomic_json(self.checkpoints_path, checkpoints)

    def _event(self, phase: str, status: str, **payload: Any) -> None:
        assert self.journal is not None
        self.journal.write(phase, status, **payload)

    def _command(
        self,
        phase: str,
        argv: list[str],
        *,
        cwd: Path,
        timeout: int,
        stdout: Path | None = None,
        stderr: Path | None = None,
    ) -> CommandResult:
        stdout = stdout or self.run_dir / "commands" / f"{phase}.stdout.log"
        stderr = stderr or self.run_dir / "commands" / f"{phase}.stderr.log"
        self._event(phase, "started", argv=argv, cwd=str(cwd), timeout_seconds=timeout)
        result = run_logged(
            argv,
            cwd=cwd,
            stdout_path=stdout,
            stderr_path=stderr,
            timeout_seconds=timeout,
        )
        self._event(phase, "finished", **result.as_dict())
        return result

    def _require_success(self, phase: str, result: CommandResult) -> None:
        if result.timed_out:
            raise HarnessError(f"{phase} timed out")
        if result.exit_code != 0:
            raise HarnessError(f"{phase} failed with exit code {result.exit_code}")

    def _prepare_workspace(self) -> None:
        checkpoints = self._load_checkpoints()
        if self.resume and checkpoints.get("workspace_ready") and self.workspace.is_dir():
            self._event("workspace", "resumed", path=str(self.workspace))
            return
        if self.workspace.exists():
            shutil.rmtree(self.workspace)
        container_log = self.run_dir / "commands" / "docker-create.stdout.log"
        created = self._command(
            "docker-create",
            ["docker", "create", "--platform", self.spec.task.image_platform, self.spec.task.image],
            cwd=self.paths.project_root,
            timeout=120,
            stdout=container_log,
        )
        self._require_success("docker-create", created)
        container_id = container_log.read_text(encoding="utf-8").strip().splitlines()[-1]
        try:
            copied = self._command(
                "docker-copy",
                ["docker", "cp", f"{container_id}:/testbed", str(self.workspace)],
                cwd=self.paths.project_root,
                timeout=600,
            )
            self._require_success("docker-copy", copied)
        finally:
            subprocess.run(["docker", "rm", "-f", container_id], capture_output=True, check=False)
        for phase, argv in (
            ("git-reset", ["git", "reset", "--hard", self.spec.task.base_commit]),
            ("git-clean", ["git", "clean", "-fdx"]),
        ):
            result = self._command(phase, argv, cwd=self.workspace, timeout=120)
            self._require_success(phase, result)
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        if head != self.spec.task.base_commit:
            raise HarnessError(f"workspace HEAD mismatch: {head}")
        for document in self.spec.condition.documents:
            source = (self.paths.manifest.parent / document.source).resolve()
            destination = self.workspace / document.destination
            if destination.exists():
                raise HarnessError(f"condition would overwrite base file: {document.destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        self._checkpoint("workspace_ready", {"head": head})
        self._event("workspace", "ready", head=head, condition=self.spec.condition.id)

    def _agent_prompt(self) -> str:
        problem = (
            self.paths.task_repo / "tasks" / self.spec.task.id / "problem_statement.md"
        ).read_text(encoding="utf-8")
        return f"""You are solving one SWE-bench issue in a clean checkout at its base commit.
Use only the problem statement, repository, and condition-specific documentation in this workspace.
Do not access the internet, reference patches, SWE-bench task repositories, evaluator outputs, or
paths outside this repository. Diagnose the root cause, make the smallest correct change, run focused
tests when possible, and leave only the intended solution in the working tree. Do not commit.
The experiment token budget is {self.spec.runtime.token_budget} effective tokens.

Experiment condition: {self.spec.condition.id}

Problem statement:

{problem}
"""

    def _run_agent(self) -> CommandResult:
        result_path = self.run_dir / "agent.command.json"
        if self.resume and result_path.exists() and self.agent_events.exists():
            raw = json.loads(result_path.read_text(encoding="utf-8"))
            result = CommandResult(**raw)
            if result.exit_code == 0 and not result.timed_out and not result.error:
                self._event("agent", "resumed", result=str(result_path))
                return result
            self._event(
                "agent",
                "retrying",
                previous_exit_code=result.exit_code,
                previous_timed_out=result.timed_out,
                previous_error=result.error,
            )
        reasoning = f'model_reasoning_effort="{self.spec.runtime.reasoning_effort}"'
        result = self._command(
            "agent",
            [
                str(self.paths.codex_cli),
                "exec",
                "--cd",
                str(self.workspace),
                "--sandbox",
                "workspace-write",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--json",
                "--model",
                self.spec.runtime.model,
                "--config",
                reasoning,
                "--output-last-message",
                str(self.run_dir / "agent.last-message.txt"),
                self._agent_prompt(),
            ],
            cwd=self.workspace,
            timeout=self.spec.runtime.agent_timeout_seconds,
            stdout=self.agent_events,
            stderr=self.run_dir / "agent.stderr.log",
        )
        atomic_json(result_path, result.as_dict())
        self._checkpoint("agent_finished", result.as_dict())
        return result

    def _capture_patch(self) -> bool:
        if self.resume and self.patch_path.exists():
            self._event("patch", "resumed", path=str(self.patch_path))
            return self.patch_path.stat().st_size > 0
        intent = self._command(
            "git-intent-to-add",
            ["git", "add", "-N", "--all"],
            cwd=self.workspace,
            timeout=120,
        )
        self._require_success("git-intent-to-add", intent)
        argv = ["git", "diff", "--binary", "--", "."]
        argv.extend(f":(exclude){item.destination}" for item in self.spec.condition.documents)
        diff = self._command(
            "git-diff",
            argv,
            cwd=self.workspace,
            timeout=120,
            stdout=self.patch_path,
        )
        self._require_success("git-diff", diff)
        present = self.patch_path.exists() and self.patch_path.stat().st_size > 0
        if present:
            self.store.add_artifact(self.spec.run_id, "agent.patch", self.patch_path)
        self._checkpoint("patch_captured", {"present": present})
        self._event(
            "patch",
            "ready" if present else "empty",
            path=str(self.patch_path),
            bytes=self.patch_path.stat().st_size if self.patch_path.exists() else 0,
            sha256=sha256(self.patch_path) if present else None,
        )
        return present

    def _evaluate(self) -> tuple[dict[str, Any], CommandResult]:
        summary = self.run_dir / "evaluation-summary.json"
        command = self.run_dir / "evaluator.command.json"
        if self.resume and summary.exists() and command.exists():
            self._event("evaluation", "resumed", summary=str(summary))
            return (
                json.loads(summary.read_text(encoding="utf-8")),
                CommandResult(**json.loads(command.read_text(encoding="utf-8"))),
            )
        evaluator = SwebenchEvaluator(self.paths.swebench_cli, self.paths.project_root)
        self._event("evaluation", "started", evaluator="swebench", private_tests=True)
        evaluation, result = evaluator.evaluate(self.spec, self.patch_path, self.run_dir)
        atomic_json(summary, evaluation)
        atomic_json(command, result.as_dict())
        self._checkpoint("evaluation_finished", evaluation)
        self._event("evaluation", "finished", **evaluation)
        return evaluation, result

    def _finalize(
        self,
        outcome: Outcome,
        *,
        agent: CommandResult,
        usage: dict[str, int] | None,
        evaluation: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        result = {
            "run_id": self.spec.run_id,
            "experiment_id": self.spec.experiment_id,
            "task_id": self.spec.task.id,
            "condition_id": self.spec.condition.id,
            "repetition": self.spec.repetition,
            "status": outcome.status,
            "outcome_kind": outcome.kind,
            "resolved": outcome.resolved,
            "duration_seconds": round(time.monotonic() - self.started, 3),
            "agent": agent.as_dict(),
            "token_usage": usage,
            "token_budget": self.spec.runtime.token_budget,
            "evaluation": evaluation,
            "billing_mode": self.spec.runtime.billing_mode,
            "estimated_cost_usd": None,
            "cost_note": (
                "ChatGPT subscription run; API token pricing is not an equivalent billing basis"
                if self.spec.runtime.billing_mode == "chatgpt_subscription"
                else "API price calculation not configured"
            ),
            "error": error,
            "completed_at": utc_now(),
        }
        atomic_json(self.summary_path, result)
        self.store.finish(self.spec.run_id, result)
        self.store.add_artifact(self.spec.run_id, "result.json", self.summary_path)
        self._event("run", outcome.status, outcome_kind=outcome.kind, resolved=outcome.resolved)
        if outcome.status == "completed" and self.workspace.exists():
            shutil.rmtree(self.workspace)
            self._event("cleanup", "finished", workspace_removed=True)
        return result

    def run(self) -> dict[str, Any]:
        existing = self.store.get(self.spec.run_id)
        if existing and not self.resume:
            raise HarnessError(f"run already exists; use --resume: {self.spec.run_id}")
        if existing and self.resume and existing["status"] == "completed":
            return json.loads(existing["result_json"])
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.store.begin(self.spec, self.run_dir)
        self.journal = EventJournal(self.store, self.spec.run_id, self.run_dir / "events.jsonl")
        self._event("run", "started", run_id=self.spec.run_id, resume=self.resume)
        atomic_json(self.run_dir / "run-spec.json", self.spec.model_dump(mode="json"))
        empty_agent = CommandResult([], 1, False, 0.0, "", "")
        agent = empty_agent
        usage: dict[str, int] | None = None
        try:
            self._prepare_workspace()
            agent = self._run_agent()
            usage = parse_token_usage(self.agent_events)
            if agent.error or agent.exit_code == 127 or agent.timed_out or agent.exit_code != 0:
                outcome = classify_outcome(agent, patch_present=False)
                return self._finalize(outcome, agent=agent, usage=usage)
            if usage and usage["budget_tokens"] > self.spec.runtime.token_budget:
                raise HarnessError(
                    f"token budget exceeded: {usage['budget_tokens']} > {self.spec.runtime.token_budget}"
                )
            patch_present = self._capture_patch()
            if not patch_present:
                outcome = classify_outcome(agent, patch_present=False)
                return self._finalize(outcome, agent=agent, usage=usage)
            evaluation, _ = self._evaluate()
            outcome = classify_outcome(
                agent,
                patch_present=True,
                evaluation_valid=bool(evaluation.get("valid")),
                resolved=evaluation.get("resolved"),
            )
            return self._finalize(
                outcome, agent=agent, usage=usage, evaluation=evaluation
            )
        except Exception as exc:
            outcome = Outcome("failed", "infrastructure_failure", None)
            self._event("run", "exception", error=f"{type(exc).__name__}: {exc}")
            return self._finalize(
                outcome,
                agent=agent,
                usage=usage,
                error=f"{type(exc).__name__}: {exc}",
            )
