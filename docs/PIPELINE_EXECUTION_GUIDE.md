# ProofLoop 파이프라인 실행 가이드

## 한 문장 원칙

**Simple is best.** ProofLoop는 모델에게 한 번의 명확한 일을 맡기고, Core가 확인할 수 있는 사실만으로 결과를 판정한다. 모델 호출을 늘려서 불확실성을 덮지 않는다.

이 문서는 `/proofloop` 요청이 들어온 뒤 어떤 구간을 지나며, 각 구간이 무엇을 결정하고, 실패하면 어디서 멈추는지를 설명한다. 사람에게 보이는 예시 출력과 실제 Antigravity 수용 절차는 [기대 결과와 테스트 시나리오](EXPECTED_RESULTS_AND_TEST_SCENARIOS.md)를 따른다.

## 전체 흐름

```text
요청
  → 입력·권한 확인
  → Intent 정제
  → Strategy
  → Contract
  → Implement (모델 1회)
  → Verify
  → Review
  → Truth
```

각 화살표는 다음 단계가 이전 단계의 artifact를 읽는다는 뜻이다. 모델의 자연어 요약은 다음 단계의 성공 근거가 아니다.

## 단계별 동작

| 단계 | Core가 하는 일 | 다음 단계로 가는 조건 | 멈추는 경우와 결과 |
| --- | --- | --- | --- |
| `INIT` | 요청 원문과 해시를 저장한다. | 요청이 비어 있지 않다. | 원문을 보존할 수 없으면 시스템 오류다. |
| `PREFLIGHT` | repository와 Git 상태를 확인한다. 기존 코드를 넓게 분석해야 할 때만 CodeGraph를 준비한다. | 작업 공간을 식별할 수 있다. | Git 작업 폴더를 고르면 해결되는 문제면 `NEEDS_INPUT` 질문을 먼저 남긴다. |
| `INTENT` | 원문을 보존한 채 목표, 대상 경로, 제외 대상, 권한을 계약으로 만든다. | 변경 권한과 대상이 분명하다. | 범위·권한이 답변으로 정해질 수 있으면 `NEEDS_INPUT`으로 멈춘다. |
| `STRATEGY` | 읽기 전용 분석인지, 계획이 필요한 구현인지, 고위험 작업인지를 고른다. | 필요한 역할과 검증 경로가 정해진다. | 고위험 권한이 없으면 외부 변경을 호출하지 않는다. |
| `CONTRACT` | 허용 파일, 성공 조건, 변경 예산, 검사를 변경 전에 동결한다. | 계약이 schema를 통과한다. | 범위 변경이 필요하면 질문을 남긴다. schema 오류는 Core 결함으로 `FAILED`다. |
| `IMPLEMENT` | 계약과 작업 공간만 구현 역할에 전달한다. | 역할이 종료한다. | 인증·네트워크·provider 문제가 첫 호출에서 나면 `BLOCKED`로 종료한다. 자동으로 다른 역할을 부르지 않는다. |
| `VERIFY` | Core가 검사 명령, 브라우저 확인, diff guard를 실행한다. | 모든 필수 검사가 통과하고 계약 범위를 지킨다. | 검사 실패는 `FAILED`다. diff 위반은 즉시 `FAILED`이며 자동 모델 재시도가 없다. |
| `REVIEW` | deterministic fast lane 또는 필요한 독립 리뷰로 범위와 단순성을 확인한다. | 승인 증거가 있다. | 리뷰가 승인하지 않으면 그 근거가 남는다. |
| `TRUTH` | 현재 run의 검사·diff·리뷰 evidence를 묶어 `PROVEN`, `PARTIAL`, `FAILED`, `BLOCKED` 중 하나를 판정한다. | 부모 소유 evidence가 완전하다. | 증거가 없으면 성공이라고 말하지 않는다. `NEEDS_INPUT`은 Truth 이전의 질문 대기라 Truth verdict가 아니다. |

## 답변이 필요한 경우

`BLOCKED`와 `NEEDS_INPUT`은 다르다.

- `NEEDS_INPUT`: 사용자의 선택이나 정보 한 가지가 다음 행동을 정할 수 있다. 예: “분석만 할까요, 파일을 수정해도 될까요?”
- `BLOCKED`: 로그인, provider 장애, 네트워크처럼 말 한마디로 현재 프로세스를 고칠 수 없는 외부 상태다.

MCP를 쓰는 경우 Core는 `input-request.json`과 `input.required` 이벤트로 질문을 즉시 보낸다. 클라이언트는 `proofloop_answer_question(session_id, answers)`로 답한다. 이전 run은 변경하지 않고, 원문과 답변을 함께 보존한 새 continuation run을 시작한다. 답변이 의미 없는 자동 재시도를 허용하지는 않는다.

## 요청 정제 레이어

원문 요청은 `request-envelope.json`에 변경 없이 남는다. `IntentContract`는 이를 다음처럼 짧고 구조화된 Markdown으로 바꾼다.

