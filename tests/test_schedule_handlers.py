"""Хендлеры расписания: служебные сообщения и отправка."""

import datetime
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

import config
import render_rich
import scheduler
from handlers import schedule, start
from tests.rich_fixtures import GROUP, at, lessons_for

USER = {"user_id": 9, "group_name": GROUP, "subgroup_cs": 1, "subgroup_en": 1, "classic_view": 0}


@pytest_asyncio.fixture
async def state() -> FSMContext:
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=9, user_id=9))


async def test_period_header_edit_targets_correct_message(state):
    """Регресс: шапка «Выбери период» не обновлялась из-за позиционных аргументов.

    В aiogram 3.x сигнатура — (text, business_connection_id, chat_id, message_id).
    """
    calls = []

    async def edit_message_text(
        text, business_connection_id=None, chat_id=None, message_id=None, **kw
    ):
        calls.append((text, business_connection_id, chat_id, message_id))

    message = MagicMock()
    message.bot.edit_message_text = edit_message_text
    message.chat.id = 9
    await state.update_data(last_bot_msg=77)

    await schedule._update_period_header(message, state, "<b>Сегодня</b>")

    assert calls == [("<b>Сегодня</b>", None, 9, 77)]


def _message(user_id: int = 9) -> MagicMock:
    message = MagicMock()
    message.from_user.id = user_id
    message.chat.id = user_id
    message.delete = AsyncMock()
    message.answer = AsyncMock(return_value=MagicMock(message_id=5))
    message.bot.delete_message = AsyncMock()
    return message


@pytest.mark.parametrize(("stored", "expected"), [(0, True), (1, False)])
async def test_classic_command_toggles_flag(state, monkeypatch, stored, expected):
    calls = []

    async def get_user(user_id):
        return {"user_id": user_id, "group_name": "ИСП-25-1", "classic_view": stored}

    async def update_user_classic_view(user_id, classic):
        calls.append((user_id, classic))

    monkeypatch.setattr(start, "get_user", get_user)
    monkeypatch.setattr(start, "update_user_classic_view", update_user_classic_view)
    message = _message()

    await start.cmd_classic(message, state)

    assert calls == [(9, expected)]
    text = message.answer.await_args.args[0]
    assert ("классический" if expected else "новый") in text
    assert "/classic" in text


# ── send_schedule: выбор вида и откат ─────────────────────


def _bot() -> MagicMock:
    bot = MagicMock()
    bot.send_rich_message = AsyncMock(return_value=MagicMock(message_id=101))
    bot.send_message = AsyncMock(side_effect=[MagicMock(message_id=201), MagicMock(message_id=202)])
    bot.edit_message_reply_markup = AsyncMock()
    bot.delete_message = AsyncMock()
    return bot


def _views(html: str = "<p>x</p>"):
    rich = AsyncMock(return_value=html)
    classic = AsyncMock(return_value=[("<b>classic</b>", None)])
    return rich, classic


async def test_send_schedule_rich_with_skip_entity_detection():
    bot = _bot()
    rich, classic = _views()

    sent = await schedule.send_schedule(bot, 9, USER, rich=rich, classic=classic)

    assert [msg.message_id for msg in sent] == [101]
    rich_message = bot.send_rich_message.await_args.kwargs["rich_message"]
    assert rich_message.html == "<p>x</p>"
    assert rich_message.skip_entity_detection is True
    assert rich_message.markdown is None and rich_message.blocks is None
    classic.assert_not_awaited()
    bot.send_message.assert_not_awaited()


async def test_send_schedule_falls_back_to_classic_on_bad_request(caplog):
    bot = _bot()
    bot.send_rich_message.side_effect = TelegramBadRequest(
        method=MagicMock(), message="can't parse rich message"
    )
    rich, classic = _views("<p>" + "я" * 600 + "</p>")

    with caplog.at_level(logging.ERROR, logger=schedule.logger.name):
        sent = await schedule.send_schedule(bot, 9, USER, rich=rich, classic=classic)

    assert [msg.message_id for msg in sent] == [201]
    assert bot.send_message.await_args.kwargs["text"] == "<b>classic</b>"
    assert bot.send_message.await_args.kwargs["parse_mode"] == "HTML"
    (record,) = caplog.records
    assert "can't parse rich message" in record.getMessage()
    assert "<p>" + "я" * 496 in record.getMessage()
    assert "я" * 500 not in record.getMessage()  # в лог — только первые 500 символов


