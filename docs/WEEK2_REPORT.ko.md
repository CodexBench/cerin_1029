# CodexBench Week 2 완료 보고서

## 결론

Week 2의 핵심 사이클인 `run → patch → private test → stored result`를 구현하고 실제 SWE-bench Verified 3과제 × 2조건 × 1회, 총 6회에 적용했다.

- 6/6 실행이 agent 및 evaluator 인프라 오류 없이 완료됐다.
- 4/6 patch가 비공개 테스트를 통과해 resolved됐다.
- 2/6은 evaluator가 정상 동작한 상태에서 테스트가 실패한 정상 실패였다.
- 결과는 실행별 JSONL/JSON과 단일 SQLite database에 함께 저장했다.
- 동일 명세의 완료 run을 `--resume`으로 재호출했을 때 모델이나 evaluator를 다시 실행하지 않고 즉시 기존 결과를 반환했다.

## 요구사항 체크

| 요구사항 | 상태 | 구현/증거 |
|---|---|---|
| Pydantic TaskSpec/ConditionSpec/RunSpec | 완료 | `codexbench/specs.py`, extra field 금지·경로·commit 검증 |
| 원본 commit workspace 생성·reset·clean | 완료 | 공식 task image의 `/testbed` 추출 후 `git reset --hard`, `git clean -fdx` |
| Codex 비대화형 로그·종료·timeout | 완료 | `codex exec --json`, stdout/stderr/last message/exit code/process-group timeout |
| Patch와 private Docker evaluator | 완료 | `git diff --binary`, SWE-bench Verified Docker evaluator |
| JSONL/SQLite 및 idempotent resume | 완료 | 결정적 run ID, append-only events, SQLite PK, `--resume` |
| 4개 결과 경로 자동 테스트 | 완료 | normal success/failure, timeout, installation failure |
| 3과제 × 2조건 × 1회 | 완료 | 6개 stored run |

## 파일럿 조건

- `control`: 추가 저장소 지침 없음
- `combined`: 일반적인 Repository Guide와 Test Guide를 담은 `AGENTS.md`
- Model: `gpt-5.6-sol`
- Reasoning: `high`
- Effective token budget: 50,000
- Agent/evaluator timeout: 각각 1,800초
- Seed: 1029

과제는 모두 Python/SymPy의 SWE-bench Verified task다.

- `sympy__sympy-19637`
- `sympy__sympy-20590`
- `sympy__sympy-20916`

## 실제 결과

| Task | 조건 | 결과 | Resolved | 시간(초) | Effective tokens |
|---|---|---|---:|---:|---:|
| 19637 | control | normal_success | Yes | 92.402 | 18,250 |
| 19637 | combined | normal_success | Yes | 94.608 | 26,017 |
| 20590 | control | normal_success | Yes | 156.569 | 41,135 |
| 20590 | combined | normal_success | Yes | 140.605 | 46,845 |
| 20916 | control | normal_failure | No | 124.380 | 24,028 |
| 20916 | combined | normal_failure | No | 170.689 | 36,036 |

전체 평균:

- Resolved rate: 4/6 = 66.67%
- 평균 wall time: 129.875초
- 평균 effective tokens: 32,051.833

조건별:

| 조건 | Resolved | 평균 시간(초) | 평균 effective tokens |
|---|---:|---:|---:|
| control | 2/3 | 124.450 | 27,804.333 |
| combined | 2/3 | 135.301 | 36,299.333 |

반복이 한 번이고 과제가 세 개뿐이므로 이 차이를 AGENTS.md의 효과로 일반화할 수 없다. Week 2 결과는 연구 결론이 아니라 실행·평가·저장 시스템의 검증 결과다.

## 정상 실패 분석

`sympy__sympy-20916`의 control과 combined 모두 같은 방향의 patch를 만들었다. ASCII 문자에만 적용되던 정규식을 Unicode 문자로 넓혀 `ω0 → ω₀`를 처리했지만, Unicode 숫자 `𝟙`도 숫자 suffix로 잘못 분리했다.

비공개 평가 결과:

- patch 적용: 성공
- evaluator 인프라: 정상
- PASS_TO_PASS `test_requires_partial`: 통과
- FAIL_TO_PASS `test_super_sub`: 실패
- 구체적인 실패: `split_super_sub("w𝟙") == ("w", [], ["𝟙"])` invariant 위반

따라서 이 두 실행은 infrastructure failure가 아니라 `normal_failure`로 저장했다.

## 자동 테스트

총 14개 테스트가 통과했다.

- Pydantic commit/path validation
- 결정적 run ID와 repetition 구분
- SQLite `INSERT OR IGNORE` idempotency
- append-only JSONL/SQLite event sequence
- stdout/stderr/exit code 수집
- process-group timeout
- executable 부재 exit 127
- cached token 제외 budget 계산
- normal success
- normal failure
- timeout
- installation failure

## 오류와 해결

### Editable install 실패

첫 `pip install -e .`에서 setuptools가 `reports`, `experiments`, `instructions`를 top-level package로 오인했다.

- 원인: flat layout에서 자동 package discovery 사용
- 해결: `pyproject.toml`에 `packages = ["codexbench"]` 명시
- 결과: editable install 및 14개 테스트 통과

### Docker 자원 경고

Docker memory가 약 8GB이고 host는 arm64, 평가 image는 amd64다.

- 대응: source image build를 하지 않고 공식 prebuilt image를 `--platform linux/amd64`로 pull
- 결과: 세 image ID와 architecture를 `runs/validation.json`에 기록

## 비용

Codex CLI 인증은 ChatGPT 구독 경로다. ChatGPT 구독 사용량은 API 토큰 가격과 같은 과금 단위가 아니므로 USD 추정치를 만들지 않았다.

- `estimated_cost_usd`: `null`
- 대신 기록: raw input, cached input, uncached input, output, reasoning output, effective tokens, wall time

향후 API 인증 경로를 사용할 경우 모델·날짜가 고정된 가격표를 별도 입력으로 받아 비용을 계산해야 한다.

## 완료 게이트

로컬 환경에서는 문서화된 명령으로 전체 사이클과 `--resume` 재호출을 재현했다. 저장소에는 설치, validate, 단일 run, 전체 matrix, report 명령이 포함된다.

판정은 **PASS WITH PORTABILITY AUDIT PENDING**이다. 다른 사람의 물리적 노트북에서 README만 보고 실행하는 최종 외부 재현성 검사는 아직 수행하지 않았으므로, 해당 검증은 팀원의 clone-and-run으로 완료해야 한다.

## 공식 Codex 동작 근거

공식 OpenAI 문서의 eval 예시에 따라 `codex exec --json`을 사용해 stdout JSONL을 저장하고 deterministic check가 가능한 trace로 취급했다. 현재 설치된 Codex CLI 0.152.1의 `exec --help`도 JSONL, sandbox, output-last-message 및 resume 명령을 제공함을 확인했다.