```text
Objective
Acceptance Criteria
Constraints
Non-Goals
Unknowns
```

이 정제본은 explorer, planner, implementer, reviewer의 `Goal`과 context에 들어간다. 정적 웹 템플릿처럼 planner를 건너뛰는 경우에도 implementer prompt projection에 정제본, 허용 파일, Core-owned check ID가 함께 남는다. 따라서 `prompt-projections/*implementer_fast.md`에서 실제 전달 여부를 확인할 수 있다.

## 계약을 만드는 두 경로

### 정적 웹 템플릿

`example/` 아래에 HTML/CSS/JS 웹 결과물을 만드는 요청은 Core가 이미 아는 작은 형태다. 이 경로는 아래 계약을 즉시 만든다.

```text
허용 파일: example/index.html, example/style.css, example/app.js
성공 조건: 웹 구조, JavaScript, 브라우저 로드, 애니메이션, 상호작용
추가 조건: 요청에 Three.js가 있으면 실제 라이브러리 참조와 런타임 사용
변경 예산: 파일 3개, 새 파일 3개, 의존성 추가 금지
기본 모델 호출: 1회
기본 자동 복구 호출: 0회
```

이 요청이 “복잡하다”는 표현을 포함해 T2로 분류되어도 planner와 reviewer 역할을 먼저 호출하지 않는다. Core가 이미 파일·검사·범위를 알고 있기 때문이다. 구현 역할 한 번과 Core 검증만 실행한다.

줄 수 상한은 없다. 파일 범위와 의존성 금지가 계약을 지키고, 불필요하게 큰 구현은 Ponytail 단순성 검토에서 찾아낸다. 범위가 더 크면 이 템플릿을 쓰지 않고 계획 경로로 간다.

### 그 밖의 구현

파일 하나를 고쳤다고 해서 `1,500줄` 같은 일반 상한을 자동으로 만들지 않는다. 비정적 직접 요청은 planner가 실제 대상·성공 조건·변경 예산을 계약으로 작성한 뒤에만 구현을 시작한다. 따라서 사용자가 보지 못한 공통 line cap 때문에 완료된 작업이 실패하는 경로는 없다.

## 실패와 재시도

재시도는 성공 확률이 아니라 비용을 먼저 고려한다.

1. 기본 계약은 `maxFastAttempts: 1`, `maxRecoveryAttempts: 0`이다.
2. 계약이 명시적으로 더 큰 수를 선언한 경우에만 검사 실패 후 재시도를 고려한다.
3. 허용 경로·파일 수·명시적으로 설정한 줄 수·의존성 계약을 위반하면 즉시 `TASK_CONTRACT_VIOLATION`으로 종료한다. 두 번째 모델 호출은 하지 않는다.
4. 첫 모델 호출 자체가 인증·네트워크·provider 문제로 막히면 `BLOCKED`다. 구현 실패로 바꾸지 않는다.
5. `BLOCKED`는 “다시 해보면 될 것 같다”는 뜻이 아니다. 필요한 외부 조치가 구체적으로 적혀야 한다.

과거의 문제는 1차 구현이 line budget을 넘은 뒤 fast/recovery 호출을 다시 시작했고, 그 두 번째 호출의 AGY timeout이 원래 위반을 가린 것이었다. 현재 경로는 첫 위반에서 멈춘다.

## 제한 감사

