# Proposal: README.md Architecture & Design Update

> **Purpose:** 이 문서는 최근 새롭게 재설계 및 구현 완료된 ProofLoop 핵심 아키텍처(내부적으로 Phase P~12, V2 아키텍처로 불린 사항들)를 `README.md`에 명확하게 반영하기 위한 **수정 제안 및 섹션별 재구조화 가이드**입니다.
> **Design Principle:** 'v2'라는 버전 마케팅 용어 대신, 사용자와 개발자가 실질적으로 얻게 되는 **"Grounded Prompt Compiler", "Deterministic Proof Graph", "Intent Reconciler", "In-Chat Relay Observability", "Truth Verdict Gate"** 등 기능적 가치와 작동 메커니즘 중심으로 설명합니다.

---

## 1. 개편 필요성 분석 (Why Update?)

현재 `README.md`는 ProofLoop의 핵심 철학(*"Make coding agents prove they are done."*)과 기본 동작(`v0.4.0-alpha` 소개, T0~T3 에스컬레이션 테이블)을 잘 담고 있습니다. 하지만 최근 완료된 아키텍처 고도화의 **가장 강력하고 차별화된 5대 핵심 파이프라인**이 고스란히 드러나지 않고 있습니다:

1. **저장소 사실 기반 프롬프트 컴파일러 (Grounded Prompt Compiler & IR v1):** 단순 프롬프트 전송이 아닌, Grounding Wave 0 조사 결과(CodeGraph/테스트 명령어)와 목표·권한을 결합해 구조화된 `PromptIR`로 변환하고 모델별 맞춤 렌더링(`gpt56-outcome-v1`, `claude-review-v1`)을 수행하는 과정.
2. **사전 계약 검증기 (Intent Reconciler Guard):** 모델이 임의로 권한 밖의 부수 효과(무단 배포, PR 생성)를 추가하거나 기존 테스트 약화를 시도할 때, 코딩 전에 이를 탐지하고 차단/수정(`BLOCKED` / `Reconciliation`)하는 방어 체계.
3. **실시간 터미널 중계 및 비공개 추론 보호 (In-Chat Relay & Redaction):** 호스트 CLI(AGY/Claude/Codex) 대화창 안에서 자식 프로세스의 진행률(`[ProofLoop] phase=... role=... elapsed=...`)을 커서(`next-line`) 기반으로 중복 없이 보여주면서, 공급자의 비공개 추론(`thinking/reasoning`)을 완벽히 마스킹하여 유출하지 않는 관측성 계약.
4. **실패 지문(Fingerprint) 기반 복구 상태 기계 (Recovery FSM):** 단순 반복 재시도가 아니라, 실패 유형(`UNIQUE_CONSTRAINT_RACE`, `DESIGN_CONFLICT` 등)을 지문으로 분류하여 빠른 반복(최대 2회) ➔ 복구 역할(Recovery role) ➔ 상위 기획자 회귀(Re-plan)로 경로를 동적으로 변경하는 메커니즘.
5. **완주 판정 기계 검증 (Expected Output & Truth Engine):** 에이전트의 "완료했습니다" 주장 대신, 10대 관측성/정합성 계약(`expected-output-report.json`)을 통과하고 부모 증거(`truth-report.json`)가 입증되어야만 최종 `PROVEN` 판정을 내리는 이중 게이트.

---

## 2. README.md 섹션별 수정 제안 (Proposed Outline & Changes)

다음은 기존 `README.md`의 흐름을 자연스럽게 유지하면서 신규 아키텍처 역량을 삽입할 수 있는 **6단계 구조화 제안**입니다.

### 📍 [제안 A] 섹션 1: "How ProofLoop Works (The Core Pipeline)" 신설
> **위치:** `## The idea in one minute` 바로 아래, 혹은 `## What happens after invocation`을 격상하여 대체
> **목적:** 사용자의 프롬프트가 어떤 정밀한 파이프라인을 거쳐 코딩과 증명으로 이어지는지 한눈에 보여주는 다이어그램 및 5단계 명세 추가

