"""Ranking cache (M5): keyed by `content_hash` so an unchanged job is never re-ranked.

Thin adapter over the `ranking_cache` table (see `repository`) that speaks in terms
of `RankingResult` and remembers which model produced each cached judgement.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.database import repository as repo
from app.ranking.prompt import RankingResult


@dataclass
class CachedRanking:
    """A cached judgement plus the model that produced it."""

    result: RankingResult
    llm_model: str | None


def get_cached(session: Session, content_hash: str) -> CachedRanking | None:
    """Return the cached ranking for a content hash, or None on a miss."""
    row = repo.get_cached_ranking(session, content_hash)
    if row is None:
        return None
    result = RankingResult(
        score=row.score,
        pros=list(row.pros_json or []),
        cons=list(row.cons_json or []),
        reason=row.reason or "",
    )
    return CachedRanking(result=result, llm_model=row.llm_model)


def store(session: Session, content_hash: str, result: RankingResult, llm_model: str) -> None:
    """Persist a freshly-computed ranking so the next run reuses it."""
    repo.set_cached_ranking(
        session,
        content_hash=content_hash,
        score=result.score,
        pros=result.pros,
        cons=result.cons,
        reason=result.reason,
        llm_model=llm_model,
    )
