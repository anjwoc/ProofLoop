완성된 ProofLoop는 사용자가 어느 Host에서 실행하든 **동일한 요청 계약·실행 전략·검증 기준**으로 동작하고, 진행 상황을 실시간으로 보여주는 형태가 돼.

# 1. 전체 사용자 경험

```text
사용자
  │
  │  "결제 재시도 시 중복 결제가 발생하지 않도록 구현해줘"
  ▼
Codex / Claude Code / AGY CLI
  │
  │  /proofloop 또는 /using proofloop
  ▼
ProofLoop Runtime
  │
  ├─ 요청 해석
  ├─ 저장소 조사
  ├─ 실행 계약 생성
  ├─ 작업 난이도·위험 판단
  ├─ Host·모델·역할 선택
  ├─ 모델별 프롬프트 컴파일
  ├─ 구현 실행
  ├─ 실패 감지 및 제한적 복구
  ├─ 실제 테스트와 Surface 검증
  ├─ 독립 리뷰
  └─ 증거 기반 최종 판정
       │
       ▼
PROVEN / PARTIAL / BLOCKED / FAILED
```

사용자는 긴 프롬프트를 직접 작성하지 않아도 돼.

```text
현재 방식

사용자
→ 상세한 파일 경로 설명
→ 구현 방법 설명
→ 테스트 방법 설명
→ 하지 말아야 할 것 설명
→ 실행
```

완성된 ProofLoop에서는:

```text
사용자
→ 목표만 전달
→ ProofLoop가 저장소를 조사
→ 요청을 실행 계약으로 정제
→ 적합한 방식으로 실행
→ 결과를 증명
```

---

# 2. 대표 시나리오: 결제 중복 처리 방지

사용자가 Codex에서 다음과 같이 입력했다고 가정하자.

```text
/using proofloop 결제 요청이 재시도되더라도 중복 결제가 되지 않도록 구현해줘
```

## 2.1 요청 수신

ProofLoop는 원본 요청을 절대 수정하지 않는 기준점으로 저장한다.

```json
{
  "requestId": "pl-20260721-8f29",
  "rawText": "결제 요청이 재시도되더라도 중복 결제가 되지 않도록 구현해줘",
  "rawHash": "sha256:...",
  "invocationSource": "codex",
  "explicitAuthority": "REPOSITORY_MUTATION"
}
```

CLI에는 다음처럼 보인다.

```text
[00:00.000] Request received
[00:00.012] Authority detected: REPOSITORY_MUTATION
[00:00.013] External deployment permission: NOT GRANTED
[00:00.014] Git remote permission: NOT GRANTED
```

ProofLoop는 `구현해줘`를 다음과 같이 해석한다.

```text
허용:
- 저장소 파일 조사
- 코드 수정
- 테스트 추가 및 실행
- 로컬 검증

허용되지 않음:
- commit
- push
- PR 생성
- 배포
- 실제 결제 시스템 호출
```

---

# 3. IntentGate 동작

```text
Raw Request
  ↓
IntentGate
  ├─ Intent: MUTATE
  ├─ Clarity: GROUNDABLE
  ├─ Authority: REPOSITORY_MUTATION
  └─ Grounding required: YES
```

현재 요청만으로는 다음을 알 수 없다.

```text
- 결제가 어디에서 처리되는가
- idempotency key가 이미 존재하는가
- DB unique constraint가 있는가
- Redis나 Kafka가 사용되는가
- 어떤 테스트 방식이 존재하는가
```

하지만 이 정보는 사용자에게 물을 내용이 아니라 저장소에서 조사할 내용이므로 질문하지 않는다.

```text
[00:00.020] Intent classified: MUTATE
[00:00.021] Clarity: GROUNDABLE
[00:00.022] Repository discovery selected instead of user clarification
```

---

# 4. Grounding Wave 0

ProofLoop가 먼저 저장소를 읽는다.

