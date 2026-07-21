# Host Capability Contract

상태: `FIXES_APPLIED_PENDING_REVIEW`, H03-S1 구현 완료 (G-19, 21 tests + 7 subtests)  
주 설계: Claude Opus, 실제 Claude Code `--model opus` 호출  
독립 리뷰: GPT-5.6 Sol 완료

독립 리뷰 원문과 승인된 Slice 1 경계는
[리뷰 문서](reviews/03-host-capability-gpt-5.6-sol.md)에 저장한다. 현재 trace, truth, registry,
orchestrator와 연결하는 변경은 후속 설계가 승인될 때까지 금지한다.

## 1. 문제

현재 `RuntimeSpec`, `CONTROLLER_ROUTES`, `capability()`는 ProofLoop가 요청하려는 구성을 선언한다.
`probe()`는 실행 파일과 버전이 존재함을 확인한다. 둘 다 특정 invocation에서 모델, reasoning,
access mode가 실제 적용됐다는 증거는 아니다.

특히 다음 값을 분리해야 한다.

- ProofLoop가 요청한 값
- 호스트가 설정 요청을 받았다고 응답한 값
- 호스트 이벤트에서 관측한 값
- 독립적으로 인증된 실행 identity
- 그 증거만으로 Core가 허용하는 제품 주장

ACP의 `set_config_option` 성공도 acknowledged configuration이지 provider execution identity가 아니다.
Antigravity는 현재 `agy` session model로 실행되며 ProofLoop가 invocation별 모델을 지정하지 않는다.

## 2. 불변 조건

1. static declaration과 binary probe는 routing proof가 아니다.
2. requested, acknowledged, observed, authenticated를 한 필드로 합치지 않는다.
3. 모델·reasoning·access는 각각 독립적으로 판정한다.
4. host output과 candidate artifact는 검증 전까지 신뢰하지 않는다.
5. 같은 입력 record 집합은 순서와 무관하게 같은 판정을 만든다.
6. 새 host plugin은 capability를 선언할 수 있지만 증거 수준과 release verdict를 정할 수 없다.
7. 지원하지 않는 기능은 fallback success가 아니라 명시적 downgrade, unproven 또는 blocked가 된다.

## 3. 다섯 evidence facet

| 단계 | 이름 | 의미 | 제품 주장 가능 여부 |
| --- | --- | --- | --- |
| C0 | `DECLARED` | adapter/registry가 지원한다고 선언 | 불가 |
| C1 | `AVAILABLE` | 특정 binary/version probe 성공 | 불가 |
| C2 | `ACKNOWLEDGED` | session/host가 요청 설정을 수락·대체·거절 | 실행 identity 주장 불가 |
| C3 | `OBSERVED` | invocation 연결 host event에서 값을 관측 | source 강도에 따라 제한 |
| C4 | `ATTESTATION_CANDIDATE` | adapter가 검증 가능한 attestation 후보를 제출 | 자체로 주장 불가 |

이 facet은 단조로운 evidence ladder가 아니다. observation이 declaration이나 acknowledgement를
자동으로 포함하지 않으며 scope도 다를 수 있다. 연결된 subject chain과 claim policy가 요구하는 facet이
모두 있어야 claim을 평가한다.

`VERIFIED_ATTESTATION`은 adapter가 제출할 수 있는 상태가 아니다. trust anchor를 가진 Core verifier만
만들 수 있다. 현재 코드에는 signature, certificate, key 또는 attestation verification 경로가 없으므로
Codex·Claude·Gemini의 상한은 host-reported observation, ACP의 상한은 host-acknowledged config다.
H03은 capability-policy satisfaction만 계산하며 certification은 `NOT_EVALUATED`로 고정한다.

## 4. 데이터 모델

모든 record는 `schemaVersion`, `recordType`, `recordId`, `source`와 canonical content digest를 갖는다.
future live record의 timestamp는 판단의 비결정 입력으로 쓰지 않고 freshness policy가 필요할 때만
검증한다. H03-S1에는 clock과 persistence가 없으며 immutable in-memory value만 다룬다.

```json
{
  "schemaVersion": "1.0",
  "recordType": "CAPABILITY_OBSERVATION",
  "recordId": "...",
  "subject": {
    "runId": "...",
    "sessionId": "...",
    "invocationId": "...",
    "role": "implementer_fast",
    "runtime": "codex"
  },
  "dimension": "MODEL",
  "scope": "INVOCATION",
  "value": "gpt-5.6-terra",
  "state": "OBSERVED",
  "source": {
    "kind": "HOST_EVENT",
    "artifactSha256": "...",
    "jsonPointer": "/model"
  },
  "recordSha256": "..."
}
```

H03 dimension:

- `MODEL_SELECTION`
- `MODEL_IDENTITY`
- `REASONING_SETTING`
- `ACCESS_POLICY`
- `ROUTING_GRAIN`
- `TRANSPORT`

필수 scope:

- `RUNTIME`
- `SESSION`
- `INVOCATION`
- `ROLE`

상태별 필드:

