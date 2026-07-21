# Prompt Refinement Contract

상태: `FIXES_APPLIED_PENDING_REVIEW`, H01-S1 구현 완료, H01-S5 구현 가능  
주 설계: Claude Opus, 실제 Claude Code `--model opus` 호출  
독립 리뷰: GPT-5.6 Sol 완료  
구현 계획: Gemini CLI는 IAM 403으로 차단됐으나 Antigravity의 Gemini 3.1 Pro High로 완료

독립 리뷰 원문과 승인된 Slice 1 경계는
[리뷰 문서](reviews/01-prompt-refinement-gpt-5.6-sol.md)에 저장한다. 아래 설계 중 Slice 2 이후는
리뷰의 필수 수정사항을 모두 반영해 재검토하기 전까지 구현하지 않는다.

## 0. 독립 리뷰로 확정된 교정

### 권위 계층

```text
platform/host safety와 명시적 external authorization
  > 오케스트레이터에 전달된 exact Python Unicode request
  > Core narrowing policy
  > execution brief
  > task/work packet
  > model proposal 또는 inference
```

Proof Graph는 completion과 evidence state에만 권위가 있다. intent, approved scope, protected path와
충돌하면 Proof Graph 또는 다른 artifact를 우선하지 않고 `ARTIFACT_CONFLICT`로 차단한다.

### 현재 구현에 관한 교정

- 현재 오케스트레이터는 입력에 `.strip()`을 적용하므로 exact request 보존은 아직 구현되지 않았다.
- 보존 대상은 CLI 이전 raw bytes가 아니라 오케스트레이터에 전달된 Python Unicode 문자열이다.
- 현재 `repository-context.json`은 CodeGraph 준비 상태이지 file·symbol·test fact snapshot이 아니다.
- 현재 direct bootstrap은 task proposal과 mutation을 한 invocation에서 수행하므로 scope 사전 승인을
  보장하지 못한다.
- 기존 Proof Graph는 criterion별 check mapping을 갖지 않으므로 Execution Brief가 criterion 만족 또는
  proof status를 만들 수 없다.

### 수정된 전체 흐름

```text
exact request + legacy intent + baseline + repository fingerprint
  → discovery brief
  → optional read-only explorer
  → repository evidence snapshot
  → optional strong-model proposal
  → deterministic reconciliation
  → execution brief
  → read-only task/scope proposal
  → parent validation and scope approval
  → role-views/<invocation-id>.json
  → mutating implementation
  → deterministic evidence and Proof Graph completion
```

첫 구현에서는 이 전체 흐름을 연결하지 않는다. 순수 composer를 shadow artifact로 만들 수 있는
기반만 구현한다. 이 `H01-S1`은 구현과 검증을 완료했으며 아직 오케스트레이터에는 연결하지 않았다.

## 1. 문제

현재 `compile_intent()`는 원문, 해시, objective, acceptance criteria, 일부 risk·unknown·target을
구조화한다. 그러나 explorer, planner, direct implementer, final reviewer 프롬프트에는 원문이 다시
삽입된다. 따라서 현재 구현은 **원문 보존과 기초 intent 구조화**는 하지만, 저장소 근거를 결합한
실행용 정제 프롬프트를 만들지는 않는다.

목표는 원문을 멋있게 다시 쓰는 것이 아니다. 원문을 불변 권위로 유지하면서 저장소 사실과 결합한
`Execution Brief`를 만들고, 각 역할에는 필요한 부분만 담은 `Role View`를 제공하는 것이다.

## 2. 불변 조건

1. 원문과 SHA-256은 변경되지 않으며 충돌 시 항상 원문이 우선한다.
2. 정제는 authorization을 넓히거나 요구사항을 발명하거나 unknown을 숨기지 않는다.
3. fact, inference, assumption, decision, open question을 구분한다.
4. T0/T1은 별도 강한 모델 호출 없이 결정론적으로 정제한다.
5. T2/T3의 강한 모델은 제안만 만들며 Core reconciler가 검증·축소한다.
6. 각 역할은 transcript 전체가 아니라 최소 role view를 받는다.
7. 완료는 Proof Graph와 실제 evidence가 소유한다.
8. 권위 artifact는 부모 프로세스가 schema 검증과 reconciliation 후 materialize한다. 모델 출력은
   부모가 저장했더라도 검증 전에는 candidate다.

