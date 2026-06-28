"""
Фоновые уведомления: ежедневное расписание.
"""

import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import APP_TIMEZONE, app_now, app_today
from database import get_all_users, mark_user_daily_notify_sent
from extra_schedule import parse_extra_choices
from handlers.schedule import get_schedule_for_date_short
from keyboards import schedule_detail_kb
from message_style import HTML_PARSE_MODE, title

logger = logging.getLogger(__name__)


async def send_due_daily_schedules(bot: Bot) -> None:
    """Отправить ежедневное расписание пользователям, у которых подошло время."""
    now = app_now()
    today = app_today()
    today_iso = today.isoformat()
    current_time = now.strftime("%H:%M")
    users = await get_all_users()
    sent_count = 0

    for user in users:
        if not user.get("daily_notify_enabled"):
            continue
        if str(user.get("daily_notify_time") or "08:00") != current_time:
            continue
        if user.get("daily_notify_last_date") == today_iso:
            continue

        try:
            sg_inf = user.get("subgroup_cs", 1) or 1
            sg_eng = user.get("subgroup_en", 1) or 1
            compact = bool(user.get("compact_mode"))
            extra_keys = (
                parse_extra_choices(user.get("extra_choices"))
                if user.get("extra_in_schedule")
                else []
            )
            text = await get_schedule_for_date_short(
                user["group_name"], today, sg_inf, sg_eng, compact, extra_keys
            )
            await bot.send_message(
                chat_id=user["user_id"],
                text=f"☀️ {title('Расписание на сегодня')}\n\n{text}",
                reply_markup=schedule_detail_kb(today.isoformat()),
                parse_mode=HTML_PARSE_MODE,
                disable_notification=not bool(user.get("daily_notify_sound", 1)),
            )
            await mark_user_daily_notify_sent(user["user_id"], today_iso)
            sent_count += 1
        except Exception as e:
            logger.warning(
                "Не удалось отправить расписание пользователю %s: %s", user["user_id"], e
            )

    if sent_count:
        logger.info("Ежедневное расписание отправлено (%d пользователей)", sent_count)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Настроить и вернуть планировщик задач."""
    scheduler = AsyncIOScheduler(timezone=APP_TIMEZONE)

    # Персональные ежедневные уведомления. По умолчанию у пользователей выключены.
    scheduler.add_job(
        send_due_daily_schedules,
        trigger="interval",
        minutes=1,
        next_run_time=app_now(),
        args=[bot],
        id="daily_schedule",
        replace_existing=True,
    )

    logger.info("Планировщик настроен: проверка ежедневных расписаний каждую минуту")
    return scheduler
