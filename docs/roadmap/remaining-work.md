# ProofLoop 남은 작업 로드맵

상태 기준일: 2026-07-21  
대상 버전: `v0.4.0-alpha` 이후

이 문서는 ProofLoop가 alpha를 벗어나기 위해 남은 설계, 구현, 실측, 배포 작업의 단일 백로그다.
작업은 모델 이름이 아니라 책임 성격으로 분리한다.

- **강한 판단 모델**: Claude Opus를 주 설계자로 사용하고 GPT-5.6 Sol을 독립 설계·게이트 리뷰에 사용한다.
- **구현 모델**: Gemini 3.1 Pro를 확정된 계약 아래의 구현 계획, 코드 작성, 반복 수정에 사용한다.
- **결정론적 Core**: 테스트, diff, artifact, usage, benchmark, release 판정을 소유한다.

모델 호출이 실패하거나 실제 resolved model을 관측하지 못하면 해당 모델이 작업했다고 기록하지 않는다.

## 완료 상태

- `[ ]` 시작 전
- `[~]` 설계 또는 구현 진행 중
- `[x]` 구현과 요구 증거 완료
- `[!]` 외부 권한 또는 환경으로 차단

## A. 강한 판단 모델 우선 설계

| ID | 상태 | 설계 주제 | 주 설계 | 독립 리뷰 | 완료 산출물 |
| --- | --- | --- | --- | --- | --- |
| H-01 | `[~]` | Prompt Refinement Contract | Claude Opus | GPT-5.6 Sol | `FIXES_APPLIED_PENDING_REVIEW`; S1 완료, S5 구현 가능 |
| H-02 | `[~]` | Live Evidence Contract | Claude Opus | GPT-5.6 Sol | `FIXES_APPLIED_PENDING_REVIEW`; S1 구현 완료 (G-18) |
| H-03 | `[~]` | Host Capability Contract | Claude Opus | GPT-5.6 Sol | `FIXES_APPLIED_PENDING_REVIEW`; S1 구현 완료 (G-19) |
| H-04 | `[~]` | Benchmark Methodology | GPT-5.6 Sol | Claude Opus | `DRAFT_BY_REVIEWER`; Sol 재작성 필요 |
| H-05 | `[~]` | T0–T3 Workload Policy | Claude Opus | GPT-5.6 Sol | `DRAFT`; Sol 리뷰 대기 |
| H-06 | `[~]` | Escalation Policy | Claude Opus | GPT-5.6 Sol | `DRAFT`; Sol 리뷰 대기 |
| H-07 | `[~]` | Recovery FSM 확장 | GPT-5.6 Sol | Claude Opus | `DRAFT_BY_REVIEWER`; Sol 재작성 필요 |
| H-08 | `[~]` | Domain Pack Contract | Claude Opus | GPT-5.6 Sol | `DRAFT`; Sol 리뷰 대기 |
| H-09 | `[~]` | Security and Sandbox Threat Model | GPT-5.6 Sol | Claude Opus | `DRAFT_BY_REVIEWER`; Sol 재작성 필요 |
| H-10 | `[~]` | Product Claim and Release Policy | Claude Opus | GPT-5.6 Sol | `DRAFT`; Sol 리뷰 대기 |

## B. Gemini 3.1 Pro 구현 트랙

각 작업은 관련 H 설계가 승인된 뒤 시작한다. Gemini는 계약을 변경하지 않고, 변경이 필요하면
`DESIGN_CONFLICT`로 반환한다.

| ID | 상태 | 구현 작업 | 선행 설계 | 결정론적 완료 기준 |
| --- | --- | --- | --- | --- |
| G-01 | `[x]` | Execution Brief schema·shadow 합성기 | H-01 승인 Slice 1 | Gemini 3.1 Pro 계획, 10 tests, Ruff, GPT-5.6 Sol code review 완료 |
| G-02 | `[x]` | Role View projector와 prompt envelope | H-01 | 11 tests, Ruff, table-driven 최소 투영 |
| G-03 | `[x]` | T2/T3 refinement proposal reconciler | H-01, H-05 | 확대·발명·unknown 은폐 거절 테스트 |
| G-04 | `[~]` | Claude Code live acceptance harness | H-02, H-03 | harness 구현됨; normal/recovery truth artifact 미생성 |
| G-05 | `[~]` | Codex·Antigravity live harness 보강 | H-02, H-03 | harness 구현됨; 네 live scenario artifact 미생성 |
| G-06 | `[x]` | 실제 model/session/usage 증거 정규화 | H-02, H-03 | requested와 observed 구분, usage coverage 계산 |
| G-07 | `[~]` | Docker official evaluator | H-04, H-09 | 구현됨; clean-container 실측 미완료 |
| G-08 | `[~]` | 6-arm benchmark 실제 runner 보강 | H-04 | 정책 arm·안전한 dry-run wrapper 구현됨; Docker evaluator 포함 실측 paired run 미완료 |
| G-09 | `[~]` | ReservationFlow 반복 benchmark | H-04 | fixture와 90-trial dry-run schedule 생성 확인; 최소 5 paired repetition 미실행 |
| G-10 | `[x]` | Workload telemetry | H-05, H-06 | T0-T3 tier별 token/wall-time/reclassification 기록 |
| G-11 | `[x]` | Fingerprint 기반 recovery transition bounds | H-06, H-07 | 동일 fingerprint 반복 실패시 UNRECOVERABLE |
| G-12 | `[x]` | Goal resume/cancel과 crash recovery | H-06, H-07 | 재시작 시 이전 시도와 truth artifact 복원 |
| G-13 | `[~]` | 90 paired trial runner (pack 평가기) | H-08 | runner 구현됨; 90회 교차 실행과 scorecard 미생성 |
| G-14 | `[x]` | Domain 외부 trigger set | H-08 | user request keywords, active file patterns |
| G-15 | `[x]` | Clean install isolation verification | H-03, H-09 | clean directory에서 의존성 누락 없는지 검증 |
| G-16 | `[x]` | CI artifact integrity report | H-02, H-09, H-10 | release-check.py에서 artifact hash 검증 추가 |
| G-17 | `[x]` | CLI log realtime redaction | H-02, H-09 | stream 및 stdout에 출력되는 secret 동적 마스킹 |
| G-18 | `[x]` | L1 live-evidence bundle validator | H-02 승인 Slice 1 | 21 tests, Ruff, 325 LOC |
| G-19 | `[x]` | capability shadow validator/evaluator | H-03 승인 Slice 1 | 21 tests + 7 subtests, Ruff, 459 LOC |

