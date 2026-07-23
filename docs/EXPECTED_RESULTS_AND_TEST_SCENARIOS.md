# ProofLoop 기대 결과와 테스트 시나리오

이 문서는 ProofLoop가 사용자에게 무엇을 보여야 하는지와 Codex·Antigravity에서 그 약속을 어떻게 검증하는지를 정의한다. MCP 응답과 artifact의 필드 계약은 [expected-output.md](roadmap/expected-output.md)가 기준이다. 전체 구간의 입력·판단·실패 분기는 [파이프라인 실행 가이드](PIPELINE_EXECUTION_GUIDE.md)를 따른다. 이 문서는 그 계약을 사람이 실행하고 판정하는 방법이다.

## 성공의 정의

에이전트가 "완료했다"고 말한 것은 성공이 아니다. ProofLoop의 성공은 다음 순서를 모두 관찰하고, 마지막에 현재 실행의 증거로 Truth가 판정한 경우다.

```text
사용자 요청
  → Intent: 요청·범위·제외 대상 공개
  → Strategy: 실행 경로와 근거 공개
  → Contract: 허용 파일과 성공 조건을 변경 전에 동결
  → Implement: 변경 이유와 경로 공개
  → Verify: Core가 소유한 검사 결과 공개
  → Review: 범위·단순성·리뷰 결과 공개
  → Truth: 증거 기반 최종 판정
```

각 단계는 `events.jsonl`에 남고, MCP 클라이언트는 `proofloop_run_status`로 같은 이벤트를 순서대로 받는다. 일반 정보 출력에서는 내부 프롬프트 조립이나 역할 간 잡음 대신 아래와 같은 결정과 결과가 보여야 한다. 내용과 파일 수는 작업마다 달라진다.

```text
[ProofLoop][INTENT] 태양계 시뮬레이션 구현 요청으로 판단했습니다.
  근거: 새 디렉터리와 실행 가능한 웹 결과물 요청
  대상: example/**
  제외: 기존 ProofLoop 소스

[ProofLoop][STRATEGY] 계획형 구현을 선택했습니다.
  근거: HTML·CSS·JS 변경과 브라우저 검증이 함께 필요함
  예상 변경: 3개 파일
  검증 계획: 5개

[ProofLoop][CONTRACT] 작업 계약을 확정했습니다.
  구현: example/index.html
  구현: example/style.css
  구현: example/app.js
  성공 조건: 브라우저에서 로드되고, JavaScript 구문과 애니메이션 증거가 통과한다.
  성공 조건: Three.js 라이브러리 참조와 런타임 사용 증거가 통과한다.

[ProofLoop][IMPLEMENT] 화면 구조를 구현합니다.
  근거: Canvas와 제어 패널이 필요함
  변경: example/index.html

[ProofLoop][VERIFY] ✓ static-web-browser-load · 브라우저 로드
[ProofLoop][VERIFY] ✓ static-web-animation · 애니메이션 확인
[ProofLoop][REVIEW] ✓ 범위·변경 예산 준수
[ProofLoop][TRUTH] PROVEN
  변경: 3개 파일
  검증: 5/5 통과
```

위 표시는 단계별로 **왜 다음 행동을 하는지**, **어느 파일이 대상인지**, **무엇으로 끝을 판정하는지**를 보여 주는 계약이다. `verbose`와 `debug`에서는 명령·artifact 경로 같은 추가 증거를 볼 수 있지만, provider의 private reasoning은 출력하거나 저장하지 않는다.

## 최종 상태의 해석