## 3. Artifact 모델

```text
request.json + hash
  → intent-contract.json
  + repository-context.json
  + refinement-proposal.json       # T2/T3 선택적, 비권위
  → reconciliation-report.json     # 감사용
  → execution-brief.json           # 권위 실행 계약
  → role-views/<role>.json          # 결정론적 최소 투영
  → role invocation
  → proof-graph.json + truth-report.json
```

모든 파생 artifact는 상위 artifact의 content hash와 schema version을 provenance로 가진다. canonical
hash는 `ensure_ascii=False`, `sort_keys=True`, `separators=(",", ":")`, `allow_nan=False`로 직렬화한
UTF-8 bytes를 사용하며 self-hash는 대상에서 제외한다.

## 4. 단계별 정제

### Stage 0 — 원문 고정

향후 `request.json.request` 호환 필드를 유지하면서 `requestSha256`을 추가한다. 현재 `.strip()` 동작을
제거하는 변경은 별도 backward-compatibility slice에서 처리한다.

### Stage 1 — 결정론적 intent compile

기존 `compile_intent()`를 사용해 objective, criteria, constraints, non-goals, authorization boundary,
unknowns, risks, explicit targets를 만든다.

### Stage 2 — 저장소 근거 결합

현재 `repository-context.json`은 fact source로 사용할 수 없다. 별도 `repository-evidence-snapshot.json`
schema가 구현되기 전까지 context가 `SKIPPED` 또는 CodeGraph readiness만 담으면 facts는 빈 배열이다.
path는 승인 scope가 아니라 candidate로만 기록한다.

### Stage 3 — 선택적 refinement proposal

- T0/T1: 호출하지 않는다.
- T2: blocking ambiguity 또는 design risk가 있을 때만 호출한다.
- T3: 강한 모델의 proposal을 요청한다.

proposal은 inference, assumption, proposed decision, open question만 제안할 수 있다. 새로운 acceptance
criterion이나 authorization을 만들 수 없다.

### Stage 4 — 결정론적 reconcile

Core가 proposal을 원문, intent, repository context와 대조한다. 처리 결과는 `accepted`, `downgraded`,
`rejected` 중 하나다. 검증 실패 시 proposal 전체 또는 해당 delta를 버리고 결정론적 경로로 폴백한다.

### Stage 5 — Execution Brief 합성

proposal 여부와 무관하게 모든 tier에서 실행 브리프를 만든다. 따라서 역할 입력은 항상 같은 계약을
사용한다.

### Stage 6 — Role View 투영

Execution Brief의 정해진 필드만 역할별로 투영한다. 역할이 추가 해석을 위해 원문 전체를 기본
프롬프트에 다시 삽입하지 않는다. 원문은 경로로 참조할 수 있다.

## 5. Execution Brief schema

```json
{
  "schemaVersion": "1.0",
  "provenance": {
    "requestSha256": "...",
    "intentContractSha256": "...",
    "repositoryContextSha256": "...",
    "refinementProposalSha256": null,
    "tier": "T1",
    "generatedBy": "proofloop-core"
  },
  "authority": {
    "originalRequest": "request.json",
    "authorizationBoundary": "intent-contract.json",
    "completionAuthority": "proof-graph.json"
  },
  "objective": "...",
  "acceptanceCriteria": [],
  "constraints": [],
  "nonGoals": [],
  "risks": [],
  "facts": [],
  "inferences": [],
  "assumptions": [],
  "decisions": [],
  "openQuestions": [],
  "scope": {
    "explicitTargets": [],
    "repositoryVerifiedTargets": [],
    "outOfScope": [],
    "expansionForbidden": true
  }
}
```

