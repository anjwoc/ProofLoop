# Product Claim and Release Policy Contract

상태: `DRAFT`  
주 설계: Claude Opus  
독립 리뷰: GPT-5.6 Sol 대기

## 1. 문제

ProofLoop가 README, 랜딩페이지, 발표에서 주장할 수 있는 것은 인증된 증거 수준에 의해 결정된다.
증거 없이 효율이나 품질을 주장하면 안 된다.

## 2. 불변 조건

1. 모든 제품 주장은 재현 가능한 증거에 연결돼야 한다.
2. 증거 수준별 허용 주장이 다르다.
3. Dry-run이나 mock host 결과로 production 주장을 하지 않는다.
4. "더 효율적" "더 빠른" 비교 주장은 benchmark non-inferiority를 먼저 통과해야 한다.
5. 제한사항은 주장과 동일한 위치에 명시한다.

## 3. 증거 수준별 허용 주장

| 증거 수준 | 허용 주장 | 금지 |
|---|---|---|
| L0 (no evidence) | "설계 목표", "의도한 기능" | "달성", "검증됨", 수치 |
| L1 (structural) | "스키마 검증 통과", "구조적으로 유효" | "정확함", "성능 주장" |
| L2 (controller-verified) | "테스트 통과", "검증됨" | 비교 주장, 외부 일반화 |
| L3 (model-observed) | "실제 호스트에서 실행", "모델 관측됨" | "인증됨", 보안 주장 |
| L4 (recovery-proven) | "recovery 검증", "자동 복구 가능" | 무제한 신뢰성 주장 |
| L5 (CI-attested) | "CI 재현", "독립 검증" | — |

## 4. README/랜딩페이지 규칙

- 각 기능 주장 옆에 `[L2]` 같은 증거 수준 태그를 표시한다.
- Benchmark 수치를 인용하면 trial 수, CI, 조건을 함께 표시한다.
- "X% 토큰 절약" → usage coverage 100% + quality non-inferiority 통과 필수.
- 지원 호스트는 실제 E-01~E-06 live evidence가 있는 것만 나열한다.

## 5. Release Gate

Release 전 다음을 모두 충족해야 한다:

1. 최소 3개 호스트의 normal/recovery live evidence (E-01~E-06)
2. Benchmark quality non-inferiority 통과 (H-04)
3. Clean install 검증 (G-15)
4. CI 재현 (G-16)
5. License compatibility 확인 (R-01)
6. CHANGELOG 작성 (R-04)

## 6. 구현 슬라이스

이 설계는 policy document이며 코드 구현이 아니다. R-05 release check에서 자동화한다.

## 7. 설계 provenance

- Alpha 종료 조건 (remaining-work.md Section 114-124) 기반
- H-02 Live Evidence의 L1-L5 수준 정의 참조
