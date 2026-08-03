from __future__ import annotations

import re
from collections.abc import Sequence

from src.domain.job import JobRequirement
from src.domain.matching import EvidenceRecord
from src.services.eligibility_checker import normalize_text

_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9+#_.-]*|[\u4e00-\u9fff]{2,}")

# The alias table is deliberately small and explicit. It is a recall aid, not
# a source of new user facts.
SKILL_ALIASES: dict[str, str] = {
    "rag": "rag",
    "retrievalaugmentedgeneration": "rag",
    "检索增强生成": "rag",
    "bm25": "bm25",
    "向量检索": "vectorsearch",
    "vectorsearch": "vectorsearch",
    "vectorretrieval": "vectorsearch",
    "rerank": "reranker",
    "reranker": "reranker",
    "重排": "reranker",
    "python": "python",
    "py": "python",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "ts": "typescript",
    "typescript": "typescript",
    "js": "javascript",
    "javascript": "javascript",
}


def _tokens(value: str) -> set[str]:
    return set(_TOKEN_PATTERN.findall(normalize_text(value)))


def canonical_skill(value: str) -> str:
    normalized = normalize_text(value)
    return SKILL_ALIASES.get(normalized, normalized)


def skill_mentions(value: str) -> set[str]:
    normalized = normalize_text(value)
    mentions = {
        canonical
        for alias, canonical in SKILL_ALIASES.items()
        if alias in normalized
    }
    return mentions | {
        canonical_skill(token)
        for token in _tokens(value)
        if token in SKILL_ALIASES
    }


def _candidate_score(requirement: JobRequirement, evidence: EvidenceRecord) -> float:
    requirement_text = f"{requirement.name} {requirement.description}"
    evidence_text = f"{evidence.title} {evidence.claim} {' '.join(evidence.skills)}"
    requirement_tokens = _tokens(requirement_text)
    evidence_tokens = _tokens(evidence_text)
    token_overlap = requirement_tokens & evidence_tokens
    skill_overlap = skill_mentions(requirement_text) & (
        skill_mentions(evidence_text)
        | {canonical_skill(skill) for skill in evidence.skills}
    )
    normalized_name = normalize_text(requirement.name)
    normalized_evidence = normalize_text(evidence_text)
    phrase_match = bool(normalized_name and normalized_name in normalized_evidence)
    return float(len(token_overlap) + (2 * len(skill_overlap)) + (2 if phrase_match else 0))


def retrieve_evidence(
    user_id: str,
    requirement: JobRequirement,
    evidence: Sequence[EvidenceRecord],
    *,
    limit: int = 8,
) -> list[EvidenceRecord]:
    """Recall only the current user's evidence using deterministic lexical rules."""

    if limit <= 0:
        return []
    by_id: dict[str, EvidenceRecord] = {}
    for item in evidence:
        if item.user_id != user_id or item.id in by_id:
            continue
        score = _candidate_score(requirement, item)
        if score > 0:
            by_id[item.id] = item.model_copy(update={"retrieval_score": score})
    return sorted(
        by_id.values(),
        key=lambda item: (-float(item.retrieval_score or 0), item.id),
    )[:limit]


class EvidenceRetriever:
    """Named boundary for the M07 analysis orchestrator."""

    @staticmethod
    def retrieve(
        user_id: str,
        requirement: JobRequirement,
        evidence: Sequence[EvidenceRecord],
        *,
        limit: int = 8,
    ) -> list[EvidenceRecord]:
        return retrieve_evidence(user_id, requirement, evidence, limit=limit)
