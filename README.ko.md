# ProofLoop

**코딩 에이전트가 완료를 주장하는 데서 끝나지 않고, 증명하게 만듭니다.**

> **판단은 강한 모델에게. 반복은 빠른 모델에게. 완료 판정은 증거에게.**

ProofLoop는 Codex, Claude Code, Antigravity에서 사용하는 스킬 우선 소프트웨어 엔지니어링
런타임입니다. 하나의 공개 스킬이 사용자의 요청을 범위 보존형 intent contract로 정제하고,
작업량에 맞는 흐름을 선택하고, 역할을 분리해 실행하고, 실제 저장소 증거를 검증하고, 제한된
복구를 수행한 뒤 명시적인 truth 상태로 종료합니다.

[English README](README.md) · [효율화 전략](docs/proofloop-efficiency-strategy.md) · [벤치마크 명세](docs/swe-skills-benchmark-spec.md)

> **현재 개발 진행 중 — `v0.4.0-alpha`.** 작업량 적응형 모델 라우팅, Proof Graph, 제한된 복구
> 루프, 실시간 실행 가시성, 모델별 토큰 측정이 구현되어 결정론적 테스트를 통과했습니다. 인증된
> live evidence와 단일 모델·경쟁 workflow 대비 품질 및 토큰 효율 비교 기능은 계속 개발하고
> 실측하는 단계입니다.

## 1분 안에 이해하는 ProofLoop

일반적인 에이전트 workflow에서는 하나의 모델이 요청 이해, 설계, 저장소 탐색, 구현, 재시도,
자기 리뷰, 완료 선언까지 모두 수행합니다. 모든 단계에 가장 강한 모델을 쓰면 비싸고, 모든 단계에
빠른 모델만 쓰면 초기에 잘못 이해한 방향이 반복 과정에서 더 크게 번질 수 있습니다.

ProofLoop가 처음부터 추구한 설계는 다릅니다.

```text
거친 사용자 요청
  → 작업이 요구할 때만 영향력이 큰 판단 지점에 강한 추론 모델 배치
  → 테스트 피드백으로 교정 가능한 탐색·구현 구간은 빠른 모델이 반복
  → 의미 있는 시도마다 결정론적 검사 수행
  → 위험도·불확실성·영향 범위가 클 때만 강한 독립 리뷰 수행
  → 어떤 모델도 아닌 증거가 최종 완료 판정을 소유
```

즉, 잘못된 판단이 이후 작업을 몇 배로 늘리는 지점에는 고성능 모델을 제한적으로 사용하고,
실제 테스트로 교정할 수 있는 탐색·구현·복구에는 빠르고 상대적으로 저렴한 모델을 여러 번
활용합니다. 작은 작업에는 둘 다 불필요하게 호출하지 않는 것이 목표입니다.

이것이 ProofLoop의 역할별 모델 라우팅과 작업량 적응형 lane이 검증하려는 제품 가설입니다.
현재 아키텍처와 결정론적 동작은 구현됐지만, 실제 토큰 효율이 더 좋아진다는 결론은 아직 paired
benchmark로 증명되지 않았으므로 확정된 성능처럼 표현하지 않습니다.

![단일 모델 workflow와 강한 판단 모델, 빠른 구현 loop, 결정론적 검증, 복구, truth gate를 결합한 ProofLoop 모델 라우팅 비교](docs/assets/proof-driven-model-routing.svg)

핵심은 단순히 “모델을 여러 개 쓴다”가 아닙니다. ProofLoop는 모델 라우팅을 proof 상태와
결합합니다. 증거가 실패하면 제한된 recovery loop로 돌아가고, 고위험 proof obligation이 열려
있으면 강한 리뷰를 추가하며, 의무가 닫히면 런타임이 반복을 멈춥니다. 모델 라우팅은 다음 작업의
담당자를 결정하고, Proof는 루프를 계속할 이유와 완료를 선언할 자격을 결정합니다.