```text
[00:00.031] Grounding started
[00:00.038] Read: AGENTS.md
[00:00.041] Read: pyproject.toml
[00:00.043] Read: README.md
[00:00.050] Git branch: feature/payment-retry
[00:00.052] Dirty worktree detected: 1 user-owned file
[00:00.056] Protected user change: docs/payment-notes.md
```

CodeGraph 또는 파일 검색으로 결제 경계를 찾는다.

```text
[00:00.091] Search: payment processing entry points
[00:00.113] Found: src/payment/api.py
[00:00.124] Found: src/payment/service.py
[00:00.137] Found: src/payment/repository.py
[00:00.145] Found: tests/payment/test_payment_retry.py
[00:00.159] Existing retry header: X-Idempotency-Key
[00:00.171] Existing database field: payment_request_id
[00:00.184] Test command detected: pytest tests/payment
```

Grounding 결과:

```json
{
  "framework": "FastAPI",
  "paymentEntryPoint": "src/payment/api.py",
  "paymentService": "src/payment/service.py",
  "persistence": "PostgreSQL",
  "existingIdempotencyHeader": "X-Idempotency-Key",
  "existingUniqueConstraint": false,
  "focusedTestCommand": "pytest tests/payment",
  "protectedDirtyPaths": [
    "docs/payment-notes.md"
  ]
}
```

---

# 5. Grounded Prompt Compiler

이제 GPT-5.6 Terra 같은 강한 추론 모델이 원본 요청과 저장소 사실을 받아 실행 계약을 만든다.

중요한 점은 이 모델이 구현하는 것이 아니라 **무엇을 구현하고 어떻게 증명할지 정제한다는 것**이다.

```text
Raw Request
+ Repository Facts
+ Authority
+ Proof Policy
        ↓
Grounded Prompt Compiler
        ↓
Refined Intent Contract
```

결과 예시:

```json
{
  "objective": "동일한 idempotency key를 가진 결제 요청이 반복되더라도 결제 처리가 한 번만 수행되도록 한다.",
  "deliverables": [
    {
      "id": "D1",
      "description": "결제 처리 경계에 idempotency 보장 추가"
    },
    {
      "id": "D2",
      "description": "동시 요청과 순차 재시도에 대한 회귀 테스트 추가"
    }
  ],
  "acceptanceCriteria": [
    {
      "id": "AC1",
      "description": "동일한 idempotency key로 두 번 요청해도 결제 레코드는 하나만 생성된다.",
      "observable": true,
      "provenance": "USER_EXPLICIT"
    },
    {
      "id": "AC2",
      "description": "동시 요청에서도 실제 결제 처리는 한 번만 실행된다.",
      "observable": true,
      "provenance": "PROOF_POLICY"
    },
    {
      "id": "AC3",
      "description": "기존 API 응답 계약은 변경되지 않는다.",
      "observable": true,
      "provenance": "REPOSITORY_FACT"
    }
  ],
  "constraints": [
    "기존 X-Idempotency-Key 헤더를 재사용한다.",
    "사용자가 수정한 docs/payment-notes.md를 변경하지 않는다."
  ],
  "nonGoals": [
    "결제 API 전체 구조 리팩터링",
    "배포",
    "실제 결제 게이트웨이 호출"
  ],
  "stopCondition": "AC1, AC2, AC3이 유효한 실행 증거로 검증되면 종료한다."
}
```

---

# 6. 계약 검증

메타 모델의 결과도 그대로 믿지 않는다.

Deterministic Contract Validator가 검사한다.

```text
✓ Raw request hash preserved
✓ Repository mutation authority preserved
✓ No deployment authority added
✓ Acceptance criteria are observable
✓ Every criterion has provenance
✓ Protected user file preserved
✓ Stop condition exists
✓ Proof requirements were not weakened
```

만약 모델이 다음을 추가했다면:

```text
배포 후 실제 트래픽으로 검증한다.
```

ProofLoop는 차단한다.

