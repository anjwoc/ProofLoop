# Security and Sandbox Threat Model

상태: `DRAFT_BY_REVIEWER` (Sol이 주 설계자이나 Opus가 초안 작성, Sol 재작성 필요)  
주 설계: GPT-5.6 Sol  
독립 리뷰: Claude Opus

## 1. 문제

ProofLoop는 외부 모델을 호출하고 그 출력으로 파일을 변경한다. 권한 관리, prompt injection
방어, secret 보호, artifact 변조 감지를 위한 위협 모델이 필요하다.

## 2. 위협 범위

### 2.1 Prompt Injection

- 모델 출력이 Core 명령을 주입할 수 없다.
- 역할 프롬프트에 다른 역할의 출력을 raw로 삽입하지 않는다 (role view가 이를 방지).
- Repository file content가 prompt를 통해 주입 가능 → protected path와 scope 제한으로 완화.

### 2.2 Secret 보호

- Raw stream에 secret이 포함될 수 있다 → persistence 전 redaction 필수 (H-02 교정).
- Environment variable은 프롬프트에 삽입하지 않는다.
- Artifact에 secret pattern을 감지하면 저장을 차단한다.

### 2.3 Artifact 변조

- 모든 권위 artifact는 canonical hash로 integrity를 검증한다.
- 모델 출력은 검증 전까지 candidate이다 (H-01 불변 조건).
- Proof graph는 append-only이며 기존 entry를 삭제하지 않는다.

### 2.4 권한 격리

- 각 역할은 명시된 permission scope 내에서만 동작한다.
- `implementer_fast`와 `implementer_recovery`만 workspace-write 권한.
- `explorer_fast`와 `reviewer_deep`은 read-only.
- `planner_deep`은 plan 전용, mutation 금지.

### 2.5 Sandbox

- Docker evaluator (G-07)는 clean container에서 실행.
- Evaluator는 read-only file system, network 차단.
- Host process는 ProofLoop core와 별도 process.

## 3. 불변 조건

1. 모델은 Core policy를 변경할 수 없다.
2. Secret은 artifact에 저장되지 않는다.
3. Protected path는 모든 tier에서 변경 불가능하다.
4. Read-only 역할은 filesystem write를 수행하지 않는다.
5. Evaluator container는 네트워크 접근이 없다.

## 4. 구현 슬라이스

1. G-07: Docker evaluator (read-only sandbox)
2. G-15: clean install 격리 검증
3. G-16: CI artifact 무결성
4. G-17: live CLI redaction

## 5. 설계 provenance

- 현재 runtime permission model, artifact hash 검증 코드 기반
- 이 초안은 Opus가 작성했으며 Sol이 주 설계자로서 재작성·보완해야 한다