async def test_send_schedule_does_not_swallow_network_errors():
    bot = _bot()
    bot.send_rich_message.side_effect = TelegramNetworkError(method=MagicMock(), message="timeout")
    rich, classic = _views()

    with pytest.raises(TelegramNetworkError):
        await schedule.send_schedule(bot, 9, USER, rich=rich, classic=classic)
    bot.send_message.assert_not_awaited()


async def test_send_schedule_classic_for_classic_user():
    bot = _bot()
    rich, classic = _views()

    sent = await schedule.send_schedule(
        bot, 9, {**USER, "classic_view": 1}, rich=rich, classic=classic
    )

    assert [msg.message_id for msg in sent] == [201]
    rich.assert_not_awaited()
    bot.send_rich_message.assert_not_awaited()


async def test_send_schedule_classic_when_rich_disabled_globally(monkeypatch):
    monkeypatch.setattr(config, "RICH_SCHEDULE", False)
    bot = _bot()
    rich, classic = _views()

    await schedule.send_schedule(bot, 9, USER, rich=rich, classic=classic)

    rich.assert_not_awaited()
    bot.send_rich_message.assert_not_awaited()
    bot.send_message.assert_awaited_once()


# ── Хендлеры с реальными данными фикстур ──────────────────


@pytest.fixture
def fixed_data(monkeypatch):
    """Данные ИСП-25-2 из фикстур, без БД; «сейчас» — пятница, 25 сентября, 01:22."""

    async def get_overrides(group_name, date_iso):
        return []

    monkeypatch.setattr(schedule, "get_lessons_for_date", lambda group, date: lessons_for(date))
    monkeypatch.setattr(schedule, "get_overrides", get_overrides)
    monkeypatch.setattr(schedule, "app_now", lambda: at(25, 1, 22))
    monkeypatch.setattr(schedule, "app_today", lambda: datetime.date(2026, 9, 25))


async def test_today_button_sends_one_rich_message(state, monkeypatch, fixed_data):
    async def get_user(user_id):
        return USER

    monkeypatch.setattr(schedule, "get_user", get_user)
    message = _message()
    message.bot = _bot()
    message.bot.edit_message_text = AsyncMock()
    await state.update_data(last_bot_msg=77)

    await schedule.on_schedule_today(message, state)

    html = message.bot.send_rich_message.await_args.kwargs["rich_message"].html
    assert html.startswith("<h3>Пятница, 25 сентября</h3><p>09:20–15:00 · начало <tg-time")
    assert message.bot.send_rich_message.await_args.kwargs["reply_markup"] is None
    # «Подробнее» под таблицей (по умолчанию ссылкой), ниже ряды больших кнопок:
    # «‹ Чт, 24 | Сегодня | Сб, 26 ›», под «Сегодня» — «Эта неделя».
    assert html.endswith(
        '</table><p><tg-button type="callback_data" style="link" data="rs:f:2026-09-25:ИСП-25-2">'
        "Подробнее</tg-button></p>"
        f"<footer>{GROUP}</footer>"
        '<tg-button-row align="center">'
        '<tg-button type="callback_data" style="primary" data="rs:d:2026-09-24:ИСП-25-2">'
        "‹ Чт, 24</tg-button>"
        '<tg-button type="callback_data" style="success" data="rs:d:2026-09-25:ИСП-25-2">'
        "Сегодня</tg-button>"
        '<tg-button type="callback_data" style="primary" data="rs:d:2026-09-26:ИСП-25-2">'
        "Сб, 26 ›</tg-button>"
        "</tg-button-row>"
        '<tg-button-row align="center">'
        '<tg-button type="callback_data" style="primary" data="rs:w:2026-09-21:ИСП-25-2">'
        "Эта неделя</tg-button>"
        "</tg-button-row>"
    )
    data = await state.get_data()
    assert data["ui_msg_ids"] == [77, 101]
    assert data["last_schedule_msg"] == 101


