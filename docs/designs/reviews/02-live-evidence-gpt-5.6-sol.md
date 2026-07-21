# H-02 Live Evidence 독립 리뷰

판정: `FIX_REQUIRED`  
리뷰 모델: GPT-5.6 Sol  
역할: 독립 설계 게이트

## Critical findings

1. Challenge 발급·소비 주체와 writer authority가 정의되지 않았다. Candidate self-hash는 authenticity를
   증명하지 않는다.
2. 실제 process graph는 controller, outer host, proofloop-core, per-role host processes인데 초안은
   단일 process만 표현한다. 현재 저장 과정은 outer stream과 임시 Git baseline을 잃는다.
3. `HOST_OUTPUT`과 `ACP_SESSION_CONFIG`가 실제 provider model identity보다 강하게 표현됐다.
4. 현재 attempt/check artifact에는 L4 recovery chain을 재구성할 invocation/check/tree identity가 없다.
5. recovery fixture가 첫 시도 성공과 rerun selection bias에 취약하다.
6. 현재 raw stdout/stderr와 prompt command를 먼저 저장하는 방식은 secret 비저장 원칙과 충돌한다.

## 필수 계약 수정

- L2+는 동일 acceptance cycle에서 controller가 직접 검증할 때만 생성한다.
- persisted unsigned report를 다시 읽는 것만으로 L2+를 복원하지 않는다.
- candidate manifest, truth report, capability self-claim은 비권위 입력이다.
- self `bundleHash` 대신 validator가 canonical `candidateDigest`를 계산한다.
- run 선택은 pre-spawn set difference이며 0개는 `NO_NEW_RUN`, 여러 개는 `AMBIGUOUS_NEW_RUN`이다.
- model identity 관측과 requested route 충족을 별도 claim으로 계산한다.
- L4는 canonical `checkSpecHash`가 같은 FAIL→PASS recovery만 인정한다.
- absolute path, 삭제된 workspace 의존, 검증 불가능 Git object가 있으면 portable claim은 `UNPROVEN`이다.
- host capability와 release claim은 claim별로 독립 집계한다.
- distributable stream은 persistence 전에 redaction하고 command에는 prompt hash만 기록한다.

## 승인된 최소 Slice 1

### 목표

Candidate bundle의 구조, 경로, hash만 검증하는 pure L1 validator를 추가한다. Live runner, challenge,
release aggregation과 L2/L3/L4 판정은 금지한다.

### 허용 파일

- `proofloop_core/live_evidence.py`
- `tests/deterministic/test_live_evidence.py`

### 불변 조건

- subprocess, network, host CLI를 호출하지 않는다.
- 입력 bundle을 수정하지 않는다.
- candidate verdict, evidenceLevel, bundleHash를 신뢰하지 않는다.
- 결과는 `STRUCTURALLY_VALID` 또는 `REJECTED`와 validator 계산 `candidateDigest`만 반환한다.
- L2 이상 또는 `PROVEN`을 반환하지 않는다.
- bundle-relative regular file만 허용한다.
- absolute, parent traversal, symlink, hardlink, special file을 거절한다.
- duplicate, Unicode NFC collision, case-fold collision path를 거절한다.
- manifest에 없는 file과 manifest가 누락한 file을 거절한다.
- hash와 size를 재계산한다.
- 최대 256 files, 총 64 MiB를 초과하면 거절한다.
- unknown schema field를 fail closed한다.
- `truth-report.json`은 일반 artifact일 뿐 권위가 없다.

### 필수 테스트

- 최소 valid bundle
- self `PROVEN`과 requested model이 결과를 승격하지 못함
- 1-byte mutation과 size mismatch
- absolute path, traversal, symlink, hardlink, special file
- duplicate/NFC/case-fold collision
- unexpected/missing file
- malformed JSON/JSONL
- file count/byte limit
- 입력 파일 불변

## 다음 게이트

L2 이상, signature/HMAC/CI attestation, 동일 UID 공격자, raw stream 보존, legacy absolute reference
migration이 요구되면 구현을 중단하고 별도 설계로 승격한다.

