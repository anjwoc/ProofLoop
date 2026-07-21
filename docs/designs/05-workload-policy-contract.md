# T0–T3 Workload Policy Contract

상태: `DRAFT`  
주 설계: Claude Opus  
독립 리뷰: GPT-5.6 Sol 대기

## 1. 문제

현재 `strategy.py`의 `classify_request()`와 `reclassify_after_diff()`가 T0-T3 분류를 수행하지만
정책이 코드에 암묵적으로 존재한다. 분류 기준, 재분류 조건, direct lane 진입 조건, tier별 역할 활성화
규칙을 설계 계약으로 명문화해야 한다.

## 2. 현재 구현 사실

- `classify_request(text, override?, repository_signals?)` → `StrategyDecision`
- 전략: `REPOSITORY_ANALYSIS`, `HIGH_RISK_ENGINEERING`, `DIRECT_VERIFIED_CHANGE`, `PLANNED_IMPLEMENTATION`
- 점수: `risk` (0/3), `complexity` (0/1/2), `uncertainty` (0/2)
- Tier 결정: 점수 합계와 정규식 기반
- `reclassify_after_diff()`: 첫 diff 후 critical path, cross-cutting, scope 확대로 tier 상승만 허용
- `_apply_repository_signals()`: public contract 변경 등 repository fact로 T2로 승격

## 3. 불변 조건

1. Tier는 `T0` < `T1` < `T2` < `T3` 단조 순서이며 재분류는 상승만 허용한다.
2. T0/T1은 강한 모델 호출 없이 결정론적으로 실행한다.
3. T2는 blocking ambiguity 또는 design risk가 있을 때만 강한 모델 proposal을 요청한다.
4. T3는 항상 explorer, planner, reviewer를 활성화한다.
5. 분류는 request text, repository signals, override만 입력으로 받는다. 모델 출력에 의존하지 않는다.
6. Tier 하향은 금지한다. 오분류 의심 시 `TIER_OVERRIDE_REQUESTED`로 사용자에게 반환한다.
7. 재분류 시점은 first diff 이후 한 번이다. 반복 재분류는 하지 않는다.

## 4. Tier 정의

### T0 — Direct Verified Change

- 조건: bounded local change, 500자 미만, `risk + complexity + uncertainty ≤ 1`
- 역할: implementer만, planner/reviewer/explorer 없음
- 정제: 결정론적, 강한 모델 미호출
- direct lane: scope가 명시적이고 hard gate 없으며 단일 파일 변경 예상

### T1 — Planned Implementation

- 조건: mutation 있지만 high-risk/complex/uncertain 아님, `1 < score_sum < 4`
- 역할: implementer + 필요 시 planner
- 정제: 결정론적, 강한 모델 미호출
- reviewer: T1에서는 optional (complexity ≥ 2이면 T2로 승격)

### T2 — Deep Planning

- 조건: `complexity ≥ 2` 또는 `uncertainty ≥ 2` 또는 `score_sum ≥ 4` 또는 repository signal 승격
- 역할: planner + implementer + reviewer + optional explorer
- 정제: blocking ambiguity 시 강한 모델 proposal 요청 가능
- repository signal 승격: public contract 변경, 새 dependency, test-coverage 영향

### T3 — High Risk Engineering

- 조건: `risk ≥ 3` 또는 hard gate (security, migration, deploy, greenfield)
- 역할: explorer + planner + implementer + reviewer 전부
- 정제: 강한 모델 proposal 필수

## 5. Direct Lane 기준

Direct lane (`DIRECT_VERIFIED_CHANGE`)은 다음을 모두 만족할 때 진입한다:

1. Request가 500자 미만
2. `_DIRECT` 패턴 매치 (fix, rename, typo, format 등)
3. `_HIGH_RISK` 패턴 미매치
4. `_MUTATION` 패턴 미매치 또는 `_ANALYSIS_ONLY` 미매치
5. Hard gate 없음

First diff 재분류에서 direct lane이 취소되면 T1 이상으로만 상승한다.

## 6. 재분류 규칙

`reclassify_after_diff(decision, changed_paths)`:

| 조건 | 결과 |
|---|---|
| Critical path (auth, payment, migration, security 등) | → T3 |
| Cross-cutting (≥3 root dirs 또는 ≥4 files) 이고 T0/T1 | → T2 |
| Scope 확대 (≥2 files) 이고 T0 | → T1 |
| 그 외 | tier 유지 |

재분류 후 역할 활성화는 새 tier에 따라 결정한다. 재분류는 한 번만 수행하며
결과를 `reclassifiedTier`, `reclassificationGate`, `reclassifiedAt`로 기록한다.

## 7. Repository Signal 승격

`_apply_repository_signals(decision, signals)`:

| Signal | 승격 |
|---|---|
| `hasPublicContractChange` | T2 이상 |
| `hasNewDependency` | T2 이상 |
| `crossCuttingRoots ≥ 3` | T2 이상 |
| `hasSecurityAnnotation` | T3 |

Signal은 repository context에서 결정론적으로 추출한다. 모델이 signal을 만들지 않는다.

## 8. Telemetry 계약

Tier별 다음 지표를 기록하되 이 설계에서 수집 구현은 하지 않는다 (G-10에서 구현):

- 분류된 tier와 재분류 tier
- 역할별 token 소비
- 역할별 wall-time
- 최종 quality verdict (proof graph에서)
- 오분류 의심 flag (사용자 override 또는 reviewer finding)

## 9. T2 Refinement 생략 조건

H-01 리뷰에서 확정된 조건을 반복한다. T2에서 강한 모델 proposal을 생략하는 조건:

- risk, uncertainty, hard gate, blocking question이 모두 0
- acceptance가 explicit
- public contract, persistent state, critical path가 아님
- repository evidence가 현재 baseline에 고정

이 조건을 모두 만족하면 T2이지만 T1과 동일한 결정론적 경로로 실행한다.

## 10. 구현 슬라이스

1. `strategy.py` 기존 코드는 변경하지 않는다 (이미 테스트 통과)
2. G-03 reconciler가 이 정책을 참조해 tier별 정제 경로를 선택한다
3. G-10에서 telemetry 수집기를 구현한다

## 11. Acceptance Tests

- T0: 500자 미만 fix 요청 → `DIRECT_VERIFIED_CHANGE`, planner=false, reviewer=false
- T1: 일반 mutation → `PLANNED_IMPLEMENTATION`, tier=T1
- T2: complex 또는 uncertain → tier=T2, planner=true, reviewer=true
- T3: security/migration → tier=T3, explorer=true
- 재분류: T0 → T1 (scope 확대), T1 → T2 (cross-cutting), any → T3 (critical path)
- 재분류 하향 금지
- repository signal: public contract → T2 이상
- override: 지원, 유효하지 않으면 ValueError

## 12. 설계 provenance

- 현재 `strategy.py` 코드 기반 역공학 + H-01 리뷰에서 확정된 T2 skip 조건 통합
- 기존 `test_strategy.py` 17 tests 전부 통과 상태에서 작성
