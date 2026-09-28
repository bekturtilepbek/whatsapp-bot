"""GET /usage (FEATURES.md 6.15) — superadmin/admin (platform-wide),
сумма токенов/стоимости по боту за период. cost — локальная оценка (см.
db.usage docstring), не биллинговые данные OpenAI.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from db.usage import list_usage_by_bot
from fastapi import APIRouter, HTTPException, Query

from ..db import SessionDep
from ..schemas.usage import UsageSummaryOut
from ..security import PlatformWide

router = APIRouter(prefix="/usage", tags=["usage"])

# "all" — без отсечки по времени, весь usage_events целиком.
PERIOD_TO_DAYS: dict[str, int | None] = {"7d": 7, "30d": 30, "90d": 90, "all": None}
DEFAULT_PERIOD = "30d"


@router.get("", response_model=list[UsageSummaryOut])
async def list_usage(
    session: SessionDep,
    _admin: PlatformWide,
    period: str = Query(DEFAULT_PERIOD),
) -> list[UsageSummaryOut]:
    if period not in PERIOD_TO_DAYS:
        allowed = sorted(PERIOD_TO_DAYS)
        raise HTTPException(
            status_code=422, detail=f"Неизвестный период: {period!r} (допустимо: {allowed})"
        )
    days = PERIOD_TO_DAYS[period]
    since = datetime.now(UTC) - timedelta(days=days) if days is not None else None

    summaries = await list_usage_by_bot(session, since=since)
    return [
        UsageSummaryOut(
            bot_id=s.bot_id,
            bot_name=s.bot_name,
            tokens_in=s.tokens_in,
            tokens_out=s.tokens_out,
            cost=s.cost,
        )
        for s in summaries
    ]
