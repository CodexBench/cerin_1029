import json
from pathlib import Path

from codexbench.runner import parse_token_usage


def test_tokens_exclude_cached_input_from_budget(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 70,
                    "output_tokens": 20,
                    "reasoning_output_tokens": 5,
                },
            }
        )
        + "\n"
    )
    usage = parse_token_usage(path)
    assert usage["uncached_input_tokens"] == 30
    assert usage["budget_tokens"] == 50

