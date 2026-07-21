# Benchmark Methodology Contract

상태: `DRAFT_BY_REVIEWER` (Sol이 주 설계자이나 Opus가 초안 작성, Sol 재작성 필요)  
주 설계: GPT-5.6 Sol  
독립 리뷰: Claude Opus

## 1. 문제

ProofLoop의 효율과 품질 주장은 공정한 benchmark로 뒷받침돼야 한다. 현재 `swe_skills_bench.py`에
task pinning과 domain coverage 검사가 있지만 6-arm 비교, 통계적 비열등성, usage coverage 계산은
구현되지 않았다.

## 2. 현재 구현 사실

- `swe_skills_bench.py`: pinned task import, domain coverage (backend/frontend/devops), preflight CLI
- `benchmark.py`: 6-arm dry-run runner, paired key 기반 비교, timeout/partial failure placeholder
- `tokscale.py`: session 별 token reconciliation, cost 계산

## 3. 불변 조건

1. 품질 비열등성(non-inferiority)을 먼저 통과한 뒤에만 효율 비교를 보고한다.
2. 6-arm 비교: ProofLoop(3 host) vs Vanilla(3 host), 동일 task set, 동일 순서.
3. Paired trial: 각 task는 모든 arm에서 실행하며 paired key로 연결한다.
4. 최소 trial 수: SWE 30, ReservationFlow 5, Domain 90 (per pack).
5. Usage coverage: 보고하는 token 효율의 분모에 모든 invocation이 포함돼야 한다 (100%).
6. Docker evaluator: verifier는 read-only, hash 불변, clean container에서 실행한다.
7. Resume: 중단된 benchmark는 완료된 trial을 보존하고 이어서 실행한다.
8. Partial failure: 한 arm이 실패해도 다른 arm은 계속 실행한다. 비교는 paired complete만 사용.

## 4. 통계 방법

- Bootstrap 95% CI for quality pass rate difference
- Non-inferiority margin δ = 5% (ProofLoop quality ≥ vanilla - 5%)
- Token efficiency: median ratio with bootstrap CI
- Wall-time: median ratio (참고용, 주장 근거 아님)

## 5. 6-Arm 구조

| Arm | Host | Controller |
|---|---|---|
| PL-Claude | Claude Code | ProofLoop |
| PL-Codex | Codex | ProofLoop |
| PL-Antigravity | Antigravity | ProofLoop |
| Van-Claude | Claude Code | Vanilla |
| Van-Codex | Codex | Vanilla |
| Van-Antigravity | Antigravity | Vanilla |

## 6. 구현 슬라이스

1. G-07: Docker evaluator (read-only verifier)
2. G-08: 6-arm runner 보강 (resume, paired key, timeout)
3. G-09: ReservationFlow 반복 benchmark

## 7. 설계 provenance

- 현재 `benchmark.py`, `swe_skills_bench.py`, `tokscale.py` 기반
- 이 초안은 Opus가 작성했으며 Sol이 주 설계자로서 재작성·보완해야 한다
