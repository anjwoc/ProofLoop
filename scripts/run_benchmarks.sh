#!/usr/bin/env bash
# Plan or explicitly execute reproducible ProofLoop benchmarks.
#
# This wrapper intentionally defaults to dry-run. A benchmark invokes multiple
# authenticated coding agents and can incur meaningful cost, so a shell typo
# must never silently begin a full experiment.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/run_benchmarks.sh [options]

Plan benchmark schedules by default. Add --execute only after reviewing the
printed trial count, host/model selections, Docker prerequisites, and budget.

Options:
  --reservation              Run the ReservationFlow fixture (default).
  --swe                      Run the SWE-Skills-Bench fixture; requires --swe-upstream.
  --swe-upstream PATH        Checked-out, pinned SWE-Skills-Bench repository.
  --execute                  Run authenticated model trials. Without it, use --dry-run.
  --baseline-host HOST       Baseline CLI host (default: codex).
  --baseline-model MODEL     Baseline model identifier (required for --execute).
  --proofloop-host HOST      ProofLoop controller: claude-code, codex, antigravity (default: antigravity).
  --repetitions N            Paired repetitions (default: 5 for ReservationFlow, 1 for SWE).
  --timeout-seconds N        Per-trial timeout (default: 1200).
  --help                     Print this help without creating artifacts.

The script never enables Antigravity permission bypass. Set that environment
variable yourself only in an isolated unattended environment when you have
explicitly reviewed the resulting scope.
EOF
}

execute=false
reservation=false
swe=false
swe_upstream=""
baseline_host="codex"
baseline_model=""
proofloop_host="antigravity"
repetitions=""
timeout_seconds="1200"

while (($#)); do
  case "$1" in
    --reservation) reservation=true ;;
    --swe) swe=true ;;
    --swe-upstream)
      shift
      swe_upstream="${1:-}"
      ;;
    --execute) execute=true ;;
    --baseline-host)
      shift
      baseline_host="${1:-}"
      ;;
    --baseline-model)
      shift
      baseline_model="${1:-}"
      ;;
    --proofloop-host)
      shift
      proofloop_host="${1:-}"
      ;;
    --repetitions)
      shift
      repetitions="${1:-}"
      ;;
    --timeout-seconds)
      shift
      timeout_seconds="${1:-}"
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if ! $reservation && ! $swe; then
  reservation=true
fi
if $swe && [[ -z "$swe_upstream" ]]; then
  printf '%s\n' '--swe requires --swe-upstream PATH' >&2
  exit 2
fi
if $execute && [[ -z "$baseline_model" ]]; then
  printf '%s\n' '--execute requires --baseline-model so the comparison is reproducible.' >&2
  exit 2
fi

run_fixture() {
  local name="$1"
  local suite="$2"
  local repo="$3"
  local environment="$4"
  local fixture_repetitions="$5"
  local -a command=(
    python3 -m proofloop_core.cli benchmark
    --suite "$suite"
    --repo "$repo"
    --mode both
    --policy all
    --baseline-host "$baseline_host"
    --proofloop-host "$proofloop_host"
    --timeout-seconds "$timeout_seconds"
    --repetitions "${repetitions:-$fixture_repetitions}"
  )
  if [[ -n "$baseline_model" ]]; then
    command+=(--baseline-model "$baseline_model")
  else
    # dry-run still needs a stable label in its manifest; it is explicitly
    # marked as unmeasured and no host process is launched.
    command+=(--baseline-model UNSET_FOR_DRY_RUN)
  fi
  if [[ "$environment" == "swe-skills" ]]; then
    command+=(--environment swe-skills --swe-upstream "$swe_upstream")
  fi
  if ! $execute; then
    command+=(--dry-run)
  fi

  printf '\n== %s (%s) ==\n' "$name" "$($execute && printf EXECUTE || printf DRY_RUN)"
  printf 'Command:'
  printf ' %q' "${command[@]}"
  printf '\n'
  "${command[@]}"
}

if $reservation; then
  run_fixture \
    "ReservationFlow" \
    "benchmarks/reservation-flow/suite.json" \
    "benchmarks/reservation-flow/seed" \
    "local" \
    "5"
fi
if $swe; then
  run_fixture \
    "SWE-Skills-Bench" \
    "benchmarks/swe-skills-bench/catalog.json" \
    "/tmp/swe-trial" \
    "swe-skills" \
    "1"
fi