그림의 모델명은 하드코딩된 의존성이 아니라 구체적인 라우팅 예시입니다. 호스트는 강한 판단에
Claude Opus, Fable, GPT-5.6 Sol을 사용하고, 검증 피드백이 있는 구현 반복에는 Claude Haiku나
Gemini 3.5 Flash를 사용할 수 있습니다. 실제 Registry 설정, 호스트 능력, 모델 가용성, 관측된
model trace가 최종 기준입니다.

### 언제 더 강한 역할이나 모델로 승격하는가

승격은 모델이 스스로 더 강한 모델을 요청해서 일어나는 것이 아니라, 런타임이 관측한 위험 신호와
열린 proof gap을 기준으로 결정합니다. 현재 기본 정책은 다음과 같습니다.

| 관측 신호 | 런타임 결정 |
| --- | --- |
| 보안·인증·결제·권한·동시성·migration·schema·데이터 손실·배포 등 critical path | T3로 진입하고 강한 설계·탐색·독립 리뷰와 고위험 proof obligation 요구 |
| 공개 계약·영속 상태·greenfield architecture·넓은 범위·높은 불확실성 | T2/T3로 진입하거나 승격하고 planner, 필요 시 explorer, deep review 추가 |
| 첫 diff가 critical path를 건드림 | 최초 요청이 단순해 보여도 T3로 승격 |
| 첫 diff가 최상위 root 3개 이상 또는 파일 4개 이상으로 확장 | 과소평가된 T0/T1 작업을 T2로 승격 |
| 같은 결정론적 실패 fingerprint가 2회 반복되거나 기본 fast attempt 2회가 소진 | recovery 역할로 전환하고 T0/T1을 T2로 승격한 뒤 deep review 요구 |
| 실패가 `DESIGN_CONFLICT`, `SPEC_AMBIGUITY`, `CONTRACT_CHANGE`로 분류됨 | 구현을 반복하지 않고 강한 planner로 되돌림 |
| deep reviewer가 `FIX_REQUIRED` 또는 `OVERBUILT` 판정 | 제한된 recovery repair 1회 후 전체 검사를 다시 실행하고 재리뷰 |
| recovery·replan·시간·토큰 예산 소진 | 무한 승격하지 않고 `BLOCKED` 또는 `FAILED`로 종료 |

기본 repair 예산은 fast attempt 최대 2회 이후 recovery attempt 최대 1회입니다. Task brief는 더
엄격한 예산을 지정할 수 있으며, 모든 전환과 승격 이유는 event stream과 artifact에 기록됩니다.

## ProofLoop를 만드는 이유

코딩 에이전트는 그럴듯한 변경을 잘 만듭니다. 하지만 그럴듯함은 완료가 아닙니다.

모델은 테스트를 실행하지 않고 통과했다고 말할 수 있고, 오래된 증거를 재사용하거나, 요청
범위를 조용히 넓히거나, 진전 없이 복구를 반복하거나, 한 줄짜리 수정에 지나친 토큰을 쓸 수
있습니다. 프롬프트 규율은 도움이 되지만, 같은 모델이 요청·구현·증거·최종 판정을 모두 소유하게
두는 것만으로는 부족합니다.

ProofLoop는 네 가지 원칙을 따릅니다.

1. **주장보다 증거.** 모델의 설명보다 결정론적 검사, 보호 파일 무결성, 현재 artifact를 우선합니다.
2. **루프는 런타임이 소유.** 재시도·에스컬레이션·복구·소진을 프롬프트가 아닌 명시적 상태 전이로 관리합니다.
3. **작업이 요구한 만큼만 실행.** 작은 변경은 fast lane으로 처리하고, 불확실성·영향 범위·proof gap이 있을 때만 역할과 리뷰를 추가합니다.
4. **정확성에는 절제도 포함.** 코드가 맞아도 범위를 벗어났거나 과도하게 설계됐거나 증거가 오래됐으면 완료로 인정하지 않습니다.

## 그래서 나에게 어떻게 도움이 되는가

사용자는 평소 코딩 에이전트에게 말하듯 요청하면 됩니다. 이후 ProofLoop는 그 요청을 명시적인
계약으로 만들고, 작업이 감당할 만한 프로세스만 선택하고, 실행되는 역할과 모델 변경을 보여주고,
“모델이 자신 있게 말했다”를 “저장소가 증명됐다”로 취급하지 않습니다.

