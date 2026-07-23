# ProofLoop Execution Ledger

Branch: `codex/preserve-eb097dd-with-main`

This file is the handoff for the next executor. Do not change a status to `PASSED` without pasting the command, exit code, duration, and artifact path.

## Status vocabulary

- `PASSED`: observed evidence supports the exact claim
- `FAILED`: observed evidence contradicts the claim
- `BLOCKED`: an external condition prevented execution
- `UNEXECUTED`: no command/observation was completed

## Current ledger

| ID | Gate | Status | Evidence / reason |
| --- | --- | --- | --- |
| S-01 | Target branch source read | `PASSED` | Connected GitHub app returned current files |
| S-02 | LazyCodex plan committed | `PASSED` | `plans/proofloop-truth-hardening-audit.md` |
| S-03 | Mandatory prompt contract committed | `PASSED` | `proofloop_core/prompting/renderers.py` |
| S-04 | Entry skill anti-deception contract committed | `PASSED` | `skills/proofloop/SKILL.md` |
| S-05 | Run provenance metadata committed | `PASSED` | `proofloop_core/contracts/run_state.py` |
| S-06 | Empty-check Truth guard committed | `PASSED` | `proofloop_core/assurance/truth.py` |
| T-01 | New targeted tests executed | `UNEXECUTED` | Local repository checkout unavailable in this session |
| T-02 | Existing deterministic suite executed | `UNEXECUTED` | Same |
| P-01 | Package validation executed | `UNEXECUTED` | Same |
| V-01 | agent-skill-creator spec validation | `UNEXECUTED` | Validator not installed/executed |
| V-02 | agent-skill-creator security scan | `UNEXECUTED` | Scanner not installed/executed |
| C-01 | GitHub CI | `UNEXECUTED` | No workflow run/status found |
| L-01 | Authenticated Codex normal acceptance | `UNEXECUTED` | Requires current isolated runtime and authenticated Codex CLI |
| L-02 | Authenticated AGY normal acceptance | `UNEXECUTED` | Requires current isolated runtime and authenticated AGY CLI |
| L-03 | Static-web solar-system acceptance | `BLOCKED` | Documented test files/scenario fixture do not currently exist/match |

## Step 1 — Checkout and identify the exact revision

```bash
git fetch origin
git switch codex/preserve-eb097dd-with-main
git pull --ff-only

git rev-parse HEAD | tee /tmp/proofloop-source-commit.txt
git status --short
```

Pass conditions:

- branch name matches
- working tree is clean before execution
- source commit is retained with reports

## Step 2 — Confirm documented command drift

```bash
test -f tests/deterministic/test_direct_bootstrap.py
test -f tests/deterministic/test_static_web.py
cat tests/live/fixtures/normal/README.md
```

Expected current result:

- first two commands fail because the documented files are missing
- fixture request describes `IdempotencyExecutor`, not the documented solar-system scenario

Record this as `FAILED`, not as a harness problem.

## Step 3 — Run targeted deterministic guards

```bash
python3 -m pytest \
  tests/deterministic/test_prompt_integrity.py \
  tests/deterministic/test_evidence_origin_and_empty_truth.py \
  tests/deterministic/test_host_runner_timeouts.py \
  tests/deterministic/test_orchestrator_smoke.py \
  -q
```

Record:

- start/end time
- exit code
- full log path
- failed test IDs
- source commit

## Step 4 — Run the canonical deterministic suite

```bash
python3 scripts/run_tests.py 2>&1 | tee /tmp/proofloop-deterministic.log
status=${PIPESTATUS[0]}
printf 'exitCode=%s\n' "$status"
exit "$status"
```

Do not delete or deselect failing tests to get green.

## Step 5 — Run packaging evidence separately

```bash
python3 scripts/validate_package.py 2>&1 | tee /tmp/proofloop-package-validation.log
status=${PIPESTATUS[0]}
printf 'exitCode=%s\n' "$status"
exit "$status"
```

A package PASS proves packaging constraints only. It does not replace behavior tests or live acceptance.

## Step 6 — Validate documentation command paths

