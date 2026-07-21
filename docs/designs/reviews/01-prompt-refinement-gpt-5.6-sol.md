# H-01 Prompt Refinement 독립 리뷰

판정: `FIX_REQUIRED`  
리뷰 모델: GPT-5.6 Sol  
역할: 독립 설계 게이트  
대상: `docs/designs/01-prompt-refinement-contract.md`

## Critical findings

1. Proof Graph는 completion만 소유하며 authorization을 덮어쓸 수 없다. artifact 충돌은
   `ARTIFACT_CONFLICT`로 차단해야 한다.
2. 현재 오케스트레이터는 request에 `.strip()`을 적용하고 `request.json`에 hash가 없어 exact 원문
   보존 주장이 사실이 아니다.
3. 현재 repository context는 CodeGraph readiness일 뿐 file·symbol·test fact snapshot이 아니며,
   explorer 이전 execution brief 생성은 순환 의존을 만든다.
4. untyped array schema로는 deterministic reconciliation을 구현할 수 없다.
5. direct bootstrap은 scope 승인 전에 task 작성과 mutation을 동시에 수행한다.
6. 기존 Proof Graph는 criterion별 check mapping이 없으므로 brief가 criterion 만족을 주장할 수 없다.

## Important findings

- constraints, non-goals, risk signals를 brief에서 누락하면 안 된다.
- canonical JSON hash 규칙을 고정해야 한다.
- role view는 역할별 고정 파일이 아니라 invocation별 artifact여야 한다.
- proof graph hash와 obligation revision을 role view provenance에 넣어야 한다.
- `refiner_deep` 신규 역할 대신 첫 단계는 기존 `planner_deep`을 refinement purpose로 재사용한다.
- 부모가 저장한 모델 출력도 검증 전에는 candidate다.
- legacy artifact 1.0을 읽되 기존 run을 재작성하지 않는 호환 정책이 필요하다.
- blocking authorization ambiguity는 deterministic fallback이 아니라 `BLOCKED`여야 한다.

## 확정 결정

### Path 승인

모델은 candidate만 제안하고 부모 Core만 승인한다. 승인 조건은 repository-relative, symlink-safe,
existing path 또는 승인 parent 아래 planned-new path, objective/criterion 연결, protected path 제외,
change budget 이내, external write 아님이다.

### T2 refinement 생략

risk, uncertainty, hard gate, blocking question이 모두 없고 acceptance가 explicit이며 public contract,
persistent state, critical path가 아니고 repository evidence가 현재 baseline에 고정된 경우에만 생략한다.

### 사용자 결정

제품 동작이 여러 개 가능하거나 공개 API·UX·migration·보안·외부 side effect·비용·배포·authorization
확대가 관련되면 planner가 결정하지 않는다. 입력 채널이 없으면 `questions.json`과
`USER_DECISION_REQUIRED`로 차단한다.

### 원문 excerpt

Core가 exact substring, start/end offset, request hash를 검증한 인용만 역할별 합계 2,000자까지
허용한다. paraphrase는 인용으로 표시할 수 없다.

### Proposal 모델 증거

proposal에는 runtime, invocation ID, requested/observed model, model evidence, trace hash가 필요하다.
observed evidence가 없으면 canonical brief에 반영하지 않는다.

## 승인된 최소 Slice 1

### 파일 범위

- `proofloop_core/execution_brief.py` 신규
- `tests/deterministic/test_execution_brief.py` 신규

### 불변 조건

- orchestrator, intent compiler, scanner, Proof Graph를 수정하지 않는다.
- 모델 호출과 파일 mutation이 없는 pure composer다.
- raw request를 독립 비정형 field로 복제하지 않는다. Legacy objective와 criterion의 exact clause는
  typed field에서 허용한다.
- 기존 criterion ID와 statement를 그대로 보존한다.
- constraints, non-goals, risks, unknowns를 보존한다.
- repository path는 candidate이며 `approvedPaths`는 빈 배열이다.
- skipped/readiness-only context에서 repository fact를 발명하지 않는다.
- proof status나 criterion 만족을 생성하지 않는다.
- canonical hash를 고정하고 입력 mapping을 mutation하지 않는다.

### 필수 테스트

- dict key 순서와 무관한 hash
- request/intent/strategy/context/baseline 변화 시 hash 변화
- legacy intent 1.0 field와 criterion 보존
- raw request 전문 부재
- unknown/constraint/non-goal/risk 보존
- skipped context에서 빈 facts
- target은 candidate이며 authorization이 아님
- source reference 없는 fact/inference 거절
- blocking question 하향 금지
- schema version과 unknown top-level field 거절
- 입력 객체 불변

## 다음 게이트

Slice 1 외의 orchestrator prompt cutover, role view, strong refiner는 전체 계약 수정 후 다시
GPT-5.6 Sol 설계 리뷰를 받아야 한다.

## Slice 1 구현 중 binding clarification

한 줄 request는 legacy objective와 `AC-001.statement`에 그대로 보존되므로 문자열 자체의 완전한
부재를 요구하면 criterion 보존과 충돌한다. “raw request absent”는 다음 field가 brief schema에 없다는
구조적 의미로 확정한다.

```text
request, originalRequest, rawRequest, requestText, transcript
```

Exact request string node는 `/objective`와 해당 `/acceptanceCriteria/<n>/statement`처럼 승인된 typed
위치에서만 허용한다.