| 상태 | 의미 | 사용자에게 남아야 하는 것 |
| --- | --- | --- |
| `PROVEN` | 허용 범위의 변경이 현재 검증·리뷰·proof evidence를 통과했다. | `truth-report.json`, `run-outcome.json`, `checks/checks.json`, `review.json`, `events.jsonl` |
| `PARTIAL` | 실행은 끝났지만 일부 주장이 증명되지 않았다. 성공으로 취급하지 않는다. | 증명되지 않은 항목과 evidence 경로 |
| `NEEDS_INPUT` | 사용자의 답 하나가 범위·권한·성공 조건을 정할 수 있어 Truth 전에 멈췄다. | `input-request.json`의 질문; MCP에서는 `proofloop_answer_question`으로 답한 뒤 새 continuation run 시작 |
| `BLOCKED` | 인증, 네트워크, 권한, 제공자 응답 등 외부 상태 때문에 의미 있는 다음 진행을 할 수 없다. | 구체적인 blocker와 재시도 전 필요한 외부 조치 |
| `FAILED` | 구현·검증·범위 계약이 실패했다. | 실패한 검사 또는 위반과 artifact 경로 |
| 시스템 오류 | ProofLoop 자체가 Truth 전에 실패했다. 이는 작업 실패 판정으로 위장하지 않는다. | `run-error.json`; Truth verdict와 `truth-report.json`은 만들지 않는다. |

`BLOCKED`는 단순히 오래 걸렸다는 뜻이 아니다. 예를 들어 호스트가 초기 출력을 주지 못해 timeout이 났다면, 실제 단조 시계 기준으로 경과한 시간이 evidence에 남아야 한다. 3초 만에 `85s`처럼 표시되는 것은 허용되지 않는다.

## 테스트 시나리오

### 1. 결정론적 회귀 테스트

테스트는 바꾼 약속을 직접 검증해야 한다. 정적 웹 계약을 바꾼 경우의 기본 게이트는 다음과 같다.

```bash
python3 -m pytest \
  tests/deterministic/test_direct_bootstrap.py \
  tests/deterministic/test_task_brief.py \
  tests/deterministic/test_verification_plan.py \
  tests/deterministic/test_static_web.py \
  tests/deterministic/test_orchestrator_smoke.py::test_static_web_uses_core_contract_and_emits_visible_progress_before_host_work \
  tests/deterministic/test_orchestrator_smoke.py::test_contract_violation_does_not_spend_a_recovery_call \
  tests/deterministic/test_orchestrator_smoke.py::test_failed_core_check_is_failed_without_a_second_model_call \
  tests/deterministic/test_orchestrator_smoke.py::test_owner_decision_pauses_for_input_instead_of_claiming_blocked \
  tests/deterministic/test_orchestrator_smoke.py::test_spec_ambiguity_after_a_real_failed_check_requests_owner_input \
  tests/deterministic/test_mcp_control_plane.py::test_mcp_can_resume_a_question_with_an_owner_answer \
  -q
python3 scripts/validate_package.py
```

첫 명령은 실제 Core 경로를 직접 증명한다. Three.js 요구와 정제본이 계약·implementer prompt에 들어가는지, 빈약한 Three.js 주장이나 구문 오류가 거절되는지, 검사 실패와 변경 계약 위반이 두 번째 모델 호출 없이 `FAILED`로 끝나는지, 그리고 답변 가능한 모호성은 MCP 질문과 continuation으로 바뀌는지를 확인한다. `validate_package.py`는 수정한 코드가 설치본에 포함되는지만 확인한다. 전체 회귀 스위트는 광범위한 회귀 점검일 뿐, 이 기능의 수용 증거로 대체하지 않는다.

### 2. Antigravity 키체인·인증 smoke test

이 테스트는 Antigravity를 완전히 재시작한 뒤, 이미 로그인된 계정으로 실행한다. 기존 팝업이 떠 있으면 **취소**하고, "기본값으로 재설정"을 누르지 않는다.

테스트는 변경해도 되는 별도 작업 공간에서 실행한다.

```text
/proofloop example 디렉토리에 태양계 시뮬레이션 웹을 구현해줘.
```

기대 결과:

