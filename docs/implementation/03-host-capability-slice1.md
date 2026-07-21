# H03-S1 Gemini 3.1 Pro 구현 계획

상태: `PLANNED_AND_DESIGN_CLARIFIED`  
대상: synthetic capability record validator/evaluator  
승인 계약: `docs/designs/reviews/03-host-capability-gpt-5.6-sol.md`

## 실제 모델 실행

Antigravity CLI 1.1.4에서 다음 모델을 read-only plan mode로 실행했다.

```text
agy --mode plan --model "Gemini 3.1 Pro (High)"
```

Gemini는 enum/dataclass, canonical digest, validation phase, dimension evaluator, execution disposition,
stable reason code와 table-driven test 순서를 제시했다.

## 승인된 구현 방향

- 신규 `proofloop_core/capability_contract.py`
- 신규 `tests/deterministic/test_capability_contract.py`
- no-I/O, no integration pure evaluator
- strict schema와 canonical digest
- MODEL_SELECTION, MODEL_IDENTITY, REASONING_SETTING, ACCESS_POLICY, ROUTING_GRAIN, TRANSPORT
- declaration, local probe, Core request, host acknowledgement, host-reported observation만 입력 허용
- validation/support/value relation/claim/disposition/certification 축 분리
- certification은 항상 `NOT_EVALUATED`
- exact model equality, runtime-version-scoped opaque reasoning/access
- missing required claim은 block
- preferred gap은 명시적 eligible fallback이 있을 때만 downgrade
- input permutation과 무관한 결과, stable sorted reason code

## Gemini 제안에 대한 상위 계약 교정

Gemini 초안은 host-reported model string이 일치하면 MODEL_IDENTITY를 곧바로 `SATISFIED`로 처리했다.
이는 “host-reported이며 unauthenticated”라는 상위 계약과 혼동될 수 있다. claim에는 요구 evidence facet을
명시하고 다음을 구분해야 한다.

```text
claim: HOST_REPORTED_MODEL_MATCH
  → 일치하는 host observation으로 SATISFIED 가능

claim: AUTHENTICATED_MODEL_IDENTITY
  → H03-S1에서는 항상 UNPROVEN
```

GPT-5.6 Sol의 binding clarification에 따라 S1은 두 claim을 모두 허용한다.

- `HOST_REPORTED_MODEL_MATCH`: 일치하는 `HOST_EVENT` observation이면 `SATISFIED`, achieved evidence는
  `HOST_REPORTED`, certification은 `NOT_EVALUATED`
- `AUTHENTICATED_MODEL_IDENTITY`: 같은 observation으로 value relation은 `MATCH`일 수 있지만 claim은
  `UNPROVEN`, disposition은 claim의 `onUnproven` 정책에 따라 `BLOCK`, reason은
  `AUTHENTICATED_IDENTITY_EVIDENCE_MISSING`

또한 Gemini는 하나의 `CapabilityRecord` 안에 claims/evidence list를 넣었지만 binding clarification은
fact-only evidence record, requirement-only claim, derived evaluation을 세 객체로 분리하도록 확정했다.
evidence input은 self-authoritative digest를 받지 않고 Core가 canonical record digest를 계산한다.

## 제안 Public API

```python
def validate_records(records: Sequence[Mapping[str, object]]) -> ValidatedRecordSet:
    ...

def evaluate_capability(
    records: ValidatedRecordSet,
    claim: Mapping[str, object],
    fallback: Mapping[str, object] | None = None,
) -> CapabilityEvaluation:
    ...
```

검증 실패와 claim evaluation을 분리해 malformed record가 의미 판정으로 흘러들지 않게 한다.

## Stable reason code 방향

- `RECORD_DIGEST_MISMATCH`
- `RECORD_UNKNOWN_FIELD`
- `RECORD_FORBIDDEN_SOURCE`
- `RECORD_DUPLICATE_ID`
- `SOURCE_BINDING_INCOMPLETE`
- `MODEL_ACK_IDENTITY_INSUFFICIENT`
- `MODEL_HOST_REPORT_UNAUTHENTICATED`
- `MODEL_VALUE_MISMATCH`
- `OPAQUE_VALUE_RUNTIME_MISMATCH`
- `REQUIRED_EVIDENCE_MISSING`
- `FALLBACK_NOT_ELIGIBLE`
- `EXPLICIT_FALLBACK_SELECTED`
- `CERTIFICATION_NOT_EVALUATED`

## Test table

- record와 claim 순열을 바꿔도 byte-equivalent evaluation
- declaration/probe/request로 model identity proof 불가
- ACP exact ack도 identity `UNPROVEN`
- ack substitution은 `SUBSTITUTED`, observed로 복사되지 않음
- host report는 unauthenticated 상태 유지
- forbidden state/source 거절
- required missing은 block
- explicit eligible fallback만 downgrade
- Antigravity session evidence는 per-role routing 불충족
- cross-runtime reasoning/access 비교는 `UNPROVEN`
- unknown field, malformed subject, duplicate ID, digest mismatch, unbound source 거절
- `CERTIFIED` 출력 불가

## Budget

- production 최대 250 nonblank LOC
- tests 최대 300 nonblank LOC
- dependency 0
- public functions 최대 2개

## 확정 schema gate

개별 record, claim과 evaluation의 최소 JSON shape는
`docs/designs/reviews/03-host-capability-gpt-5.6-sol.md`의 binding clarification으로 확정했다.

signature, live artifact, persistence, alias, cross-host ontology, truth/benchmark integration 요구는
`DESIGN_CONFLICT`다.
