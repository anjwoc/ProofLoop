# H01-S1 Gemini 3.1 Pro 구현 계획 상태

상태: `IMPLEMENTED_AND_VERIFIED`  
대상: 순수 deterministic Execution Brief composer  
승인 계약: `docs/designs/reviews/01-prompt-refinement-gpt-5.6-sol.md`

## 실제 호출 결과

2026-07-20 Gemini CLI 0.47.0에서 `gemini-3.1-pro-preview`를 read-only plan mode로 호출했다.
Google Cloud가 다음 권한을 거부해 모델 응답이 생성되지 않았다.

```text
cloudaicompanion.companions.generateChat
status: PERMISSION_DENIED (403)
```

Gemini CLI 경로에서는 모델 응답이 생성되지 않았다. 다른 모델을 Gemini로 표시하거나 자동 대체하지
않는다.

## 성공한 대체 실행 경로

로컬 Antigravity CLI 1.1.4가 제공하는 `Gemini 3.1 Pro (High)`를 read-only plan mode로 실행했다.
첫 호출은 headless command permission 요청이 자동 거부됐고, 두 번째 호출은 승인된 계약을 프롬프트에
직접 제공해 도구 없이 완료됐다.

```text
agy --mode plan --model "Gemini 3.1 Pro (High)" -p <compact-work-packet>
```

Gemini는 stdlib-only manual validation, canonical hashing, pure composer, 입력 불변성, 승인되지 않은
I/O·orchestrator·Proof Graph 변경 시 `DESIGN_CONFLICT`를 반환하는 계획을 제시했다.

## Gemini에 전달할 승인된 범위

- 신규 `proofloop_core/execution_brief.py`
- 신규 `tests/deterministic/test_execution_brief.py`
- pure composer와 manual schema validation만 구현
- orchestrator, intent, scanner, Proof Graph 수정 금지
- 모델 호출·role view·prompt cutover·scope approval 구현 금지
- raw request 전문을 output에 포함하지 않음
- legacy intent criteria/constraints/non-goals/risks/unknowns 보존
- repository target은 candidate이며 approved path는 비움
- readiness-only context에서는 facts를 만들지 않음
- canonical JSON hash 규칙 고정

## 확정 구현 순서

1. `execution_brief.py`에 schema error와 strict input validator를 만든다.
2. canonical JSON serialization과 provenance hash를 구현한다.
3. legacy intent fields를 손실 없이 보존하는 pure composer를 구현한다.
4. target은 candidate, scope는 `UNRESOLVED`, facts/inferences는 빈 상태로 만든다.
5. 승인된 deterministic tests를 추가한다.

Gemini가 제안한 `executionBriefVersion` 명칭과 추가 fact/inference 입력 모델은 상위 계약에서 승인되지
않았으므로 구현에서 제외한다. 출력은 Core convention인 `schemaVersion`을 사용한다.

## 구현 및 검증 결과

- 구현: `proofloop_core/execution_brief.py`
- 결정론적 테스트: `tests/deterministic/test_execution_brief.py`
- targeted test: 10개 통과
- Ruff 및 `git diff --check`: 통과
- 전체 프로젝트 테스트: 218개 통과, optional ACP SDK 1개 skip
- GPT-5.6 Sol 독립 코드 리뷰: `APPROVE`, blocking finding 없음
- 범위: shadow composer만 구현했으며 orchestrator prompt cutover와 모델 호출은 포함하지 않음
