# Live Evidence Contract

상태: `FIXES_APPLIED_PENDING_REVIEW`, H02-S1 구현 완료 (G-18, 21 tests)  
주 설계: Claude Opus, 실제 Claude Code `--model opus` 호출  
독립 리뷰: GPT-5.6 Sol 완료

독립 리뷰 원문과 승인된 Slice 1은
[리뷰 문서](reviews/02-live-evidence-gpt-5.6-sol.md)에 저장한다. L2 이상의 live claim, challenge,
capture, recovery, release aggregation은 아래 필수 교정이 완료되기 전까지 구현하지 않는다.

## 0. 독립 리뷰로 확정된 교정

- Trusted boundary는 acceptance controller, Core validator, versioned release policy뿐이다. host/model,
  workspace, stream, candidate manifest와 orchestrator truth는 모두 untrusted input이다.
- challenge는 provider identity가 아니라 freshness만 보조한다. prompt·environment·workspace에 nonce를
  넣는 설계는 제거한다.
- unsigned persisted bundle은 이후 release에서 L2+ 증거로 재사용할 수 없다. portable claim에는 CI
  attestation 또는 공개키 서명이 필요하다.
- 실제 process graph는 controller → outer host → proofloop-core → per-role host process다. 단일 process
  record로 표현하지 않는다.
- `HOST_OUTPUT`은 generic strong model attestation이 아니다. host-specific parser/version, raw event
  digest, event type, JSON pointer, session identity가 필요하다.
- `ACP_SESSION_CONFIG`는 provider attestation이 아니라 host-acknowledged config다.
- L3는 `modelIdentityObserved`와 `requestedRouteFulfilled`를 분리한다.
- L4는 deterministic check failure recovery만 의미한다. reviewer `FIX_REQUIRED` repair는 별도 claim이다.
- raw stream을 저장한 뒤 redaction하는 방식은 “secret을 저장하지 않음”을 충족하지 않는다.
- run 선택은 spawn 전 run ID set과 종료 후 set difference로 정확히 하나만 고른다. `latest`와 mtime
  선택은 금지한다.
- candidate가 제출한 `bundleHash`, verdict, evidenceLevel, capability는 권위가 없다. validator가
  `candidateDigest`를 계산한다.

## 1. 목적과 위협

이 계약은 fake host, requested model label, 복사된 stale run, 모델이나 러너가 작성한 truth가
“인증된 live proof”로 승격되지 못하게 한다. 결정론적 Core가 원시 artifact를 다시 검증해 최종
증거 수준을 계산한다.

| 위협 | 차단 원칙 |
| --- | --- |
| simulated process를 live로 표기 | simulation은 orchestration mechanics만 증명 |
| requested model을 observed model로 표기 | 강한 provider/host source만 관측 증거로 인정 |
| 과거 성공 run 재사용 | run identity, baseline, capture time, challenge와 artifact hash 검증 |
| runner가 acceptance truth 작성 | runner 결과는 candidate, Core가 최종 report 재산출 |
| recovery role 라벨만 기록 | 실제 deterministic FAIL→수정→동일 check PASS 전이 요구 |

## 2. Evidence level

| 레벨 | 이름 | 지원 가능한 주장 |
| --- | --- | --- |
| L0 | `SIMULATED` | orchestration mechanics와 parser fixture가 동작함 |
| L1 | `DETERMINISTIC` | artifact가 schema와 내부 규칙을 통과함 |
| L2 | `OBSERVED_LOCAL` | 실제 host executable process와 session output이 캡처됨 |
| L3 | `OBSERVED_ROUTED` | requested model과 강하게 관측된 resolved/active model의 관계가 증명됨 |
| L4 | `OBSERVED_RECOVERED` | Core 검증 실패 후 실제 수정과 동일 check 재통과가 증명됨 |

Evidence level은 주장별 상한이다. 부족한 artifact는 가장 높은 완전한 하위 수준으로 강등하며,
simulation은 authenticated claim에 기여하지 않는다.

호스트 capability는 레벨과 별도로 기록한다.

- `PER_ROLE_ROUTING`
- `SESSION_ONLY_ROUTING`
- `ROLE_ISOLATION_ONLY`
- `AUTOMATED_RECOVERY`
- `NO_AUTOMATED_RECOVERY`