### 분류 규칙

- `facts`: 원문 line 또는 repository context의 구체적인 source reference가 있어야 한다.
- `inferences`: 두 개 이상의 source reference 또는 한 fact와 명시적 추론 설명이 필요하다.
- `assumptions`: 근거가 충분하지 않은 가역적 선택이며 절대 숨기지 않는다.
- `decisions`: 승인된 scope 안에 있고 acceptance criterion 또는 fact에 연결돼야 한다.
- `openQuestions`: intent unknown과 proposal question의 합집합이다. blocking을 비차단으로 내릴 수 없다.

## 6. Role View schema와 envelope

```json
{
  "schemaVersion": "1.0",
  "role": "implementer_fast",
  "provenance": {
    "executionBriefSha256": "...",
    "proofGraphSha256": null,
    "obligationRevision": 0
  },
  "objective": "...",
  "acceptanceCriteria": [],
  "scope": {},
  "decisions": [],
  "openQuestions": [],
  "authorityRefs": {
    "originalRequest": "request.json",
    "executionBrief": "execution-brief.json",
    "proofGraph": "proof-graph.json"
  }
}
```

| 역할 | 기본 포함 | 기본 제외 |
| --- | --- | --- |
| explorer | objective, verified facts, targets, open questions | decisions, 전체 criteria 설명 |
| planner | objective, criteria, scope, decisions, blocking questions | transcript, 무관한 facts |
| implementer | objective, criteria, allowed scope, approved decisions | proposal, planner의 자유 추론 |
| recovery | implementer view + failure fingerprint + prior evidence | 무관한 history |
| reviewer | objective, criteria, scope, assumptions, open questions, evidence refs | implementer summary 신뢰 |

## 7. Anti-drift validation

Reconciler는 다음 순서로 검사한다.

1. request, intent, repository context hash가 현재 artifact와 일치하는지 확인한다.
2. proposal이 fact 또는 acceptance criterion을 새로 만들면 거절한다.
3. proposal path가 explicit target 또는 repository-verified candidate인지 확인한다.
4. inference의 source reference가 실제로 존재하는지 확인한다.
5. assumption이 결과에서 사라지지 않았는지 확인한다.
6. open question은 합집합으로 보존하고 blocking을 하향하지 않는다.
7. decision이 acceptance criterion과 scope에 연결되는지 확인한다.
8. authorization boundary가 원본 intent보다 넓어지지 않았는지 확인한다.

Repository에 존재한다는 사실만으로 변경 권한이 생기지는 않는다. explicit target이 없는 경우
repository-verified path는 **candidate**이며 planner나 Core policy가 허용 경계를 정해야 한다.

## 8. 실패와 승격

| 상황 | 처리 |
| --- | --- |
| proposal schema 오류 | proposal 폐기, 결정론적 brief 생성 |
| provenance hash 불일치 | 모든 파생 artifact 무효화 후 재컴파일 |
| scope 확대 | 해당 delta 거절, audit finding 기록 |
| 발명된 criterion | proposal 거절 |
| blocking question | 역할 실행 전 사용자 입력 또는 strong planner로 승격 |
| strong refiner timeout | 결정론적 brief로 폴백하되 ambiguity를 숨기지 않음 |
| role view schema 오류 | 해당 역할 실행 차단 |
| brief와 Proof Graph 또는 scope artifact 충돌 | `ARTIFACT_CONFLICT`로 차단 |

## 9. 구현 슬라이스

1. `execution_brief.py`: 오케스트레이터와 연결하지 않는 순수 composer와 schema validation
2. legacy request/intent 보존과 shadow artifact 생성
3. discovery brief와 repository evidence snapshot
4. read-only task/scope proposal과 parent approval로 direct bootstrap 분리
5. `role_view.py`: invocation별 envelope와 최소 투영
6. orchestrator prompt cutover
7. `refinement.py`: T2/T3 proposal schema와 deterministic reconciler
8. tier routing과 escalation 통합

각 슬라이스는 이전 단계만 의존하며 독립 테스트와 rollback이 가능해야 한다.

