# ProofLoop Skill-First Core

ProofLoop는 한 번 설치한 뒤 한 줄로 호출하면 **작업 분류, 역할별 모델 호출, 실제 검증, 제한된 복구 루프, 독립 리뷰, 진실성 판정**을 자동 수행하는 소프트웨어 엔지니어링 Skill Harness다.

현재 버전은 **v0.4.0-alpha 개발본**이다. 자동 orchestrator와 결정론적 검증은 구현됐지만, 인증된 실제 Codex/Antigravity 모델 실행 증거는 아직 사용자 환경에서 확인해야 한다. 따라서 전체 릴리스 상태는 `FAIL`을 유지한다.

## 사용자 경험

### Codex

```text
$proofloop 결제 중복 요청 문제를 수정해줘. 공개 API는 유지하고 실제 테스트를 실행해.
```

또는 `/skills`에서 `proofloop`를 선택한다.

### Antigravity

```text
/proofloop 결제 중복 요청 문제를 수정해줘. 공개 API는 유지하고 실제 테스트를 실행해.
```

### Claude Code

```text
/proofloop 결제 중복 요청 문제를 수정해줘. 공개 API는 유지하고 실제 테스트를 실행해.
```

사용자는 `invoke-role`, `record-attempt`, `verify-run` 같은 내부 명령을 직접 실행하지 않는다.

## 실제 동작

```text
/proofloop 요청
→ proofloop-core orchestrate
→ preflight 및 Git baseline
→ 작업 전략 선택
→ 역할별 격리된 호스트 CLI 호출
→ 실제 test/build/typecheck 명령 실행
→ diff/test-integrity/변경 예산 검사
→ 실패 fingerprint 계산
→ fast 재시도 또는 recovery 승격
→ 독립 reviewer
→ hallucination/anti-bloat/truth gate
→ PROVEN | UNPROVEN | FAILED | BLOCKED
```

현재 구현된 mutation 전략:

- `DIRECT_VERIFIED_CHANGE`: 작고 명확한 변경. Deep planner를 생략할 수 있다.
- `PLANNED_IMPLEMENTATION`: deep planner → fast implementer → 검증 → reviewer.
- `HIGH_RISK_ENGINEERING`: 결제·동시성·보안 등 고위험 변경에 더 엄격한 계획과 리뷰를 적용한다.

`REPOSITORY_ANALYSIS` 전용 orchestration은 아직 구현하지 않았다. 분석 요청을 받으면 허술한 보고서를 생성하지 않고 `ANALYSIS_ORCHESTRATION_NOT_IMPLEMENTED`로 차단한다.

## 실시간 실행 가시성

설치된 호스트 스킬은 자동으로 human stream을 사용한다. 화면에는 현재 단계, 역할, 요청/관찰 모델, 시도 횟수, 실제 검사 결과, recovery 이유, 리뷰 finding, 최종 Truth 상태가 표시된다. 동일한 이벤트 객체가 `.proofloop/runs/<run-id>/events.jsonl`에도 저장된다.

```bash
proofloop-core orchestrate --host codex --repo . --request-file request.txt \
  --output-format human --verbosity info --color auto
```

기계 소비자는 순수 JSON Lines를 선택할 수 있다. 하위 호환 기본값인 `quiet`은 최종 JSON 결과만 출력한다.

```bash
proofloop-core orchestrate --host codex --repo . --request-file request.txt --output-format jsonl
proofloop-core orchestrate --host codex --repo . --request-file request.txt --output-format quiet
```

다른 터미널에서는 같은 이벤트 스트림을 재생하거나 계속 따라갈 수 있다.

```bash
proofloop-core watch --run latest --repo . --format human
proofloop-core watch --run-dir .proofloop/runs/<run-id> --format jsonl --task TASK-001 --level warning
```

실제 모델이 관찰되지 않으면 requested-only로 표시하며 모델 라우팅은 `UNPROVEN`으로 유지한다. 전체 stdout/stderr는 run의 invocation 및 check artifact에 보존된다.

## 모델 역할

| 역할 | Claude 예시 | Codex 예시 | Antigravity 외부 모드 예시 |
|---|---|---|---|
| `planner_deep` | Opus/Fable | `gpt-5.6` | Gemini 3.1 Pro High |
| `implementer_fast` | Haiku | `gpt-5.6-terra` | Gemini 3.5 Flash Low |
| `implementer_recovery` | Sonnet | `gpt-5.6` | Gemini 3.1 Pro High |
| `reviewer_deep` | Fable/Opus | `gpt-5.6` | Gemini 3.1 Pro High |

