"""
Фоновые уведомления: ежедневное расписание.
"""

import datetime
import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import APP_TIMEZONE, app_now, app_today
from database import (
    delete_pending_alerts,
    get_all_users,
    get_expired_alerts,
    get_overrides,
    mark_user_daily_notify_sent,
)
from extra_schedule import get_extras_for_date, parse_extra_choices
from handlers.schedule import (
    _has_added_override,
    get_lessons_for_date,
    get_schedule_for_date_short,
)
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
            # Режим: расписание на сегодня (утро) или на завтра (вечер).
            target = str(user.get("daily_notify_target") or "today")
            if target == "tomorrow":
                target_date = today + datetime.timedelta(days=1)
                header = f"🌙 {title('Расписание на завтра')}"
            else:
                target_date = today
                header = f"☀️ {title('Расписание на сегодня')}"

            sg_inf = user.get("subgroup_cs", 1) or 1
            sg_eng = user.get("subgroup_en", 1) or 1
            compact = bool(user.get("compact_mode"))
            extra_keys = (
                parse_extra_choices(user.get("extra_choices"))
                if user.get("extra_in_schedule")
                else []
            )

            # Пустой день (нет ни пар, ни выбранных кружков, ни добавленных старостой
            # пар) не отправляем — без лишнего шума.
            lessons = get_lessons_for_date(user["group_name"], target_date)
            extras = get_extras_for_date(user["group_name"], target_date, extra_keys)
            if not lessons and not extras:
                overrides = await get_overrides(user["group_name"], target_date.isoformat())
                if not _has_added_override(overrides):
                    continue

            text = await get_schedule_for_date_short(
                user["group_name"], target_date, sg_inf, sg_eng, compact, extra_keys
            )
            # Удаляем неактуальное ежедневное расписание за прошлый раз, если оно ещё висит.
            prev_msg_id = user.get("daily_notify_last_msg_id")
            if prev_msg_id:
                try:
                    await bot.delete_message(user["user_id"], prev_msg_id)
                except Exception:
                    pass  # сообщение уже удалено или недоступно
            sent = await bot.send_message(
                chat_id=user["user_id"],
                text=f"{header}\n\n{text}",
                reply_markup=schedule_detail_kb(target_date.isoformat()),
                parse_mode=HTML_PARSE_MODE,
                disable_notification=not bool(user.get("daily_notify_sound", 1)),
            )
            await mark_user_daily_notify_sent(user["user_id"], today_iso, sent.message_id)
            sent_count += 1
        except Exception as e:
            logger.warning(
                "Не удалось отправить расписание пользователю %s: %s", user["user_id"], e
            )

    if sent_count:
        logger.info("Ежедневное расписание отправлено (%d пользователей)", sent_count)


async def cleanup_expired_alerts(bot: Bot) -> None:
    """Удалить алерты об изменениях, которым больше 24 часов."""
    alerts = await get_expired_alerts()
    if not alerts:
        return

    for alert in alerts:
        try:
            await bot.delete_message(alert["user_id"], alert["message_id"])
        except Exception:
            pass  # сообщение уже удалено или недоступно
    await delete_pending_alerts([alert["id"] for alert in alerts])
    logger.info("Автоудалены устаревшие алерты (%d шт.)", len(alerts))


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

    # Автоудаление алертов об изменениях старше 24 часов.
    scheduler.add_job(
        cleanup_expired_alerts,
        trigger="interval",
        minutes=10,
        next_run_time=app_now(),
        args=[bot],
        id="cleanup_alerts",
        replace_existing=True,
    )

    logger.info(
        "Планировщик настроен: ежедневные расписания (1 мин) + автоудаление алертов (10 мин)"
    )
    return scheduler