```text
[00:01.220] Contract violation detected
[00:01.221] Unauthorized external side effect: production deployment
[00:01.223] Contract repair requested
```

수정되지 않으면:

```text
Verdict: BLOCKED
Reason: The proposed contract requires authority not granted by the user.
```

---

# 7. 작업 등급과 전략 선택

ProofLoop가 정제된 계약과 저장소 구조를 기준으로 난이도를 판정한다.

```json
{
  "complexity": 3,
  "uncertainty": 2,
  "risk": 4,
  "proofCost": 3,
  "scopeSize": 2,
  "externality": 0,
  "tier": "T2"
}
```

결제 경계이므로 단순 worker 하나에게 맡기지 않는다.

```text
Selected strategy:

Explorer
  ↓
Planner
  ↓
Implementer
  ↓
Deterministic Checks
  ↓
Surface Verification
  ↓
Independent Reviewer
  ↓
Truth Engine
```

실시간 화면:

```text
[00:01.290] Workload classified: T2
[00:01.292] Strategy selected: EXPLORE_PLAN_EXECUTE
[00:01.294] Independent review: REQUIRED
[00:01.295] Maximum implementation attempts: 2
```

---

# 8. 모델과 역할 선택

예상 라우팅 예시:

```text
Intent Refiner
└─ GPT-5.6 Terra
   이유: 요구사항·권한·증거 계약 설계

Explorer
└─ Gemini 3.1 Pro
   이유: 저장소 전반의 관련 경로 탐색

Planner
└─ GPT-5.6 Terra
   이유: 결제 상태 경계 및 실패 시나리오 설계

Implementer
└─ Codex의 GPT-5.6 Sol
   이유: 제한된 범위 코드 구현

Reviewer
└─ Claude
   이유: 명시적 계약·범위·예외 조건에 대한 독립 검토

Truth Engine
└─ Deterministic Runtime
   이유: 모델이 최종 성공 판정을 내리지 않음
```

이 선택 이유도 사용자에게 표시된다.

```text
[00:01.301] Model selected
             Role: planner
             Model: GPT-5.6 Terra
             Reason: high-risk state boundary design

[00:01.305] Model selected
             Role: implementer
             Model: GPT-5.6 Sol
             Reason: bounded implementation task

[00:01.307] Model selected
             Role: reviewer
             Model: Claude
             Reason: independent contract and edge-case review
```

실제 모델 가용성에 따라 달라질 수 있지만, **사용했다고 주장하는 모델과 실제 실행 모델이 일치해야 한다.**

---

# 9. Execution Blueprint 생성

Planner는 하나의 거대한 구현 요청을 받지 않는다.

작업을 증명 가능한 단위로 분해한다.

```yaml
tasks:
  - id: TASK-1
    title: Retry behavior reproduction
    objective: 기존 중복 결제 동작을 테스트로 재현한다.
    allowedPaths:
      - tests/payment/**
    protectedPaths:
      - docs/payment-notes.md
    stopWhen:
      - 회귀 테스트가 기존 코드에서 실패한다.

  - id: TASK-2
    title: Idempotency persistence boundary
    objective: 동시 요청에서도 하나의 결제만 생성되도록 한다.
    dependencies:
      - TASK-1
    allowedPaths:
      - src/payment/service.py
      - src/payment/repository.py
      - tests/payment/**
    stopWhen:
      - focused regression test가 통과한다.

  - id: TASK-3
    title: Public contract verification
    objective: 기존 API 응답 계약이 유지되는지 확인한다.
    dependencies:
      - TASK-2
    stopWhen:
      - 기존 contract test가 통과한다.

  - id: TASK-4
    title: Independent verification
    objective: 구현 범위와 증거를 독립적으로 검토한다.
    dependencies:
      - TASK-3
```

---

# 10. 모델별 프롬프트 렌더링

동일한 TaskBrief라도 모델별로 다른 형태로 전달된다.

