# Spec: ProofLoop SWE-Skills-Bench 실측 파이프라인

## Objective

ProofLoop의 단일 모델 대비 품질과 토큰 효율을 공식 SWE-Skills-Bench 작업에서 재현 가능하게 측정한다. Dry-run 성공을 성능 점수로 오인하지 않으며, 고정된 저장소 commit, Docker image, 외부 evaluator, 모델·가격 snapshot, 무작위 paired schedule을 하나의 benchmark manifest로 보존한다.

비교군은 다음 여섯 개로 고정한다.

1. `single-no-skill`: 단일 모델, 외부 skill 없음
2. `single-proofloop-domain`: 같은 단일 모델에 ProofLoop의 범용 domain pack과 fingerprint로 확인된 기술 adapter만 주입
3. `single-official-skill`: 단일 모델, 해당 SWE-Skills-Bench skill 주입
4. `proofloop-core`: ProofLoop kernel 사용, skill resolver 비활성화
5. `proofloop-adaptive`: 작업량·proof gap 기반 내장 skill과 역할 선택
6. `proofloop-full`: 전체 계획·구현·review·recovery loop

`single-proofloop-domain`은 orchestration 효과를 제거한 스킬 자체의 소거 실험이다. 예를 들어 backend task에서 repository가 Django 5를 실제로 선언한 경우에만 `backend-development + django-5 reference`가 들어간다. Django는 독립 제품 arm이나 공개 skill이 아니다.

## Assumptions

- 사용자는 현재 설계대로 구현하는 것을 승인했다.
- 공식 upstream 테스트의 exit code와 test count가 1차 판정 권위다.
- ProofLoop와 single-agent는 동일한 host/model, task prompt, timeout, repository commit을 사용한다.
- 에이전트는 host checkout을 수정하고 공식 Docker image는 그 checkout을 평가한다. 이 실행 방식은 manifest에 `HOST_AGENT_DOCKER_EVALUATOR`로 기록한다.
- 유료 모델 trial은 별도 비용 승인이 있기 전에는 실행하지 않는다.
- LLM judge는 이번 구현의 필수 판정자가 아니며, 향후 보조 품질 지표로만 추가한다.

## Tech Stack

- Python 3 표준 라이브러리
- Docker CLI
- 기존 ProofLoop host adapters, tokScale, usage ledger
- upstream SWE-Skills-Bench task, skill, test files

새로운 필수 Python 패키지는 추가하지 않는다.

## Commands

```bash
# 무과금 domain skill trigger 검증과 paired behavior trial 계획 생성.
proofloop-core qualify-skills \
  --external-catalog benchmarks/swe-skills-bench/catalog.json \
  --behavior-repetitions 3 --seed 19 \
  --output reports/domain-skill-qualification.json

# 공식 환경·task·image·test 검증. 기본값은 image를 pull하지 않는다.
proofloop-core swe-preflight --suite /tmp/swe-suite.json --upstream /path/to/SWE-Skills-Bench

# 무과금 schedule/환경 준비 검증
proofloop-core benchmark --suite /tmp/swe-suite.json --repo . \
  --environment swe-skills --swe-upstream /path/to/SWE-Skills-Bench \
  --baseline-host codex --baseline-model MODEL --proofloop-host codex \
  --policy all --include-official-skill --dry-run

# 실제 canary. 외부 모델 비용이 발생한다.
proofloop-core benchmark --suite /tmp/swe-suite.json --repo . \
  --environment swe-skills --swe-upstream /path/to/SWE-Skills-Bench \
  --baseline-host codex --baseline-model MODEL --proofloop-host codex \
  --policy all --include-official-skill --only TASK_ID --repetitions 1

# 중단된 benchmark 재개
proofloop-core benchmark --resume /path/to/.proofloop/benchmarks/BENCHMARK_ID
```

## Project Structure

```text
proofloop_core/benchmark.py              공통 schedule, arm 실행, 집계
proofloop_core/benchmark_environment.py  local/SWE 환경 준비와 evaluator
proofloop_core/swe_skills_bench.py       upstream import와 preflight
proofloop_core/cli.py                    benchmark/preflight CLI
benchmarks/swe-skills-bench/             고정 task catalog
tests/deterministic/                     schedule, parser, 통계, 보안 경계 테스트
tests/integration/                       Docker CLI 경계 테스트
```

