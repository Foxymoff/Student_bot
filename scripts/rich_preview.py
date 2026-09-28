"""
Превью rich-расписания на тестовом боте.

Рендерит те же случаи, что golden-тесты (tests/rich_fixtures.py), и живые «сегодня» и
«эта неделя» для группы по реальным данным, отправляет их через sendRichMessage,
печатает эхо сервера (message.rich_message) и проверяет, применились ли атрибуты.
Случай live_nav отправляет «сегодня» с кнопками навигации и сразу перерисовывает его
на завтра через editMessageText(rich_message) — как при нажатии кнопки.

    TEST_BOT_TOKEN=... TEST_CHAT_ID=... python scripts/rich_preview.py [случай ...]

Без аргументов отправляет все случаи. С боевым ботом не работает: токен совпадает
с PROD_BOT_TOKEN (если задан) или getMe отвечает боевым username
(PROD_BOT_USERNAME, по умолчанию innoportalbot). Код выхода 1 — есть непройденные проверки.
"""

import asyncio
import datetime
import html as html_lib
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiogram import Bot  # noqa: E402
from aiogram.types import (  # noqa: E402
    InlineKeyboardMarkup,
    InputRichMessage,
    Message,
    RichBlockButtons,
    RichBlockDetails,
    RichBlockParagraph,
    RichBlockTable,
    RichTextButton,
    RichTextDateTime,
    RichTextMarked,
)

from config import app_now, app_today  # noqa: E402
from handlers import schedule  # noqa: E402
from keyboards import schedule_nav_kb  # noqa: E402
from render_rich import (  # noqa: E402
    has_lessons,
    needs_upcoming,
    render_day_html,
    render_week_html,
)
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


def _live_nav(offset: int) -> str:
    """Живое сообщение: день today+offset с кнопками навигации (как у бота)."""
    today = app_today()
    target = today + datetime.timedelta(days=offset)
    day = schedule.build_rich_day(schedule.get_lessons_for_date(LIVE_GROUP, target), target)
    nav = schedule.day_nav(target, LIVE_GROUP, today)
    toggle = schedule.details_toggle(target, LIVE_GROUP, detailed=False)
    return render_day_html(day, now=app_now(), group=LIVE_GROUP, nav=nav, toggle=toggle)


TOGGLE_VARIANTS = {
    "keyboard": "Вариант 1 · «Подробнее» inline-кнопкой под сообщением",
    "link": "Вариант 2 · «Подробнее» ссылкой под таблицей",
    "pill": "Вариант 3 · «Подробнее» маленькой синей кнопкой под таблицей",
}


def _toggle_variants() -> list[tuple[str, str, InlineKeyboardMarkup | None]]:
    """Сегодняшний день по реальным данным в трёх вариантах «Подробнее» — кратко и подробно."""
    today = app_today()
    day = schedule.build_rich_day(schedule.get_lessons_for_date(LIVE_GROUP, today), today)
    upcoming = None
    if needs_upcoming(day, app_now()):
        for offset in range(1, 15):
            date = today + datetime.timedelta(days=offset)
            candidate = schedule.build_rich_day(
                schedule.get_lessons_for_date(LIVE_GROUP, date), date
            )
            if has_lessons(candidate):
                upcoming = candidate
                break
    result = []
    for detailed in (False, True):
        nav = schedule.day_nav(today, LIVE_GROUP, today, detailed=detailed)
        toggle = schedule.details_toggle(today, LIVE_GROUP, detailed=detailed)
        for variant, caption in TOGGLE_VARIANTS.items():
            in_body = variant != "keyboard"
            html = render_day_html(
                day,
                now=app_now(),
                group=LIVE_GROUP,
                upcoming=upcoming,
                nav=nav,
                detailed=detailed,
                toggle=toggle if in_body else None,
                toggle_style=variant if in_body else None,
            )
            markup = None if in_body else schedule_nav_kb([[toggle]])
            view = "подробный вид" if detailed else "краткий вид"
            result.append((f"{caption} · {view}", html, markup))
    return result


# Подпись над снимком: какой момент изображён. Относительное время в <tg-time>
# телефон считает от настоящего «сейчас», поэтому у снимков за 25.09 оно «назад».
CAPTIONS: dict[str, str] = {
    "day_today_before_first": "Кратко · пт 25.09, 01:22 — до первой пары",
    "day_today_second_pair": "Кратко · пт 25.09, 11:30 — идёт 2 пара",
    "day_today_break": "Кратко · пт 25.09, 10:55 — перемена перед 2 парой",
    "day_today_after_last": "Кратко · пт 25.09, 16:00 — пары закончились",
    "day_tomorrow": "Кратко · «Завтра» из чт 24.09, 20:00",
    "day_no_pairs": "Кратко · вс 27.09 без пар",
    "day_one_pair": "Кратко · сб 26.09 — одна пара",
    "day_with_extra": "Кратко · с кружком",
    "day_with_changes": "Кратко · отмена, смена аудитории, примечание, онлайн",
    "full_today_before_first": "Подробно · пт 25.09, 01:22 — до первой пары",
    "full_today_second_pair": "Подробно · пт 25.09, 11:30 — идёт 2 пара",
    "full_today_break": "Подробно · пт 25.09, 10:55 — перемена перед 2 парой",
    "full_today_after_last": "Подробно · пт 25.09, 16:00 — пары закончились",
    "full_tomorrow": "Подробно · «Завтра» из чт 24.09, 20:00",
    "full_one_pair": "Подробно · сб 26.09 — одна пара",
    "full_with_extra": "Подробно · с кружком",
    "full_with_changes": "Подробно · отмена, смена аудитории, примечание, онлайн",
    "full_added_and_renamed": "Подробно · староста переименовал пару и добавил 4-ю",
    "full_all_cancelled": "Подробно · все пары отменены",
    "day_with_nav": "Кнопки · открыт сегодняшний день (пт 25.09): «Сегодня» выделена",
    "day_tomorrow_with_nav": "Кнопки · открыт другой день (сб 26.09)",
    "week_this_with_nav": "Кнопки · текущая неделя: «Эта неделя» выделена",
    "week_past_with_nav": "Кнопки · прошлая неделя",
    "week_this_friday": "Неделя · пт 25.09, 01:22",
}
CAPTION_NOTE = "«через…/…назад» считается от настоящего времени"

