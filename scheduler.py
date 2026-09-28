"""
Фоновые уведомления: ежедневное расписание.
"""

import asyncio
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
    update_user_profile,
)
from extra_schedule import get_extras_for_date, parse_extra_choices
from handlers.schedule import (
    _has_added_override,
    day_views,
    get_lessons_for_date,
    send_schedule,
)
from message_style import title

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
            if await _send_daily_schedule(bot, user, today):
                sent_count += 1
        except Exception as e:
            logger.warning(
                "Не удалось отправить расписание пользователю %s: %s", user["user_id"], e
            )

    if sent_count:
        logger.info("Ежедневное расписание отправлено (%d пользователей)", sent_count)


async def _send_daily_schedule(bot: Bot, user: dict, today: datetime.date) -> bool:
    """Отправить расписание одному пользователю; False — день пустой, не шлём."""
    # Режим: расписание на сегодня (утро) или на завтра (вечер).
    target = str(user.get("daily_notify_target") or "today")
    if target == "tomorrow":
        target_date = today + datetime.timedelta(days=1)
        lead = "Расписание на завтра"
        header = f"🌙 {title(lead)}"
    else:
        target_date = today
        lead = "Расписание на сегодня"
        header = f"☀️ {title(lead)}"

    group_name = user["group_name"]
    extra_keys = parse_extra_choices(user.get("extra_choices"))

    # Пустой день (нет ни пар, ни выбранных кружков, ни добавленных старостой
    # пар) не отправляем — без лишнего шума.
    lessons = get_lessons_for_date(group_name, target_date)
    extras = get_extras_for_date(group_name, target_date, extra_keys)
    if not lessons and not extras:
        overrides = await get_overrides(group_name, target_date.isoformat())
        if not _has_added_override(overrides):
            return False

    # Подпись сверху — чтобы было понятно, что это автоотправка, а не ответ на кнопку.
    views = day_views(user, group_name, target_date, lead=lead, classic_header=header)

    # Удаляем неактуальное ежедневное расписание за прошлый раз, если оно ещё висит.
    prev_msg_id = user.get("daily_notify_last_msg_id")
    if prev_msg_id:
        try:
            await bot.delete_message(user["user_id"], prev_msg_id)
        except Exception:
            pass  # сообщение уже удалено или недоступно
    sent = await send_schedule(
        bot,
        user["user_id"],
        user,
        rich=views.rich,
        classic=views.classic,
        rich_markup=views.markup,
        disable_notification=not bool(user.get("daily_notify_sound", 1)),
    )
    await mark_user_daily_notify_sent(user["user_id"], today.isoformat(), sent[-1].message_id)
    return True


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


async def warm_profiles(bot: Bot) -> None:
    """Разово подтянуть имя/@username всех пользователей в БД — для поиска в админке.

    Обрабатываем только тех, у кого профиль ещё пустой, с паузами между
    запросами, чтобы не упереться в лимиты Telegram. Безопасно запускать
    повторно: уже заполненные профили пропускаются.
    """
    users = await get_all_users()
    updated = 0
    for user in users:
        if user.get("username") or user.get("first_name") or user.get("last_name"):
            continue
        try:
            chat = await bot.get_chat(user["user_id"])
        except Exception:
            continue  # пользователь заблокировал бота или недоступен
        await update_user_profile(user["user_id"], chat.username, chat.first_name, chat.last_name)
        updated += 1
        await asyncio.sleep(0.2)
    if updated:
        logger.info("Прогрев профилей: обновлено %d", updated)


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