## GPT-5.6 Sol에 전달되는 구현 프롬프트

```text
ROLE
Implement the approved idempotency task.

GOAL
Ensure identical payment retries create and process only one payment.

STOP WHEN
The focused sequential and concurrent retry scenarios pass,
the existing API contract remains unchanged,
and the final diff stays inside the approved paths.

EVIDENCE
- Initial failing regression result
- Focused test result
- Existing payment contract test
- Final diff

SCOPE
Allowed:
- src/payment/service.py
- src/payment/repository.py
- tests/payment/**

Protected:
- docs/payment-notes.md
- public response schema
- deployment configuration

MUST NOT
- Change the public response contract
- Skip or weaken tests
- Modify unrelated modules
- Claim completion without artifact references
```

## Claude Reviewer에 전달되는 프롬프트

```text
You are the independent reviewer.

Review the implementation against the immutable request and approved contract.

Verify:
1. The implementation prevents sequential duplicate retries.
2. The implementation prevents concurrent duplicate processing.
3. Existing API response behavior remains unchanged.
4. No protected or unrelated files were modified.
5. Tests were not weakened or skipped.
6. Every completion claim is supported by a current artifact.

Do not trust the implementer's completion summary as evidence.
Use the final diff, command outputs, test artifacts, and proof graph.

Return FAILED if a mandatory criterion lacks valid evidence.
```

---

# 11. 실행 중 관찰 화면

사용자는 CLI에서 내부 private chain-of-thought를 보는 것이 아니라, 다음을 본다.

```text
┌─ ProofLoop Run ──────────────────────────────────────────────┐
│ Run       pl-20260721-8f29                                  │
│ Intent    MUTATE · REPOSITORY_MUTATION                      │
│ Tier      T2                                                │
│ Host      Codex                                             │
│ Strategy  explore → plan → implement → verify               │
│ Status    RUNNING                                           │
├─ Active Work ────────────────────────────────────────────────┤
│ Role       implementer_deep                                 │
│ Model      GPT-5.6 Sol                                      │
│ Task       2/4 · Idempotency persistence boundary           │
│ Attempt    1/2                                              │
├─ Timeline ───────────────────────────────────────────────────┤
│ 00:01 read src/payment/service.py                           │
│ 00:02 read src/payment/repository.py                        │
│ 00:05 added concurrent retry regression                     │
│ 00:07 pytest retry_concurrent FAILED                        │
│ 00:08 changed src/payment/repository.py                     │
│ 00:11 pytest retry_concurrent PASSED                        │
│ 00:13 running existing payment contract tests               │
├─ Proof Obligations ──────────────────────────────────────────┤
│ ✓ Request fidelity                                         │
│ ✓ Authority preserved                                      │
│ ✓ Regression reproduced                                    │
│ ✓ Sequential retry                                         │
│ ✓ Concurrent retry                                         │
│ ○ Public contract preserved                                │
│ ○ Scope integrity                                          │
│ ○ Independent review                                       │
├─ Budget ─────────────────────────────────────────────────────┤
│ Budgeted 42,100 / 100,000 · Raw 88,400 · Retries 0 / 2    │
└──────────────────────────────────────────────────────────────┘
```

`Raw`는 provider가 보고한 입력·출력·cache read·cache write를 모두 더한
관측치다. 모델별 사용량과 벤치마크에는 이 값을 그대로 사용한다. `Budgeted`는
실행을 멈추게 하는 보수적 예산 단위로, cache read만 10% 가중하고 나머지는
전부 반영한다. 따라서 캐시가 많이 재사용됐다는 사실을 숨기지 않으면서도,
이미 캐시된 문맥이 구현 단계의 예산을 전부 소진시키지는 않는다. 실제 비용은
사용 가능할 때 TokScale의 별도 비용 근거로 표시하며, 토큰을 달러로 추정해
속이지 않는다.

사용자가 `Prompts` 탭을 열면:

