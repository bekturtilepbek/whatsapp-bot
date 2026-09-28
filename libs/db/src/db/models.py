"""SQLAlchemy 2.0 async модели ядра.

Блок 1 STAGE1_CORE: bots, bot_sessions. Блок 2: contacts, messages,
usage_events. Остальное из ARCHITECTURE.md §5 — по мере фаз (Блок 3+).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Bot(Base):
    """Бот = запись в БД (ADR-005). Ничего per-bot в коде — только здесь."""

    __tablename__ = "bots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    # Отдельный system prompt для vision-ответа на фото (FEATURES.md 2.1).
    # NULL = vision не настроен у этого бота — падаем в старую медиа-заглушку.
    # Без server_default: NULL — осознанное состояние "не настроено", в
    # отличие от system_prompt, где пустая строка была бы валидным (хоть и
    # бесполезным) промптом.
    image_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Отдельный system prompt для PDF-ответа (FEATURES.md 2.4) — та же логика,
    # что и image_prompt: NULL = PDF не настроен у этого бота, падаем в
    # старую медиа-заглушку.
    pdf_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Дефолт по прежней практике продукта (FEATURES.md 9.4) — единственный
    # известный рынок на старте; поле переопределяется per bot.
    timezone: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'Asia/Bishkek'")
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Сотрудник (роль prompter), который "ведёт" бота — для отчётности/
    # дашборда, НЕ то же самое, что доступ (bot_access остаётся отдельным
    # many-to-many, у бота может быть несколько людей с доступом, но не
    # больше одного ответственного). SET NULL, не CASCADE — увольнение/
    # смена роли пользователя не должна сносить бота, только обнулять ссылку.
    responsible_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    session: Mapped[BotSession | None] = relationship(
        back_populates="bot", uselist=False, cascade="all, delete-orphan"
    )
    responsible_user: Mapped[User | None] = relationship(foreign_keys=[responsible_user_id])

    @property
    def phone(self) -> str | None:
        """Номер, если бот когда-либо был привязан — иначе None.
        Требует, чтобы .session был eager-loaded (см. get_bot/list_bots)."""
        return self.session.phone if self.session else None

    @property
    def linked_at(self) -> datetime | None:
        """Момент привязки; None — бот не привязан или был явно отключён
        (clearSession в gateway обнуляет это поле, см. services/gateway/src/db/bots.ts)."""
        return self.session.linked_at if self.session else None

    @property
    def status(self) -> str | None:
        """Живой статус соединения Baileys (FEATURES.md 6.17) — connecting/
        qr/open/reconnecting/logged_out; None — сессия ни разу не поднималась.
        Пишет gateway напрямую в BotSession.status (services/gateway/src/session/manager.ts,
        publishStatus) при каждом connection.update — ADR-006, состояние в Postgres,
        не только событие в Redis Stream (которое пайплайн диалога всё равно дропает)."""
        return self.session.status if self.session else None

    @property
    def last_seen(self) -> datetime | None:
        """Момент последнего события от сокета (любой статус, не только open) —
        обновляется тем же вызовом, что и status. До первого события — None."""
        return self.session.last_seen if self.session else None


class BotSession(Base):
    """Auth-state сессии Baileys — в Postgres (ADR-006), не в памяти процесса.

    bot_id — одновременно PK и FK: у бота ровно одна сессия.
    """

    __tablename__ = "bot_sessions"

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), primary_key=True
    )
    auth_state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # connecting/qr/open/reconnecting/logged_out — набор значений не в БД
    # (простой String, не Postgres enum), валидируется на стороне gateway/api.
    status: Mapped[str | None] = mapped_column(String, nullable=True)

    bot: Mapped[Bot] = relationship(back_populates="session")


class PromptVersion(Base):
    """История промптов бота (FEATURES.md 3.7/3.8) — только для отката/аудита.
    Источник истины для ТЕКУЩЕГО промпта остаётся Bot.system_prompt/
    image_prompt/pdf_prompt (см. db.bots.update_bot) — эта таблица ничего
    не меняет в том, что читает worker для LLM-контекста.
    """

    __tablename__ = "prompt_versions"
    __table_args__ = (
        Index("ix_prompt_versions_bot_kind_created", "bot_id", "kind", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    # Монотонный порядок вставки (тот же паттерн, что Message.seq выше) —
    # created_at = func.now() фиксируется на начало ТРАНЗАКЦИИ в Postgres,
    # а update_bot теперь может вставить baseline- и новую версию в одной
    # транзакции (см. record_version_if_changed) — обе получили бы
    # идентичный created_at, и "последняя версия" стала бы недетерминированной.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False, unique=True)
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    # "main" | "image" | "pdf" — обычная строка (как Message.role,
    # ToolBinding.tool_name), не Postgres ENUM: миграция на новый kind проще.
    kind: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'admin'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Contact(Base):
    """Контакт = wa_id + lid (FEATURES.md 9.2): WhatsApp мигрирует на LID,
    без второго поля история человека раздваивается. Матчинг — по wa_id ИЛИ
    lid, см. db.contacts.match_or_create_contact.
    """

    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("bot_id", "wa_id", name="uq_contacts_bot_wa_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    wa_id: Mapped[str | None] = mapped_column(String, nullable=True)
    lid: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Message(Base):
    """История диалога. wa_msg_id — только у сообщений клиента (role=user);
    у ответов ассистента NULL (свой client_msg_id живёт в Redis-идемпотентности
    gateway, не здесь) — UNIQUE(bot_id, wa_msg_id) NULL с NULL не конфликтует.

    seq — монотонный порядок вставки (Postgres IDENTITY), источник истины для
    сортировки истории. ts НЕ годится сам по себе: insert_outgoing пишет
    datetime.now(UTC) с полной точностью, insert_incoming — ts из события
    (у реального WhatsApp это целые секунды) — при вставках впритык друг к
    другу более грубый ts может оказаться МЕНЬШЕ уже сохранённого точного,
    хотя запись сделана позже, и сортировка по ts переставляет историю
    местами. seq не подвержен этому — id не подходит на его место (UUID
    случайный, не монотонный).
    """

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("bot_id", "wa_msg_id", name="uq_messages_bot_wa_msg_id"),
        Index("ix_messages_contact_id_seq", "contact_id", "seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False, unique=True)
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    wa_msg_id: Mapped[str | None] = mapped_column(String, nullable=True)
    media_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UsageEvent(Base):
    """Учёт токенов и стоимости вызовов LLM (FEATURES.md 3.9 — упрощённая
    локальная оценка cost вместо OpenAI usage API, см. libs/llm/pricing.py).
    """

    __tablename__ = "usage_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    model: Mapped[str] = mapped_column(String, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BlockedContact(Base):
    """Чёрный список номеров (FEATURES.md 1.5). Матчинг — по тому же
    "сырому" wa_id (без "+"), что и Contact.wa_id/дедуп/handoff, НЕ по
    нормализованному телефону (эталон — V1, ignored_numbers).
    """

    __tablename__ = "blocked_contacts"
    __table_args__ = (
        UniqueConstraint("bot_id", "phone", name="uq_blocked_contacts_bot_phone"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    phone: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ToolBinding(Base):
    """Тулзы, включённые конкретному боту (FEATURES.md 4.13). Сама тулза —
    код в libs/tools; эта таблица решает, что боту доступно и с каким
    config (например chat_id для telegram-лидов).
    """

    __tablename__ = "tool_bindings"
    __table_args__ = (
        UniqueConstraint("bot_id", "tool_name", name="uq_tool_bindings_bot_tool_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Product(Base):
    """Каталог товаров бота (FEATURES.md 3.4/4.1-4.6). На этой итерации —
    только сам каталог для контекста LLM (3.4); product_media/
    product_embeddings и pgvector-расширение — отдельными миграциями,
    когда появятся 4.3 (карточки) и 4.1 (векторный поиск), не раньше.

    display_custom — переопределение вывода на конкретном товаре
    (FEATURES.md 4.6), не используется до этой фичи — JSONB с дефолтом
    '{}', чтобы не понадобилась ещё одна миграция под будущие поля.
    """

    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    sku: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_custom: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # lazy="raise" — доступ к .media без явного selectinload() кидает
    # понятную ошибку сразу, а не MissingGreenlet где-то в сериализации:
    # async SQLAlchemy не умеет лениво подгружать relationship вне активного
    # await-контекста. db.products.get_product/list_products грузят media
    # явно только когда вызывающий передаёт with_media=True (api-роутер) —
    # worker (контекст LLM, product_search) не платит лишним запросом за то,
    # что не использует.
    media: Mapped[list[ProductMedia]] = relationship(
        order_by="ProductMedia.position", lazy="raise", passive_deletes=True
    )


class ProductEmbedding(Base):
    """Эмбеддинг товара для pgvector-поиска (FEATURES.md 4.1) — 1:1 с
    товаром (как BotSession.bot_id). Кто считает эмбеддинг и когда —
    Волна 3 (CRUD, create/update товара); здесь только хранение и чтение.
    """

    __tablename__ = "product_embeddings"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)


class ProductMedia(Base):
    """Фото и видео товара, одно или несколько, порядок — position
    (FEATURES.md 4.3/4.4). Видео — MIME video/mp4, отправляется нативным
    video-сообщением, тот же принцип диспетчеризации по mime_type, что и
    у Document (FEATURES.md 4.9). Загрузка (значит, и заполнение этой
    таблицы) — Волна 3 (6.8), здесь только хранение и чтение."""

    __tablename__ = "product_media"
    __table_args__ = (
        UniqueConstraint("product_id", "position", name="uq_product_media_product_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Document(Base):
    """Файл бота (FEATURES.md 4.8/4.9) — любой тип; video/* отправляется
    нативным video-сообщением, остальное — документом (решает тулза по
    mime_type, см. libs/tools/send_document.py). Загрузка (заполнение
    этой таблицы) — Волна 3 (6.7), здесь только хранение и чтение."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("bot_id", "filename", name="uq_documents_bot_filename"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String, nullable=False)
    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class User(Base):
    """Пользователь кабинета. Роль (superadmin/admin/prompter/client) —
    services/api/src/api/security.py решает по ней доступ. superadmin/
    admin видят все боты без грантов; prompter/client — только те, что
    перечислены в BotAccess (FEATURES.md 6.18). Plain String, не Postgres
    ENUM — тот же принцип, что у PromptVersion.kind (см. ниже) —
    миграция на новую роль проще."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'client'"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # Версия сессий: кладётся в JWT (claim "tv") и сверяется на каждом запросе.
    # Смена пароля её увеличивает — все ранее выданные токены перестают
    # действовать (раньше жили свои 30 дней и после смены пароля).
    token_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BotAccess(Base):
    """Грант доступа prompter/client к конкретному боту. superadmin/admin
    (User.role) гранты не нужны — видят все боты."""

    __tablename__ = "bot_access"
    __table_args__ = (UniqueConstraint("user_id", "bot_id", name="uq_bot_access_user_bot"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuditLog(Base):
    """Кто и когда поменял промпт/настройки/товар и т.п. (FEATURES.md 6.19).
    Пишется ASGI-middleware (services/api/src/api/audit.py), не роутами
    напрямую — эта модель только хранит запись."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_created_at", "created_at"),
        Index("ix_audit_log_bot_id", "bot_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    # Намеренно БЕЗ ondelete (в отличие от BotAccess, где ondelete="CASCADE"):
    # аудит-запись должна пережить удаление пользователя/бота, на которого
    # ссылается, а не исчезнуть вместе с ним. Если когда-нибудь появится
    # DELETE /users/{id} или DELETE /bots/{id} — попытка удалить строку с
    # историей аудита упрётся в FK constraint violation. Это ожидаемо: не
    # добавлять сюда CASCADE не глядя, решение нужно принимать осознанно
    # (например, обнулять actor_user_id/bot_id вместо каскадного удаления).
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    bot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
