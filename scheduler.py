"""
Фоновые уведомления: ежедневное расписание и напоминания о дедлайнах.
"""

import logging
import datetime

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import DAILY_SCHEDULE_HOUR, DAILY_SCHEDULE_MINUTE
from database import get_all_users, get_all_deadlines, mark_deadline_notified
from handlers.schedule import get_schedule_for_date

logger = logging.getLogger(__name__)


async def send_daily_schedule(bot: Bot) -> None:
    """Отправить расписание на текущий день всем пользователям."""
    today = datetime.date.today()
    users = await get_all_users()

    for user in users:
        try:
            text = get_schedule_for_date(user["group_name"], today)
            await bot.send_message(
                chat_id=user["user_id"],
                text=f"☀️ Доброе утро! Вот расписание на сегодня:\n\n{text}",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.warning("Не удалось отправить расписание пользователю %s: %s", user["user_id"], e)

    logger.info("Ежедневная рассылка расписания завершена (%d пользователей)", len(users))


async def check_deadlines(bot: Bot) -> None:
    """Проверить дедлайны и отправить уведомления за 24ч и за 1ч."""
    now = datetime.datetime.now()
    deadlines = await get_all_deadlines()

    for dl in deadlines:
        # Дедлайн хранится как дата (YYYY-MM-DD), считаем что срок — конец дня (23:59)
        dl_date = datetime.date.fromisoformat(dl["deadline_date"])
        dl_datetime = datetime.datetime.combine(dl_date, datetime.time(23, 59))
        delta = dl_datetime - now

        hours_left = delta.total_seconds() / 3600

        # Уведомление за 24 часа
        if 23 <= hours_left <= 25 and not dl["notified_24h"]:
            try:
                await bot.send_message(
                    chat_id=dl["user_id"],
                    text=(
                        f"⏰ Напоминание: до дедлайна «{dl['title']}» "
                        f"остались примерно сутки!\n"
                        f"📅 Срок: {dl_date.strftime('%d.%m.%Y')}"
                    ),
                )
                await mark_deadline_notified(dl["id"], "notified_24h")
                logger.info("Уведомление 24ч для дедлайна #%s отправлено", dl["id"])
            except Exception as e:
                logger.warning("Ошибка отправки 24ч уведомления: %s", e)

        # Уведомление за 1 час 🔥
        if 0 <= hours_left <= 1.5 and not dl["notified_1h"]:
            try:
                await bot.send_message(
                    chat_id=dl["user_id"],
                    text=(
                        f"🔥 СРОЧНО! До дедлайна «{dl['title']}» "
                        f"остался примерно 1 час!\n"
                        f"📅 Срок: {dl_date.strftime('%d.%m.%Y')}"
                    ),
                )
                await mark_deadline_notified(dl["id"], "notified_1h")
                logger.info("Уведомление 1ч для дедлайна #%s отправлено", dl["id"])
            except Exception as e:
                logger.warning("Ошибка отправки 1ч уведомления: %s", e)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Настроить и вернуть планировщик задач."""
    scheduler = AsyncIOScheduler()

    # Ежедневная рассылка расписания
    scheduler.add_job(
        send_daily_schedule,
        trigger="cron",
        hour=DAILY_SCHEDULE_HOUR,
        minute=DAILY_SCHEDULE_MINUTE,
        args=[bot],
        id="daily_schedule",
        replace_existing=True,
    )

    # Проверка дедлайнов каждые 30 минут
    scheduler.add_job(
        check_deadlines,
        trigger="interval",
        minutes=30,
        args=[bot],
        id="check_deadlines",
        replace_existing=True,
    )

    logger.info(
        "Планировщик настроен: расписание в %02d:%02d, проверка дедлайнов каждые 30 мин",
        DAILY_SCHEDULE_HOUR,
        DAILY_SCHEDULE_MINUTE,
    )
    return scheduler
