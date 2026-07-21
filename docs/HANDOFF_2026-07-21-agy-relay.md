# ProofLoop handoff — AGY route and in-chat execution relay

## 목적

ProofLoop는 **AGY CLI (`agy`)**, Claude Code CLI (`claude`), Codex CLI
(`codex`)만 지원한다. Gemini CLI를 호출하면 안 된다. 사용자는 `/proofloop
<요청>`을 실행한 동일한 Codex/Claude Code/AGY 대화에서, 별도 TUI나 웹 없이도
실행 중인 역할·모델·검증·복구·판정 로그를 계속 보고 싶어 한다.

중요한 한계: 자식 CLI 프로세스는 호스트 대화에 스스로 push할 수 없다. 따라서
정답은 **부모 ProofLoop run을 백그라운드에서 실행하고, 호스트 에이전트가 짧은
terminal 호출로 관측 가능 이벤트를 반복 relay하는 것**이다. private reasoning,
raw provider transcript는 중계하거나 영속화하면 안 된다.

## 이번 세션에서 반영한 변경

아래 변경은 작업 트리에 적용되어 있다. 사용자 소유의 대규모 기존 dirty change가
있으므로 이 파일들과 무관한 수정은 되돌리지 말 것.

1. `proofloop_core/relay.py` 추가
   - `poll_relay()`와 `wait_and_poll_relay()`가
     `.proofloop/relay/<id>/output.log`의 **새 줄만** cursor(`next-line`)에 따라
     읽는다.
   - 출력은 `redact_secrets`를 통과한다.
   - PID liveness로 `PROOFLOOP_RELAY_ACTIVE` / `PROOFLOOP_RELAY_FINISHED`를
     판단한다.
2. `proofloop_core/cli.py`
   - `proofloop-core relay --relay-dir PATH --wait-seconds 3` 서브커맨드를 추가.
   - 이 명령은 새 observable line을 출력한 뒤 활성/종료 marker를 출력하고 즉시
     반환한다. `watch`처럼 무한 follow하지 않는다.
3. `skills/proofloop/SKILL.md`
   - 세 호스트의 공통 entry skill이 parent run을 `nohup`으로 시작한 뒤, run이 끝날
     때까지 반드시 `proofloop-core relay ... --wait-seconds 3`을 반복하도록 강화.
   - 사용자가 보는 정보는 phase/role, requested/observed model evidence, check,
     recovery, review, budget, Truth verdict로 제한한다.
4. `scripts/build_host_adapter.py`
   - AGY 전용으로 생성된 entry skill은
     `PROOFLOOP_AGY_BYPASS_PERMISSIONS=1 nohup ... proofloop-core run`을 사용한다.
5. `proofloop_core/hosts.py`
   - AGY workflow도 동일한 env와 relay 명령을 사용한다.
   - `role_only_trace_summary`는 구형 artifact replay 호환성 때문에 일반화해서
     유지했다. 제거하면 `orchestrator.py` import가 깨진다.
6. `scripts/install.py`
   - AGY install 결과의 permission bypass 설명을
     `ENABLED_FOR_PROOFLOOP_AGY_CHILDREN`으로 정정했다.
7. 문서
   - `README.md`, `references/host-capabilities.md`,
     `docs/roadmap/expected-output.md`에 relay 계약, 안전 범위, AGY 권한 전달을
     추가했다.

## AGY CLI의 실제 호출 계약 (Goalng/local-wiki에서 확인됨)

권위 있는 참고 구현:
`/Users/jaecjeong/lab/local-wiki/apps/api/agent/internal/runner/antigravity.go`

Goalng은 다음처럼 호출한다.

```text
agy --dangerously-skip-permissions --prompt <prompt> --model <display-label>
```

canonical model ID와 AGY display label의 매핑:

| Canonical ID | AGY process argument |
| --- | --- |
| `gemini-3.5-flash-medium` | `Gemini 3.5 Flash (Medium)` |
| `gemini-3.5-flash-high` | `Gemini 3.5 Flash (High)` |
| `gemini-3.5-flash-low` | `Gemini 3.5 Flash (Low)` |
| `gemini-3.1-pro-low` | `Gemini 3.1 Pro (Low)` |
| `gemini-3.1-pro-high` | `Gemini 3.1 Pro (High)` |

