"""GET /audit-log (FEATURES.md 6.19) — superadmin/admin (platform-wide),
записи пишет ASGI-middleware (services/api/src/api/audit.py), не этот
роутер.
"""

from __future__ import annotations

import uuid

from db.audit_log import list_entries
from fastapi import APIRouter, Query

from ..db import SessionDep
from ..schemas.audit_log import AuditLogOut
from ..security import PlatformWide

router = APIRouter(prefix="/audit-log", tags=["audit-log"])

AUDIT_LOG_DEFAULT_LIMIT = 50
AUDIT_LOG_MAX_LIMIT = 200


@router.get("", response_model=list[AuditLogOut])
async def list_audit_log(
    session: SessionDep,
    _admin: PlatformWide,
    bot_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    limit: int = Query(AUDIT_LOG_DEFAULT_LIMIT, ge=1, le=AUDIT_LOG_MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> list[AuditLogOut]:
    entries = await list_entries(
        session, bot_id=bot_id, actor_user_id=actor_user_id, limit=limit, offset=offset
    )
    return [
        AuditLogOut(
            id=e.id,
            actor_user_id=e.actor_user_id,
            actor_email=e.actor_email,
            bot_id=e.bot_id,
            bot_name=e.bot_name,
            action=e.action,
            payload=e.payload,
            created_at=e.created_at,
        )
        for e in entries
    ]