async def test_week_button_sends_one_rich_message(state, monkeypatch, fixed_data):
    async def get_user(user_id):
        return USER

    monkeypatch.setattr(schedule, "get_user", get_user)
    message = _message()
    message.bot = _bot()
    message.bot.edit_message_text = AsyncMock()

    await schedule.on_schedule_week(message, state)

    message.bot.send_rich_message.assert_awaited_once()
    html = message.bot.send_rich_message.await_args.kwargs["rich_message"].html
    assert html.startswith("<h3>Неделя 21–26 сентября</h3>")
    assert "<details open><summary><b>Пт, 25 сентября · сегодня</b></summary>" in html


# ── Старые кнопки «Подробнее / Свернуть» ──────────────────


def _callback(data: str) -> MagicMock:
    callback = MagicMock()
    callback.data = data
    callback.from_user.id = 9
    callback.answer = AsyncMock()
    callback.bot = _bot()
    callback.message.chat.id = 9
    callback.message.message_id = 50
    callback.message.edit_text = AsyncMock()
    return callback


@pytest.mark.parametrize("prefix", ["schedule_detail", "schedule_collapse"])
async def test_legacy_button_for_rich_user(state, monkeypatch, fixed_data, prefix):
    async def get_user(user_id):
        return USER

    monkeypatch.setattr(schedule, "get_user", get_user)
    callback = _callback(f"{prefix}:2026-09-25")
    await state.update_data(ui_msg_ids=[77, 50])
    handler = (
        schedule.on_schedule_detail
        if prefix == "schedule_detail"
        else schedule.on_schedule_collapse
    )

    await handler(callback, state)

    callback.answer.assert_awaited_once_with(schedule.LEGACY_BUTTON_TEXT)
    callback.bot.edit_message_reply_markup.assert_awaited_once_with(
        chat_id=9, message_id=50, reply_markup=None
    )
    callback.message.edit_text.assert_not_awaited()  # старое сообщение в rich не конвертируем
    html = callback.bot.send_rich_message.await_args.kwargs["rich_message"].html
    assert html.startswith("<h3>Пятница, 25 сентября</h3>")
    # «Подробнее» присылает подробный вид, «Свернуть» — краткий.
    assert ('valign="top"' in html) == (prefix == "schedule_detail")
    assert (await state.get_data())["ui_msg_ids"] == [77, 50, 101]


async def test_legacy_button_with_broken_date_only_removes_keyboard(state, monkeypatch):
    async def get_user(user_id):
        return USER

    monkeypatch.setattr(schedule, "get_user", get_user)
    callback = _callback("schedule_detail:not-a-date")
    callback.bot.edit_message_reply_markup.side_effect = TelegramBadRequest(
        method=MagicMock(), message="message is not modified"
    )

    await schedule.on_schedule_detail(callback, state)

    callback.answer.assert_awaited_once_with(schedule.LEGACY_BUTTON_TEXT)
    callback.bot.send_rich_message.assert_not_awaited()
    callback.bot.send_message.assert_not_awaited()


async def test_legacy_button_for_classic_user_keeps_old_behavior(state, monkeypatch, fixed_data):
    async def get_user(user_id):
        return {**USER, "classic_view": 1}

    monkeypatch.setattr(schedule, "get_user", get_user)
    callback = _callback("schedule_detail:2026-09-25")

    await schedule.on_schedule_detail(callback, state)

    callback.message.edit_text.assert_awaited_once()
    assert callback.message.edit_text.await_args.kwargs["reply_markup"] == (
        schedule.schedule_collapse_kb("2026-09-25")
    )
    callback.bot.send_rich_message.assert_not_awaited()


# ── Ежедневная рассылка ───────────────────────────────────


@pytest.fixture
def daily(monkeypatch, fixed_data):
    marked = []

    async def mark_user_daily_notify_sent(user_id, date_iso, message_id):
        marked.append((user_id, date_iso, message_id))

    monkeypatch.setattr(scheduler, "get_lessons_for_date", lambda group, date: lessons_for(date))
    monkeypatch.setattr(scheduler, "get_overrides", schedule.get_overrides)
    monkeypatch.setattr(scheduler, "mark_user_daily_notify_sent", mark_user_daily_notify_sent)
    return marked


