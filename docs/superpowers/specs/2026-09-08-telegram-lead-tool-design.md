# Лиды в Telegram-группу (FEATURES.md 4.7)

**Статус:** утверждено пользователем 2026-09-08
**Волна:** 2, итерация 6 из 6 (после 4.13, 3.4, 4.1/4.2, 4.3/4.4, 4.5/4.6;
следующая и последняя в Волне 2 — 4.8/4.9 файлы/видео)

## Контекст

Вторая настоящая тулза платформы (первая — `search_products`, 4.1/4.2).
Клиент интересуется покупкой/услугой — LLM собирает данные и отправляет
уведомление менеджерам в Telegram-группу, как это делал V1
(`sendToTelegramGroup`).

**Расхождения с FEATURES.md, найденные в архиве**:
- Сигнатура `sendToTelegramGroup(data, userId, notificationType)` из
  FEATURES.md неточна — реально `(data, userId)`, третьего параметра нет
  ни в одной из трёх копий архива.
- FEATURES.md помечает фичу как `V1`, но по факту это **V1-DRIFT**: общий
  каркас функции (Telegram Bot API `sendMessage`, credentials из
  `process.env`, `try/catch` → текст ошибки как результат тулзы, ссылка
  `wa.me/{номер}`) идентичен во всех трёх копиях архива, но **набор
  полей лида и текст сообщения жёстко зашиты под нишу конкретного
  клиента и разъехались**: node-bot3 (недвижимость) — 6 полей
  (client_name, phone_number, rooms_or_square_meters, payment_method,
  down_payment, purchase_purpose); node-bot2 (стройка) — 3 поля
  (client_name, phone_number, details). node-decide не содержит эту
  тулзу вообще.

**Решение пользователя**: платформенный стандарт — generic-вариант по
образцу node-bot2 (имя/телефон/свободный текст с деталями), без
per-bot-настраиваемой схемы полей в этой итерации; такая настройка —
задел на будущий UI (Волна 3+). Обе строки FEATURES.md (4.7 про фичу и
её реальную сигнатуру) фиксируются как V1-DRIFT в самом файле, по
прецеденту 4.2/4.3.

## Слои

Первая итерация, реально трогающая `libs/integrations` (кроме уже
существующего `storage`) — HTTP-вызов к внешнему API, не к БД/LLM.

- **`libs/integrations`** — новый `telegram.py`, тонкий клиент Telegram
  Bot API. Новая зависимость пакета — `httpx` (уже используется
  транзитивно во всём стеке через `openai`, поведение под нагрузкой уже
  проверено проектом).
- **`libs/tools`** — новая тулза `telegram_lead.py`, аналогично
  `product_search.py`: единственное место, знающее и про
  `integrations.telegram`, и про `db` (подгрузка контакта).
- **`libs/db`** — ничего нового не создаётся: `Contact` уже есть,
  `ToolBinding.config` уже задуман под `chat_id` (комментарий модели).

## `libs/integrations/src/integrations/telegram.py`

```python
"""Клиент Telegram Bot API — тонкая обёртка над sendMessage. Токен —
платформенный (ADR-007, .env только на серверах), chat_id — per bot,
передаётся вызывающим (tool_bindings.config, см. libs/tools/telegram_lead.py).
"""

from __future__ import annotations

import os

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org"
REQUEST_TIMEOUT_SECONDS = 10.0


class TelegramNotConfiguredError(Exception):
    """TELEGRAM_BOT_TOKEN не задан в окружении — платформа не настроена
    на отправку уведомлений в Telegram вообще (не путать с тем, что у
    конкретного бота нет chat_id — это отдельная, per-bot ошибка,
    обрабатывается в tools/telegram_lead.py)."""


async def send_message(chat_id: str, text: str) -> None:
    """Бросает исключение при сбое (сетевом, таймауте, ошибке Telegram
    API) — вызывающий (тулза) решает, как это представить LLM."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise TelegramNotConfiguredError("TELEGRAM_BOT_TOKEN не задан")

    url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
        )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error: {payload.get('description')}")
```

`raise_for_status()` покрывает сетевые/HTTP-ошибки (4xx/5xx от самого
Telegram, например неверный токен → 401); `payload.get("ok")` покрывает
семантические ошибки, которые Telegram возвращает с HTTP 200 (например,
чат не найден).

## `libs/tools/src/tools/telegram_lead.py`

