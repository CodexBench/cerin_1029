from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from codexbench.process import CommandResult, run_logged
from codexbench.specs import RunSpec


class EvaluationError(RuntimeError):
    pass


class SwebenchEvaluator:
    def __init__(self, binary: Path, project_root: Path):
        self.binary = binary
        self.project_root = project_root

    def evaluate(self, spec: RunSpec, patch: Path, run_dir: Path) -> tuple[dict[str, Any], CommandResult]:
        predictions = run_dir / "predictions.jsonl"
        predictions.write_text(
            json.dumps(
                {
                    "instance_id": spec.task.id,
                    "model_name_or_path": f"{spec.runtime.model}-{spec.condition.id}",
                    "model_patch": patch.read_text(encoding="utf-8"),
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        evaluator_run_id = f"cb2-{spec.run_id}"
        result = run_logged(
            [
                str(self.binary),
                "eval",
                spec.task.dataset,
                "--instance",
                spec.task.id,
                "--run-id",
                evaluator_run_id,
                "--workers",
                "1",
                "--timeout",
                str(spec.runtime.evaluator_timeout_seconds),
                "--predictions",
                str(predictions),
            ],
            cwd=self.project_root,
            stdout_path=run_dir / "evaluator.stdout.log",
            stderr_path=run_dir / "evaluator.stderr.log",
            timeout_seconds=spec.runtime.evaluator_timeout_seconds + 300,
        )
        source = self.project_root / "logs" / "evaluation" / evaluator_run_id
        destination = run_dir / "evaluation"
        if source.is_dir() and not destination.exists():
            shutil.copytree(source, destination)
        results_path = destination / "results.json"
        if result.exit_code != 0 or not results_path.exists():
            return {
                "valid": False,
                "resolved": None,
                "run_id": evaluator_run_id,
                "error": "evaluator command failed or results.json is missing",
            }, result
        results = json.loads(results_path.read_text(encoding="utf-8"))
        required = {
            "total_instances": 1,
            "submitted_instances": 1,
            "completed_instances": 1,
            "error_instances": 0,
            "infra_failure_instances": 0,
        }
        mismatches = {
            key: {"expected": expected, "actual": results.get(key)}
            for key, expected in required.items()
            if results.get(key) != expected
        }
        return {
            "valid": not mismatches,
            "resolved": results.get("resolved_instances") == 1,
            "run_id": evaluator_run_id,
            "mismatches": mismatches,
            "results": results,
            "artifact": str(destination),
        }, result