```text
Prompt IR version: v1
Renderer: gpt56-outcome-v1
Role: implementer_deep
Prompt hash: sha256:...
Dispatched at: 00:01.482

[View raw request]
[View refined contract]
[View rendered prompt]
[View context references]
```

`Files` 탭:

```text
Modified:
  src/payment/repository.py
  tests/payment/test_payment_retry.py

Protected and unchanged:
  docs/payment-notes.md

Unrelated changes:
  None
```

---

# 12. 실패와 Recovery 시나리오

첫 구현 후 동시성 테스트가 실패했다고 가정하자.

```text
[00:07.210] Check failed: concurrent retry regression
[00:07.215] Failure fingerprint created:
             category=UNIQUE_CONSTRAINT_RACE
             signature=payment_request_id_duplicate
```

첫 번째 실패는 같은 implementer가 수정한다.

```text
Attempt 1
→ 애플리케이션 레벨 사전 조회 구현
→ 동시 요청에서 race 발생
→ 실패
```

Recovery Controller가 증거를 근거로 경로를 바꾼다.

```text
[00:07.230] Recovery decision
             Previous hypothesis: pre-check prevents duplicates
             Contradiction: two concurrent requests pass pre-check
             Next strategy: persistence-level uniqueness
```

두 번째 시도:

```text
Attempt 2
→ DB unique constraint 또는 atomic insert 적용
→ duplicate conflict를 기존 결과 조회로 변환
→ 동시성 테스트 통과
```

동일 실패가 또 반복되면:

```text
[00:15.000] Repeated failure fingerprint detected
[00:15.002] Retry budget exhausted
[00:15.003] No further autonomous retries permitted
```

최종 판정:

```text
FAILED

Reason:
The concurrent retry requirement could not be proven within the approved
retry budget.

Evidence:
- Attempt 1 failure
- Attempt 2 failure
- Repeated fingerprint UNIQUE_CONSTRAINT_RACE
```

모델이 “거의 해결했다”고 말해도 `PARTIAL` 또는 `FAILED`이지 `PROVEN`이 아니다.

---

# 13. 검증 시나리오

구현 완료 후 Runtime이 직접 검증한다.

```text
[00:13.010] Check started:
              pytest tests/payment/test_payment_retry.py

[00:13.804] Check passed:
              4 passed

[00:13.806] Check started:
              pytest tests/payment/test_contract.py

[00:15.110] Check passed:
              18 passed

[00:15.112] Scope integrity check started
[00:15.130] Scope integrity passed

[00:15.132] Test weakening check started
[00:15.150] No skipped, removed, or weakened tests detected
```

Surface 검증:

```text
Invocation:
POST /payments
X-Idempotency-Key: retry-123

Concurrent requests:
20

Observed:
- HTTP success responses: 20
- Payment records created: 1
- External charge invocation count: 1

Pass rule:
Payment record count == 1
External charge invocation count == 1
```

Artifact:

```text
evidence/http/concurrent-payment-retry.json
evidence/database/payment-record-count.json
evidence/commands/payment-contract-tests.txt
```

---

# 14. 독립 리뷰

Reviewer는 implementer의 “완료했습니다” 메시지를 보지 않거나, 보더라도 증거로 인정하지 않는다.

```text
Reviewer inputs:

- Immutable raw request
- Refined Intent Contract
- Final diff
- Current repository state
- Test artifacts
- Surface evidence
- Proof obligations
```

Reviewer 결과:

```json
{
  "status": "PASS",
  "findings": [],
  "verified": [
    "Sequential retries are idempotent",
    "Concurrent retries are idempotent",
    "Public API contract is unchanged",
    "No unrelated files were modified",
    "No tests were weakened"
  ]
}
```

Reviewer가 문제를 찾으면:

```json
{
  "status": "FAIL",
  "findings": [
    {
      "severity": "HIGH",
      "description": "The duplicate conflict returns HTTP 500 instead of the existing success response."
    }
  ]
}
```