Until an automated validator is added, use this temporary check:

```bash
python3 - <<'PY'
from pathlib import Path

required = [
    Path('tests/deterministic/test_direct_bootstrap.py'),
    Path('tests/deterministic/test_static_web.py'),
]
missing = [str(path) for path in required if not path.is_file()]
if missing:
    raise SystemExit('DOCUMENTED TEST PATHS MISSING:\n- ' + '\n- '.join(missing))
print('DOCUMENTED TEST PATHS: PASS')
PY
```

This is expected to fail until the documentation or tests are corrected.

## Step 7 — Install the exact source into an isolated runtime

```bash
export PROOFLOOP_HOME="$(mktemp -d -t proofloop-home.XXXXXX)"
python3 scripts/install.py \
  --host all \
  --scope project \
  --target "$PWD/.proofloop-test-install" \
  --without-tokscale

printf 'PROOFLOOP_HOME=%s\n' "$PROOFLOOP_HOME"
"$PROOFLOOP_HOME/bin/proofloop-core" --help >/tmp/proofloop-runtime-help.txt
```

Verify source/runtime equality before any live run:

```bash
diff -qr proofloop_core "$PROOFLOOP_HOME/runtime/proofloop_core"
diff -qr skills "$PROOFLOOP_HOME/runtime/skills"
diff -qr proofloop_protocols "$PROOFLOOP_HOME/runtime/proofloop_protocols"
```

All three diffs must exit `0`.

## Step 8 — Run current authenticated Codex acceptance once

```bash
PROOFLOOP_HOME="$PROOFLOOP_HOME" \
python3 scripts/run_host_live.py \
  --host codex \
  --scenario normal \
  --keep-workspace \
  --timeout-seconds 1800 \
  2>&1 | tee /tmp/proofloop-codex-live.log
```

Required evidence:

- authenticated host did start
- source/runtime diff from Step 7 passed
- `run.json.host == codex`
- `run.json.evidenceOrigin == CLI_HOST_RUN`
- preserved host transcript
- non-empty checks
- current-run sealed evidence
- expected-output report
- no simulation label

Because the current `normal` fixture is not the documented static-web scenario, even a `PROVEN` result here proves only the concurrency fixture.

## Step 9 — Run current authenticated AGY acceptance once

```bash
PROOFLOOP_HOME="$PROOFLOOP_HOME" \
python3 scripts/run_host_live.py \
  --host agy \
  --scenario normal \
  --keep-workspace \
  --timeout-seconds 1800 \
  2>&1 | tee /tmp/proofloop-agy-live.log
```

Additionally record:

- whether `/proofloop` resolved to the skill or workflow
- whether authentication/keychain prompts appeared
- requested versus observed model evidence
- whether the permission mode was visible

## Step 10 — Restore the advertised static-web acceptance

Choose one honest path:

### Option A — Restore the promise

Add a dedicated `static-web-solar-system` fixture, the missing deterministic tests, and explicit browser assertions. Then run:

```bash
python3 scripts/run_host_live.py \
  --host codex \
  --scenario static-web-solar-system \
  --keep-workspace
```

### Option B — Narrow the promise

Change the expectation document to the actual concurrency fixture and remove static-web claims that are not currently implemented.

Do not keep a solar-system guide that runs a concurrency fixture.

## Step 11 — External skill validation

With `agent-skill-creator` checked out at a known commit:

```bash
python3 /path/to/agent-skill-creator/scripts/validate.py skills/proofloop
python3 /path/to/agent-skill-creator/scripts/security_scan.py skills/proofloop
```

Because ProofLoop uses additional protocol directories, add equivalent validation for every `proofloop_protocols/*` package rather than validating only the entry skill.

## Final acceptance template

```text
Source commit:
Installed runtime hash/commit:
Host and version:
Scenario ID:
Request hash:
Command:
Started/finished/duration:
Exit code:
Deterministic checks:
Package validation:
Skill validation/security scan:
Truth verdict:
Evidence scope:
Observed model routing:
Artifacts:
Known limitations:
```

A blank field is an evidence gap, not a pass.
