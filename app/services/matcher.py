from __future__ import annotations

import math
import re
from typing import Iterable, List, Optional

from app.core.models import MatchCandidate, Product

try:  # pragma: no cover - depends on optional dependency
    from rapidfuzz import fuzz

    def similarity(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        return float(fuzz.token_set_ratio(a, b)) / 100.0

except ImportError:  # pragma: no cover
    from difflib import SequenceMatcher

    def similarity(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, a, b).ratio()


FLAGSHIP_PATTERNS = (
    "旗舰店",
    "自营",
    "官方旗舰",
    "官方店",
    "品牌直营",
)

BRACKET_RE = re.compile(r"[【\[（(][^】\])）]*[】\])）]")


def is_flagship_store(store: str) -> bool:
    store = store or ""
    return any(pattern in store for pattern in FLAGSHIP_PATTERNS)


def clean_title(title: str) -> str:
    text = BRACKET_RE.sub(" ", title or "")
    return re.sub(r"\s+", " ", text).strip()


def build_query(product: Product) -> str:
    return product.query


def score_candidate(candidate: MatchCandidate, product: Product) -> float:
    score = 0.0
    title = clean_title(candidate.title)
    query = product.query

    title_score = similarity(title, query) if title else 0.0
    score += title_score * 45.0

    if product.spec:
        spec_score = similarity(title, product.spec)
        if product.spec.lower() in title.lower():
            spec_score = max(spec_score, 0.9)
        score += spec_score * 15.0

    if candidate.is_flagship or is_flagship_store(candidate.store):
        score += 25.0

    if product.store_hint:
        store_score = similarity(candidate.store, product.store_hint)
        score += store_score * 25.0

    if candidate.sales > 0:
        score += min(math.log10(candidate.sales + 1) / 5.0, 1.0) * 10.0

    return round(score, 2)


def rank_candidates(
    candidates: Iterable[MatchCandidate], product: Product
) -> List[MatchCandidate]:
    ranked: List[MatchCandidate] = []
    for candidate in candidates:
        candidate.score = score_candidate(candidate, product)
        ranked.append(candidate)
    ranked.sort(key=lambda c: (c.score, c.is_flagship, c.sales), reverse=True)
    return ranked


def best_candidate(
    candidates: Iterable[MatchCandidate], product: Product, min_score: float = 55.0
) -> Optional[MatchCandidate]:
    ranked = rank_candidates(candidates, product)
    if not ranked:
        return None
    if ranked[0].score < min_score:
        return None
    return ranked[0]