## C. 모델이 아닌 자동화가 소유할 작업

다음 판정은 모델 출력으로 대체하지 않는다.

- 공식 테스트 exit code와 test count
- protected fixture와 verifier hash
- changed files, dependency, LOC budget
- artifact schema와 provenance hash
- model evidence source와 session identity
- token usage coverage와 cost coverage
- benchmark repetition과 paired trial completeness
- bootstrap confidence interval과 quality non-inferiority
- retry, recovery, time, token budget
- release gate와 domain pack 승격 조건

## D. 인증 E2E 및 실측

| ID | 상태 | 시나리오 | 요구 증거 |
| --- | --- | --- | --- |
| E-01 | `[~]` | Codex normal | 실제 session, observed model, checks, truth, usage |
| E-02 | `[~]` | Codex recovery | 실제 첫 실패, fingerprint, recovery model, 재검증 |
| E-03 | `[~]` | Claude normal | 실제 session, observed model, checks, truth, usage |
| E-04 | `[~]` | Claude recovery | 실제 실패·복구 artifact |
| E-05 | `[~]` | Antigravity normal | role-isolated session과 capability downgrade 명시 |
| E-06 | `[~]` | Antigravity recovery | 실제 bounded recovery 또는 지원 불가의 정직한 판정 |
| E-07 | `[~]` | Domain behavior | 5개 pack, 90 paired trial |
| E-08 | `[~]` | SWE 6-arm efficacy | dry-run이 아닌 전체 trial과 Docker evaluator |
| E-09 | `[~]` | ReservationFlow | greenfield 프로젝트 최소 5 paired repetition |

## E. 외부 배포 게이트

| ID | 상태 | 작업 | 완료 기준 |
| --- | --- | --- | --- |
| R-01 | `[x]` | License / Dependencies 점검 | OSS 라이선스 충돌 없음, README에 명시 |
| R-02 | `[x]` | Roadmap / Documentation 정리 | Alpha 릴리즈 상태로 README 및 roadmap 업데이트 |
| R-03 | `[x]` | H-10 Product Claim 리뷰 | 증거가 없는 수치나 주장이 포함되지 않도록 검수 |
| R-04 | `[x]` | CHANGELOG 작성 | Alpha 버전 변경사항 및 주요 제약사항 명시 |
| R-05 | `[~]` | Final Release Check (L5) | deterministic lint/type/test와 live evidence 모두 통과해야 함 |
| R-06 | `[~]` | 공개 scorecard | 실측 재현 명령·raw artifact·제한사항 공개 필요 |

## 실행 순서

1. H-01 설계 승인 후 G-01/G-02를 구현한다.
2. H-02와 H-03을 차례로 설계하고 G-04/G-05/G-06을 구현한다.
3. E-01부터 E-06까지 인증 live evidence를 확보한다.
4. H-04와 H-09를 승인한 뒤 G-07/G-08/G-09를 구현·실행한다.
5. 실측 결과로 H-05/H-06/H-07을 확정하고 G-10/G-11/G-12를 구현한다.
6. H-08과 G-13/G-14를 통해 검증된 pack만 승격한다.
7. H-10을 마지막 주장 게이트로 사용하고 R-01부터 R-06을 닫는다.

## 2026-07-21 검증 기록

- 결정론적 회귀, 패키지 검증, Ruff, 그리고 `mypy proofloop_core`는 통과했다.
- `codex`, `claude`, `agy` 세 CLI의 설치·버전은 확인했지만, 인증 세션을 소모하는 normal/recovery
  실행은 아직 수행하지 않았다.
- ReservationFlow의 Core·Adaptive·Full 정책 및 ablation arms에 대한 dry-run schedule은 90 trials로
  생성됐다. dry-run은 모델 호출·토큰·pass rate를 측정하지 않으므로 효율 주장의 증거가 아니다.
- `scripts/run_benchmarks.sh`는 기본 dry-run이며, 실제 모델 호출은 `--execute`와 명시적인
  baseline model을 요구한다.

## Alpha 종료 조건

다음이 모두 충족되기 전에는 효율 또는 시장 우위를 확정적으로 주장하지 않는다.

- 세 호스트의 지원 범위가 실제 artifact로 확인됨
- 정상과 recovery 경로가 fake host가 아닌 인증 세션에서 재현됨
- benchmark가 품질 비열등성을 먼저 통과함
- 토큰 효율 비교의 usage coverage가 100%임
- 적어도 하나의 domain pack이 E2+ scorecard로 승격됨
- clean CI, 라이선스, 설치·업그레이드 경로가 준비됨
