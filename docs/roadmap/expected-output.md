# ProofLoop expected output

ProofLoop는 에이전트의 요약이나 MCP 클라이언트의 판결을 진실로 취급하지 않는다. 실행 중에는 이벤트를, 종료 시에는 Core가 만든 결과 계약을 제공한다.

사람이 보는 단계별 기대 출력, Codex·Antigravity smoke test, Truth 상태의 해석은 [기대 결과와 테스트 시나리오](../EXPECTED_RESULTS_AND_TEST_SCENARIOS.md)를 따른다.

## MCP 실행 흐름

1. 클라이언트가 `proofloop_start_run(request_text, host, repository?, mode?)`를 호출한다. `host`는 인증된 외부 CLI를 실행할 수 있으므로 항상 명시한다.
2. 응답의 `sessionId`로 `proofloop_run_status(sessionId, after?)`를 폴링한다. 응답은 새로운 `events`, 다음 커서 `nextEvent`, 현재 상태를 담는다.
3. 상태가 `COMPLETED`가 되면 `outcome`은 Core가 쓴 `run-outcome.json`과 동일하다. `FAILED`이면 `error`와 이미 기록된 이벤트를 읽는다.

예시 시작 응답:

```json
{
  "schemaVersion": "1.0",
  "sessionId": "…",
  "status": "QUEUED",
  "runDir": null,
  "events": [],
  "nextEvent": 0
}
```

진행 중에는 `run.started`, `intent.compiled`, `strategy.selected`, `role.started`, `role.progress`, `diff_guard.completed` 같은 이벤트가 순서대로 나타난다. 각 이벤트의 원본은 `<runDir>/events.jsonl`이다.

## 종료 결과

`run-outcome.json`은 다음 필드를 제공한다.

```json
{
  "status": "COMPLETED",
  "verdict": "PROVEN|PARTIAL|BLOCKED|FAILED",
  "summary": "사용자용 한 줄 결과",
  "objective": "…",
  "acceptanceCriteria": [],
  "blockers": [],
  "unproven": [],
  "evidence": {},
  "usage": {},
  "artifacts": {
    "truthReport": "…/truth-report.json",
    "events": "…/events.jsonl",
    "run": "…/run.json"
  }
}
```

`PROVEN`은 검증 계획, 필수 검사, Diff Guard, 리뷰, Proof Graph 및 Core evidence가 모두 통과했을 때만 가능하다. MCP의 기존 `proofloop_plan_work`, `proofloop_execute_checks`, `proofloop_commit_verdict`는 임의 계획·셸 실행·클라이언트 판결을 만들지 않고 마이그레이션 안내만 반환한다.

## 격리와 복원력 검증

외부 역할 호출은 `<runDir>/invocations/<invocationId>/sandbox/` 아래의 XDG 상태를 사용한다. 호스트의 사용자 설정과 캐시는 역할에 전달하지 않는다. Chaos 검증은 랜덤 지연이나 실제 프로세스 종료가 아니라 `token_limit`, `network_latency`, `process_kill` 같은 명시적 fault point를 결정적으로 선택해 테스트한다.