예를 들어 Antigravity가 한 session model만 관측할 수 있으면 session model 증거는 만들 수 있지만
per-role cross-model routing을 주장할 수 없다.

## 3. Identity와 provenance

```text
acceptance cycle
  → run identity
  → spawned process record
  → host session
  → ordered invocation records
  → provider stream and model evidence
  → checks, diff, usage and recovery evidence
  → sealed manifest
  → Core validation result
```

필수 identity:

- acceptance cycle ID
- run ID
- host와 scenario
- repository baseline commit와 dirty-state digest
- host executable path와 version evidence
- process start/end와 exit code
- host session ID
- invocation ID, role, attempt, parent invocation
- requested model과 observed model source
- artifact content hashes

시크릿, token, cookie, Authorization header는 저장하지 않는다. 인증 상태는 실제 host/provider stream의
구조화된 성공·실패 evidence로만 추론하며 credential 자체를 증거로 사용하지 않는다.

## 4. Model-routing proof

Observed model은 다음 source만 강한 증거로 인정한다.

- `HOST_RESOLVED`
- `HOST_ACTIVE_MODEL`
- `HOST_OUTPUT`
- `ACP_SESSION_CONFIG`

`CLI_REQUESTED_ONLY`, prompt text, free-form success 문장, 역할 이름은 observed proof가 아니다.

L3 주장에는 다음이 필요하다.

1. invocation과 session identity가 있음
2. requested model이 별도 필드로 있음
3. observed model과 evidence source가 있음
4. trace artifact가 해당 invocation과 연결됨
5. 호스트 capability가 주장 범위를 지원함

requested와 observed가 다르면 실패가 아니라 `routingDivergence`로 기록한다. observed 값이 없으면
최대 L2다.

## 5. Recovery proof

`implementer_recovery`가 존재하는 것만으로 L4가 되지 않는다. 다음 전이를 모두 확인한다.

```text
initial invocation
  → Core deterministic check FAIL
  → stable failure fingerprint
  → later recovery invocation linked to failure
  → non-empty source diff relevant to allowed scope
  → previously failing check executed again
  → same check PASS
  → final diff guard and truth gate PASS
```

필수 조건:

- 실패는 모델 진술이 아니라 실제 command exit와 artifact로 생성됨
- recovery invocation은 다른 invocation ID와 증가한 attempt를 가짐
- failure fingerprint와 recovery input이 연결됨
- recovery 전후 diff가 존재함
- 실패했던 동일 check identity가 재실행됨
- retry/recovery budget 안에서 수행됨
- verifier나 protected fixture가 변경되지 않음

복구 fixture가 의도적으로 실패를 포함하면 injection spec과 fixture hash를 별도 보존한다.

## 6. Candidate bundle

러너가 수집하는 bundle은 검증 전까지 authoritative하지 않다.

```json
{
  "schemaVersion": "1.0",
  "cycleId": "...",
  "runId": "...",
  "host": "codex",
  "scenario": "recovery",
  "baselineCommit": "...",
  "process": {"exitCode": 0, "version": "..."},
  "sessionIds": [],
  "capabilities": [],
  "artifacts": [
    {"path": "model-trace.jsonl", "sha256": "...", "sizeBytes": 0}
  ],
  "sealedAt": "...",
  "bundleHash": "..."
}
```

Core validator는 다음을 다시 계산한다.

- 모든 상대 경로가 bundle root 내부인지
- symlink escape가 없는지
- 파일 hash와 size가 맞는지
- 필수 artifact 누락 여부
- JSON/JSONL schema와 identity chain
- baseline·scenario·host 일치
- model evidence source
- recovery state transition
- secret redaction 검사
- manifest에 없는 예상치 못한 file 처리 정책

`truth-report.json`을 runner가 acceptance summary로 덮어쓰는 현재 동작은 제거 대상이다. 원래
orchestrator report는 별도 이름으로 보존하고 Core validation report와 혼동하지 않는다.

## 7. 호스트별 acceptance matrix

| 호스트 | normal | recovery | routing 경계 |
| --- | --- | --- | --- |
| Codex | L2/L3 bundle | L4 요구 | observed role model이 있을 때만 per-role 주장 |
| Claude Code | 신규 자동 harness | 신규 recovery harness | observed session/role evidence 필요 |
| Antigravity | 실제 process와 session evidence | 지원 범위 내 실제 recovery | 현재 session-only 또는 role-isolation-only 가능성 명시 |