- `REQUESTED`: ProofLoop route와 요청값
- `ACKNOWLEDGED`: `ACCEPTED`, `SUBSTITUTED`, `REJECTED`, `UNSUPPORTED`
- `OBSERVED`: source kind, artifact digest, event type, JSON pointer
- `ATTESTATION_CANDIDATE`: attestation kind와 subject binding candidate. S1 입력에서는 금지

`ResolvedRuntime.model`은 cutover 전까지 requested model 의미만 갖는다. `observedModel`을 requested나
acknowledged 값으로 채우지 않는다.

## 5. 판정 모델

Core는 서로 다른 의미를 한 enum에 섞지 않고 dimension마다 다음 축을 독립 반환한다.

```text
validation: VALID | REJECTED
support: SUPPORTED | UNSUPPORTED | UNKNOWN
valueRelation: MATCH | SUBSTITUTED | CONFLICT | UNKNOWN
claimVerdict: SATISFIED | UNPROVEN | CONTRADICTED
executionDisposition: ALLOW | DOWNGRADE | BLOCK
certification: NOT_EVALUATED
reasonCodes: stable sorted list
```

`DOWNGRADE`는 명시적 fallback candidate가 있고 그 candidate도 독립적으로 실행 가능할 때만 허용한다.
누락 evidence를 fallback success로 바꾸지 않는다.

전체 invocation은 필요한 dimension 정책을 합성한다. 예를 들어 모델이 `UNPROVEN`이어도 개발 실행은
허용할 수 있지만, “인증된 교차 모델 routing” benchmark에는 포함하지 않는다. 반대로 read-only가
hard requirement인데 access가 `UNPROVEN`이면 해당 역할 실행 또는 결과 승격을 차단한다.

### Reasoning과 access 비교

reasoning 값은 `{runtime, runtimeVersion, nativeValue}` opaque tuple로 보존한다. `low < medium < high`를
모든 host에 보편적으로 적용하지 않는다. host adapter가 versioned ontology mapping을 제공하고 Core
policy가 이를 별도 승인한 경우에만 ordered downgrade를 계산한다.

access도 S1에서는 `{runtime, runtimeVersion, nativeValue}`로 보존한다. 향후 별도 검토된 mapping이
승인된 뒤에만 다음과 같은 capability set 정규화를 고려한다.

```text
filesystem: NONE | READ | WRITE
network: DENY | ALLOW
command: DENY | ALLOWLIST | ALLOW
approval: REQUIRED | BYPASS
```

비교 불가능하거나 관측되지 않은 조합은 더 안전한 값으로 추정하지 않고 `UNPROVEN` 또는 `CONFLICT`로
처리한다.

## 6. Resolution 알고리즘

1. registry declaration을 읽되 proof로 사용하지 않는다.
2. executable/transport availability로 route candidate를 선택한다.
3. invocation 전에 requested record를 부모 Core가 만든다.
4. session negotiation 결과를 acknowledged record로 정규화한다.
5. raw host event를 실제 worker runtime, transport, executable identity/version, invocation, session,
   role, attempt, parser ID/version, event type, artifact digest, JSON pointer/line, source sequence와 결속한
   observation candidate로 만든다.
6. schema, digest, subject chain과 source policy를 검증한다.
7. dimension별 effective result와 downgrade reason code를 계산한다.
8. 실행 허용 정책과 release-claim 정책을 별도로 적용한다.

Fallback은 `preferred runtime unavailable` 같은 자유문 대신 stable reason code와 원래 candidate chain을
보존한다. fallback runtime의 requested model을 원래 모델의 observed value로 기록하지 않는다.

## 7. 실패 및 downgrade 규칙

| 조건 | 실행 판정 | 인증/benchmark 판정 |
| --- | --- | --- |
| ACP SDK 없음, legacy CLI 가능 | policy 허용 시 실행 | legacy source 수준으로 제한 |
| output parser 실패 | 실행 결과는 보존 | 관련 C3/C4 claim `UNPROVEN` |
| model ack만 존재 | 실행 가능 | routed model `UNPROVEN` |
| observed와 verified attestation 충돌 | `CONFLICT` | hard reject |
| per-role 요청 불가 | session model로 실행 가능 | per-role routing `UNSUPPORTED` |
| read-only enforcement 미관측 | planner 결과 격리 가능 | mutation-sensitive 승격 차단 |
| usage 일부 누락 | 작업 품질 판정과 분리 | 효율 benchmark 제외 |
| fallback runtime 선택 | reason과 chain 표시 | 원래 route fulfilled 주장 금지 |

## 8. Registry/plugin 경계

host adapter는 다음만 제공한다.

- launcher와 probe descriptor
- supported transport와 요청 encoding
- parser ID/version
- declarative capability와 routing grain
- host-specific value를 Core ontology로 바꾸는 mapping

Core는 다음을 독점한다.

- record schema와 canonical hashing
- subject/provenance validation
- evidence source strength policy
- effective capability와 downgrade 판정
- benchmark inclusion과 release claim

새 host는 adapter 등록으로 추가하고 `host == ...` 분기를 늘리지 않는 것이 목표다. 단, 기존 분기 제거는
행동 호환성 테스트 후 별도 migration으로 수행한다.