그러면 PROVEN이 금지되고 recovery budget이 남아 있을 경우 다시 구현 단계로 돌아간다.

---

# 15. Truth Engine 판정

Truth Engine은 다음 그래프만 본다.

```text
AC1: 순차 재시도 중복 방지
  ├─ focused test artifact
  └─ database count artifact

AC2: 동시 재시도 중복 방지
  ├─ concurrent test artifact
  ├─ external invocation count
  └─ reviewer confirmation

AC3: 공개 계약 유지
  ├─ contract test result
  ├─ response snapshot
  └─ final diff inspection
```

모든 필수 증거가 유효하면:

```text
VERDICT: PROVEN
```

최종 출력:

```text
PROVEN

결제 요청 재시도에 대한 멱등성 처리가 구현되고 검증되었습니다.

검증된 항목:
- 동일 key 순차 요청: 결제 1건
- 동일 key 동시 요청 20건: 결제 1건
- 외부 결제 처리 호출: 1회
- 기존 API 계약 테스트: 통과
- 허용 범위 밖 변경: 없음
- 테스트 약화 또는 삭제: 없음
- 독립 리뷰: 통과

변경 파일:
- src/payment/repository.py
- tests/payment/test_payment_retry.py

실행하지 않은 작업:
- commit
- push
- PR 생성
- 배포

Run:
pl-20260721-8f29
```

---

# 16. 모호한 요청 시나리오

사용자:

```text
/proofloop 로그인 구조를 더 좋게 개선해줘
```

ProofLoop가 저장소를 조사한다.

```text
- 세션 인증과 JWT 인증이 함께 존재
- 기존 API 호환성을 유지할지 불명확
- 인증 체계를 완전히 변경할 수도 있음
- 공개 계약에 영향을 줄 가능성이 큼
```

이것은 단순 구현 선택이 아니라 제품 소유자 판단이 필요하다.

ProofLoop는 질문을 여러 개 던지지 않고, 핵심 결정 하나만 묻는다.

```text
현재 로그인 구조에는 세션 방식과 JWT 방식이 함께 존재합니다.

이번 작업의 목표를 하나 선택해야 합니다.

A. 기존 API 계약을 유지하면서 내부 중복 구조만 정리
B. 공개 인증 계약을 JWT 중심으로 변경

A는 저장소 내부 변경으로 진행할 수 있습니다.
B는 클라이언트 호환성에 영향을 주므로 명시적인 승인이 필요합니다.
```

사용자가 응답하지 않는 `--clarify never` 모드라면:

```text
BLOCKED

Reason:
A public authentication contract decision is required.
ProofLoop did not silently select a breaking API change.
```

---

# 17. 분석 전용 시나리오

사용자:

```text
/proofloop 이 저장소의 결제 장애 가능성을 분석해줘
```

IntentGate:

```text
Intent: AUDIT
Authority: READ_ONLY
```

실행:

```text
Explorer
→ Architecture analysis
→ Failure boundary mapping
→ Evidence collection
→ Reviewer
→ Audit report
```

파일을 수정하려는 agent가 발생하면 즉시 차단한다.

```text
[00:04.110] Unauthorized mutation attempted
[00:04.112] Path: src/payment/service.py
[00:04.114] Operation blocked by authority guard
```

최종 결과:

```text
PROVEN

분석 범위 내에서 다음 장애 경계가 확인되었습니다.

1. 결제 처리와 이벤트 발행 사이 원자성 부재
2. 재시도 시 idempotency 보장 부재
3. Kafka 전송 실패 후 재처리 기준 불명확

증거:
- src/payment/service.py: 관련 처리 경계
- src/payment/events.py: 비트랜잭션 이벤트 발행
- tests/payment/: 재시도 테스트 부재

저장소 변경:
- 없음
```