```python
"""Лид в Telegram-группу (FEATURES.md 4.7) — эталон V1 (sendToTelegramGroup),
generic-набор полей (не привязан к нише клиента, см. спеку). chat_id —
per bot (tool_bindings.config), токен — платформенный (integrations.telegram).
"""

from __future__ import annotations

from typing import Any, ClassVar

from db.contacts import get_contact
from integrations.telegram import TelegramNotConfiguredError, send_message

from .base import ToolContext, ToolExecutionResult

_MISSING_CHAT_ID_ERROR = "Лиды в Telegram не настроены для этого бота (нет chat_id)."
_NOT_CONFIGURED_ERROR = "Лиды в Telegram не настроены на платформе (нет TELEGRAM_BOT_TOKEN)."


def _format_lead_message(client_name: str, phone: str, details: str, wa_link: str) -> str:
    """Эталон V1 (sendToTelegramGroup) — нейтральный текст, не привязанный
    к нише клиента (в архиве было под конкретный бизнес каждой копии)."""
    return (
        f"*Новая заявка*\n\n"
        f"*Клиент:* {client_name}\n"
        f"*Телефон:* `{phone}`\n"
        f"*Детали:* {details}\n\n"
        f"[Написать в WhatsApp]({wa_link})"
    )


class TelegramLeadTool:
    name = "send_telegram_lead"
    description = "Отправляет заявку клиента менеджерам в Telegram-группу."
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "client_name": {"type": "string", "description": "Имя клиента"},
            "phone_number": {
                "type": "string",
                "description": (
                    "Номер телефона клиента, если он назвал ДРУГОЙ номер, не тот, "
                    "с которого пишет в WhatsApp. Если не называл — не заполнять."
                ),
            },
            "details": {
                "type": "string",
                "description": "Что интересует клиента, контекст диалога",
            },
        },
        "required": ["client_name", "details"],
    }

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolExecutionResult:
        chat_id = ctx.config.get("chat_id")
        if not chat_id:
            return ToolExecutionResult(content=_MISSING_CHAT_ID_ERROR)

        async with ctx.session_factory() as session:
            contact = await get_contact(session, ctx.contact_id)

        wa_id = contact.wa_id if contact is not None else None
        phone = str(arguments.get("phone_number") or wa_id or "не указан")
        client_name = str(arguments.get("client_name", ""))
        details = str(arguments.get("details", ""))
        wa_link = f"https://wa.me/{wa_id}" if wa_id else "не указана"

        message = _format_lead_message(client_name, phone, details, wa_link)

        try:
            await send_message(str(chat_id), message)
        except TelegramNotConfiguredError:
            return ToolExecutionResult(content=_NOT_CONFIGURED_ERROR)
        except Exception:
            return ToolExecutionResult(content="Не удалось отправить заявку в Telegram.")

        return ToolExecutionResult(content="Заявка отправлена менеджерам.")
```

`get_contact(session, contact_id)` — новая узкая функция в `libs/db/src/db/contacts.py`
(`session.get(Contact, contact_id)` — прямой lookup по PK, не `select`)
— единственное дополнение в `libs/db` для этой итерации, миграций не
требует.

## Границы этой итерации

Не входит: per-bot настраиваемая схема полей лида (задел на UI, Волна
3+); нормализация номера по FEATURES.md 9.1 (отдельная фича — `wa_id`
контакта используется как есть, без форматирования); ретраи HTTP-вызова
к Telegram (тот же принцип, что и у остальных внешних вызовов в этой
волне — не добавляем без явного технического долга/находки); что-либо
из `notificationType` FEATURES.md, — параметра не существует в архиве,
не переносим.

## Тесты

- `libs/integrations`: `send_message` — успешный вызов (мок `httpx`
  через `httpx.MockTransport`, не реальная сеть), `TelegramNotConfiguredError`
  при отсутствующем токене, `raise_for_status`/`ok:false` пробрасываются
  как исключения.
- `libs/tools`: `TelegramLeadTool.execute()` — успешная отправка
  (mocked `send_message`), нет `chat_id` в `ctx.config` → текст ошибки
  без похода в сеть, `TelegramNotConfiguredError` → текст ошибки,
  произвольное исключение при отправке → текст ошибки (не проброс),
  `phone_number` не передан LLM → используется `wa_id` контакта,
  `_format_lead_message` — форматирование текста.
- `libs/db`: `get_contact` — находит по id, `None` для несуществующего.
