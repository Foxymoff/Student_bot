"""
Рассылка админа всем пользователям (/announce).

Сообщение приходит без звука, с кнопкой «Скрыть» и удаляется само через 24 часа — тот же
механизм, что у алертов старосты (alert:delete, pending_alerts). Содержимое — копия
сообщения админа (текст с форматированием, фото, видео…) или готовая сводка обновления.
Кому рассылка уже ушла, помечается в БД (users.last_announcement = id рассылки), поэтому
повторное «Разослать» после сбоя досылает только оставшимся.
"""

import asyncio
import logging
from dataclasses import asdict, dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from database import add_pending_alert, get_users_without_announcement, mark_announcement_sent
from keyboards import alert_delete_kb
from message_style import HTML_PARSE_MODE, esc

logger = logging.getLogger(__name__)

# Готовая сводка обновления: у неё постоянный id — дважды её никто не получит.
ANNOUNCEMENT_ID = "2026-09-rich-schedule"
# Пауза между сообщениями рассылки: держимся далеко от лимита Telegram (~30 в секунду).
SEND_PAUSE_SECONDS = 0.05


# От лица автора бота, коротко и по делу: с маленькой буквы, без тире.
ANNOUNCEMENT_LINES: tuple[str, ...] = (
    "обновил расписание в боте:",
    "",
    "• сразу открывается сегодняшний день, дни и недели листаются кнопками под ним",
    "• кнопка «подробнее» переехала под таблицу",
    "• бот запоминает предпочитаемый вид отображения, полный или краткий",
    "• доп. занятия теперь всегда в расписании, отдельную кнопку убрал",
    "• полезные ссылки переехали в меню: /links",
    "",
    "если расписание не отображается, обнови телеграм или включи старый вид: /classic",
    "старый вид оставил только на случай проблем, обновляться он больше не будет",
    "вопросы, баги и предложения: @foxymoff",
)


def announcement_text() -> str:
    """Текст сводки обновления (HTML parse_mode)."""
    return "\n".join(esc(line) for line in ANNOUNCEMENT_LINES)


@dataclass(frozen=True)
class BroadcastContent:
    """Что рассылаем: готовый HTML-текст или копию сообщения админа."""

    text: str | None = None
    from_chat_id: int | None = None
    message_id: int | None = None

    def to_data(self) -> dict:
        return asdict(self)

    @classmethod
    def from_data(cls, data: dict) -> "BroadcastContent":
        return cls(**{key: data.get(key) for key in ("text", "from_chat_id", "message_id")})


class BroadcastAborted(Exception):
    """Сообщение не уходит никому (например, исходник удалён) — рассылка остановлена."""


async def send_broadcast(bot: Bot, user_id: int, content: BroadcastContent) -> int:
    """Отправить одному пользователю: без звука, «Скрыть», автоудаление через 24 часа."""
    if content.text is not None:
        sent = await bot.send_message(
            chat_id=user_id,
            text=content.text,
            reply_markup=alert_delete_kb(),
            parse_mode=HTML_PARSE_MODE,
            disable_notification=True,
        )
    else:
        sent = await bot.copy_message(
            chat_id=user_id,
            from_chat_id=content.from_chat_id,
            message_id=content.message_id,
            reply_markup=alert_delete_kb(),
            disable_notification=True,
        )
    await add_pending_alert(user_id, sent.message_id)
    return sent.message_id


def _recipient_gone(exc: TelegramBadRequest) -> bool:
    """Ошибка про конкретного получателя (чата нет), а не про само сообщение."""
    return "chat not found" in str(exc).lower()


async def broadcast_recipients(broadcast_id: str, *, exclude: set[int] = frozenset()) -> list[int]:
    """Кому рассылка broadcast_id ещё не отправлена (без исключённых, например автора)."""
    users = await get_users_without_announcement(broadcast_id)
    return [user["user_id"] for user in users if user["user_id"] not in exclude]


async def broadcast(
    bot: Bot,
    content: BroadcastContent,
    broadcast_id: str,
    *,
    exclude: set[int] = frozenset(),
    pause: float = SEND_PAUSE_SECONDS,
) -> tuple[int, int]:
    """Разослать всем, кому рассылка ещё не отправлена. Вернуть (отправлено, не доставлено).

    Заблокировавших бота и удалённые чаты помечаем как обработанные — повторять
    бессмысленно; сетевые ошибки не помечаем, их догонит повторное «Разослать».
    Если ломается само сообщение, бросаем BroadcastAborted, не помечая остальных.
    """
    sent = failed = 0
    for user_id in await broadcast_recipients(broadcast_id, exclude=exclude):
        try:
            try:
                await send_broadcast(bot, user_id, content)
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
                await send_broadcast(bot, user_id, content)
        except TelegramForbiddenError as exc:
            logger.info("Рассылка не доставлена пользователю %s: %s", user_id, exc)
            await mark_announcement_sent(user_id, broadcast_id)
            failed += 1
        except TelegramBadRequest as exc:
            if not _recipient_gone(exc):
                raise BroadcastAborted(str(exc)) from exc
            logger.info("Рассылка не доставлена пользователю %s: %s", user_id, exc)
            await mark_announcement_sent(user_id, broadcast_id)
            failed += 1
        except Exception as exc:
            logger.warning("Не удалось отправить рассылку пользователю %s: %s", user_id, exc)
            failed += 1
        else:
            await mark_announcement_sent(user_id, broadcast_id)
            sent += 1
        await asyncio.sleep(pause)
    logger.info("Рассылка %s: отправлено %d, не доставлено %d", broadcast_id, sent, failed)
    return sent, failed