여기서 `PROVEN`은 “시스템에 장애가 없다”는 의미가 아니라, **보고서의 주장들이 저장소 증거로 입증됐다는 의미**다.

---

# 18. Host 전환 시나리오

같은 요청을 세 Host에서 실행할 수 있다.

## Codex

```text
/using proofloop 결제 재시도 중복 처리를 방지해줘
```

## Claude Code

```text
/proofloop 결제 재시도 중복 처리를 방지해줘
```

## Antigravity

```text
Workflow: ProofLoop
Request: 결제 재시도 중복 처리를 방지해줘
```

세 Host 모두 다음 계약은 동일하다.

```text
- objective
- authority
- acceptance criteria
- proof obligations
- allowed scope
- protected scope
- stop condition
```

달라지는 부분:

```text
- Host 호출 방식
- 사용할 수 있는 모델
- Tool invocation 방식
- streaming event parsing
- session resume 방식
- 최종 prompt 표현
```

예를 들어 AGY CLI에 요청 모델이 없다면:

```text
[00:00.320] Requested model unavailable on AGY CLI
[00:00.321] Candidate substitution: Gemini 3.1 Pro
[00:00.322] Contract and proof requirements unchanged
```

모델 변경이 허용되지 않은 설정이면:

```text
BLOCKED

Reason:
The requested model is unavailable on the selected Host,
and automatic substitution is disabled.
```

지원하지 않는 모델을 사용했다고 속이지 않는다.

---

# 19. UI 구현 시나리오

사용자:

```text
/proofloop 현재 실행 상태를 보여주는 웹 대시보드를 구현해줘
```

라우팅:

```text
Intent Refiner: GPT-5.6 Terra
Planner: GPT-5.6 Terra
Visual Engineer: Gemini 3.1 Pro
Backend Implementer: GPT-5.6 Sol
Reviewer: Claude
```

Gemini 전용 Prompt에는 다음이 포함된다.

```text
USER-VISIBLE SURFACE
ProofLoop run timeline and proof obligation dashboard

REQUIRED STATES
- Empty state
- Active run
- Failed check
- Recovery in progress
- PROVEN result
- BLOCKED result

VISUAL CONSTRAINTS
- Existing design tokens must be reused
- Timeline and proof status must be distinguishable
- No generic AI chat layout
- Desktop and narrow viewport must both work

SURFACE EVIDENCE
- Actual browser render
- Interaction recording
- Console error check
- Screenshot artifacts
```

최종 검증은 단순 빌드 성공이 아니다.

```text
✓ frontend build
✓ backend API
✓ browser loaded
✓ active event appended in real time
✓ proof status updated
✓ failed run displayed
✓ console error absent
✓ screenshot artifact present
```

---

# 20. 사용자가 최종적으로 느끼게 될 변화

현재 ProofLoop:

```text
명령 실행
→ CLI 내부에서 무언가 수행
→ 중간 과정이 잘 보이지 않음
→ 완료 메시지를 받아도 실제 작업 내용을 다시 확인해야 함
```

완성된 ProofLoop:

```text
요청 입력
→ 요청이 어떻게 해석됐는지 확인
→ 무엇을 조사하는지 확인
→ 어떤 모델이 어떤 역할을 맡았는지 확인
→ 실제 전달 Prompt 확인
→ 어떤 파일과 명령이 사용되는지 실시간 확인
→ 실패 이유와 복구 경로 확인
→ 증거가 하나씩 충족되는 과정 확인
→ 완료 메시지가 아니라 Truth Verdict 수신
```

사용자는 최종적으로 다음 세 가지 질문에 항상 답을 얻는다.

```text
1. 지금 무엇을 하고 있는가?
2. 왜 이 모델과 전략을 선택했는가?
3. 실제로 완료되었다는 증거는 무엇인가?
```

# 21. 완성된 제품의 최종 모습

