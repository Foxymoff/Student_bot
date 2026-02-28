"""
Модуль работы с базой данных SQLite через aiosqlite.
"""

import logging
import aiosqlite
from config import DB_PATH

logger = logging.getLogger(__name__)


async def init_db() -> None:
    """Создание таблиц при первом запуске."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                group_name TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS homework (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                subject TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS deadlines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                deadline_date TEXT NOT NULL,
                notified_24h INTEGER DEFAULT 0,
                notified_1h INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        await db.commit()
    logger.info("База данных инициализирована")


# ── Пользователи ──────────────────────────────────────────


async def get_user(user_id: int) -> dict | None:
    """Получить данные пользователя по user_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def add_user(user_id: int, group_name: str) -> None:
    """Добавить или обновить пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO users (user_id, group_name)
               VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET group_name = excluded.group_name""",
            (user_id, group_name),
        )
        await db.commit()
    logger.info("Пользователь %s сохранён с группой %s", user_id, group_name)


async def get_all_users() -> list[dict]:
    """Получить список всех пользователей."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ── Домашнее задание ───────────────────────────────────────


async def add_homework(user_id: int, subject: str, text: str) -> None:
    """Добавить запись домашнего задания."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO homework (user_id, subject, text) VALUES (?, ?, ?)",
            (user_id, subject, text),
        )
        await db.commit()


async def get_homework(user_id: int, subject: str) -> list[dict]:
    """Получить ДЗ пользователя по предмету."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM homework WHERE user_id = ? AND subject = ? ORDER BY created_at DESC",
            (user_id, subject),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_homework_subjects(user_id: int) -> list[str]:
    """Получить список предметов, по которым есть ДЗ."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT DISTINCT subject FROM homework WHERE user_id = ? ORDER BY subject",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]


# ── Дедлайны ──────────────────────────────────────────────


async def add_deadline(user_id: int, title: str, deadline_date: str) -> None:
    """Добавить дедлайн (deadline_date в формате YYYY-MM-DD)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO deadlines (user_id, title, deadline_date) VALUES (?, ?, ?)",
            (user_id, title, deadline_date),
        )
        await db.commit()


async def get_deadlines(user_id: int) -> list[dict]:
    """Получить дедлайны пользователя, отсортированные по дате."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM deadlines WHERE user_id = ? ORDER BY deadline_date ASC",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_all_deadlines() -> list[dict]:
    """Получить все дедлайны (для планировщика уведомлений)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM deadlines ORDER BY deadline_date ASC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def mark_deadline_notified(deadline_id: int, field: str) -> None:
    """Пометить дедлайн как уведомлённый (field = 'notified_24h' или 'notified_1h')."""
    if field not in ("notified_24h", "notified_1h"):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE deadlines SET {field} = 1 WHERE id = ?", (deadline_id,)
        )
        await db.commit()
