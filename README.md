# cerin_1029 — CodexBench Week 2

Codex CLI가 SWE-bench 과제 하나를 해결하고, 생성한 patch를 agent가 볼 수 없는 Docker 평가기에서 채점한 뒤 JSONL과 SQLite로 저장하는 재현 가능한 실행기입니다.

이번 Week 2 범위는 다음 한 사이클입니다.

```text
validated RunSpec
  → clean base-commit workspace
  → codex exec JSONL
  → agent.patch
  → private SWE-bench Docker tests
  → JSON result + SQLite row
```

## 구현 결과

- Pydantic `TaskSpec`, `ConditionSpec`, `RunSpec`
- base commit에서 Docker workspace 생성·reset·clean
- Codex stdout JSONL, stderr, 마지막 메시지, 종료 코드, timeout 수집
- agent patch 추출 및 SWE-bench Verified 비공개 평가
- append-only event JSONL과 SQLite 결과 저장
- 결정적 run ID와 하네스 수준 `--resume`
- 성공·정상 실패·timeout·설치 실패 자동 테스트
- 3과제 × 2조건 × 1회 실제 파일럿 6회

실제 결과는 [Week 2 보고서](docs/WEEK2_REPORT.ko.md)와 [자동 집계](reports/week2-summary.ko.md)에서 확인할 수 있습니다.

## 요구사항

- Python 3.11 이상
- Git
- Docker Desktop 또는 호환 Docker daemon
- Codex CLI 인증 완료
- SWE-bench CLI
- `swe-bench-tasks` 저장소

평가 image는 `linux/amd64`입니다. arm64 Mac에서는 Docker emulation을 사용하며, 공식 prebuilt image를 사용해야 합니다.

## 새 환경에서 준비

```bash
git clone git@github.com:CodexBench/cerin_1029.git
cd cerin_1029

python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pip install swebench

git clone https://github.com/SWE-bench/swe-bench-tasks.git

codex --version
docker info
```

Codex 또는 SWE-bench가 다른 위치에 있다면 다음 환경 변수로 경로를 지정할 수 있습니다.

```bash
export CODEXBENCH_CODEX_CLI=/absolute/path/to/codex
export CODEXBENCH_SWEBENCH_CLI=/absolute/path/to/swebench
export CODEXBENCH_TASK_REPO=/absolute/path/to/swe-bench-tasks
```

## 명세와 환경 검증

Pydantic 명세, task metadata, CLI, Docker daemon과 평가 image를 확인합니다.

```bash
.venv/bin/codexbench validate experiments/week2.yaml --pull-images
```

## 한 과제 실행

```bash
.venv/bin/codexbench run experiments/week2.yaml \
  --task sympy__sympy-20590 \
  --condition control \
  --repetition 1
```

동일 명세의 결정적 run ID가 이미 있으면 중복 실행을 거부합니다. 완료 결과를 재사용하거나 중단된 단계를 이어가려면 `--resume`을 사용합니다.

```bash
.venv/bin/codexbench run experiments/week2.yaml \
  --task sympy__sympy-20590 \
  --condition control \
  --repetition 1 \
  --resume
```

`--resume`은 조건 간 Codex 대화를 재사용하지 않습니다. 동일 run의 성공한 agent/patch/evaluation 단계만 재사용하므로 실험 컨텍스트가 섞이지 않습니다.

## 6회 파일럿과 보고서

```bash
.venv/bin/codexbench run-all experiments/week2.yaml --resume
.venv/bin/codexbench report experiments/week2.yaml --output reports
```

실행 순서는 manifest의 seed로 고정해 섞습니다. 각 실행은 다음 경로에 저장됩니다.

```text
runs/<deterministic-run-id>/
├── run-spec.json
├── events.jsonl
├── agent.events.jsonl
├── agent.stderr.log
├── agent.last-message.txt
├── agent.patch
├── evaluation-summary.json
├── evaluation/
└── result.json
```

SQLite 원본은 `runs/results.sqlite3`에 저장됩니다. 공개 가능한 핵심 실행 아티팩트는 `results/week2/`에 별도로 내보냈습니다.

## 테스트

```bash
.venv/bin/pytest
```

자동 테스트는 Pydantic 검증, 결정적 run ID, append-only event 순서, SQLite idempotency, stdout/stderr·종료 코드 수집, timeout process-group 종료, 토큰 계산과 다음 네 결과 경로를 검사합니다.

- `normal_success`
- `normal_failure`
- `timeout`
- `installation_failure`

## 비용 해석

이 파일럿은 ChatGPT 구독으로 인증된 Codex CLI를 사용했습니다. 따라서 API 토큰 가격을 곱한 USD 값은 실제 청구 비용과 동등하지 않아 `estimated_cost_usd=null`로 저장합니다. 대신 실행 시간과 raw/cached/uncached/output/effective token을 모두 기록합니다.

## 보안 및 격리 한계

Agent는 clean workspace의 issue와 조건 문서만 받으며 Gold patch와 evaluator 결과는 agent 실행 후 생성됩니다. 비공개 테스트는 SWE-bench Docker evaluator만 접근합니다. 다만 이 로컬 하네스는 별도 OS 사용자나 VM에 의한 완전한 read-deny 경계는 아닙니다. 엄격한 보안 실험에는 condition별 격리 host가 필요합니다.