## Code Style

기존 코드처럼 JSON 직렬화 가능한 `dict`를 외부 artifact 계약으로 사용하고, 외부 명령은 shell 문자열이 아니라 argv 배열로 실행한다.

```python
result = environment.evaluate(
    task,
    repository=trial_repository,
    timeout_seconds=timeout_seconds,
)
assert result["testPassRate"] <= 1.0
```

## Testing Strategy

- Small: pytest/unittest/generic test output parser, arm schedule, resume key, usage validity, paired statistics
- Medium: 임시 git repository와 fake Docker executable을 이용한 mount·read-only·commit 검증
- Large/manual: Docker daemon에서 무과금 preflight와 evaluator-only fixture 실행
- 전체 회귀: `python3 scripts/run_tests.py`

## Boundaries

### Evidence state

- `READY_FOR_BEHAVIOR_EVAL`: authoring trigger fixture가 기준을 통과했고 behavior paired schedule을 실행할 수 있다.
- `PLANNED`: trial 순서와 hash만 고정됐다. 모델 호출이나 채점은 일어나지 않았다.
- `E2 scorecard`: 외부 evaluator가 완료한 반복 trial과 100% usage coverage가 있어야만 생성할 수 있다.
- Docker preflight의 `BLOCKED`는 source/test/skill hash 검증 결과와 분리한다. 데몬이나 image가 없으면 실제 pass rate는 계속 미측정이다.

### Always

- task repository를 catalog의 commit에 고정한다.
- upstream test와 skill 문서의 SHA-256을 manifest에 기록한다.
- evaluator 파일을 read-only mount하고 실행 전후 hash를 비교한다.
- token coverage가 100%가 아닌 trial은 효율 계산에서 제외한다.
- trial을 `(mode, repetition, task, arm)` 키로 checkpoint하고 재개 가능하게 한다.
- objective 결과와 LLM judge 결과를 분리한다.

### Ask First

- 유료 모델 trial 실행
- 49개 전체 benchmark 실행
- 새로운 third-party dependency 추가
- 모델 가격표 변경

### Never

- 누락 usage를 0 token으로 처리하지 않는다.
- dry-run을 pass-rate 점수로 보고하지 않는다.
- hidden/upstream test를 agent prompt에 포함하지 않는다.
- 공식 evaluator 실패를 LLM judge로 뒤집지 않는다.
- 사용자가 이미 staging한 변경을 수정하거나 되돌리지 않는다.

## Success Criteria

- SWE preflight가 Docker, source commit, task/skill/test hash, image availability를 구조화해 보고한다.
- runner가 task별 repository와 Docker evaluator를 실제 사용하고 local ProofLoop repository를 평가 대상으로 재사용하지 않는다.
- 여섯 arm이 동일 seed에서 무작위 paired schedule을 생성한다.
- `--dry-run`은 모델을 호출하지 않고 모든 trial command와 예상 trial 수를 기록한다.
- `--resume`은 완료된 trial을 중복 실행하지 않는다.
- evaluator가 task pass, test pass/total/rate, build, timeout, protected-file integrity를 기록한다.
- usage coverage가 완전하지 않으면 `INVALID_USAGE`이며 token/cost gain을 산출하지 않는다.
- 비교 보고서가 overall/domain/workload tier별 pass rate, tokens per proven, median/p95 duration, paired 95% CI와 실제 선택된 domain pack/adapter/주입 token 추정치를 포함한다.
- Adaptive 채택 판정은 품질 비열등성 확인 후에만 효율 개선을 인정한다.
- 전체 deterministic/orchestration test suite가 통과한다.

## Open Questions

- 실제 canary에 사용할 model과 최대 비용은 사용자가 실행 직전에 결정한다.
- 9-task pilot 이후 49-task 전체 실험 반복 수는 관측된 분산과 비용을 바탕으로 결정한다.