| 내가 맡기는 작업 | 예상 실행 경로 | 얻는 실질적 가치 |
| --- | --- | --- |
| 한 파일의 기계적인 수정 | intent-lite → 빠른 구현 → 집중 검사 → truth gate | 전체 계획·리뷰 절차에 비용을 쓰지 않음 |
| 경계가 알려진 기능 추가 | 필요한 문맥만 탐색 → 빠른 구현 loop → 테스트 → 조건부 리뷰 | 저비용 반복의 실수를 객관적 피드백으로 교정 |
| 여러 모듈에 걸친 불명확한 기능 | 강한 설계 → 제한된 빠른 구현 반복 → 재분류 → 강한 리뷰 | 작업량이 큰 중간 구간 전후에만 고성능 판단 사용 |
| 회귀 또는 간헐적 오류 | 실패 fingerprint → 집중 재시도 → recovery 승격 → 새 검증 | 실패할 때마다 사용자가 직접 재프롬프트할 필요를 줄임 |
| 보안·migration·공개 계약 변경 | 고위험 lane → proof obligation → 독립 리뷰 → fail-closed truth | 위험한 성공 주장보다 `BLOCKED`·`UNPROVEN`을 선택 |

ProofLoop는 실수가 누적될 만큼 큰 작업, 검사 실패 가능성이 있는 작업, 잘못된 결과를 수용하는
비용이 큰 작업에서 가장 유효합니다. 문구 수정, 단순 이름 변경, 실행 가능한 검사가 전혀 없는
저장소에는 얻는 가치보다 overhead가 클 수 있습니다. Adaptive lane이 이 overhead를 줄이도록
설계됐지만, 실제 효율 우위는 paired benchmark가 끝날 때까지 미증명 상태입니다.

서로 다른 모델을 역할별로 사용하는 기능은 호스트 능력에도 의존합니다. Codex와 Claude Code는
역할별 모델을 요청할 수 있지만, 현재 Antigravity는 역할을 격리하되 현재 세션 모델을 사용합니다.

## 시작하기

### 요구사항

- Python 3.10 이상이 설치된 macOS 또는 Linux
- Git
- Codex, Claude Code, Antigravity 중 하나 이상의 CLI
- 고정된 로컬 tokScale 설치에 사용하는 npm

### 설치

```bash
git clone https://github.com/anjwoc/ProofLoop.git
cd ProofLoop
./install.sh
python3 scripts/doctor.py
```

다음 명령도 같은 clean install 진입점입니다.

```bash
make install
python3 scripts/install.py
python3 script/install.py
npm run proofloop:install
```

설치기는 ProofLoop가 관리하는 기존 runtime, plugin, skill, agent, workflow, marketplace 항목을
먼저 제거한 뒤 현재 빌드를 설치합니다. 관계없는 사용자 설정은 보존합니다. 설치 결과는
`~/.proofloop/install-manifest.json`에 기록됩니다.

설치 후 호스트를 재시작하고 공개 스킬 하나만 호출합니다.

```text
Codex:       $proofloop <요청>   또는 /skills에서 proofloop 선택
Claude Code: /proofloop <요청>
Antigravity: /proofloop <요청>
```

### 첫 번째 테스트에 적합한 요청

실행 가능한 테스트가 있는 깨끗한 임시 Git 저장소에서 시작하는 것이 좋습니다.

```text
/proofloop 영속성과 충돌 처리를 포함하는 멱등 예약 API를 구현해줘.
기존 응답 계약을 유지하고 회귀 테스트를 추가해. 저장소 테스트와 최종 diff가
증명되지 않으면 완료라고 말하지 마.
```

다른 터미널에서 같은 실행을 관찰할 수 있습니다.

```bash
proofloop-core watch --run latest --repo . --format human
```

완료 후 truth와 사용량 artifact를 확인합니다.

```bash
proofloop-core usage --run latest --repo . --reconcile
python3 -m json.tool .proofloop/runs/<run-id>/truth-report.json
```

## 실행 과정

