from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from codexbench.specs import RunSpec


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


class ResultStore:
    def __init__(self, database: Path):
        self.database = database
        database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def close(self) -> None:
        self.connection.close()

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                experiment_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                condition_id TEXT NOT NULL,
                repetition INTEGER NOT NULL,
                status TEXT NOT NULL,
                outcome_kind TEXT,
                resolved INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                duration_seconds REAL,
                input_tokens INTEGER,
                cached_input_tokens INTEGER,
                output_tokens INTEGER,
                budget_tokens INTEGER,
                estimated_cost_usd REAL,
                billing_mode TEXT NOT NULL,
                run_dir TEXT NOT NULL,
                result_json TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                sequence INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                phase TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                UNIQUE(run_id, sequence)
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                name TEXT NOT NULL,
                path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                bytes INTEGER NOT NULL,
                PRIMARY KEY(run_id, name)
            );
            CREATE INDEX IF NOT EXISTS idx_runs_experiment
                ON runs(experiment_id, task_id, condition_id);
            """
        )
        self.connection.commit()

    def begin(self, spec: RunSpec, run_dir: Path) -> bool:
        now = utc_now()
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO runs(
                run_id, experiment_id, task_id, condition_id, repetition,
                status, created_at, updated_at, billing_mode, run_dir
            ) VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, ?)
            """,
            (
                spec.run_id,
                spec.experiment_id,
                spec.task.id,
                spec.condition.id,
                spec.repetition,
                now,
                now,
                spec.runtime.billing_mode,
                str(run_dir),
            ),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def get(self, run_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def finish(self, run_id: str, result: dict[str, Any]) -> None:
        usage = result.get("token_usage") or {}
        resolved = result.get("resolved")
        self.connection.execute(
            """
            UPDATE runs SET
                status = ?, outcome_kind = ?, resolved = ?, updated_at = ?,
                duration_seconds = ?, input_tokens = ?, cached_input_tokens = ?,
                output_tokens = ?, budget_tokens = ?, estimated_cost_usd = ?,
                result_json = ?
            WHERE run_id = ?
            """,
            (
                result["status"],
                result["outcome_kind"],
                None if resolved is None else int(resolved),
                utc_now(),
                result.get("duration_seconds"),
                usage.get("input_tokens"),
                usage.get("cached_input_tokens"),
                usage.get("output_tokens"),
                usage.get("budget_tokens"),
                result.get("estimated_cost_usd"),
                json.dumps(result, ensure_ascii=False, sort_keys=True),
                run_id,
            ),
        )
        self.connection.commit()

    def add_event(
        self,
        run_id: str,
        sequence: int,
        phase: str,
        status: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        record = {
            "sequence": sequence,
            "timestamp": utc_now(),
            "phase": phase,
            "status": status,
            "payload": payload,
        }
        self.connection.execute(
            """
            INSERT INTO events(run_id, sequence, timestamp, phase, status, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                sequence,
                record["timestamp"],
                phase,
                status,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        self.connection.execute(
            "UPDATE runs SET updated_at = ? WHERE run_id = ?", (record["timestamp"], run_id)
        )
        self.connection.commit()
        return record

    def next_sequence(self, run_id: str) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS value FROM events WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return int(row["value"])

    def add_artifact(self, run_id: str, name: str, path: Path) -> None:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.connection.execute(
            """
            INSERT OR REPLACE INTO artifacts(run_id, name, path, sha256, bytes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, name, str(path), digest, path.stat().st_size),
        )
        self.connection.commit()

    def experiment_runs(self, experiment_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM runs WHERE experiment_id = ? ORDER BY task_id, condition_id, repetition",
            (experiment_id,),
        ).fetchall()
        return [dict(row) for row in rows]


class EventJournal:
    def __init__(self, store: ResultStore, run_id: str, path: Path):
        self.store = store
        self.run_id = run_id
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.sequence = store.next_sequence(run_id)

    def write(self, phase: str, status: str, **payload: Any) -> dict[str, Any]:
        record = self.store.add_event(
            self.run_id, self.sequence, phase, status, payload
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        self.sequence += 1
        return record

