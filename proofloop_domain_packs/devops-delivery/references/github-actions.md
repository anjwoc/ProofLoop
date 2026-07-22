# GitHub Actions Adapter

Use only when fingerprint confirms GitHub Actions (`.github/workflows/`).

## Quick orientation

```bash
# List all workflows
ls .github/workflows/

# Check what triggers and jobs exist
grep -r "^on:\|^jobs:" .github/workflows/ | head -30

# Find reusable workflow calls
grep -r "uses:" .github/workflows/ | head -20

# Find secret references
grep -r "secrets\." .github/workflows/ | grep -v "#"
```

## Before any change — render the workflow locally

```bash
# actionlint: catches most structural problems before pushing
brew install actionlint
actionlint .github/workflows/your-workflow.yml

# act: dry-run locally (optional, needs Docker)
act -n push --job build   # dry-run: shows what would run
```

## Action pinning — never use `@main` or `@v3` floating tags

```yaml
# ❌ Floating — changes under you
uses: actions/checkout@v4

# ✅ Pinned to SHA — immutable
uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2

# Find the SHA for any action:
# gh release view --repo actions/checkout v4.2.2 --json tagName,targetCommitish
```

## Secret boundary — never interpolate secrets in shell commands

```yaml
# ❌ Shell injection risk — secret value may contain shell metacharacters
- run: ./deploy.sh ${{ secrets.API_KEY }}

# ✅ Correct — pass via environment variable
- run: ./deploy.sh
  env:
    API_KEY: ${{ secrets.API_KEY }}

# ❌ Also wrong — printing secrets to log
- run: echo "Key is ${{ secrets.API_KEY }}"

# Check for untrusted input interpolation in PR-triggered workflows
grep -r "github.event.pull_request\|github.head_ref" .github/workflows/ | grep -v "#"
```

## Permissions — least privilege

```yaml
# Set at workflow level (applies to all jobs unless overridden)
permissions:
  contents: read      # default: read
  pull-requests: write  # only if PR comments are written
  id-token: write     # only for OIDC (cloud auth without stored secrets)

# ❌ Never
permissions: write-all
```

## Concurrency — prevent racing deploys

```yaml
concurrency:
  group: deploy-${{ github.ref }}
  cancel-in-progress: false  # ❌ true for deploy = can leave partial deploy
  # use true only for PR checks (build, test) where cancellation is safe
```

## Reusable workflows — check inputs and secrets

```yaml
# Caller
jobs:
  build:
    uses: ./.github/workflows/build.yml
    with:
      environment: staging
    secrets:
      deploy-key: ${{ secrets.DEPLOY_KEY }}

# Callee (build.yml) — declare inputs explicitly
on:
  workflow_call:
    inputs:
      environment:
        required: true
        type: string
    secrets:
      deploy-key:
        required: true
```

```bash
# Verify the reusable workflow file exists before pushing
ls .github/workflows/build.yml

# Validate the caller correctly passes all required inputs
actionlint .github/workflows/caller.yml
```

## Job dependency and promotion gates

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps: [...]

  deploy:
    needs: test          # test must pass before deploy runs
    environment: production  # requires manual approval if configured
    if: github.ref == 'refs/heads/main'  # only on main
```

**Do not remove `needs:` or `if:` conditions** — this lets deploy run without passing tests.

## Artifact flow

```yaml
# Upload
- uses: actions/upload-artifact@v4
  with:
    name: build-output
    path: dist/
    retention-days: 7  # don't use default 90 days for build artifacts

# Download in next job
- uses: actions/download-artifact@v4
  with:
    name: build-output
    path: dist/
```

## Common failure paths

1. **`pull_request_target`** instead of `pull_request`: runs with write permissions and secrets — extremely dangerous with untrusted code
2. **Expression injection**: `${{ github.event.issue.title }}` in `run:` → shell injection
3. **Missing `if: failure()`**: cleanup steps that only run on failure require explicit condition
4. **Cache key collision**: two jobs with same cache key writing different content → unpredictable cache
5. **Matrix strategy**: `fail-fast: true` (default) cancels all matrix jobs on first failure — set `false` if you want all results
