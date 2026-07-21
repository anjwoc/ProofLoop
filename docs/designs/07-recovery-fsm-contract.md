# Recovery FSM 확장 Contract

상태: `DRAFT_BY_REVIEWER` (Sol이 주 설계자이나 Opus가 초안 작성, Sol 재작성 필요)  
주 설계: GPT-5.6 Sol  
독립 리뷰: Claude Opus

## 1. 문제

현재 recovery는 `decide_next()`의 action enum과 orchestrator의 `_activate_recovery_protocol()`로
처리된다. Triage → repair → rollback → reverify 상태와 불변식이 명시적 FSM으로 정의되지 않았다.

## 2. 현재 구현 사실

- `decide_next()`: RUN_FAST, RETRY_FAST, RUN_RECOVERY, RETRY_RECOVERY, STOP
- `_activate_recovery_protocol()`: recovery obligation을 proof graph에 추가
- Recovery role: `implementer_recovery` (host별 다른 model route)
- Goal 모드: replan counter로 재시도 제어
- `versioned_singleflight.py`: concurrent execution dedup (live fixture)

## 3. 불변 조건

1. Recovery FSM 상태 전이는 결정론적이다. 같은 입력은 같은 전이를 만든다.
2. 모든 상태에는 bounded timeout이 있다. 무한 대기 상태는 없다.
3. Rollback은 workspace를 baseline으로 복원한다. Partial rollback은 없다.
4. Reverify는 원래 check spec과 동일한 check를 실행한다 (canonical checkSpecHash 일치).
5. Recovery attempt는 failure fingerprint를 입력으로 받는다.
6. 동일 fingerprint 반복 실패는 `UNRECOVERABLE`로 전이한다.

## 4. FSM 상태

```text
NORMAL → TRIAGE → REPAIR → REVERIFY → NORMAL
                                     → TRIAGE (re-enter if new failure)
              → ROLLBACK → REVERIFY → NORMAL
                                    → STOP (unrecoverable)
         → STOP (budget exhausted or unrecoverable)
```

| 상태 | 진입 조건 | 탈출 조건 |
|---|---|---|
| NORMAL | 초기 또는 reverify 성공 | check 실패 |
| TRIAGE | check 실패 감지 | repair 또는 rollback 결정 |
| REPAIR | triage에서 수리 가능 판정 | repair 완료 (성공/실패) |
| ROLLBACK | repair 실패 또는 triage에서 rollback 결정 | baseline 복원 완료 |
| REVERIFY | repair/rollback 후 | check 재실행 결과 |
| STOP | budget 소진 또는 unrecoverable | terminal |

## 5. Triage 판정

Triage는 failure fingerprint를 분석하여 다음 중 하나를 결정한다:

- `REPAIR`: 수리 가능한 실패 (test failure, lint error, type error)
- `ROLLBACK`: 수리 불가능한 실패 (corrupt state, missing baseline)
- `STOP`: 예산 소진 또는 반복 실패

## 6. 구현 슬라이스

1. G-11: fingerprint별 bounded transition test
2. G-12: goal resume/cancel/crash recovery

## 7. 설계 provenance

- 현재 `orchestrator.py`, `attempts.py` 코드 기반
- 이 초안은 Opus가 작성했으며 Sol이 주 설계자로서 재작성·보완해야 한다
