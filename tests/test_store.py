import json
from pathlib import Path

from codexbench.store import EventJournal, ResultStore


def test_store_and_journal_are_idempotent(tmp_path: Path, run_spec) -> None:
    store = ResultStore(tmp_path / "results.sqlite3")
    run_dir = tmp_path / "run"
    try:
        assert store.begin(run_spec, run_dir) is True
        assert store.begin(run_spec, run_dir) is False
        journal = EventJournal(store, run_spec.run_id, run_dir / "events.jsonl")
        journal.write("run", "started", value=1)
        journal.write("run", "finished", value=2)
        records = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
        assert [record["sequence"] for record in records] == [1, 2]
        assert store.next_sequence(run_spec.run_id) == 3
    finally:
        store.close()


def test_completed_result_is_stored(tmp_path: Path, run_spec) -> None:
    store = ResultStore(tmp_path / "results.sqlite3")
    try:
        store.begin(run_spec, tmp_path / "run")
        store.finish(
            run_spec.run_id,
            {
                "status": "completed",
                "outcome_kind": "normal_success",
                "resolved": True,
                "duration_seconds": 2.5,
                "token_usage": {"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 3, "budget_tokens": 9},
                "estimated_cost_usd": None,
            },
        )
        row = store.get(run_spec.run_id)
        assert row["status"] == "completed"
        assert row["resolved"] == 1
        assert row["budget_tokens"] == 9
    finally:
        store.close()