```text
공개 proofloop 스킬
  → intent contract: 원 요청, 범위, 미확정 사항, 권한 보존
  → workload profile: 위험도·변경 면적·불확실성으로 T0–T3 분류
  → 저장소 preflight와 Git snapshot
  → proof graph: 닫아야 할 증명 의무 정의
  → 조건부 protocol, domain pack, 역할, 모델 선택
  → 역할·모델·검사 이벤트를 실시간 표시하며 구현
  → 첫 diff 이후 재분류
  → 결정론적 검사, diff guard, 보호 증거 확인
  → 실패 fingerprint를 이용한 제한된 복구
  → 필요한 경우 독립 리뷰
  → truth gate와 anti-bloat gate
  → PROVEN | UNPROVEN | FAILED | BLOCKED
```

사용자 모드는 세 가지입니다.

| 모드 | 용도 | 동작 |
| --- | --- | --- |
| `adaptive` | 기본 개발 작업 | 작업량과 proof gap이 요구하는 가장 가벼운 흐름 선택 |
| `goal` | 여러 단계의 수렴 작업 | 목표가 증명되거나 예산이 소진되거나 실제로 막힐 때까지 반복 |
| `audit` | 읽기 전용 분석 | 소스 변경 권한 없이 증거와 분석 보고서 생성 |

```bash
proofloop-core run --mode adaptive --host codex --repo . --request-file request.txt
proofloop-core run --mode goal --host claude-code --repo . --request-file request.txt
proofloop-core run --mode audit --host codex --repo . --request-file audit.txt
```

## 실행 가시성과 artifact

화면에는 단계, 역할 시작, 요청 모델과 실제 관측 모델, 모델 변경, 시도 횟수, 검사 결과, 복구 이유,
리뷰 결과, 토큰 진행 상황, 최종 truth 상태가 표시됩니다. 모델을 실제로 관측하지 못하면
requested-only로 표시하고 모델 라우팅을 `UNPROVEN`으로 유지합니다.

`.proofloop/runs/<run-id>/`에는 다음과 같은 기계 판독 가능한 artifact가 남습니다.

- `intent-contract.json`, `workload-profile.json`, `proof-graph.json`
- `skill-resolution.json`, `domain-selection.json`
- `events.jsonl`, `model-trace.jsonl`, `invocations/`
- `attempts.jsonl`, 검사 출력, diff 증거
- `usage/usage-summary.json`, `truth-report.json`

TUI·relay·CI를 위한 JSONL 출력도 지원합니다.

```bash
proofloop-core run --mode adaptive --host codex --repo . --request-file request.txt \
  --output-format jsonl
```

## ProofLoop와 Superpowers, 일반 스킬의 차이

