# Domain Pack Contract

상태: `DRAFT`  
주 설계: Claude Opus  
독립 리뷰: GPT-5.6 Sol 대기

## 1. 문제

현재 `skill_registry.py`에 pack 구조가 존재하지만 pack의 proof obligation, 승격·강등 기준, 외부
trigger set, scorecard 계산 규칙이 명문화되지 않았다.

## 2. 현재 구현 사실

- `DomainPack` dataclass: name, displayName, probes, skills, escalation, roles, evidence
- `load_pack()`: TOML에서 pack 로드, strict schema validation
- Experimental pack은 `--opt-in-experimental` 없이 자동 선택 불가
- Pack에는 positive/negative trigger keywords, file pattern, escalation 조건 포함

## 3. 불변 조건

1. Pack은 core ProofLoop 기능이 아니라 부가적인 도메인 전문화다.
2. Pack 추가·제거는 core truth gate를 변경하지 않는다.
3. Pack 승격은 E2+ scorecard (90 paired trial 이상)를 통과해야 한다.
4. Experimental pack은 opt-in 없이 production 결과에 영향을 주지 않는다.
5. Pack의 skill은 core skill과 동일한 proof obligation을 따른다.
6. 강등: scorecard regression 또는 false-positive rate > 10%이면 experimental로 강등한다.
7. Pack 정의는 선언적이며 런타임 코드를 포함하지 않는다.

## 4. Pack 구조

```toml
[pack]
name = "test-engineering"
displayName = "Test Engineering"
status = "experimental"  # experimental | validated | stable

[probes]
keywords = ["test", "coverage", "spec"]
filePatterns = ["*_test.*", "test_*.*", "*.spec.*"]

[escalation]
on = ["uncovered_critical_path", "flaky_test_detected"]

[evidence]
requiredTrials = 90
minimumPairedSuccess = 0.85
```

## 5. 승격 기준

| 전이 | 조건 |
|---|---|
| experimental → validated | 90 paired trial, success ≥ 85%, false-positive ≤ 10% |
| validated → stable | 추가 90 trial에서 regression 없음, 3명 이상 외부 사용자 |
| stable → validated | scorecard regression |
| any → experimental | false-positive > 10% 또는 critical bug |

## 6. Scorecard 계산

- 90 paired trial: pack 활성 vs 비활성, 동일 task set
- Quality: proof graph pass rate 비교
- Efficiency: token 소비 비교
- False positive: pack이 잘못된 도메인에 활성화된 비율
- 통계: bootstrap 95% CI, non-inferiority margin δ = 5%

## 7. 구현 슬라이스

1. 기존 `skill_registry.py`는 변경하지 않는다
2. G-13에서 90 paired trial runner를 구현한다
3. G-14에서 외부 trigger set을 구현한다

## 8. 설계 provenance

- 현재 `skill_registry.py` 코드 기반 역공학
- H-04 (Benchmark Methodology)와 연계하여 scorecard 통계 방법을 결정