각 시나리오는 `PROVEN`, `UNPROVEN`, `LIVE_FAILED`, `REJECTED`를 구분한다. 호스트가 기능을 지원하지
않는 경우 simulation으로 대체하지 않고 capability-limited `UNPROVEN`으로 남긴다.

## 8. Freshness, replay, tamper

- acceptance cycle은 재사용할 수 없는 challenge를 발급한다.
- challenge, run identity와 capture time은 bundle provenance에 연결한다.
- release check가 허용하는 freshness window를 명시한다.
- 동일 run/bundle/challenge의 중복 제출을 감지한다.
- hash 불일치, path escape, protected artifact 변경, secret scan hit는 `REJECTED`다.
- host crash, auth failure, timeout은 `LIVE_FAILED`로 보존하며 simulated pass로 대체하지 않는다.
- artifact 누락은 `PASS` 기본값이 아니라 `UNPROVEN`이다.

Challenge/controller envelope, host identity와 portable attestation은 별도 후속 설계다. 승인 전에는
L2 이상의 persisted claim을 만들지 않는다.

## 9. Release aggregation

Core는 candidate bundle의 자체 verdict를 신뢰하지 않고 검증 결과를 집계한다.

- deterministic suite와 simulated host fixture는 별도 development health다.
- authenticated model routing은 L3 bundle에서만 증명된다.
- authenticated recovery는 L4 bundle에서만 증명된다.
- host capability가 session-only이면 주장을 해당 범위로 축소한다.
- tamper는 해당 bundle을 hard reject한다.
- missing/partial/live failure는 성공으로 승격하지 않는다.
- 전체 release 조건은 요구 host·scenario matrix를 명시적으로 정의한다.

## 10. 구현 슬라이스

1. candidate manifest schema와 pure Core validator
2. model-routing evidence 판정기
3. recovery transition 판정기
4. live runner capture·redaction·bundle 생성
5. Claude Code normal/recovery harness
6. Codex·Antigravity harness를 동일 contract로 이전
7. release-check aggregation 통합
8. 악성·stale·partial bundle negative fixture

각 slice는 actual host 호출 없이 pure validator fixture부터 개발한다. live runner가 최종 판정 로직을
소유하지 않도록 한다.

## 11. Acceptance tests

- requested model만 있는 bundle은 L3가 되지 않는다.
- simulated fixture는 authenticated claim에 기여하지 않는다.
- recovery role label만 있는 bundle은 L4가 되지 않는다.
- 같은 check의 실제 FAIL→PASS와 linked diff가 있어야 L4가 된다.
- stale/replayed challenge를 거절한다.
- artifact 1 byte 변경을 감지한다.
- path traversal과 symlink escape를 거절한다.
- secret pattern이 발견된 bundle을 거절한다.
- runner가 작성한 final truth를 권위로 사용하지 않는다.
- Claude/Codex/Antigravity capability보다 큰 주장을 거절한다.
- timeout과 auth failure가 simulated success로 바뀌지 않는다.

## 12. Non-goals과 금지 shortcut

- credential 자체를 수집하거나 저장하지 않는다.
- 모델 응답 품질을 이 계약에서 평가하지 않는다.
- requested model 이름을 observed model로 복사하지 않는다.
- latest run directory를 무조건 인증 run으로 선택하지 않는다.
- `implementer_recovery` 문자열만으로 recovery를 증명하지 않는다.
- runner가 Core truth를 덮어쓰지 않는다.
- 누락 artifact를 pass 기본값으로 채우지 않는다.
- 지원하지 않는 host capability를 성공처럼 표현하지 않는다.

## 13. 설계 provenance와 다음 게이트

- 실제 호출: `claude -p --model opus --effort high --permission-mode plan`
- 검증된 현재 구현 사실을 입력으로 제공하고 도구 없이 완료했다.
- 이 문서는 Claude 결과를 현재 파일과 용어에 맞게 편집한 초안이다.

- GPT-5.6 Sol 독립 리뷰는 전체 계약을 `FIX_REQUIRED`로 판정했다.
- 첫 구현은 bundle-relative regular file, hash, size, path collision만 검사하는 pure L1 validator다.
- challenge/controller envelope, capture, recovery chain, release integration은 각각 재설계·재리뷰한다.

