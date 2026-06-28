"""
Модуль работы с базой данных SQLite через aiosqlite.
"""

import datetime
import json
import logging

import aiosqlite

from config import DB_PATH, GROUPS

logger = logging.getLogger(__name__)

VALID_ROLES = {"student", "starosta", "admin"}
VALID_OVERRIDE_TYPES = {"cancel", "room_change", "online", "note", "reorder"}
VALID_SUBGROUPS = {1, 2}


def _ensure_group(group_name: str) -> None:
    """Проверить, что группа известна проекту."""
    if group_name not in GROUPS:
        raise ValueError(f"Неизвестная группа: {group_name}")


def _ensure_subgroups(*subgroups: int | None) -> None:
    """Проверить допустимые номера подгрупп."""
    for subgroup in subgroups:
        if subgroup is None:
            continue
        if int(subgroup) not in VALID_SUBGROUPS:
            raise ValueError(f"Некорректная подгруппа: {subgroup}")


def _ensure_iso_date(value: str) -> None:
    """Проверить дату в формате YYYY-MM-DD."""
    datetime.date.fromisoformat(value)


def _ensure_role(role: str) -> None:
    """Проверить допустимую роль пользователя."""
    if role not in VALID_ROLES:
        raise ValueError(f"Некорректная роль: {role}")


def _ensure_override_type(override_type: str) -> None:
    """Проверить допустимый тип изменения расписания."""
    if override_type not in VALID_OVERRIDE_TYPES:
        raise ValueError(f"Некорректный тип изменения расписания: {override_type}")


async def init_db() -> None:
    """Создание таблиц при первом запуске."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                group_name TEXT NOT NULL,
                subgroup_cs INTEGER DEFAULT 1,
                subgroup_en INTEGER DEFAULT 1,
                role TEXT DEFAULT 'student',
                compact_mode INTEGER DEFAULT 0,
                extra_choices TEXT DEFAULT '[]',
                extra_in_schedule INTEGER DEFAULT 0,
                daily_notify_enabled INTEGER DEFAULT 0,
                daily_notify_time TEXT DEFAULT '08:00',
                daily_notify_sound INTEGER DEFAULT 1,
                daily_notify_last_date TEXT,
                change_alert_enabled INTEGER DEFAULT 0,
                change_alert_sound INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        # Миграция: добавляем колонки, если таблица уже существовала без них
        for col, definition in [
            ("subgroup_cs", "INTEGER DEFAULT 1"),
            ("subgroup_en", "INTEGER DEFAULT 1"),
            ("role", "TEXT DEFAULT 'student'"),
            ("created_at", "TEXT DEFAULT (datetime('now'))"),
            ("compact_mode", "INTEGER DEFAULT 0"),
            ("extra_choices", "TEXT DEFAULT '[]'"),
            ("extra_in_schedule", "INTEGER DEFAULT 0"),
            ("daily_notify_enabled", "INTEGER DEFAULT 0"),
            ("daily_notify_time", "TEXT DEFAULT '08:00'"),
            ("daily_notify_sound", "INTEGER DEFAULT 1"),
            ("daily_notify_last_date", "TEXT"),
            ("change_alert_enabled", "INTEGER DEFAULT 0"),
            ("change_alert_sound", "INTEGER DEFAULT 1"),
        ]:
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            except aiosqlite.OperationalError:
                pass  # колонка уже существует

        await db.execute("""
            CREATE TABLE IF NOT EXISTS schedule_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT NOT NULL,
                date TEXT NOT NULL,
                lesson_num INTEGER NOT NULL,
                subgroup INTEGER,
                override_type TEXT NOT NULL,
                new_value TEXT,
                comment TEXT,
                created_by INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        for col, definition in [
            ("subgroup", "INTEGER"),
        ]:
            try:
                await db.execute(f"ALTER TABLE schedule_overrides ADD COLUMN {col} {definition}")
            except aiosqlite.OperationalError:
                pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS extra_lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT NOT NULL,
                week_type TEXT NOT NULL,
                day_name TEXT NOT NULL,
                type TEXT NOT NULL,
                time TEXT,
                subject TEXT,
                room TEXT,
                teacher TEXT,
                note TEXT
            )
        """)
        await db.commit()
    logger.info("База данных инициализирована")


# ── Пользователи ──────────────────────────────────────────


async def get_user(user_id: int) -> dict | None:
    """Получить данные пользователя по user_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def add_user(user_id: int, group_name: str) -> None:
    """Добавить или обновить пользователя."""
    _ensure_group(group_name)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO users (user_id, group_name, extra_choices)
               VALUES (?, ?, '[]')
               ON CONFLICT(user_id) DO UPDATE SET
                   group_name = excluded.group_name,
                   extra_choices = CASE
                       WHEN users.group_name != excluded.group_name THEN '[]'
                       ELSE users.extra_choices
                   END,
                   extra_in_schedule = CASE
                       WHEN users.group_name != excluded.group_name THEN 0
                       ELSE users.extra_in_schedule
                   END""",
            (user_id, group_name),
        )
        await db.commit()
    logger.info("Пользователь %s сохранён с группой %s", user_id, group_name)


async def update_user_subgroups(user_id: int, sg_inf: int, sg_eng: int) -> None:
    """Обновить подгруппы пользователя."""
    _ensure_subgroups(sg_inf, sg_eng)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET subgroup_cs = ?, subgroup_en = ? WHERE user_id = ?",
            (sg_inf, sg_eng, user_id),
        )
        await db.commit()


async def update_user_compact(user_id: int, compact: bool) -> None:
    """Переключить компактный режим отображения."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET compact_mode = ? WHERE user_id = ?",
            (1 if compact else 0, user_id),
        )
        await db.commit()


