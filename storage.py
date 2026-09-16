"""
Персистентное FSM-хранилище aiogram поверх SQLite.

MemoryStorage теряет состояние при рестарте контейнера: пропадают ui_msg_ids
(какие сообщения — активный экран), навигация и незавершённые флоу, из-за чего
после пересборки бот «перестаёт адекватно работать». Это хранилище пишет
состояние в файл на volume, поэтому оно переживает рестарт.
"""

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import aiosqlite
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey


class SQLiteStorage(BaseStorage):
    """FSM-хранилище на SQLite: переживает перезапуск процесса."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        # Таблицу и WAL настраиваем синхронно один раз при старте.
        with sqlite3.connect(self._path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS fsm ("
                "key TEXT PRIMARY KEY, state TEXT, data TEXT NOT NULL DEFAULT '{}')"
            )
            db.commit()

    @staticmethod
    def _key(key: StorageKey) -> str:
        return ":".join(
            str(part)
            for part in (
                key.bot_id,
                key.chat_id,
                key.user_id,
                key.thread_id,
                key.business_connection_id,
                key.destiny,
            )
        )

    async def set_state(self, key: StorageKey, state: str | State | None = None) -> None:
        value = state.state if isinstance(state, State) else state
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "INSERT INTO fsm (key, state) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET state = excluded.state",
                (self._key(key), value),
            )
            await db.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute("SELECT state FROM fsm WHERE key = ?", (self._key(key),))
            row = await cursor.fetchone()
        return row[0] if row else None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        payload = json.dumps(dict(data), ensure_ascii=False)
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "INSERT INTO fsm (key, data) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET data = excluded.data",
                (self._key(key), payload),
            )
            await db.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute("SELECT data FROM fsm WHERE key = ?", (self._key(key),))
            row = await cursor.fetchone()
        if not row or not row[0]:
            return {}
        try:
            return json.loads(row[0])
        except (TypeError, ValueError):
            return {}

    async def close(self) -> None:
        return None
