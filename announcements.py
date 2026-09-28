"""
Сводка обновления для пользователей.

Беззвучное обычное сообщение (не rich — его прочитают и старые версии Telegram) с кнопкой
«Скрыть» и автоудалением через 24 часа: тот же механизм, что у алертов старосты
(alert:delete, pending_alerts). Рассылает админ командой /announce; кому сводка уже
отправлена, помечается в БД — повторное нажатие и рестарт не дают дублей.
"""

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from database import add_pending_alert, get_users_without_announcement, mark_announcement_sent
from keyboards import alert_delete_kb
from message_style import HTML_PARSE_MODE, titled

logger = logging.getLogger(__name__)

# Новая сводка — новый идентификатор: тогда её получат все снова.
ANNOUNCEMENT_ID = "2026-09-rich-schedule"
# Пауза между сообщениями рассылки: держимся далеко от лимита Telegram (~30 в секунду).
SEND_PAUSE_SECONDS = 0.05


def announcement_text() -> str:
    """Текст сводки обновления (HTML parse_mode)."""
    return titled(
        "Что нового в расписании",
        "• Одна аккуратная таблица на день: номер пары, предмет, аудитория.\n"
        "• «Подробнее» под таблицей — полные названия, преподаватели и время. "
        "Бот запомнит, какой вид тебе удобнее.\n"
        "• Кнопками под расписанием листаются дни и недели — прямо в том же сообщении.\n"
        "• Выбранные доп. занятия теперь сразу в расписании.\n"
        "• Полезные ссылки переехали в меню: /links\n\n"
        "Если расписание не отображается, обнови Telegram или включи прежний вид: /classic",
    )


async def send_announcement(bot: Bot, user_id: int) -> int:
    """Отправить сводку одному пользователю: без звука, «Скрыть», автоудаление через 24 ч."""
    sent = await bot.send_message(
        chat_id=user_id,
        text=announcement_text(),
        reply_markup=alert_delete_kb(),
        parse_mode=HTML_PARSE_MODE,
        disable_notification=True,
    )
    await add_pending_alert(user_id, sent.message_id)
    await mark_announcement_sent(user_id, ANNOUNCEMENT_ID)
    return sent.message_id


async def broadcast_announcement(bot: Bot, *, pause: float = SEND_PAUSE_SECONDS) -> tuple[int, int]:
    """Разослать сводку всем, кому она ещё не отправлена. Вернуть (отправлено, не доставлено).

    Заблокировавших бота и недоступные чаты помечаем как обработанные — повторять
    бессмысленно; сетевые и прочие ошибки не помечаем, их догонит повторная рассылка.
    """
    sent = failed = 0
    for user in await get_users_without_announcement(ANNOUNCEMENT_ID):
        user_id = user["user_id"]
        try:
            try:
                await send_announcement(bot, user_id)
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
                await send_announcement(bot, user_id)
        except (TelegramForbiddenError, TelegramBadRequest) as exc:
            logger.info("Сводка не доставлена пользователю %s: %s", user_id, exc)
            await mark_announcement_sent(user_id, ANNOUNCEMENT_ID)
            failed += 1
        except Exception as exc:
            logger.warning("Не удалось отправить сводку пользователю %s: %s", user_id, exc)
            failed += 1
        else:
            sent += 1
        await asyncio.sleep(pause)
    logger.info("Сводка обновления разослана: отправлено %d, не доставлено %d", sent, failed)
    return sent, failed