```text
                           ProofLoop
┌────────────────────────────────────────────────────────────┐
│ Request Compiler                                           │
│ "사용자가 원하는 것이 정확히 무엇인가?"                   │
├────────────────────────────────────────────────────────────┤
│ Strategy Router                                            │
│ "어떤 Host·모델·역할·실행 전략이 적합한가?"               │
├────────────────────────────────────────────────────────────┤
│ Observable Runtime                                         │
│ "현재 무엇을 읽고, 수정하고, 실행하고 있는가?"             │
├────────────────────────────────────────────────────────────┤
│ Recovery Controller                                        │
│ "왜 실패했으며, 다음 시도는 무엇이 달라지는가?"            │
├────────────────────────────────────────────────────────────┤
│ Proof Engine                                               │
│ "어떤 acceptance criterion이 어떤 증거로 입증됐는가?"      │
├────────────────────────────────────────────────────────────┤
│ Truth Engine                                               │
│ "이 결과를 정말 완료로 인정할 수 있는가?"                  │
└────────────────────────────────────────────────────────────┘
           │                    │                    │
           ▼                    ▼                    ▼
         Codex             Claude Code         Antigravity
```

결과적으로 ProofLoop는 다음 경험을 제공하게 돼.

> **사용자는 목표만 전달하지만, 실행 과정은 숨겨지지 않는다.**
> **에이전트는 자율적으로 일하지만, 권한과 반복은 통제된다.**
> **모델은 완료를 주장할 수 있지만, 완료 여부는 증거가 결정한다.**

---

# 22. 실행 수용 기준

이 문서는 단순한 비전 문서가 아니다. ProofLoop는 완료된 run에
`expected-output-report.json`을 남기며, 아래 약속을 기계적으로 검사한다.

```text
원본 요청·hash·runId가 보존된다
실행 run / request envelope / grounding이 같은 저장소 루트를 가리킨다
IntentGate·권한·정제된 실행 계약·전략이 확인 가능하다
역할이 실행되면 렌더된 prompt, 진행 이벤트, 요청 모델과 관측/미관측 모델 근거가 남는다
역할이 종료된 run은 raw token과 budgeted token 사용량을 모델별로 남긴다
AGY CLI가 90초 동안 첫 stdout/stderr를 내지 않으면 `HOST_INITIAL_OUTPUT_TIMEOUT`으로
종료하고, 호스트 장애로 인한 `BLOCKED` verdict와 원인을 남긴다
호스트 대화는 parent run이 끝날 때까지 짧은 `relay` 호출을 반복해, 새로 생긴 관측 가능
실행 이벤트(역할·모델·도구/검사·복구·리뷰·판정)를 같은 세션에 한 번씩 표시한다
종료된 mutation run은 parent-owned checks·diff·review·proof·Truth artifact를 모두 남긴다
```

단, 외부 모델 quota·권한·호스트 장애처럼 **변경 전에** 차단된 `BLOCKED` run은 성공 run의
checks/diff/review를 가장해서 만들지 않는다. 대신 `truth-report.json`의 안정적인 blocker code,
`verdict.issued`와 `run.blocked` 이벤트, 이미 관측된 역할·모델·usage 증거를 남긴다. 이 역시
사용자에게 정직하고 즉시 설명 가능한 정상 종료다. `PROVEN` 또는 `PARTIAL` mutation run만
전체 parent-owned 검증 묶음을 요구한다.

사용자 또는 릴리스 검증기는 다음으로 직접 확인할 수 있다.

```bash
python3 scripts/verify_expected_output.py \
  .proofloop/runs/<run-id> \
  --repository "$(git rev-parse --show-toplevel)" \
  --require-terminal
```

`PASS`는 이 관찰 가능성 계약이 충족되었다는 뜻이며, 변경 자체의 성공은
별도의 `truth-report.json` verdict가 결정한다. 예를 들어 요청 파일 디렉터리를
저장소로 잘못 사용하면, 역할 로그가 존재해도 `repository_binding: FAIL`로
수용되지 않는다.
