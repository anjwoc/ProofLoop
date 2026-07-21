# Escalation Policy Contract

상태: `DRAFT`  
주 설계: Claude Opus  
독립 리뷰: GPT-5.6 Sol 대기

## 1. 문제

현재 `decide_next()`와 orchestrator의 recovery loop가 fast retry, recovery, replan, stop 조건을
처리하지만 정책이 코드에 분산되어 있다. 이 계약은 escalation 경로, budget 소진, 종료 조건을
명문화한다.

## 2. 현재 구현 사실

- `decide_next(attempts, max_fast, max_recovery)` → `RUN_FAST` / `RETRY_FAST` / `RUN_RECOVERY` / `RETRY_RECOVERY` / `STOP`
- `max_fast_attempts` 기본 2, `max_recovery_attempts` 기본 1
- `max_replans` 기본 2 (goal 모드)
- `_activate_recovery_protocol()` → recovery obligation을 proof graph에 추가
- reviewer `FIX_REQUIRED` → recovery 재실행
- goal 모드: cycle 기반 탐색, 수렴 후 종료

## 3. 불변 조건

1. Escalation은 단조 상승이다: fast → recovery → replan → stop. 역행하지 않는다.
2. 각 단계의 budget은 유한하며 소진 시 다음 단계로 자동 전이한다.
3. Recovery는 failure fingerprint (check name, error pattern)를 포함해야 한다.
4. Replan은 goal 모드에서만 허용한다. 일반 run에서는 recovery 실패 시 stop한다.
5. Stop은 `BUDGET_EXHAUSTED`, `UNRECOVERABLE`, 또는 `USER_CANCELLED` 사유를 포함한다.
6. 모든 전이는 event로 기록한다. 관측할 수 없는 전이는 없다.
7. Token budget 소진은 hard stop이며 escalation을 bypass하지 않는다.

## 4. Escalation Ladder

```text
RUN_FAST (1st attempt)
  → PASS → done
  → FAIL → RETRY_FAST (if fast budget remaining)
    → PASS → done
    → FAIL → RUN_RECOVERY (if recovery budget > 0)
      → PASS → done
      → FAIL → RETRY_RECOVERY (if recovery budget remaining)
        → PASS → done
        → FAIL → REPLAN (if goal mode and replan budget > 0)
          → new task → RUN_FAST (restart ladder)
        → FAIL → STOP (budget exhausted)
```

## 5. Budget 기본값

| Budget | 기본값 | 최소 | 최대 |
|---|---|---|---|
| `maxFastAttempts` | 2 | 1 | 5 |
| `maxRecoveryAttempts` | 1 | 0 | 3 |
| `maxReplans` | 2 (goal only) | 0 | 5 |
| `tokenBudget` | host 기본값 | — | — |
| `timeoutSeconds` | 300 | 30 | 3600 |

Budget 0은 해당 단계를 건너뛴다 (예: `maxRecoveryAttempts=0` → fast 실패 시 바로 replan 또는 stop).

## 6. Failure Fingerprint

Recovery 진입 시 다음 정보를 수집한다:

- `failedCheckNames`: 실패한 check 이름 목록
- `errorPattern`: stderr/output에서 추출한 에러 패턴 (redacted)
- `failureCount`: 동일 fingerprint 연속 실패 횟수
- `lastAttemptRole`: 마지막 시도 역할

동일 fingerprint로 2회 이상 연속 실패하면 `UNRECOVERABLE`로 stop한다.

## 7. Reviewer FIX_REQUIRED 처리

- Reviewer가 `FIX_REQUIRED`를 반환하면 recovery로 전이한다.
- Recovery budget이 0이면 `FIX_REQUIRED`를 최종 결과로 보고한다.
- `FIX_REQUIRED`에서 recovery 성공 후 재검증한다.

## 8. Goal 모드 Replan

- Fast + recovery 모두 실패 시 goal loop가 replan을 시도한다.
- Replan은 새 task를 생성하고 escalation ladder를 초기화한다.
- `maxReplans` 소진 시 goal이 `BUDGET_EXHAUSTED`로 종료한다.
- Replan 시 이전 attempt의 evidence를 새 task에 전달한다.

## 9. 종료 조건

| 사유 | 설명 |
|---|---|
| `PASS` | 모든 checks 통과, truth gate 충족 |
| `BUDGET_EXHAUSTED` | fast + recovery + replan budget 모두 소진 |
| `UNRECOVERABLE` | 동일 fingerprint 2회 연속 또는 결정론적 불가 판정 |
| `TOKEN_BUDGET_EXCEEDED` | Hard token limit 초과 |
| `TIMEOUT` | 역할별 또는 전체 timeout 초과 |
| `USER_CANCELLED` | 사용자 취소 |
| `ROLE_CANCELLED` | 역할 실행 취소 (외부 interrupt) |

## 10. Token Budget Hard Stop

`adaptive_hard_token_budget`가 설정되면:
- 현재 소비가 budget의 90%에 도달하면 `TOKEN_WARNING` event를 emit한다
- 100%에 도달하면 현재 역할을 즉시 중단하고 `TOKEN_BUDGET_EXCEEDED`로 stop한다
- Recovery나 replan으로 우회하지 않는다

## 11. Acceptance Tests

- fast 2회 실패 → recovery 진입
- recovery 실패 → goal 모드에서 replan, 일반 모드에서 stop
- 동일 fingerprint 2회 연속 → UNRECOVERABLE
- budget 0 단계 건너뛰기
- reviewer FIX_REQUIRED → recovery → 재검증
- token budget 초과 → hard stop
- 모든 전이에서 event 기록 확인

## 12. 구현 슬라이스

1. `decide_next()` 기존 코드는 변경하지 않는다 (이미 테스트 통과)
2. G-11에서 fingerprint 기반 bounded transition을 추가한다
3. G-12에서 goal resume/crash recovery를 추가한다

## 13. 설계 provenance

- 현재 `orchestrator.py`, `attempts.py`, `goal.py` 코드 기반 역공학
- 기존 orchestrator 테스트 22개 통과 상태에서 작성
