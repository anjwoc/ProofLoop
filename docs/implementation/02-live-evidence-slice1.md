# H02-S1 Gemini 3.1 Pro 구현 계획

상태: `PLANNED_GEMINI_3_1_PRO`  
대상: candidate bundle의 순수 L1 구조 validator  
승인 계약: `docs/designs/reviews/02-live-evidence-gpt-5.6-sol.md`

## 실제 모델 실행

Antigravity CLI 1.1.4에서 다음 모델을 read-only plan mode로 실행했다.

```text
agy --mode plan --model "Gemini 3.1 Pro (High)"
```

모델은 public API, stable reason code, filesystem 검증 순서, canonical digest, 테스트 matrix와 LOC
budget을 제안했다.

## 승인된 구현 범위

- 신규 `proofloop_core/live_evidence.py`
- 신규 `tests/deterministic/test_live_evidence.py`
- stdlib-only, subprocess/network/host 호출 없음
- 결과는 `STRUCTURALLY_VALID` 또는 `REJECTED`뿐
- candidate의 `verdict`, `evidenceLevel`, `bundleHash`는 판정 근거로 사용하지 않음
- bundle-relative regular file만 허용
- absolute path, traversal, symlink, hardlink, special file 거절
- duplicate, NFC, case-fold collision 거절
- manifest와 실제 tree의 missing/unexpected file 거절
- SHA-256, size, JSON/JSONL syntax 재검증
- 256 files, 64 MiB 제한
- validator가 계산한 canonical `candidateDigest` 반환

## Public API 방향

```python
def validate_bundle(bundle_root: Path, manifest: Mapping[str, object]) -> ValidationResult:
    ...
```

`ValidationResult`는 immutable이며 status, stable reason code, candidate digest를 담는다. 오류 detail은
secret-bearing file content나 absolute host path를 포함하지 않는다.

## Stable reason code

- `REJECTED_SCHEMA_VIOLATION`
- `REJECTED_BUNDLE_LIMIT_EXCEEDED`
- `REJECTED_PATH_SECURITY_VIOLATION`
- `REJECTED_PATH_COLLISION`
- `REJECTED_FILE_TYPE_VIOLATION`
- `REJECTED_MISSING_ARTIFACT`
- `REJECTED_UNEXPECTED_ARTIFACT`
- `REJECTED_HASH_MISMATCH`
- `REJECTED_SIZE_MISMATCH`
- `REJECTED_MALFORMED_JSON`
- `REJECTED_MALFORMED_JSONL`

여러 오류가 동시에 존재할 때 결과가 filesystem iteration order에 흔들리지 않도록 validation stage와
정렬 순서를 고정한다.

## 검증 순서

1. manifest 타입, 허용 key, artifact entry 타입을 strict 검증한다.
2. path를 lexical 검사하고 duplicate/NFC/case-fold collision을 판정한다.
3. bundle tree를 정렬된 순서로 열거해 missing/unexpected/type/limit을 확인한다.
4. 각 artifact를 descriptor 기반으로 열고 `fstat` regular-file·link-count를 확인한다.
5. bounded chunk로 size와 SHA-256을 계산한다.
6. `.json`과 `.jsonl`은 제한 안에서 구문 검증한다.
7. self-claim을 제외하고 재계산된 artifact metadata로 canonical candidate digest를 만든다.

가능한 플랫폼에서는 `O_NOFOLLOW`를 사용한다. 지원되지 않는 플랫폼에서도 pre-open `lstat`, open 후
`fstat`, inode/device 일치를 검사하되 이는 hostile concurrent writer에 대한 완전한 OS isolation이
아님을 명시한다.

## 테스트 matrix

- 최소 valid bundle
- `PROVEN` self-claim이 `STRUCTURALLY_VALID` 이상으로 승격되지 않음
- artifact 1 byte mutation과 size mismatch
- absolute, parent traversal, empty path
- symlink와 hardlink
- duplicate, NFC, case-fold collision
- unexpected와 missing file
- malformed JSON과 JSONL
- 257 files와 64 MiB + 1 byte
- unknown schema field
- 입력 manifest와 artifact가 변경되지 않음
- manifest/artifact 순서를 바꿔도 동일 digest

## Gemini 제안 중 보류한 부분

Gemini는 `version`, `candidate_verdict`, `evidence_level`, `bundle_hash`라는 snake_case manifest를
제안했다. 상위 H-02 계약은 camelCase `schemaVersion`과 더 풍부한 identity를 사용하므로 이 이름은
확정하지 않는다. 구현 전에 H02-S1의 최소 manifest schema를 Core convention에 맞게 고정해야 한다.

또한 plain `open()`만으로 TOCTOU가 해결된다고 보지 않는다. pure validator의 범위 안에서는 descriptor
검사를 강화하고, 동일 UID의 hostile concurrent writer까지 막아야 하면 OS isolation 설계로 승격한다.

## 복잡도 budget

- production: 200 nonblank LOC 목표, 최대 250
- test: 350 nonblank LOC 이내
- 외부 dependency 0
- public API 1개와 immutable result type만 노출

## `DESIGN_CONFLICT`

다음 요구가 생기면 구현을 중단하고 상위 설계로 반환한다.

- signature, key, challenge, portable attestation
- live capture, subprocess, network, host CLI
- release-check 또는 orchestrator 연결
- `PROVEN`이나 L2 이상 판정
- bundle 수정·정리·sanitization
- absolute reference 호환
- secret-bearing raw stream 보존