ProofLoop의 `proofloop_core/host_runner.py`는 이미 이 계약으로 수정돼 있다.
canonical ID는 durable trace에 남고 display label만 process boundary에서 쓴다.

## 이미 확보한 실제 실행 증거

1. 설치된 AGY는 `agy --version` = `1.1.5`이고, Flash/Pro 모델 목록을 제공한다.
2. 실제 AGY direct role invocation 성공:

```bash
PROOFLOOP_AGY_BYPASS_PERMISSIONS=1 \
  ~/.proofloop/bin/proofloop-core invoke-role \
  --host agy --role explorer_fast \
  --repo tests/live/fixtures/normal \
  --run-dir /tmp/proofloop-agy-direct-role \
  --prompt 'Inspect only...' --timeout-seconds 240
```

- exit 0, `PASS`
- requested model: `gemini-3.5-flash-medium`
- recorded command contained `agy --dangerously-skip-permissions --prompt ...
  --model "Gemini 3.5 Flash (Medium)"`
- AGY 1.1.5 does not expose a resolved model; `observedModel: null` and
  `CLI_REQUESTED_ONLY` are the intentional, honest result.
3. 실제 AGY adaptive run에서는 explorer Flash와 planner Pro를 실행하는
`runtime.selected` / `model.changed` 이벤트를 확인했다. reviewer가 장시간 silent라
토큰 절약을 위해 의도적으로 중단했다. 이 run은 완주 증거가 아니다.
4. 새 relay command의 local fixture 검증:
   - 처음 호출은 두 개의 `[ProofLoop]` line과 `PROOFLOOP_RELAY_ACTIVE`를 출력.
   - 두 번째 호출은 이미 읽은 line을 재출력하지 않음.
5. `python3 -m py_compile proofloop_core/relay.py proofloop_core/cli.py
   scripts/build_host_adapter.py proofloop_core/hosts.py` 통과.
6. `scripts/build_host_adapter.py --host agy`로 만든 임시 adapter에는 아래가 확인됨.
   - entry skill에 `PROOFLOOP_AGY_BYPASS_PERMISSIONS=1`
   - host `agy`
   - `proofloop-core relay`

## 확인/미완료 항목 (2026-07-21 세션 2 업데이트)

1. **clean install 완료 ✅ (2026-07-21 세션 2)**
   - `python3 scripts/install.py --host all --scope user --without-tokscale` 재실행 성공.
   - Claude plugin validate/uninstall/reinstall, Codex plugin remove/reinstall,
     AGY 두 skill 경로와 global workflow의 stale-item 제거/재설치가 모두 완료됐다.
   - 설치본에서 AGY skill/workflow의 `--host agy`,
     `PROOFLOOP_AGY_BYPASS_PERMISSIONS=1`, `proofloop-core relay`를 직접 확인했다.

2. **relay cursor 동작 검증 ✅ (2026-07-21 세션 2)**
   - fixture `/tmp/proofloop-relay-fixture` 로 두 번 호출:
     - 1회차: 3개 observable line + `PROOFLOOP_RELAY_FINISHED` 출력.
     - 2회차: 이미 읽은 line 재출력 없이 `PROOFLOOP_RELAY_FINISHED` 만 출력.
   - cursor(`next-line`) 기반 dedupliation 확인.

3. **AGY direct invoke-role 재검증 ✅ (2026-07-21 세션 2)**
   - 명령: `PROOFLOOP_AGY_BYPASS_PERMISSIONS=1 proofloop-core invoke-role --host agy --role explorer_fast`
   - 결과: `exit 0`, `verdict: PASS`.
   - `invocation.json` 확인:
     - `host: agy`
     - `command[0]: /opt/homebrew/bin/agy`
     - `command` 내 `--dangerously-skip-permissions` 포함.
     - `--model 'Gemini 3.5 Flash (Medium)'` — Goalng canonical 계약과 일치.
     - `requestedModel: gemini-3.5-flash-medium`, `observedModel: null`, `modelEvidence: CLI_REQUESTED_ONLY`.
   - AGY 1.1.5는 resolved model을 노출하지 않으므로 `CLI_REQUESTED_ONLY`는 정직한 정상 결과.