설정된 모델명은 증거가 아니다. ProofLoop는 `requestedModel`과 `observedModel`을 구분하고, 호스트 출력에서 실제 모델이 관찰되지 않으면 모델 라우팅을 `UNPROVEN`으로 유지한다.

## Repair Loop

Orchestrator가 직접 다음을 소유한다.

```text
fast attempt 1
→ 실제 검사 실패
→ fresh fast attempt 2
→ 동일 fingerprint 반복
→ recovery model
→ 실제 검사
→ reviewer
```

리뷰가 `FIX_REQUIRED` 또는 `OVERBUILT`이면 recovery 구현 → 재검증 → 재리뷰를 한 번 수행한다. 예산을 소진하면 `BLOCKED`다.

## Truth·Hallucination·Anti-Bloat

- 실제 명령 exit code만 검사 결과로 인정한다.
- 테스트 삭제·skip·assertion 약화·범위 밖 수정·무단 의존성 변경을 차단한다.
- 변경 파일·추가 LOC·신규 파일 예산을 검사한다.
- reviewer의 `OVERBUILT` 판정은 테스트 통과와 무관하게 완료를 차단한다.
- 최종 FACT claim은 JSON evidence assertion과 일치해야 한다.
- 증거 없음은 `UNPROVEN`, 증거 모순은 `FAILED`다.

## 설치

```bash
unzip proofloop-skill-first-core-v0.4.0-alpha.zip
cd proofloop-skill-first-core-v0.4.0-alpha

python3 scripts/validate_package.py
./install.sh
python3 scripts/doctor.py
```

전체 호스트 설치:

```bash
./install.sh
```

`./install.sh`는 `python3`를 자동으로 찾아 사용자 범위의 전체 호스트를 clean install한다.
특정 호스트만 설치하려면 `./install.sh --host codex --scope user`처럼 기존 옵션을 그대로
전달하면 된다. `make install`과 `python3 ./scripts/install.py`도 같은 동작이며 npm 패키지는 필요 없다.

설치는 clean reinstall 방식이며 반복 실행해도 같은 결과를 낸다. 생성된 어댑터를 검증한 뒤
ProofLoop가 관리하는 런타임·플러그인·에이전트·스킬·워크플로·marketplace 항목만 제거하고
새 빌드를 설치한다. 다른 호스트 플러그인, 에이전트, 스킬과 사용자 설정은 보존한다.

Antigravity는 기본적으로 위험한 permission bypass를 사용하지 않는다. 무인 실행에 반드시 필요한 환경에서만 명시적으로 활성화한다.

```bash
export PROOFLOOP_ANTIGRAVITY_BYPASS_PERMISSIONS=1
```

이 옵션은 호스트 도구 실행 권한을 넓히므로 격리된 테스트 저장소에서만 사용하는 것을 권장한다.

## 사용자 환경 Live 검증

정상 실행:

```bash
python3 scripts/run_host_live.py --host codex --scenario normal --keep-workspace
python3 scripts/run_host_live.py --host antigravity --scenario normal --keep-workspace
```

실제 recovery 증명:

```bash
python3 scripts/run_host_live.py --host codex --scenario recovery --keep-workspace
python3 scripts/run_host_live.py --host antigravity --scenario recovery --keep-workspace
```

Recovery fixture에서 fast 모델이 첫 시도에 성공하면 정상 실행 성공일 수는 있지만 recovery 증거는 아니다. 실제 `implementer_recovery` 호출이 관찰되지 않으면 acceptance verdict는 `UNPROVEN / RECOVERY_NOT_OBSERVED`다.

결과는 다음에 저장된다.

```text
reports/live/<host>-<scenario>/
```

릴리스 판정:

```bash
python3 scripts/release_check.py
```

정적·fixture 테스트가 모두 통과해도 인증된 normal/recovery live pair가 없으면 `Overall release: FAIL`이다.

## 현재 증명 상태

- 자동 Orchestrator 상태 머신: `SIMULATED_PROVEN`
- Codex 한 명령 프로세스 루프: `SIMULATED_HOST_E2E_PROVEN`
- Antigravity 한 명령 프로세스 루프: `SIMULATED_HOST_E2E_PROVEN`
- 실제 test/diff/truth 판정: `PROVEN_BY_LOCAL_TESTS`
- 인증된 Codex 모델 라우팅·복구: `UNPROVEN`
- 인증된 Antigravity 모델 라우팅·복구: `UNPROVEN`
- Repository analysis orchestration: `NOT_IMPLEMENTED`
- 전체 릴리스: `FAIL`
