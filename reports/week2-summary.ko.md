# Week 2 파일럿 결과

- Experiment: `week2-pilot-3x2`
- 실행: `6/6`
- 완료 matrix: `True`
- 과금 경로: `chatgpt_subscription`
- 금전 비용: `N/A` — Monetary cost is N/A because ChatGPT subscription usage is not equivalent to API token pricing.

## 조건별 집계

| 조건 | 실행 | 완료 | Resolved | 성공률 | 평균 시간(초) | 평균 effective tokens |
|---|---:|---:|---:|---:|---:|---:|
| combined | 3 | 3 | 2 | 0.6667 | 135.301 | 36299.333 |
| control | 3 | 3 | 2 | 0.6667 | 124.45 | 27804.333 |

## 실행별 결과

| Task | 조건 | 결과 | Resolved | 시간(초) | effective tokens |
|---|---|---|---:|---:|---:|
| sympy__sympy-19637 | combined | normal_success | True | 94.608 | 26017 |
| sympy__sympy-19637 | control | normal_success | True | 92.402 | 18250 |
| sympy__sympy-20590 | combined | normal_success | True | 140.605 | 46845 |
| sympy__sympy-20590 | control | normal_success | True | 156.569 | 41135 |
| sympy__sympy-20916 | combined | normal_failure | False | 170.689 | 36036 |
| sympy__sympy-20916 | control | normal_failure | False | 124.38 | 24028 |