async def test_daily_notify_rich_has_lead_and_respects_sound(daily):
    bot = _bot()
    user = {**USER, "daily_notify_target": "today", "daily_notify_sound": 0}

    assert await scheduler._send_daily_schedule(bot, user, datetime.date(2026, 9, 25))

    kwargs = bot.send_rich_message.await_args.kwargs
    assert kwargs["rich_message"].html.startswith(
        "<p><b>Расписание на сегодня</b></p><h3>Пятница, 25 сентября</h3>"
    )
    assert kwargs["disable_notification"] is True
    assert daily == [(9, "2026-09-25", 101)]


async def test_daily_notify_classic_user_gets_old_message(daily):
    bot = _bot()
    user = {**USER, "classic_view": 1, "daily_notify_target": "tomorrow", "daily_notify_sound": 1}

    assert await scheduler._send_daily_schedule(bot, user, datetime.date(2026, 9, 24))

    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["text"].startswith("🌙 <b>Расписание на завтра</b>\n\n<b>25 сентября")
    assert kwargs["reply_markup"] == schedule.schedule_detail_kb("2026-09-25")
    assert kwargs["disable_notification"] is False
    bot.send_rich_message.assert_not_awaited()


async def test_daily_notify_skips_empty_day(daily):
    bot = _bot()
    user = {**USER, "daily_notify_target": "today"}

    assert not await scheduler._send_daily_schedule(bot, user, datetime.date(2026, 9, 27))
    bot.send_rich_message.assert_not_awaited()


# ── Настройки: вид расписания ─────────────────────────────


async def test_settings_toggle_classic(monkeypatch):
    calls = []

    async def get_user(user_id):
        return {**USER, "compact_mode": 1}

    async def update_user_classic_view(user_id, classic):
        calls.append((user_id, classic))

    monkeypatch.setattr(start, "get_user", get_user)
    monkeypatch.setattr(start, "update_user_classic_view", update_user_classic_view)
    callback = MagicMock()
    callback.data = "settings:classic:1"
    callback.from_user.id = 9
    callback.answer = AsyncMock()
    callback.message.edit_text = AsyncMock()

    await start.on_toggle_classic(callback)

    assert calls == [(9, True)]
    kb = callback.message.edit_text.await_args.kwargs["reply_markup"]
    assert "settings:compact:0" in {b.callback_data for row in kb.inline_keyboard for b in row}
    assert "компактный" in callback.message.edit_text.await_args.args[0]


async def test_settings_toggle_classic_same_value_only_answers(monkeypatch):
    async def get_user(user_id):
        return USER

    monkeypatch.setattr(start, "get_user", get_user)
    callback = MagicMock()
    callback.data = "settings:classic:0"
    callback.from_user.id = 9
    callback.answer = AsyncMock()
    callback.message.edit_text = AsyncMock()

    await start.on_toggle_classic(callback)

    callback.answer.assert_awaited_once_with("Уже включён новый вид")
    callback.message.edit_text.assert_not_awaited()


# ── Живое сообщение: навигация ────────────────────────────

FRIDAY = datetime.date(2026, 9, 25)


def test_nav_data_roundtrip_and_limit():
    for group in config.GROUPS:
        data = schedule.nav_data(schedule.NAV_DAY, FRIDAY, group)
        assert len(data.encode()) <= 64
        assert schedule.parse_nav_data(data) == ("d", FRIDAY, group)


@pytest.mark.parametrize(
    "data",
    ["rs:d:2026-13-01:ИСП-25-2", "rs:x:2026-09-25:ИСП-25-2", "rs:d:2026-09-25:ЧУЖАЯ", "rs:d"],
)
def test_parse_nav_data_rejects_garbage(data):
    assert schedule.parse_nav_data(data) is None


def _flat(rows):
    return [(b.text, b.active) for row in rows for b in row]


def _buttons(rows):
    return [[(b.text, b.current) for b in row] for row in rows]