#### 제안 텍스트/다이어그램:
```markdown
## How ProofLoop Works: The Five-Stage Proof Pipeline

ProofLoop processes every engineering request through an immutable, verification-first pipeline:

1. **Intent & Grounding (Wave 0):**
   - The raw user request is frozen (`request-envelope.json`).
   - ProofLoop inspects the repository (`AGENTS.md`, `pyproject.toml`, Git status, CodeGraph boundaries) before asking any questions, extracting exact framework boundaries, existing test commands, and protected user files.

2. **Grounded Prompt Compilation & Reconciliation:**
   - A meta-compiler transforms the objective, repository facts, and authority boundaries into a structured `Prompt IR (v1)`.
   - **The Intent Reconciler Guard** inspects the contract before execution. If a model hallucinates unauthorized side effects (e.g., production deployment, creating PRs) or weakens proof requirements, the run is blocked or repaired immediately.

3. **Adaptive Routing & Blueprinting:**
   - Workloads are classified into tiers (`T0` to `T3`) based on complexity, uncertainty, risk, and blast radius.
   - Tasks are broken down into dependency-gated blueprints (`TASK-1`, `TASK-2`, etc.) with strict allowed/protected path constraints.

4. **Isolated Role Execution & Live In-Chat Relay:**
   - Specialized roles (`explorer`, `planner`, `implementer`, `reviewer`) are dispatched with model-specific rendered prompts (`gpt56-outcome-v1`, `claude-review-v1`).
   - The **In-Chat Relay (`proofloop-core relay`)** streams observed role, model, phase, check, and recovery events directly into your host CLI session (AGY, Claude Code, or Codex) without exposing private provider reasoning (`thinking` redaction).

5. **Truth Engine & Evidence Verdict:**
   - No completion claim is accepted without evidence. The deterministic kernel verifies parent-owned checks, diff scope integrity, and test non-weakening.
   - Outputs an authoritative verdict: `PROVEN`, `PARTIAL`, `FAILED`, or `BLOCKED`.
```

---

### 📍 [제안 B] 섹션 2: "Adaptive Lanes & First-Diff Guard" 보강
> **위치:** 기존 `### When does ProofLoop escalate to a stronger role or model?` 테이블 상단/하단
> **목적:** 초기 분류뿐 아니라 구현 중 diff가 발생했을 때 동적으로 에스컬레이션되는 **First-Diff Reclassification Guard**와 **Task Blueprint** 설명 추가

#### 제안 내용:
* **First-Diff Reclassification Guard:** 처음에 단순(`T0`/`T1`)으로 분류된 작업이라도, 구현자가 만든 첫 번째 Diff가 보안/결제/동시성 경계를 건드리거나 3개 이상의 루트/4개 이상의 파일을 변경하면 즉시 `T2`/`T3`로 동적 승격(`Reclassify`)되고 독립 검토자(`Reviewer`)가 의무 할당됨을 명시.
* **Blueprint Task Boundaries:** 단일 프롬프트로 전체 코딩을 지시하지 않고, 독립적인 과제 단위(`TASK-1: 재현 테스트 추가`, `TASK-2: 경계 구현`, `TASK-3: 계약 검증`)로 의존성을 제어함을 추가.

---

### 📍 [제안 C] 섹션 3: "Bounded Recovery & Failure Fingerprinting" 신설/보강
> **위치:** 기존 `## Why ProofLoop exists` 직전 또는 `## How does that help me?` 연계
> **목적:** 무한 루프나 토큰 낭비를 막는 실패 지문 판별 및 상태 기계(`Recovery FSM`)의 강점 부각

#### 제안 내용:
```markdown
### Bounded Recovery via Failure Fingerprints

When a check fails, ProofLoop does not blindly ask the model to "try again." It constructs a **Failure Fingerprint** (`category + signature`) to govern recovery:

- **Targeted Fast Retries:** Up to two fast attempts allowed for local code/test fixes (`implementer_fast`).
- **Recovery Controller Escalation:** If the same failure fingerprint repeats, the runtime halts naive retries and switches to a dedicated `recovery` role with deeper context and historical contradiction analysis.
- **Structural Re-planning:** If the failure fingerprint indicates `DESIGN_CONFLICT`, `SPEC_AMBIGUITY`, or `CONTRACT_CHANGE`, work is automatically routed back up to the strong planner (`planner_deep`) instead of burning tokens on implementation retries.
- **Budget Exhaustion:** Every run has a strict token and attempt budget (`Budgeted Tokens`). If recovery limits are reached, the run terminates honestly as `FAILED` with full evidence history.
```

---

### 📍 [제안 D] 섹션 4: "Host Parity & Honest Capability Accounting" 확장
> **위치:** `## Testing in Codex, Claude Code, and Antigravity` 또는 `## Getting started`
> **목적:** 3대 호스트(`codex`, `claude`, `agy`)의 동작 차이와 모델 증거 기록(`model-trace.jsonl`)의 정직성 계약 명시