- Google OAuth 로그인 창이나 macOS "키체인을 찾을 수 없음" 팝업이 나타나지 않는다.
- `runtime agy` 또는 Antigravity 역할 실행이 보이고, 모델은 host가 구조화된 증거를 제공할 때만 `VERIFIED`로 표시된다. AGY가 모델 해상도를 제공하지 않으면 `CLI_REQUESTED_ONLY` / `UNPROVEN`은 정직한 정상 표시다.
- `example/index.html`, `example/style.css`, `example/app.js` 계약이 구현 전 동결된다.
- `static-web-structure`, `static-web-javascript-syntax`, `static-web-browser-load`, `static-web-animation`, `static-web-interaction-wiring` 검사가 실행된다. Three.js 요청에서는 JavaScript 검사에 실제 라이브러리 참조와 런타임 사용 확인이 함께 들어간다.
- 모든 검사가 통과하고 범위 검토도 통과한 경우에만 `PROVEN`이 나온다.

이 profile은 웹 문서 구조, JavaScript 구문, 브라우저 로드, 화면 변화, 확대·이동 wiring을 검증한다. **8개 행성이 시각적으로 정확히 렌더링됐다는 의미 검증까지 자동으로 보장하지는 않는다.** 그 요구가 중요하면 Canvas 요소 수나 브라우저 E2E assertion을 TaskBrief의 명시적 검사로 추가해야 한다.

다시 Google 로그인이나 키체인 팝업이 뜨면 다음을 실패 증거로 보존한다.

- 실행 시각과 Run ID
- 팝업 화면
- `<runDir>/invocations/*/stderr.log`
- `<runDir>/events.jsonl`

기대되는 macOS 격리 경계는 인증용 실제 사용자 `HOME`을 유지하면서 `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`, `XDG_STATE_HOME`만 invocation sandbox로 격리하는 것이다.

### 3. 인증된 host acceptance test

설치된 호스트 CLI와 실제 인증 상태를 함께 검증하려면 다음 live runner를 사용한다.

```bash
python3 scripts/run_host_live.py --host antigravity --scenario normal --keep-workspace
```

`normal`은 `PROVEN` Truth report와 `expected-output-report.json`의 `status: PASS`가 모두 있어야 통과다. 이 호출은 실제 모델 토큰을 사용하므로, 정상 수용 실행은 한 번만 수행한다. `recovery` 시나리오는 의도적으로 실패·재호출을 만드는 비용 실험이므로, 정상 흐름이 증명된 뒤 별도 예산을 승인했을 때만 실행한다.

### 4. timeout 표시 검증

호스트의 초기 응답 timeout을 시험할 때는 진짜 경과 시간을 측정한다. 짧은 실험에는 환경변수로 임계값을 낮춘다.

```bash
PROOFLOOP_AGY_INITIAL_OUTPUT_TIMEOUT_SECONDS=15 \
python3 scripts/run_host_live.py --host antigravity --scenario normal --keep-workspace
```

기대 결과는 heartbeat의 `elapsedSeconds`가 실제 시간에 따라 단조 증가하는 것이다. timeout이 발생하면 `BLOCKED`에는 제공자 초기 응답 부재와 실제 timeout 값이 포함되어야 하며, 과거 heartbeat 횟수를 초 단위로 잘못 환산해서는 안 된다.

## 설치 후 테스트 전 확인

소스 수정은 설치본에 자동 반영되지 않는다. 런타임이나 host adapter를 변경한 뒤에는 해당 host를 다시 설치하고 앱을 재시작한다.

```bash
python3 scripts/install.py --host antigravity --scope user --without-tokscale
```

Codex와 Antigravity를 함께 갱신해야 하면 `--host all`을 사용한다. 설치 후에는 새 작업에서 테스트한다. 이미 시작된 자식 프로세스는 이전 환경과 이전 실행 파일을 유지한다.

## 실패 보고에 필요한 최소 정보

실패를 재현 가능한 개선 항목으로 만들려면 아래 네 가지를 함께 제공한다.

1. 입력한 `/proofloop` 요청 원문
2. Run ID와 터미널의 마지막 30줄
3. `truth-report.json` 또는 `run-error.json`
4. 팝업·브라우저 오류가 있으면 화면과 해당 invocation의 `stderr.log`

이 정보가 있어야 `BLOCKED`, task-level `FAILED`, ProofLoop 시스템 오류, host 인증 오류를 섞지 않고 수정할 수 있다.