[Superpowers](https://github.com/obra/superpowers/tree/d884ae04edebef577e82ff7c4e143debd0bbec99)는
성숙한 조합형 개발 방법론입니다. 공개 workflow는 brainstorming, worktree, 세부 계획, TDD,
subagent 구현, 리뷰, 완료 검증을 강제합니다. ProofLoop도 체계적인 작업과 증거를 중시하지만,
런타임 수준에서 다른 문제를 해결합니다.

| 관점 | 일반 단일 스킬 | Superpowers | ProofLoop |
| --- | --- | --- | --- |
| 기본 단위 | 모델 문맥에 주입하는 도메인 지침 | 조합 가능한 필수 workflow 스킬 | 하나의 공개 스킬과 런타임·내부 protocol |
| workflow 소유자 | 현재 모델 | 스킬 지침과 호스트 도구 | 런타임 FSM, proof graph, 예산, host adapter |
| 작업량 적응 | 주로 수동 | 의도적으로 포괄적인 workflow | T0–T3 fast/full lane과 첫 diff 재분류 |
| 검증 | 스킬과 모델에 의존 | verification-before-completion 규율 | 결정론적 명령, 증거 권위, diff guard, truth gate |
| 복구 | 재프롬프트 또는 개별 디버깅 지침 | systematic-debugging workflow | 실패 fingerprint, 제한 재시도, recovery 역할, 소진 상태 |
| 모델 라우팅 | 호스트 기본값 | 호스트/subagent에 의존 | 역할 registry와 요청/관측 모델 trace |
| 토큰 측정 | 대개 없음 | 핵심 공개 주장 아님 | run·task·role·model·invocation별 ledger와 tokScale |
| 도메인 지식 | 스킬의 핵심 가치인 경우가 많음 | 주로 개발 프로세스 방법론 | 범용 domain pack과 저장소 조건부 기술 adapter |
| 완료 결과 | 자연어 응답 | workflow 완료 규율 | artifact를 동반한 네 가지 truth 상태 |

이 표는 아키텍처 비교이지 성능 순위가 아닙니다. 현재 ProofLoop가 Superpowers보다 pass rate나
토큰 면에서 우수하다고 입증한 통제 벤치마크는 없습니다. Superpowers도 behavior test를 운영하므로,
동일 task·model·host·제한시간·저장소 상태·외부 evaluator를 사용해야 공정하게 비교할 수 있습니다.

## 현재 실제로 증명된 범위

| 주장 | 현재 증거 | 상태 |
| --- | --- | --- |
| 결정론적 커널과 패키지 동작 | 로컬 테스트 209개 및 package validation 통과 | `DEVELOPMENT_PROVEN` |
| one-command orchestration | fake-host 프로세스와 orchestration 테스트 | `SIMULATED_PROVEN` |
| 다섯 팩의 작성용 trigger | 작성자가 만든 positive/negative fixture 모두 F1 1.0 | `AUTHORING_SET_ONLY` |
| 외부 trigger routing | 고정 SWE-Skills-Bench 제목에서 backend/frontend/devops F1 1.0 | `LIMITED_EXTERNAL_MEASURED` |
| test-engineering/code-review 외부 routing | 외부 catalog 표본 없음 | `UNMEASURED` |
| domain pack behavior | paired trial 90회 계획, 미실행 | `PLANNED` |
| 6-arm SWE 효용 비교 | 162회 dry-run, Docker evaluator 미완료 | `UNMEASURED` |
| 인증된 교차 모델 라우팅과 복구 | 승인된 live artifact 없음 | `UNPROVEN` |
| 토큰 효율 또는 시장 우위 | 완료된 paired model benchmark 없음 | `UNPROVEN` |

기계 판독 보고서는 [`reports/domain-skill-qualification.json`](reports/domain-skill-qualification.json)과
[`reports/release-check.json`](reports/release-check.json)에 있습니다. Dry-run이나 작성용 fixture를 실제
작업 pass rate로 표현하지 않습니다.

## 내장 domain pack 상태

현재 backend development, frontend development, DevOps delivery, test engineering, code review의 다섯
범용 팩이 있습니다. Django, React, Spring, GitHub Actions, Kustomize, Flux 등은 범용 팩 내부의 조건부
adapter이지 공개 제품 스킬이 아닙니다.

모든 팩은 아직 `EXPERIMENTAL`이며 반복 behavior/efficacy scorecard가 승격을 정당화하기 전까지
Adaptive 기본 선택에서 제외됩니다.

```bash
proofloop-core run --mode adaptive --host codex --repo . --request-file request.txt \
  --experimental-domain-packs
```

## 토큰 사용량과 벤치마크

provider가 보고한 input, output, cache-read, cache-write, reasoning token을 run·task·role·model·session·
invocation별로 기록합니다. 누락된 사용량은 0으로 바꾸지 않고 효율 계산을 무효화합니다.

```bash
proofloop-core usage --run latest --repo .
proofloop-core usage --run-dir .proofloop/runs/<run-id> --reconcile
```

벤치마크는 다음 여섯 비교군을 같은 조건으로 배정합니다.

1. 단일 모델, 스킬 없음
2. 단일 모델, ProofLoop domain pack만 사용
3. 단일 모델, 공식 외부 스킬 사용
4. 스킬 resolver를 끈 ProofLoop Core
5. Adaptive ProofLoop
6. Full ProofLoop

고정 저장소, 읽기 전용 공식 테스트, Docker 평가, 사용량 coverage, 반복 횟수, 승격 기준은
[SWE-Skills-Bench 명세](docs/swe-skills-benchmark-spec.md)에 정리되어 있습니다.

## Codex, Claude Code, Antigravity에서 테스트하기

세 호스트 모두에서 공개 ProofLoop 스킬 하나만 참조하고 프로젝트성 작업을 요청하면 end-to-end
smoke test가 됩니다. 실제 Git 저장소와 실행 가능한 검사가 있어야 entry skill, 런타임, 이벤트,
artifact, 검사, truth gate가 제대로 연결됐는지 확인할 수 있습니다.

| 호스트 | 호출 | smoke test로 확인할 수 있는 것 | 모델 라우팅 경계 |
| --- | --- | --- | --- |
| Codex | `$proofloop <요청>` 또는 `/skills` | 전체 런타임, 실시간 이벤트, 검사, 복구, artifact, truth | 역할별 모델을 요청할 수 있지만 관측된 model trace가 있어야 실제 사용을 증명 |
| Claude Code | `/proofloop <요청>` | 전체 런타임, 실시간 이벤트, 검사, 복구, artifact, truth | 역할별 모델을 요청할 수 있지만 관측된 model trace가 있어야 실제 사용을 증명 |
| Antigravity | `/proofloop <요청>` | 역할별로 격리된 Antigravity 프로세스를 포함한 전체 경로 | `ROLE_ROUTING_ONLY`; 현재 세션 모델을 사용 |

세 호스트 모두 같은 기준으로 테스트합니다.

1. 설치 후 해당 호스트를 재시작합니다.
2. 테스트가 통과하는 임시 Git 저장소를 사용합니다.
3. 테스트·영속성·오류 처리·호환성 제약이 포함된 프로젝트성 작업을 요청합니다.
4. 다른 터미널에서 `proofloop-core watch --run latest --repo . --format human`을 실행합니다.
5. `truth-report.json`, `model-trace.jsonl`, 검사 artifact, 최종 diff, usage coverage를 확인합니다.
6. 실제 실패 검사가 있는 두 번째 시나리오로 제한된 recovery를 확인합니다. 첫 시도 성공은 recovery 증거가 아닙니다.

호스트별 호출 예시는 다음과 같습니다.

```text
# Codex
$proofloop 영속성·충돌 처리·회귀 테스트가 있는 멱등 예약 API를 구현해줘.

# Claude Code
/proofloop 영속성·충돌 처리·회귀 테스트가 있는 멱등 예약 API를 구현해줘.

# Antigravity
/proofloop 영속성·충돌 처리·회귀 테스트가 있는 멱등 예약 API를 구현해줘.
```

현재 유지 관리되는 인증 acceptance 자동화는 Codex와 Antigravity를 지원합니다.

```bash
python3 scripts/run_host_live.py --host codex --scenario normal --keep-workspace
python3 scripts/run_host_live.py --host codex --scenario recovery --keep-workspace
python3 scripts/run_host_live.py --host antigravity --scenario normal --keep-workspace
python3 scripts/run_host_live.py --host antigravity --scenario recovery --keep-workspace
python3 scripts/release_check.py
```

Claude Code는 `/proofloop`를 통한 대화형 테스트가 가능하지만, `run_host_live.py`에는 아직 Claude
acceptance 시나리오가 없습니다. 이는 자동화된 릴리스 증거의 공백이며 Claude가 이미 live-proven이라고
주장해서는 안 됩니다.

Antigravity의 권한 우회는 기본적으로 꺼져 있습니다. 격리된 무인 테스트 환경에서만
`PROOFLOOP_ANTIGRAVITY_BYPASS_PERMISSIONS=1`을 사용하세요.

## 외부 배포 전 남은 게이트

- 인증된 호스트 acceptance artifact
- 완료된 behavior 및 paired efficacy trial
- Docker 기반 공식 evaluator 결과
- 소프트웨어 라이선스 선택과 `LICENSE` 파일 추가
- 깨끗한 환경에서 동일 증거를 다시 만드는 CI

이 게이트가 닫히기 전 랜딩페이지에는 “신뢰성과 토큰 효율 향상을 목표로 설계됨”이라고 표현하고,
“더 뛰어남”, “검증된 N% 절감”처럼 아직 증명되지 않은 문구는 사용하지 않습니다.