## 9. 현재 호스트의 보수적 초기 matrix

| 호스트 | 요청 grain | 현재 확정 가능한 범위 | 아직 증명되지 않은 범위 |
| --- | --- | --- | --- |
| Codex | invocation | CLI/ACP 요청, parser candidate | authenticated active model, access enforcement |
| Claude Code | invocation | CLI/ACP 요청, parser candidate | provider-signed execution identity |
| Gemini CLI | invocation | CLI/ACP 요청, parser candidate | reasoning 적용, authenticated identity |
| Antigravity | session | executable/session 실행 | ProofLoop per-role model routing |

이 표는 live acceptance 결과 전까지 capability 선언의 상한이며 `CERTIFIED`를 의미하지 않는다.

## 10. Migration

1. `RuntimeSpec`와 route table은 당분간 C0 source로 유지한다.
2. `ResolvedRuntime`은 requested route로 의미를 고정하고 observation을 별도 record로 분리한다.
3. `capability()`와 `probe()` output에 schema version과 declaration/probe facet을 추가한다.
4. 기존 event에서 candidate record를 shadow 생성하되 현재 report verdict는 바꾸지 않는다.
5. host별 live fixture가 통과한 뒤에만 legacy `observedModel` consumer를 새 record view로 전환한다.
6. 한 release 동안 legacy 필드와 새 field를 함께 제공하고 ambiguity warning을 기록한다.

## 11. Acceptance tests

- record 순서를 섞어도 같은 결과가 나온다.
- acknowledged model만으로 fulfilled/attested 판정이 나오지 않는다.
- requested model을 observed field로 복사한 fixture를 거절한다.
- Antigravity session observation을 per-role routing proof로 승격하지 않는다.
- parser failure가 requested value fallback으로 바뀌지 않는다.
- model은 fulfilled지만 reasoning과 access는 unproven일 수 있다.
- ordered ontology가 없는 reasoning 값을 임의로 비교하지 않는다.
- access capability set의 incomparable 상태를 안전한 값으로 추정하지 않는다.
- fallback chain과 stable reason code가 보존된다.
- plugin declaration이 Core verdict나 evidence strength를 지정하면 거절한다.
- record digest, subject ID와 source binding이 맞지 않으면 거절한다. S1은 artifact bytes를 읽지 않으므로
  artifact hash 진위는 검증하지 않는다.
- S1은 `ATTESTED`, `PROVIDER_SIGNED`, `CERTIFIED` 입력과 출력을 거절한다.

## 12. 구현 Slice

1. **H03-S1:** no-I/O schema validator와 deterministic per-dimension evaluator
2. RuntimeSpec/route declaration shadow importer
3. requested와 acknowledged record 생성
4. host event observation extractor
5. access/reasoning ontology와 policy
6. host별 live source validation
7. reports와 benchmark cutover
8. registry 기반 adapter migration

### 제안된 첫 Slice

- 신규 `proofloop_core/capability_contract.py`
- 신규 `tests/deterministic/test_capability_contract.py`
- JSON object 입력의 strict manual validation과 validator-computed record digest
- MODEL_SELECTION, MODEL_IDENTITY, REASONING_SETTING, ACCESS_POLICY, ROUTING_GRAIN, TRANSPORT만 지원
- validation/support/relation/claim/disposition을 분리한 판정
- requested/acknowledged/host-reported synthetic fixture만 사용
- 실제 host 호출, registry 수정, orchestrator 연결, `CERTIFIED` 판정은 금지

## 13. Non-goals

- static model 이름을 runtime proof로 바꾸기
- 모든 provider가 서명 attestation을 제공한다고 가정하기
- host-specific access mode 문자열을 보편적 security guarantee로 취급하기
- H-02 live capture 또는 release policy를 이 문서에서 구현하기
- 기존 host 분기를 한 번에 제거하기

## 14. 미해결 질문

1. host-attested model identity를 어떤 제품 문구까지 허용할 것인가?
2. provider-signed 또는 독립 side-channel이 없는 경우 최고 evidence level은 무엇인가?
3. access enforcement를 process sandbox 관측으로 검증할지, host acknowledgement까지만 기록할지?
4. capability record persistence와 append-only revision을 어느 artifact store가 소유할지? S1은 이를
   구현했다고 주장하지 않는다.
5. host/parser version이 바뀌었을 때 certification을 자동 만료할지?

## 15. 설계 provenance

- 첫 Opus 호출은 2분 동안 결과를 반환하지 않아 중단했으며 설계 기여로 기록하지 않는다.
- 재시도는 `claude -p --model opus --effort medium --tools "" --no-session-persistence`로 완료됐다.
- Opus 원안의 Codex `HOST_ATTESTED`, Claude `PROVIDER_SIGNED` 등은 현재 증거가 없으므로 본 문서의
  확정 matrix에서 제거했다.
- GPT-5.6 Sol은 전체 계약을 `FIX_REQUIRED`로 판정했고 위 교정을 요구했다.
- H03-S1은 두 신규 파일에 한정된 pure synthetic record validator/evaluator로 승인됐다.