def test_day_and_week_nav():
    day = schedule.day_nav(datetime.date(2026, 9, 27), GROUP, FRIDAY)
    today = schedule.day_nav(FRIDAY, GROUP, FRIDAY)
    full = schedule.day_nav(datetime.date(2026, 9, 27), GROUP, FRIDAY, detailed=True)
    week = schedule.week_nav(datetime.date(2026, 9, 21), GROUP, FRIDAY)
    next_week = schedule.week_nav(datetime.date(2026, 9, 28), GROUP, FRIDAY)

    assert _buttons(day) == [
        [("‹ Сб, 26", False), ("Сегодня", False), ("Пн, 28 ›", False)],
        [("Эта неделя", False)],
    ]
    assert day[0][1].data == "rs:d:2026-09-25:ИСП-25-2"
    assert day[1][0].data == "rs:w:2026-09-21:ИСП-25-2"  # текущая неделя
    assert today[0][1].current  # открыт сегодняшний день — «Сегодня» выделена
    # Подробный вид: листание остаётся подробным.
    assert [b.data for b in full[0]] == [
        "rs:f:2026-09-26:ИСП-25-2",
        "rs:f:2026-09-25:ИСП-25-2",
        "rs:f:2026-09-28:ИСП-25-2",
    ]
    assert _buttons(week) == [
        [("‹ Пред.", False), ("Эта неделя", True), ("След. ›", False)],
        [("Сегодня", False)],
    ]
    assert week[0][2].data == "rs:w:2026-09-28:ИСП-25-2"
    assert week[1][0].data == "rs:d:2026-09-25:ИСП-25-2"
    assert next_week[0][1].data == "rs:w:2026-09-21:ИСП-25-2"
    assert not next_week[0][1].current


def test_details_toggle_button():
    short = schedule.details_toggle(FRIDAY, GROUP, detailed=False)
    full = schedule.details_toggle(FRIDAY, GROUP, detailed=True)

    assert (short.text, short.data) == ("Подробнее", "rs:f:2026-09-25:ИСП-25-2")
    assert (full.text, full.data) == ("Кратко", "rs:d:2026-09-25:ИСП-25-2")


@pytest.mark.parametrize("variant", ["link", "pill"])
async def test_toggle_in_body(monkeypatch, fixed_data, variant):
    monkeypatch.setattr(render_rich, "DETAILS_TOGGLE", variant)

    views = schedule.day_views(USER, GROUP, FRIDAY)
    html = await views.rich()

    assert views.markup is None
    style = {"link": "link", "pill": "primary"}[variant]
    assert f'style="{style}" data="rs:f:2026-09-25:ИСП-25-2">Подробнее' in html


async def test_toggle_as_inline_keyboard(monkeypatch, fixed_data):
    monkeypatch.setattr(render_rich, "DETAILS_TOGGLE", "keyboard")

    views = schedule.day_views(USER, GROUP, FRIDAY, detailed=True)
    html = await views.rich()

    assert "Кратко" not in html  # не в теле — под сообщением
    ((button,),) = views.markup.inline_keyboard
    assert (button.text, button.callback_data) == ("Кратко", "rs:d:2026-09-25:ИСП-25-2")
    assert "<tg-button-row" in html  # навигация по-прежнему в теле


def test_extras_only_for_own_group():
    user = {**USER, "extra_choices": '["a"]'}  # кружки всегда в расписании

    assert schedule._viewer(user, GROUP)[3] == ["a"]
    assert schedule._viewer(user, "МР-25")[3] == []


def test_nav_as_keyboard_when_not_in_body(monkeypatch, fixed_data):
    monkeypatch.setattr(schedule, "NAV_IN_BODY", False)

    views = schedule.day_views(USER, GROUP, FRIDAY)

    rows = views.markup.inline_keyboard
    assert [[(b.text, b.style) for b in row] for row in rows] == [
        [("‹ Чт, 24", None), ("Сегодня", "primary"), ("Сб, 26 ›", None)],
        [("Эта неделя", None)],
    ]


def _nav_callback(data: str, message_id: int = 50) -> MagicMock:
    callback = _callback(data)
    callback.message.message_id = message_id
    callback.bot.edit_message_text = AsyncMock()
    return callback


@pytest.fixture
def rich_user(monkeypatch):
    async def get_user(user_id):
        return USER

    monkeypatch.setattr(schedule, "get_user", get_user)