| 항목 | 현재 정책 | 이유 | 실패했을 때 |
| --- | --- | --- | --- |
| 일반 직접 작업 `1,500줄` | 제거 | 요청 크기와 무관한 숫자였다. | planner가 범위별 계약을 만든다. |
| 검사 기본 `300초` | 제거 | 검사마다 필요한 시간은 다르다. | 명시한 deadline이 없으면 Core가 임의의 300초 cap을 붙이지 않는다. |
| Core 주입 검사 `600초` | 제거 | Core 검사에만 다른 숨은 기본값을 주는 것은 일관되지 않다. | 검사 자체가 가진 실패 근거를 기록한다. |
| 기본 fast/recovery 재시도 `2/1` | `1/0` | 실패 증거 없이 모델을 더 부르는 비용을 막는다. | 사용자가 명시한 계약만 추가 시도를 허용한다. |
| 정적 웹 줄 수 상한 | 제거 | 세 파일이라는 명시 범위로 충분하다. | Ponytail이 불필요한 복잡성을 검토한다. |
| 역할별 `300초` cap | 제거 | tier가 구현 시간을 몰래 줄여서는 안 된다. | run을 시작할 때 선택한 deadline을 모든 역할에 동일하게 쓴다. |
| CodeGraph `300초` cap | 제거 | 인덱싱은 repository 크기에 따라 다르다. | `PROOFLOOP_CODEGRAPH_TIMEOUT_SECONDS`를 명시했을 때만 deadline을 둔다. |
| intent classifier `30초` cap | 제거 | 분류 단계만 몰래 짧게 끝내면 이후 경로가 왜곡된다. | 같은 run deadline을 쓴다. |
| skill `maxSeconds: 300` 기본값 | 제거 | skill metadata가 실행 시간을 암묵적으로 정하면 안 된다. | skill이 명시한 값만 기록하며 실행을 끊지 않는다. |
| 브라우저 로드 15초, JavaScript 구문 검사 30초 | 유지, verifier 내부 | 멈춘 Chrome/Node 프로세스를 회수하기 위한 짧은 검사 deadline이다. 작업 전체 시간 제한이 아니다. | 해당 검사는 `FAIL`이고 원인을 기록한다. |
| 애니메이션 browser virtual time 0.1초·1.5초 | 유지, verifier 내부 | 서로 다른 두 시점의 화면이 실제로 달라졌는지 비교하기 위한 관찰 시점이다. | 화면 변화가 없으면 해당 검사는 `FAIL`이다. |
| AGY 첫 출력 deadline | 기본값 없음 | 이전 90초 계수는 잘못된 차단을 만들었다. | 사용자가 `PROOFLOOP_AGY_INITIAL_OUTPUT_TIMEOUT_SECONDS`를 명시했을 때만 적용한다. |
| host 전체 timeout | 호출자가 명시한 값 | 무한 대기를 막는 운영 경계다. 기본 CLI 값은 설정에서 바꿀 수 있으며, `--print-timeout`으로 AGY에 전달된다. | 실제 단조 시계 elapsed와 timeout 이유를 남긴 `BLOCKED`다. |
| event 출력 4,000자 | 유지, 화면 출력만 | 터미널·MCP 메시지가 폭주하지 않게 한다. 원본 stdout/stderr artifact는 그대로 보존한다. | 결과 판정에는 영향을 주지 않는다. |
| 토큰 tier 값 | skill 선택 예산 | 어느 skill reference를 주입할지 고르는 값이지 host 실행을 강제 종료하는 값은 아니다. | 선택되지 않은 skill은 이유와 함께 기록한다. |

## Hook과 MCP의 역할

Hook과 MCP는 실행을 빠르게 만드는 마법이 아니다. 책임을 분명하게 나누는 장치다.

```text
MCP 요청 → ProofLoop Core → host adapter → AGY/Antigravity
                 ↓                  ↑
            events.jsonl ← relay ← host stream
```

- MCP는 요청·상태·artifact를 즉시 전달한다.
- host adapter는 AGY/Antigravity를 실행할 뿐, Truth를 결정하지 않는다.
- macOS에서 AGY/Antigravity는 실제 사용자 `HOME`을 유지한다. Keychain이 로그인 keychain을 찾게 하기 위해서다. XDG 상태만 invocation sandbox에 격리한다.
- Stop hook은 부모 Core가 Truth를 만들기 전에 자식 역할을 다시 호출하지 않도록 한다.
- 파일 탐색은 기존 repository를 분석할 때 CodeGraph를 먼저 사용한다. 새 결과물을 처음 만드는 경우에는 탐색할 기존 코드가 없으므로 CodeGraph가 필수는 아니다.

Hook은 Google OAuth를 통과시키거나 provider가 응답하도록 만들 수 없다. 로그인, 계정 권한, 네트워크 문제는 host가 해결해야 한다. ProofLoop의 책임은 그것을 `FAILED`로 위장하거나 재시도로 토큰을 소모하지 않는 것이다.

## 무엇이 증명됐고, 무엇이 아직 남았는가

결정론적 검증으로 증명할 수 있는 것:

- Three.js 요청이 계약과 검사에 들어간다.
- 정제본이 static implementer의 실제 prompt projection에 들어간다.
- 사용자 답변이 필요한 요청은 `BLOCKED` 대신 `NEEDS_INPUT` artifact와 질문으로 멈춘다.
- 주석만 있는 가짜 Three.js 주장은 통과하지 않는다.
- 비정적 직접 요청에 공통 1,500줄 계약을 만들지 않는다.
- timeout을 생략한 검사에 300초를 몰래 넣지 않는다.
- 변경 계약 위반은 두 번째 모델 호출 없이 `FAILED`로 끝난다.
- 설치 패키지에 현재 runtime 파일이 포함된다.

실제 인증된 Antigravity 실행으로만 증명할 수 있는 것:

- 계정이 로그인 상태에서 AGY가 실제로 역할 결과를 돌려준다.
- Keychain/OAuth 팝업 없이 host가 시작된다.
- 실제 요청이 `PROVEN`까지 도달한다.

따라서 수용 실행은 로그인된 Antigravity에서 한 번만 실행한다. 이 실행이 실패하면 같은 요청을 자동 반복하지 않고 Run ID, `events.jsonl`, `stderr.log`, `truth-report.json`을 근거로 다음 수정을 결정한다.
