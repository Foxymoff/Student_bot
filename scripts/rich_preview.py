"""
Превью rich-расписания на тестовом боте.

Рендерит те же случаи, что golden-тесты (tests/rich_fixtures.py), и живые «сегодня» и
«эта неделя» для группы по реальным данным, отправляет их через sendRichMessage,
печатает эхо сервера (message.rich_message) и проверяет, применились ли атрибуты.

    TEST_BOT_TOKEN=... TEST_CHAT_ID=... python scripts/rich_preview.py [случай ...]

Без аргументов отправляет все случаи. С боевым ботом не работает: токен совпадает
с PROD_BOT_TOKEN (если задан) или getMe отвечает боевым username
(PROD_BOT_USERNAME, по умолчанию innoportalbot). Код выхода 1 — есть непройденные проверки.
"""

import asyncio
import datetime
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiogram import Bot  # noqa: E402
from aiogram.types import (  # noqa: E402
    InputRichMessage,
    Message,
    RichBlockDetails,
    RichBlockParagraph,
    RichBlockTable,
    RichTextDateTime,
    RichTextMarked,
)

from config import app_now, app_today  # noqa: E402
from handlers import schedule  # noqa: E402
from render_rich import has_lessons, render_day_html, render_week_html  # noqa: E402
from tests.rich_fixtures import CASES  # noqa: E402

LIVE_GROUP = os.getenv("PREVIEW_GROUP", "ИСП-25-2")
PROD_BOT_USERNAME = os.getenv("PROD_BOT_USERNAME", "innoportalbot")


def _live_day() -> str:
    """«Сегодня» по реальным данным группы (без изменений старосты из БД)."""
    today = app_today()
    now = app_now()
    day = schedule.build_rich_day(schedule.get_lessons_for_date(LIVE_GROUP, today), today)
    upcoming = None
    for offset in range(1, 15):
        date = today + datetime.timedelta(days=offset)
        candidate = schedule.build_rich_day(schedule.get_lessons_for_date(LIVE_GROUP, date), date)
        if has_lessons(candidate):
            upcoming = candidate
            break
    return render_day_html(day, now=now, group=LIVE_GROUP, upcoming=upcoming)


def _live_week() -> str:
    """«Эта неделя» по реальным данным группы (без изменений старосты из БД)."""
    today = app_today()
    monday = today - datetime.timedelta(days=today.weekday())
    days = [
        schedule.build_rich_day(schedule.get_lessons_for_date(LIVE_GROUP, date), date)
        for date in (monday + datetime.timedelta(days=i) for i in range(7))
    ]
    return render_week_html(days, now=app_now(), group=LIVE_GROUP, which="this")


ALL_CASES = {**CASES, "live_today": _live_day, "live_week": _live_week}


# ── Проверки по эху сервера ───────────────────────────────


def _walk(blocks: list) -> Iterator:
    for block in blocks:
        yield block
        if isinstance(block, RichBlockDetails):
            yield from _walk(block.blocks)


def _texts(text) -> Iterator:
    """Все фрагменты RichText в глубину."""
    if text is None or isinstance(text, str):
        return
    if isinstance(text, list):
        for part in text:
            yield from _texts(part)
        return
    yield text
    yield from _texts(getattr(text, "text", None))


def _plain(text) -> str:
    if text is None:
        return ""
    if isinstance(text, str):
        return text
    if isinstance(text, list):
        return "".join(_plain(part) for part in text)
    return _plain(getattr(text, "text", None))


def check_echo(html: str, message: Message) -> list[tuple[str, bool]]:
    """Сверить эхо с отправленной разметкой: (что проверяли, прошло ли)."""
    rich = message.rich_message
    if rich is None:
        return [("в ответе есть rich_message", False)]
    blocks = list(_walk(rich.blocks))
    tables = [b for b in blocks if isinstance(b, RichBlockTable)]
    details = [b for b in blocks if isinstance(b, RichBlockDetails)]
    paragraphs = [b for b in blocks if isinstance(b, RichBlockParagraph)]
    fragments = [
        fragment
        for block in blocks
        for text in [getattr(block, "text", None), getattr(block, "summary", None)]
        for fragment in _texts(text)
    ]
    fragments += [
        fragment
        for table in tables
        for row in table.cells
        for cell in row
        for fragment in _texts(cell.text)
    ]

    expected_open = [bool(m.group(1)) for m in re.finditer(r"<details( open)?>", html)]
    detail_tables = [
        table for table in tables if any("–" in _plain(row[0].text) for row in table.cells)
    ]
    time_tags = re.findall(r'<tg-time unix="\d+" format="(\w+)">', html)
    echo_times = [f for f in fragments if isinstance(f, RichTextDateTime)]
    return [
        ("таблицы: is_compact", all(t.is_compact for t in tables)),
        ("таблицы: is_striped", all(t.is_striped for t in tables)),
        (
            "колонка аудитории: align=right",
            all(row[-1].align == "right" for t in tables for row in t.cells),
        ),
        (
            "подробности: valign=top у времени",
            all(row[0].valign == "top" for t in detail_tables for row in t.cells),
        ),
        ("details: is_open как в разметке", [bool(d.is_open) for d in details] == expected_open),
        ("пустых абзацев нет", all(_plain(p.text).strip() for p in paragraphs)),
        (
            "tg-time: format=r",
            len(echo_times) == len(time_tags)
            and all(f.date_time_format == "r" for f in echo_times),
        ),
        (
            "mark применился",
            ("<mark>" in html) == any(isinstance(f, RichTextMarked) for f in fragments),
        ),
    ]


async def _refuse_prod(bot: Bot, token: str) -> str | None:
    """Причина отказа, если это боевой бот."""
    prod_token = os.getenv("PROD_BOT_TOKEN")
    if prod_token and token == prod_token:
        return "TEST_BOT_TOKEN совпадает с PROD_BOT_TOKEN"
    me = await bot.get_me()
    if (me.username or "").lower() == PROD_BOT_USERNAME.lower():
        return f"TEST_BOT_TOKEN принадлежит боевому боту @{me.username}"
    return None


async def main(names: list[str]) -> int:
    token = os.getenv("TEST_BOT_TOKEN", "")
    chat_id = os.getenv("TEST_CHAT_ID", "")
    if not token or not chat_id:
        print("Нужны TEST_BOT_TOKEN и TEST_CHAT_ID", file=sys.stderr)
        return 2
    unknown = [name for name in names if name not in ALL_CASES]
    if unknown:
        print(f"Нет таких случаев: {', '.join(unknown)}. Есть: {', '.join(ALL_CASES)}")
        return 2

    bot = Bot(token)
    failed = 0
    try:
        reason = await _refuse_prod(bot, token)
        if reason:
            print(f"Отказ: {reason}", file=sys.stderr)
            return 2
        for name in names or list(ALL_CASES):
            html = ALL_CASES[name]()
            message = await bot.send_rich_message(
                chat_id=int(chat_id),
                rich_message=InputRichMessage(html=html, skip_entity_detection=True),
                disable_notification=True,
            )
            print(f"\n===== {name} ({len(html)} символов) =====")
            if message.rich_message is not None:
                print(message.rich_message.model_dump_json(indent=2, exclude_none=True))
            for label, ok in check_echo(html, message):
                failed += not ok
                print(f"  [{'ok' if ok else 'FAIL'}] {label}")
            await asyncio.sleep(1)
    finally:
        await bot.session.close()
    print(f"\nНепройденных проверок: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
