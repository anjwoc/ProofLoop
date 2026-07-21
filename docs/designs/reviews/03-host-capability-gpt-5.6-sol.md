# H-03 Host Capability Contract 독립 리뷰

리뷰 모델: GPT-5.6 Sol  
판정: `FIX_REQUIRED`  
검증: 관련 테스트 35개 통과, optional ACP integration 1개 skip

## 필수 교정

1. declaration, availability, acknowledgement, observation, attestation은 단조 evidence ladder가 아니라
   서로 다른 predicate와 scope를 가진 facet이다.
2. adapter는 `ATTESTATION_CANDIDATE`만 제출할 수 있다. trust anchor를 가진 Core verifier만
   `VERIFIED_ATTESTATION`을 만들 수 있으며 현재 구현에는 그런 검증 경로가 없다.
3. 현재 Codex·Claude·Gemini host output은 host-reported observation이고 ACP readback은
   host-acknowledged config다. 어느 것도 authenticated model identity가 아니다.
4. validation, support, value relation, claim verdict, execution disposition을 한 enum에 합치지 않는다.
5. certification은 H-02/H-09/H-10 책임이다. H03-S1은 항상 `NOT_EVALUATED`다.
6. reasoning/access native value는 runtime version에 결속된 opaque value다. 별도 승인 mapping 없이
   cross-host 비교하지 않는다.
7. observation은 worker runtime, transport, executable, invocation/session/role/attempt, parser/version,
   source event와 causal sequence에 결속해야 한다.
8. no-I/O S1은 supplied record의 canonical digest만 검증할 수 있다. artifact bytes, append-only
   persistence 또는 authenticity를 검증한다고 주장하지 않는다.
9. usage와 recovery control은 각각 telemetry/benchmark와 recovery FSM 책임이므로 H03에서 제외한다.

## 승인 Work Packet: H03-S1

### Goal

synthetic capability record에 대한 pure strict validator와 per-dimension evaluator를 추가한다.

### Allowed files

- `proofloop_core/capability_contract.py`
- `tests/deterministic/test_capability_contract.py`

### Invariants

- filesystem, subprocess, environment, clock, network, host, registry, parser, orchestrator, truth, benchmark와
  연결하지 않는다.
- dimension은 `MODEL_SELECTION`, `MODEL_IDENTITY`, `REASONING_SETTING`, `ACCESS_POLICY`,
  `ROUTING_GRAIN`, `TRANSPORT`만 허용한다.
- source는 declaration, local probe, Core request, host config acknowledgement, host-reported observation만
  허용한다.
- `ATTESTED`, `PROVIDER_SIGNED`, `CERTIFIED` 입력을 거절한다.
- ACP acknowledgement는 model identity observation을 만족하지 못한다.
- host output은 authenticated identity를 만족하지 못한다.
- reasoning/access는 runtime-version-scoped opaque value다.
- exact model equality만 사용하고 alias normalization은 보류한다.
- 결과의 reasons는 stable sort하며 input permutation과 무관하다.
- `recordDigest`는 canonical content integrity이며 authenticity가 아니다.
- 결과는 validation, support, relation, claim, disposition을 분리한다.

### Required tests

- record 순열을 바꿔도 byte-equivalent 결과
- declaration/probe/request만으로 observed model identity를 만족하지 못함
- exact ACP acknowledgement도 identity `UNPROVEN`
- ACP substitution은 `SUBSTITUTED`지만 observed identity로 복사되지 않음
- Codex·Claude·Gemini host event는 unauthenticated host-reported 상태
- `ATTESTED`/`PROVIDER_SIGNED` input 거절
- missing evidence는 `UNPROVEN`, mismatch는 `CONTRADICTED`
- required gap은 block; preferred gap은 explicit eligible fallback이 있을 때만 downgrade
- Antigravity session evidence는 per-role routing을 만족하지 못함
- cross-runtime reasoning/access 비교는 `UNPROVEN`
- unknown field, malformed subject, duplicate ID, digest mismatch, unbound source 거절
- S1은 절대 `CERTIFIED`를 출력하지 않음

### Escalation

signature, attestation, artifact read, append-only persistence, alias normalization, cross-host ontology, 기존
truth/benchmark 변경 또는 두 파일 밖 수정이 필요하면 구현을 중단하고 새 설계 게이트로 반환한다.

## Binding clarification

Evidence record는 fact만, claim은 requirement만, evaluation은 derived verdict만 담는다. evidence record에
`FULFILLED`, `UNPROVEN`, `BLOCK`, `ATTESTED`, `CERTIFIED`를 넣지 않는다.

S1은 다음 claim을 분리 지원한다.

- `HOST_REPORTED_MODEL_MATCH`: matching host observation으로 만족 가능
- `AUTHENTICATED_MODEL_IDENTITY`: claim은 입력 가능하지만 S1에는 이를 만족할 admissible evidence가
  없으므로 matching host observation이 있어도 `UNPROVEN`

두 경우 모두 achieved evidence는 `HOST_REPORTED`, certification은 `NOT_EVALUATED`다. authenticated
claim의 exact value가 일치해도 `AUTHENTICATED_IDENTITY_EVIDENCE_MISSING`으로 block한다. evidence
candidate는 self digest를 제출하지 않으며 validator가 canonical record digest를 계산한다.