#### 제안 내용:
* **Honest Model Trace (`CLI_REQUESTED_ONLY` vs Explicit):**
  - Codex 및 Claude Code는 역할별로 명시적 모델(`--model` 또는 환경 변수)을 요청할 수 있으며, 실제 Provider가 응답한 헤더/로그가 확인되어야만 관측 모델(`observedModel`)로 인정됨을 명확히 기술.
  - AGY CLI(`Antigravity integration`)는 세션 모델을 공유하므로 `ROLE_ROUTING_ONLY` 모드로 동작하며, 요청 모델을 속이지 않고 정직하게 `requested-only` 및 `candidate substitution` 상태로 기록함을 표기.
* **Unified Clean Reinstall:** `python3 scripts/install.py --host all`을 통해 레거시 찌꺼기를 정리하고 3대 호스트 어댑터 및 CLI 중계(`relay`) 메커니즘을 한 번에 동기화할 수 있음을 강조.

---

### 📍 [제안 E] 섹션 5: "The Truth Engine & Expected Output Verification" 신설
> **위치:** `## Visible execution, model changes, and artifacts` 하단
> **목적:** 이 도구가 왜 단순 프롬프트 래퍼가 아닌지 증명하는 10대 기계적 검증 기준(`expected-output-report.json`) 소개

#### 제안 내용:
```markdown
### Mechanical Verification: The Expected Output Contract

Every completed run emits `expected-output-report.json`, a mechanical audit verifying that the runtime observed strict proof and observability discipline across 10 checkpoints:

1. `repository_binding`: Run, request envelope, and grounding snapshot point to the exact target repository root.
2. `immutable_request`: Raw user request and SHA-256 hash are preserved without alteration.
3. `intent_and_authority_visibility`: IntentGate authority classifications are recorded and emitted.
4. `refined_intent_contract`: Objectives, observable acceptance criteria, and authority boundaries are inspectable.
5. `grounding_wave_zero`: Preflight facts and verified test commands are retained.
6. `strategy_and_execution_brief`: Workload tier (`T0-T3`) and scoped brief are documented.
7. `observable_role_progress`: Active phase transitions and rendered prompt IRs are inspectable.
8. `model_trace_honesty`: Requested vs. observed model traces are recorded without false claims.
9. `private_reasoning_redacted`: All host logs have provider private reasoning/thinking blocks completely scrubbed.
10. `evidence_backed_truth_verdict`: The terminal `PROVEN`, `PARTIAL`, `BLOCKED`, or `FAILED` verdict is backed by concrete check, diff, review, and token usage artifacts.

You can mechanically audit any run yourself using:
```bash
python3 scripts/verify_expected_output.py .proofloop/runs/<run-id> --require-terminal
```
```

---

## 3. 요약 및 기대 효과 (Summary of Proposal)

| 기존 README 구성 | 제안하는 개편 방향 (`PROPOSAL_README_ARCHITECTURE_UPDATE.md`) | 주요 기대 효과 |
| :--- | :--- | :--- |
| `v0.4.0-alpha` 및 기본 개념 소개 | **"Grounded Prompt Compiler & IR v1", "Intent Reconciler"** 파이프라인 전면 배치 | 단순 "다중 모델 사용 도구"라는 오해를 없애고, 저장소 사실을 바탕으로 안전하게 작동하는 프롬프트 컴파일러임을 각인 |
| T0~T3 에스컬레이션 표 | **"First-Diff Guard"** 및 **"Blueprint Task Graph"** 의존성 설명 추가 | 코딩 도중 위험이 발견되면 즉시 검증 단계를 강화하는 동적 안전망 강조 |
| 일반적인 복구 및 재시도 언급 | **"Failure Fingerprint-Based Recovery FSM"** 및 예산 한계 명확화 | 무한 재시도로 토큰을 낭비하지 않고 원인 규명(Re-plan)으로 회귀하는 효율성 입증 |
| CLI 실행 결과 파일 목록 | **"In-Chat Relay" (Redaction 보장)** 및 **"10대 Expected Output 검증"** 섹션 신설 | 어떤 호스트에서든 비공개 추론 유출 없이 깔끔하게 중계되며, 기계가 판정한 증명서가 발행됨을 명확히 전달 |