async def update_user_extra_choices(user_id: int, choices: list[str]) -> None:
    """Сохранить выбранные пользователем доп. занятия."""
    value = json.dumps(choices, ensure_ascii=False)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET extra_choices = ? WHERE user_id = ?",
            (value, user_id),
        )
        await db.commit()


async def update_user_extra_in_schedule(user_id: int, enabled: bool) -> None:
    """Переключить отображение доп. занятий в основном расписании."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET extra_in_schedule = ? WHERE user_id = ?",
            (1 if enabled else 0, user_id),
        )
        await db.commit()


async def update_user_daily_notify(
    user_id: int,
    enabled: bool,
    notify_time: str | None = None,
    sound: bool | None = None,
) -> None:
    """Обновить настройки ежедневного уведомления с расписанием."""
    fields = ["daily_notify_enabled = ?"]
    values: list[object] = [1 if enabled else 0]
    if notify_time is not None:
        fields.append("daily_notify_time = ?")
        values.append(notify_time)
    if sound is not None:
        fields.append("daily_notify_sound = ?")
        values.append(1 if sound else 0)
    if not enabled:
        fields.append("daily_notify_last_date = NULL")
    values.append(user_id)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE users SET {', '.join(fields)} WHERE user_id = ?",
            tuple(values),
        )
        await db.commit()


async def mark_user_daily_notify_sent(user_id: int, sent_date: str) -> None:
    """Запомнить дату последней ежедневной отправки пользователю."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET daily_notify_last_date = ? WHERE user_id = ?",
            (sent_date, user_id),
        )
        await db.commit()


async def update_user_change_alert(
    user_id: int,
    enabled: bool,
    sound: bool | None = None,
) -> None:
    """Обновить настройки алертов об отмене пары и смене аудитории."""
    fields = ["change_alert_enabled = ?"]
    values: list[object] = [1 if enabled else 0]
    if sound is not None:
        fields.append("change_alert_sound = ?")
        values.append(1 if sound else 0)
    values.append(user_id)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE users SET {', '.join(fields)} WHERE user_id = ?",
            tuple(values),
        )
        await db.commit()


