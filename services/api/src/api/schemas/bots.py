"""Pydantic v2 схемы бота для api."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

LifecycleStatus = Literal["in_development", "active", "frozen", "unpaid"]


class BotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    enabled: bool
    phone: str | None
    linked_at: datetime | None
    # Живой статус сессии Baileys (FEATURES.md 6.17) — connecting/qr/open/
    # reconnecting/logged_out, None пока не привязан ни разу. Пишет gateway
    # напрямую при каждом connection.update, см. Bot.status в libs/db/src/db/models.py.
    status: str | None
    last_seen: datetime | None
    system_prompt: str
    image_prompt: str | None
    pdf_prompt: str | None
    timezone: str
    settings: dict[str, Any]
    # Сотрудник (роль prompter), ведущий бота — FEATURES.md 6.18, ответственный
    # при создании. email — витринное поле (join на users), сырой id в
    # кабинете не показать читаемо; оба заполняются вручную в роутере
    # (bot.responsible_user, а не автомачинг from_attributes — ORM-атрибута
    # responsible_user_email не существует).
    responsible_user_id: UUID | None
    # Дефолт None — model_validate(bot) не видит этого поля на ORM-объекте
    # (from_attributes читает только реальные атрибуты), значение
    # проставляется ПОСЛЕ валидации в _to_bot_out (routers/bots.py); без
    # дефолта здесь сама model_validate() упала бы "field required".
    responsible_user_email: str | None = None
    # Служебный статус клиента (FEATURES.md 6.22) — только superadmin/admin,
    # остальным роутер обнуляет (см. _to_bot_out). Дефолт None по той же
    # причине, что и responsible_user_email выше.
    lifecycle_status: LifecycleStatus | None = None
    created_at: datetime


class BotCreate(BaseModel):
    name: str
    responsible_user_id: UUID | None = None


class BotPatch(BaseModel):
    """Имя + настройки + ответственный — вкладка "Настройки" (FullBotAccess,
    недоступно роли client, FEATURES.md 6.18 ролевой пересмотр). enabled и
    промпты — отдельные роуты/схемы ниже (BotEnabledPatch/BotPromptsPatch):
    разные вкладки кабинета, разный уровень доступа (enabled-тумблер на
    "Обзоре" доступен и client, промпты — нет)."""

    name: str | None = None
    settings: dict[str, Any] | None = None
    # Явный None ≠ "не передано" (снять ответственного — валидная операция),
    # поэтому в роутере отличаем через "responsible_user_id" in data
    # (exclude_unset), а не через сам этот дефолт.
    responsible_user_id: UUID | None = None


class BotLifecycleStatusPatch(BaseModel):
    """Служебный статус клиента (6.22) — только PlatformWide."""

    lifecycle_status: LifecycleStatus


class BotEnabledPatch(BaseModel):
    """Тумблер "Обзора" (пауза/возобновление) — доступен всем ролям с
    доступом к боту, включая client."""

    enabled: bool


class BotPromptsPatch(BaseModel):
    """Вкладка "Промпты" — FullBotAccess, недоступно client."""

    system_prompt: str | None = None
    image_prompt: str | None = None
    pdf_prompt: str | None = None


class BotStats(BaseModel):
    """Стат-плитки вкладки "Обзор" в кабинете — отдельная ручка (не поле
    BotOut), чтобы не вешать два лишних COUNT(*) на каждый GET /bots
    (список ботов рендерит их пачкой, детальная статистика ему не нужна)."""

    messages_count: int
    contacts_count: int


OverviewPeriod = Literal["24h", "7d", "30d"]


class OverviewCounts(BaseModel):
    """Агрегаты одного окна. resolved_without_human_pct — доля активных
    клиентов без передачи менеджеру; null, если данных недостаточно
    (нет активных клиентов или окно начинается раньше, чем стали писаться
    события передачи — FEATURES.md 5.7)."""

    clients_active: int
    clients_new: int
    messages_in: int
    messages_out: int
    handoffs: int
    resolved_without_human_pct: int | None


class BotOverview(OverviewCounts):
    """Агрегаты "Обзора" за период (6.23) + то же за соседнее окно того же
    размера — для сравнения "было/стало"."""

    period: OverviewPeriod
    handoff_tracked_since: datetime | None
    previous: OverviewCounts


class ActiveChatOut(BaseModel):
    """Один активный (перехваченный менеджером) чат — вкладка "Активные
    чаты". chat_id — сырой WhatsApp JID (remoteJid), contact_* — best-effort
    подсказка из БД (см. db.contacts.find_by_identifier), может быть пустой."""

    chat_id: str
    contact_name: str | None = None
    contact_phone: str | None = None
    # Сколько секунд осталось до авто-возврата — None если TTL почему-то не
    # читается (ключ истёк между SCAN и TTL, защитный случай).
    auto_release_in_seconds: int | None = None