ALL_CASES = {
    **CASES,
    "live_today": _live_day,
    "live_week": _live_week,
    "live_nav": lambda: _live_nav(0),
    # Три варианта «Подробнее» (6 сообщений) — отправляются отдельно, с клавиатурой.
    "toggle_variants": lambda: "",
}


# ── Проверки по эху сервера ───────────────────────────────

_BUTTON_RE = re.compile(r'<tg-button type="callback_data"(?: style="(\w+)")? data="([^"]*)">')


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
    if isinstance(text, RichTextButton):
        return _plain(text.button.text)
    return _plain(getattr(text, "text", None))


def check_echo(html: str, message: Message) -> list[tuple[str, bool]]:
    """Сверить эхо с отправленной разметкой: (что проверяли, прошло ли)."""
    rich = message.rich_message
    if rich is None:
        return [("в ответе есть rich_message", False)]
    blocks = list(_walk(rich.blocks))
    # Таблицы расписания; строка «Подробнее … группа» (кнопка в ячейке) — без полос, не в счёт.
    tables = [
        b
        for b in blocks
        if isinstance(b, RichBlockTable)
        and not any(
            isinstance(f, RichTextButton) for row in b.cells for c in row for f in _texts(c.text)
        )
    ]
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
        for table in (b for b in blocks if isinstance(b, RichBlockTable))
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
    sent_buttons = [
        (style or None, html_lib.unescape(data)) for style, data in _BUTTON_RE.findall(html)
    ]
    # Кнопки ряда (<tg-button-row>) и кнопки внутри абзаца (RichTextButton).
    all_buttons = [
        button
        for block in blocks
        if isinstance(block, RichBlockButtons)
        for button in block.buttons
    ] + [f.button for f in fragments if isinstance(f, RichTextButton)]
    echo_buttons = [(b.style, b.callback_data) for b in all_buttons if b.callback_data]
    echo_disabled = sum(1 for b in all_buttons if b.disabled is not None)
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
        # Порядок разный: кнопки в абзаце идут в разметке раньше рядов навигации.
        ("кнопки: style и callback_data", sorted(sent_buttons) == sorted(echo_buttons)),
        ("неактивные кнопки", html.count('<tg-button type="disabled">') == echo_disabled),
    ]


def _report(name: str, html: str, message: Message | bool) -> int:
    """Напечатать эхо и проверки; вернуть число непройденных."""
    print(f"\n===== {name} ({len(html)} символов) =====")
    if not isinstance(message, Message):
        print("  [FAIL] в ответе нет сообщения")
        return 1
    if message.rich_message is not None:
        print(message.rich_message.model_dump_json(indent=2, exclude_none=True))
    failed = 0
    for label, ok in check_echo(html, message):
        failed += not ok
        print(f"  [{'ok' if ok else 'FAIL'}] {label}")
    return failed


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
            if name == "toggle_variants":
                for caption, html, markup in _toggle_variants():
                    caption_html = html_lib.escape(caption, quote=False)
                    html = f"<p><i>{caption_html}</i></p>{html}"
                    message = await bot.send_rich_message(
                        chat_id=int(chat_id),
                        rich_message=InputRichMessage(html=html, skip_entity_detection=True),
                        reply_markup=markup,
                        disable_notification=True,
                    )
                    failed += _report(caption, html, message)
                    await asyncio.sleep(1)
                continue
            html = ALL_CASES[name]()
            if name in CAPTIONS:
                caption = html_lib.escape(f"{CAPTIONS[name]} · {CAPTION_NOTE}", quote=False)
                html = f"<p><i>{caption}</i></p>{html}"
            message = await bot.send_rich_message(
                chat_id=int(chat_id),
                rich_message=InputRichMessage(html=html, skip_entity_detection=True),
                disable_notification=True,
            )
            failed += _report(name, html, message)
            if name == "live_nav":
                # Как нажатие «завтра ›»: то же сообщение перерисовывается на месте.
                await asyncio.sleep(1)
                edited_html = _live_nav(1)
                edited = await bot.edit_message_text(
                    chat_id=int(chat_id),
                    message_id=message.message_id,
                    rich_message=InputRichMessage(html=edited_html, skip_entity_detection=True),
                )
                failed += _report("live_nav → правка на завтра", edited_html, edited)
            await asyncio.sleep(1)
    finally:
        await bot.session.close()
    print(f"\nНепройденных проверок: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
