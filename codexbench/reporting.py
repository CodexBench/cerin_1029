from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from codexbench.specs import ExperimentSpec
from codexbench.store import ResultStore, utc_now


def _average(values: list[float | int | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return round(statistics.mean(clean), 3) if clean else None


def generate_report(
    experiment: ExperimentSpec,
    store: ResultStore,
    output_dir: Path,
) -> dict[str, Any]:
    rows = store.experiment_runs(experiment.experiment_id)
    expected = len(experiment.tasks) * len(experiment.conditions) * experiment.repetitions
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["condition_id"]].append(row)

    def aggregate(items: list[dict[str, Any]]) -> dict[str, Any]:
        completed = [item for item in items if item["status"] == "completed"]
        resolved = [item for item in completed if item["resolved"] == 1]
        return {
            "runs": len(items),
            "completed": len(completed),
            "resolved": len(resolved),
            "resolved_rate": round(len(resolved) / len(completed), 4) if completed else None,
            "average_duration_seconds": _average([item["duration_seconds"] for item in items]),
            "average_budget_tokens": _average([item["budget_tokens"] for item in items]),
            "average_estimated_cost_usd": _average(
                [item["estimated_cost_usd"] for item in items]
            ),
            "outcomes": {
                kind: sum(1 for item in items if item["outcome_kind"] == kind)
                for kind in sorted({item["outcome_kind"] for item in items if item["outcome_kind"]})
            },
        }

    report = {
        "generated_at": utc_now(),
        "experiment_id": experiment.experiment_id,
        "expected_runs": expected,
        "stored_runs": len(rows),
        "complete_matrix": len(rows) == expected and all(row["status"] == "completed" for row in rows),
        "billing_mode": experiment.runtime.billing_mode,
        "cost_note": (
            "Monetary cost is N/A because ChatGPT subscription usage is not equivalent to API token pricing."
            if experiment.runtime.billing_mode == "chatgpt_subscription"
            else "API cost needs a versioned price table."
        ),
        "overall": aggregate(rows),
        "by_condition": {key: aggregate(value) for key, value in sorted(groups.items())},
        "runs": [
            {
                "run_id": row["run_id"],
                "task_id": row["task_id"],
                "condition_id": row["condition_id"],
                "status": row["status"],
                "outcome_kind": row["outcome_kind"],
                "resolved": None if row["resolved"] is None else bool(row["resolved"]),
                "duration_seconds": row["duration_seconds"],
                "budget_tokens": row["budget_tokens"],
                "run_dir": row["run_dir"],
            }
            for row in rows
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "week2-summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# Week 2 파일럿 결과",
        "",
        f"- Experiment: `{experiment.experiment_id}`",
        f"- 실행: `{len(rows)}/{expected}`",
        f"- 완료 matrix: `{report['complete_matrix']}`",
        f"- 과금 경로: `{experiment.runtime.billing_mode}`",
        f"- 금전 비용: `N/A` — {report['cost_note']}",
        "",
        "## 조건별 집계",
        "",
        "| 조건 | 실행 | 완료 | Resolved | 성공률 | 평균 시간(초) | 평균 effective tokens |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for condition, values in report["by_condition"].items():
        lines.append(
            f"| {condition} | {values['runs']} | {values['completed']} | {values['resolved']} | "
            f"{values['resolved_rate']} | {values['average_duration_seconds']} | "
            f"{values['average_budget_tokens']} |"
        )
    lines.extend(
        [
            "",
            "## 실행별 결과",
            "",
            "| Task | 조건 | 결과 | Resolved | 시간(초) | effective tokens |",
            "|---|---|---|---:|---:|---:|",
        ]
    )
    for row in report["runs"]:
        lines.append(
            f"| {row['task_id']} | {row['condition_id']} | {row['outcome_kind']} | "
            f"{row['resolved']} | {row['duration_seconds']} | {row['budget_tokens']} |"
        )
    (output_dir / "week2-summary.ko.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report