async def test_nav_edits_message_in_place(state, fixed_data, rich_user):
    callback = _nav_callback("rs:d:2026-09-26:ИСП-25-2")
    await state.update_data(last_bot_msg=77, last_schedule_msg=50)

    await schedule.on_schedule_nav(callback, state)

    # Правится только само расписание; шапка «Расписание» не меняется.
    (rich_edit,) = callback.bot.edit_message_text.await_args_list
    assert rich_edit.kwargs["chat_id"] == 9 and rich_edit.kwargs["message_id"] == 50
    html = rich_edit.kwargs["rich_message"].html
    assert html.startswith("<h3>Суббота, 26 сентября</h3>")
    assert (
        'style="primary" data="rs:d:2026-09-25:ИСП-25-2">Сегодня</tg-button>' in html
    )  # не сегодня
    callback.answer.assert_awaited_once_with()
    callback.bot.send_rich_message.assert_not_awaited()


async def test_nav_detailed_toggle_renders_full_table(state, fixed_data, rich_user):
    callback = _nav_callback("rs:f:2026-09-25:ИСП-25-2")

    await schedule.on_schedule_nav(callback, state)

    html = callback.bot.edit_message_text.await_args.kwargs["rich_message"].html
    assert html.count("<table") == 1
    assert '<td valign="top"><b>09:20</b><br><b>10:50</b></td>' in html
    assert 'data="rs:d:2026-09-25:ИСП-25-2">Кратко</tg-button>' in html


async def test_nav_week_uses_monday_and_past_kind(state, fixed_data, rich_user):
    callback = _nav_callback("rs:w:2026-09-16:ИСП-25-2")

    await schedule.on_schedule_nav(callback, state)

    html = callback.bot.edit_message_text.await_args.kwargs["rich_message"].html
    assert html.startswith("<h3>Неделя 14–19 сентября</h3>")
    assert "<details open>" not in html
    assert "Эта неделя закончилась" not in html


async def test_nav_not_modified_only_answers(state, fixed_data, rich_user):
    callback = _nav_callback("rs:d:2026-09-25:ИСП-25-2")
    callback.bot.edit_message_text.side_effect = TelegramBadRequest(
        method=MagicMock(), message="Bad Request: message is not modified"
    )

    await schedule.on_schedule_nav(callback, state)

    callback.answer.assert_awaited_once_with("Расписание актуально")
    callback.bot.send_rich_message.assert_not_awaited()


async def test_nav_edit_failure_sends_new_message(state, fixed_data, rich_user):
    callback = _nav_callback("rs:d:2026-09-25:ИСП-25-2")
    callback.bot.edit_message_text.side_effect = TelegramBadRequest(
        method=MagicMock(), message="Bad Request: message can't be edited"
    )
    await state.update_data(ui_msg_ids=[77, 50])

    await schedule.on_schedule_nav(callback, state)

    html = callback.bot.send_rich_message.await_args.kwargs["rich_message"].html
    assert html.startswith("<h3>Пятница, 25 сентября</h3>")
    assert (await state.get_data())["ui_msg_ids"] == [77, 50, 101]


async def test_nav_for_classic_user_sends_classic(state, monkeypatch, fixed_data):
    async def get_user(user_id):
        return {**USER, "classic_view": 1}

    monkeypatch.setattr(schedule, "get_user", get_user)
    callback = _nav_callback("rs:d:2026-09-25:ИСП-25-2")

    await schedule.on_schedule_nav(callback, state)

    callback.answer.assert_awaited_once_with(schedule.CLASSIC_NAV_TEXT)
    callback.bot.edit_message_text.assert_not_awaited()
    assert callback.bot.send_message.await_args.kwargs["reply_markup"] == (
        schedule.schedule_detail_kb("2026-09-25")
    )


async def test_nav_stale_button(state):
    callback = _nav_callback("rs:d:garbage")

    await schedule.on_schedule_nav(callback, state)

    callback.answer.assert_awaited_once_with("Кнопка устарела — открой расписание заново")


async def test_daily_notify_rich_has_nav(daily):
    bot = _bot()

    await scheduler._send_daily_schedule(bot, USER, FRIDAY)

    html = bot.send_rich_message.await_args.kwargs["rich_message"].html
    assert ">Подробнее</tg-button></p>" in html
    assert html.endswith(">Эта неделя</tg-button></tg-button-row>")


# ── Вход в расписание: сразу сегодняшний день ────────────


def _menu_message() -> MagicMock:
    message = _message()
    message.bot = _bot()
    message.answer = AsyncMock(return_value=MagicMock(message_id=60))
    return message