## 10. Acceptance tests

- 동일 입력과 동일 repository context는 동일 execution brief hash를 만든다.
- 원문 변경은 모든 파생 artifact를 stale로 만든다.
- T0/T1은 refinement model invocation을 만들지 않는다.
- proposal의 새 criterion과 authorization 확대는 거절된다.
- unknown과 assumption은 결과에서 사라지지 않는다.
- 각 역할 프롬프트는 raw request 전문을 포함하지 않는다.
- 역할별 view는 허용된 필드 외의 정보를 포함하지 않는다.
- refiner가 완료를 주장해도 open proof obligation이 있으면 완료되지 않는다.
- 자식 역할이 권위 artifact를 직접 작성하지 않는다.
- strong refiner 실패 시 실행은 결정론적 brief 또는 명시적 `BLOCKED`로 끝난다.

## 11. Non-goals

- 원문을 덮어쓰거나 더 좋은 문장처럼 보이게 만드는 것
- 모든 tier에서 별도 LLM 정제 호출
- refiner에게 완료 판정을 맡기는 것
- 모든 역할에 하나의 거대한 공통 프롬프트 전달
- repository context 생성 방식 교체
- 기존 Proof Graph와 recovery FSM의 대체

## 12. 보류된 설계 쟁점

다음 항목은 독립 리뷰에서 확정한다.

1. Path candidate는 부모 Core만 승인할 수 있다. repository-relative, symlink-safe, objective/criterion
   연결, protected path 제외, budget 이내 조건을 모두 만족해야 한다.
2. T2 refinement는 risk·uncertainty·hard gate·blocking question이 모두 0이고 explicit acceptance,
   non-public/non-persistent/non-critical이며 evidence가 baseline에 고정된 경우에만 생략한다.
3. baseline repository fact로 답이 유일하면 planner가 해결한다. 제품 동작, 공개 계약, migration,
   보안 정책, 외부 side effect, 비용·배포, authorization 확대는 사용자 결정이 필요하다.
4. Core가 offset과 request hash를 검증한 exact substring excerpt만 role view에 허용한다. 합계 2,000자
   상한이며 전체 원문 경로는 authority reference로 유지한다.
5. proposal invocation에는 requested/observed model, evidence level, session/invocation, trace hash가
   필수다. requested-only이면 proposal을 canonical brief에 반영하지 않는다.

## 13. 설계 provenance

- 실제 호출: `claude -p --model opus --effort high --permission-mode plan`
- 첫 repository-tool 호출은 5분 동안 결과를 반환하지 않아 종료했다.
- 두 번째 호출은 검증된 현재 구현 사실을 입력으로 제공하고 도구 없이 완료했다.
- 이 문서는 두 번째 Claude Opus 결과를 Core 계약과 현재 코드 명명에 맞게 편집한 초안이다.
- GPT-5.6 Sol 독립 리뷰가 `FIX_REQUIRED`를 판정했고 H01-S1만 구현 가능한 범위로 승인했다.
- Gemini CLI `gemini-3.1-pro-preview` 호출은 2026-07-20 Google Cloud IAM
  `cloudaicompanion.companions.generateChat` 권한 거부로 결과 없이 종료됐다.

### Raw request 비복제의 정확한 의미

Execution Brief는 원문 payload를 `request`, `originalRequest`, `rawRequest`, `requestText`, `transcript`
같은 독립 비정형 필드로 복제하지 않는다. 다만 intent contract가 정확히 보존한 objective, acceptance
criterion, constraint, non-goal은 해당 typed field에 포함할 수 있다. 한 줄 요청에서는 objective나
criterion이 원문 전체와 같아도 허용한다. 따라서 비복제는 lexical substring 부재가 아니라 허용된
typed 위치 밖 원문 복제가 없음을 뜻한다.

문자 offset과 request hash를 포함하는 exact `requestClauses`는 후속 Role View slice에서 추가하며
S1의 legacy objective·criteria에는 소급하지 않는다.