4. **initial-output timeout — 미검증 (변경 없음)**
   - `ProcessRunner`에 AGY first-output timeout(기본 90초)이 추가되어 있다.
   - 실제 silent reviewer timeout terminal은 아직 검증하지 않았다.
   - 필요할 때만 `PROOFLOOP_AGY_INITIAL_OUTPUT_TIMEOUT_SECONDS=15`로 작은 실험.

5. **legacy `antigravity` parser — 건드리지 말 것**
   - `output_parsers/__init__.py`에 legacy branch가 남아 있지만 supported hosts에는 도달 안 함.
   - 삭제 전 parser fixture와 legacy artifact compatibility 확인 필요.

6. **전체 release gate — 아직 PASS 주장 불가**
   - authenticated cross-model resolution, full recovery efficacy, behavior/token efficiency
     는 실제 benchmark evidence 부족.

7. **현재 host acceptance artifact 한계 (2026-07-21 audit)**
   - `claude-code-normal/`: explorer provider `RATE_LIMIT(429)` 종료 → `UNPROVEN`. 성공 증거 아님.
   - `codex-normal/`: `NO_PROOFLOOP_RUN`. Codex host-entry acceptance 증거 없음.
   - 현재 release evidence 범위:
     - AGY direct child route `invoke-role` PASS (x2 독립 실행).
     - relay cursor dedupliation fixture PASS.
     - installer contract 및 adapter 생성 static verification PASS.
   - 세 host의 full end-to-end, recovery, benchmark 효율 우위는 각각 별도 authenticated run 필요.

## 다음 에이전트에게 전달할 프롬프트

아래를 그대로 전달하면 된다.

```text
You are continuing work in /Users/jaecjeong/lab/ProofLoop on main. Read
docs/HANDOFF_2026-07-21-agy-relay.md first. Preserve all unrelated dirty
worktree changes; do not reset or checkout anything.

Objective: finish and verify the portable in-chat ProofLoop execution relay
for exactly these host CLIs: AGY (`agy`), Claude Code (`claude`), and Codex
(`codex`). Do not introduce or call Gemini CLI.

The implementation already adds `proofloop-core relay`, updates host entry
skills, and changes AGY child invocations to the Goalng-proven command shape.
First run:
  python3 scripts/install.py --host all --scope user --without-tokscale
and capture whether clean uninstall/reinstall succeeds.

Then inspect the installed AGY proofloop skill/workflow and perform only a
small real AGY acceptance test that proves the outer host uses `--host agy`
and that relay emits new observable lines exactly once. Use AGY CLI only for
this real test; keep token usage low. Do not claim resolved-model proof from
AGY, because AGY 1.1.5 only yields CLI_REQUESTED_ONLY unless it actually
emits resolved model metadata.

If a fix is needed, keep the safety contract: relay may show observable
phase/role/model/tool/check/recovery/review/budget/verdict events, but never
private provider reasoning or raw provider transcripts. A child process cannot
push directly into a host chat: repeated short host terminal calls are the
portable mechanism.

Do not run broad test suites merely for coverage. Use targeted static checks,
adapter generation inspection, and the small real AGY acceptance run. Update
docs/HANDOFF_2026-07-21-agy-relay.md with final evidence and remaining gaps.
Do not commit or push unless the user explicitly asks.
```

## Files owned by this incremental change

- `proofloop_core/relay.py` (new)
- `proofloop_core/cli.py`
- `proofloop_core/hosts.py`
- `skills/proofloop/SKILL.md`
- `scripts/build_host_adapter.py`
- `scripts/install.py`
- `README.md`
- `references/host-capabilities.md`
- `docs/roadmap/expected-output.md`