async def test_schedule_menu_opens_today_for_rich_user(state, fixed_data, rich_user):
    message = _menu_message()

    await schedule.on_schedule_menu(message, state)

    # Шапка «Расписание» с reply-кнопкой «⬅️ Назад», сразу за ней — сегодняшний день.
    assert message.answer.await_args.args[0] == "<b>Расписание</b>"
    assert message.answer.await_args.kwargs["reply_markup"] == schedule.back_kb()
    html = message.bot.send_rich_message.await_args.kwargs["rich_message"].html
    assert html.startswith("<h3>Пятница, 25 сентября</h3>")
    data = await state.get_data()
    assert data["ui_msg_ids"] == [60, 101]
    assert (data["last_bot_msg"], data["last_schedule_msg"]) == (60, 101)
    assert data["_nav_stack"] == ["main_menu"]
    assert await state.get_state() == schedule.ScheduleNav.period.state


async def test_schedule_menu_keeps_period_keyboard_for_classic(state, monkeypatch, fixed_data):
    async def get_user(user_id):
        return {**USER, "classic_view": 1}

    monkeypatch.setattr(schedule, "get_user", get_user)
    message = _menu_message()

    await schedule.on_schedule_menu(message, state)

    assert message.answer.await_args.kwargs["reply_markup"] == schedule.schedule_period_reply_kb()
    message.bot.send_rich_message.assert_not_awaited()
    message.bot.send_message.assert_not_awaited()


async def test_other_group_opens_today_without_extras(state, monkeypatch, fixed_data):
    user = {**USER, "extra_choices": '["x"]'}
    seen = []

    async def get_user(user_id):
        return user

    def get_extras_for_date(group_name, date, keys):
        seen.append(keys)
        return []

    monkeypatch.setattr(schedule, "get_user", get_user)
    monkeypatch.setattr(schedule, "get_extras_for_date", get_extras_for_date)
    callback = _callback("other_group:МР-25")
    callback.message.answer = AsyncMock(return_value=MagicMock(message_id=60))
    callback.message.bot = callback.bot

    await schedule.on_other_group_selected(callback, state)

    assert callback.message.answer.await_args.args[0] == "<b>МР-25</b>\n\nРасписание"
    html = callback.bot.send_rich_message.await_args.kwargs["rich_message"].html
    assert "<footer>МР-25</footer>" in html
    assert 'data="rs:w:2026-09-21:МР-25">Эта неделя' in html
    assert seen and all(keys == [] for keys in seen)  # чужая группа — без допов
    data = await state.get_data()
    assert (data["schedule_context"], data["schedule_group_name"]) == ("other", "МР-25")
    assert data["_nav_stack"] == ["other_group_select"]


# ── Кружки только в расписании, ссылки в меню команд ─────


async def test_old_extra_button_refreshes_main_menu(state, monkeypatch):
    from handlers import extra

    async def get_user(user_id):
        return {**USER, "role": "student"}

    monkeypatch.setattr(extra, "get_user", get_user)
    message = _menu_message()
    message.text = "📌 Доп. занятия"

    await extra.on_extra_menu_removed(message, state)

    keyboard = message.answer.await_args.kwargs["reply_markup"].keyboard
    assert [b.text for row in keyboard for b in row] == ["📅 Расписание"]


async def test_old_extra_settings_button_answers(monkeypatch):
    async def get_user(user_id):
        return USER

    monkeypatch.setattr(start, "get_user", get_user)
    callback = MagicMock()
    callback.data = "settings:extra_display:0"
    callback.from_user.id = 9
    callback.answer = AsyncMock()
    callback.message.edit_text = AsyncMock()

    await start.on_settings_extra_removed(callback)

    callback.answer.assert_awaited_once_with("Кружки теперь всегда в расписании", show_alert=True)
    kb = callback.message.edit_text.await_args.kwargs["reply_markup"]
    assert all(
        not b.callback_data.startswith("settings:extra") for r in kb.inline_keyboard for b in r
    )


async def test_links_command(state, monkeypatch):
    from handlers import info

    async def get_user(user_id):
        return USER

    monkeypatch.setattr(info, "get_user", get_user)
    message = _menu_message()
    message.text = "/links"

    await info.on_info_screen(message, state)

    header, body = message.answer.await_args_list
    assert header.args[0] == "<b>Полезные ссылки</b>"
    assert "sport.innopolis.university" in body.args[0]
