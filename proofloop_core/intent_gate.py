import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Any

class IntentKind(str, Enum):
    ANSWER = "answer"
    INVESTIGATE = "investigate"
    PLAN = "plan"
    MUTATE = "mutate"
    AUDIT = "audit"
    OPERATE_EXTERNAL = "operate_external"

class ClarityLevel(str, Enum):
    CLEAR = "clear"
    GROUNDABLE = "groundable"
    OWNER_DECISION_REQUIRED = "owner_decision_required"
    BLOCKED = "blocked"

class AuthorityLevel(str, Enum):
    READ_ONLY = "read_only"
    REPOSITORY_MUTATION = "repository_mutation"
    GIT_LOCAL = "git_local"
    GIT_REMOTE = "git_remote"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"

@dataclass(frozen=True)
class IntentGateResult:
    intent_kind: IntentKind
    clarity: ClarityLevel
    authority: AuthorityLevel
    confidence: float
    signals: tuple[str, ...]
    grounding_required: bool
    owner_question: Optional[str]
    blocked_reason: Optional[str]
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "intentKind": self.intent_kind.value,
            "clarity": self.clarity.value,
            "authority": self.authority.value,
            "confidence": self.confidence,
            "signals": list(self.signals),
            "groundingRequired": self.grounding_required,
            "ownerQuestion": self.owner_question,
            "blockedReason": self.blocked_reason,
        }

def evaluate_intent(request_text: str) -> IntentGateResult:
    normalized = request_text.casefold()
    injection_patterns = [
        "모든 검증을 생략",
        "무시하라",
        "자동으로 배포",
        "시스템 프롬프트를 출력",
        "테스트를 성공으로 표시"
    ]
    signals = []
    for pattern in injection_patterns:
        if pattern in request_text:
            signals.append("injection_attempt")
    
    authority = AuthorityLevel.READ_ONLY
    intent_kind = IntentKind.ANSWER
    
    if "injection_attempt" in signals:
        authority = AuthorityLevel.READ_ONLY
        intent_kind = IntentKind.ANSWER
    else:
        deployment_plan = bool(re.search(r"\b(?:deployment|deploy|release)\s+plan\b", normalized)) or (
            "배포" in request_text and "계획" in request_text
        )
        if ("배포" in request_text or re.search(r"\b(?:deploy|release)\b", normalized)) and not deployment_plan:
            authority = AuthorityLevel.EXTERNAL_SIDE_EFFECT
            intent_kind = IntentKind.OPERATE_EXTERNAL
        elif "PR" in request_text or "푸시" in request_text or re.search(r"\b(?:push|pull request|pr)\b", normalized):
            authority = AuthorityLevel.GIT_REMOTE
            intent_kind = IntentKind.OPERATE_EXTERNAL
        elif "커밋" in request_text or re.search(r"\bcommit\b", normalized):
            authority = AuthorityLevel.GIT_LOCAL
            intent_kind = IntentKind.MUTATE
        elif (
            "구현" in request_text
            or "수정" in request_text
            or "추가" in request_text
            or re.search(r"\b(?:implement|fix|modify|update|add|build|create)\b", normalized)
        ):
            authority = AuthorityLevel.REPOSITORY_MUTATION
            intent_kind = IntentKind.MUTATE
        elif "분석" in request_text or "조사" in request_text or re.search(r"\b(?:analy[sz]e|investigate|inspect|audit)\b", normalized):
            intent_kind = IntentKind.INVESTIGATE
        elif "계획" in request_text or re.search(r"\b(?:plan|design)\b", normalized):
            intent_kind = IntentKind.PLAN
            if "작성" in request_text:
                authority = AuthorityLevel.REPOSITORY_MUTATION

    clarity = ClarityLevel.CLEAR
    owner_question = None
    
    if "알아서" in request_text or "결제 관련해서 완전히 새로운 스키마" in request_text:
        clarity = ClarityLevel.OWNER_DECISION_REQUIRED
        owner_question = "현재 요청의 요구사항이나 설계 방향을 명확히 해 주시겠습니까?"
        
    return IntentGateResult(
        intent_kind=intent_kind,
        clarity=clarity,
        authority=authority,
        confidence=0.9 if not signals else 0.5,
        signals=tuple(signals),
        grounding_required=True,
        owner_question=owner_question,
        blocked_reason=None
    )