async def get_all_users() -> list[dict]:
    """Получить список всех пользователей."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_users_by_group(group_name: str) -> list[dict]:
    """Получить пользователей конкретной группы."""
    _ensure_group(group_name)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE group_name = ?",
            (group_name,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ── Роли ──────────────────────────────────────────────────


async def set_user_role(user_id: int, role: str) -> None:
    """Установить роль пользователя."""
    _ensure_role(role)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET role = ? WHERE user_id = ?",
            (role, user_id),
        )
        await db.commit()


async def get_users_by_role(role: str) -> list[dict]:
    """Получить пользователей с определённой ролью."""
    _ensure_role(role)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE role = ?", (role,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ── Schedule overrides ────────────────────────────────────


async def add_override(
    group_name: str,
    date: str,
    lesson_num: int,
    override_type: str,
    new_value: str | None = None,
    comment: str | None = None,
    created_by: int | None = None,
    subgroup: int | None = None,
) -> None:
    """Добавить изменение в расписание."""
    _ensure_group(group_name)
    _ensure_iso_date(date)
    _ensure_override_type(override_type)
    _ensure_subgroups(subgroup)
    if lesson_num < 1:
        raise ValueError("Номер пары должен быть положительным")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO schedule_overrides
               (group_name, date, lesson_num, subgroup, override_type, new_value, comment, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (group_name, date, lesson_num, subgroup, override_type, new_value, comment, created_by),
        )
        await db.commit()


async def get_overrides(group_name: str, date: str) -> list[dict]:
    """Получить все overrides для группы на дату."""
    _ensure_group(group_name)
    _ensure_iso_date(date)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM schedule_overrides
               WHERE group_name = ? AND date = ?
               ORDER BY id""",
            (group_name, date),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_group_overrides(group_name: str, from_date: str | None = None) -> list[dict]:
    """Получить изменения расписания группы, начиная с даты."""
    _ensure_group(group_name)
    if from_date:
        _ensure_iso_date(from_date)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if from_date:
            cursor = await db.execute(
                """SELECT * FROM schedule_overrides
                   WHERE group_name = ? AND date >= ?
                   ORDER BY date, lesson_num, COALESCE(subgroup, 0), id""",
                (group_name, from_date),
            )
        else:
            cursor = await db.execute(
                """SELECT * FROM schedule_overrides
                   WHERE group_name = ?
                   ORDER BY date, lesson_num, COALESCE(subgroup, 0), id""",
                (group_name,),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_override_by_id(override_id: int, group_name: str) -> dict | None:
    """Получить одно изменение расписания по id и группе."""
    _ensure_group(group_name)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM schedule_overrides WHERE id = ? AND group_name = ?",
            (override_id, group_name),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_lesson_overrides(
    group_name: str,
    date: str,
    lesson_num: int,
    subgroup: int | None = None,
) -> list[dict]:
    """Получить изменения конкретной пары."""
    _ensure_group(group_name)
    _ensure_iso_date(date)
    _ensure_subgroups(subgroup)
    if lesson_num < 1:
        raise ValueError("Номер пары должен быть положительным")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if subgroup is None:
            cursor = await db.execute(
                """SELECT * FROM schedule_overrides
                   WHERE group_name = ? AND date = ? AND lesson_num = ?
                     AND subgroup IS NULL
                   ORDER BY id""",
                (group_name, date, lesson_num),
            )
        else:
            cursor = await db.execute(
                """SELECT * FROM schedule_overrides
                   WHERE group_name = ? AND date = ? AND lesson_num = ?
                     AND subgroup = ?
                   ORDER BY id""",
                (group_name, date, lesson_num, subgroup),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def delete_override(override_id: int, group_name: str) -> bool:
    """Удалить изменение расписания по id и группе."""
    _ensure_group(group_name)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM schedule_overrides WHERE id = ? AND group_name = ?",
            (override_id, group_name),
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_lesson_overrides(
    group_name: str,
    date: str,
    lesson_num: int,
    subgroup: int | None = None,
) -> int:
    """Удалить все изменения конкретной пары."""
    _ensure_group(group_name)
    _ensure_iso_date(date)
    _ensure_subgroups(subgroup)
    if lesson_num < 1:
        raise ValueError("Номер пары должен быть положительным")
    async with aiosqlite.connect(DB_PATH) as db:
        if subgroup is None:
            cursor = await db.execute(
                """DELETE FROM schedule_overrides
                   WHERE group_name = ? AND date = ? AND lesson_num = ?
                     AND subgroup IS NULL""",
                (group_name, date, lesson_num),
            )
        else:
            cursor = await db.execute(
                """DELETE FROM schedule_overrides
                   WHERE group_name = ? AND date = ? AND lesson_num = ?
                     AND subgroup = ?""",
                (group_name, date, lesson_num, subgroup),
            )
        await db.commit()
        return cursor.rowcount


# ── Extra lessons (допы, КБ) ─────────────────────────────


async def get_extra_lessons(group_name: str, week_type: str, day_name: str) -> list[dict]:
    """Получить доп.занятия / КБ для группы на день."""
    _ensure_group(group_name)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM extra_lessons WHERE group_name = ? AND week_type = ? AND day_name = ?",
            (group_name, week_type, day_name),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
