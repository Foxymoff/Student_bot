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
    assert html.startswith("<h3>Пятница, 25 сентября</h3><p>3 пары, 09:20–15:00 · начало")
    assert message.bot.send_rich_message.await_args.kwargs["reply_markup"] is None
    # Навигация — кнопками в теле сообщения, «Сегодня» — текущая.
    assert html.endswith(
        '<tg-button-row align="center">'
        '<tg-button type="callback_data" data="rs:d:2026-09-24:ИСП-25-2">‹ Чт, 24</tg-button>'
        '<tg-button type="callback_data" style="primary" data="rs:d:2026-09-25:ИСП-25-2">'
        "Сегодня</tg-button>"
        '<tg-button type="callback_data" data="rs:d:2026-09-26:ИСП-25-2">Сб, 26 ›</tg-button>'
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
    assert "<details open><summary><mark>Пт, 25 сентября · сегодня</mark></summary>" in html


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


def test_day_and_week_nav():
    day = schedule.day_nav(datetime.date(2026, 9, 27), GROUP, FRIDAY)
    week = schedule.week_nav(datetime.date(2026, 9, 21), GROUP, FRIDAY)

    assert [(b.text, b.active) for b in day] == [
        ("‹ Сб, 26", False),
        ("Сегодня", False),
        ("Пн, 28 ›", False),
    ]
    assert day[1].data == "rs:d:2026-09-25:ИСП-25-2"
    assert [(b.text, b.active) for b in week] == [
        ("‹ Пред.", False),
        ("Эта неделя", True),
        ("След. ›", False),
    ]
    assert week[2].data == "rs:w:2026-09-28:ИСП-25-2"


def test_extras_only_for_own_group():
    user = {**USER, "extra_in_schedule": 1, "extra_choices": '["a"]'}

    assert schedule._viewer(user, GROUP)[3] == ["a"]
    assert schedule._viewer(user, "МР-25")[3] == []


def test_nav_as_keyboard_when_not_in_body(monkeypatch, fixed_data):
    monkeypatch.setattr(schedule, "NAV_IN_BODY", False)

    views = schedule.day_views(USER, GROUP, FRIDAY)

    buttons = views.markup.inline_keyboard[0]
    assert [(b.text, b.style) for b in buttons] == [
        ("‹ Чт, 24", None),
        ("Сегодня", "primary"),
        ("Сб, 26 ›", None),
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

    edits = callback.bot.edit_message_text.await_args_list
    rich_edit, header_edit = edits
    assert rich_edit.kwargs["chat_id"] == 9 and rich_edit.kwargs["message_id"] == 50
    html = rich_edit.kwargs["rich_message"].html
    assert html.startswith("<h3>Суббота, 26 сентября</h3>")
    assert (
        '<tg-button type="callback_data" data="rs:d:2026-09-25:ИСП-25-2">Сегодня</tg-button>'
        in html
    )
    assert header_edit.args[0] == "<b>Завтра</b>"
    assert header_edit.kwargs["message_id"] == 77
    callback.answer.assert_awaited_once_with()
    callback.bot.send_rich_message.assert_not_awaited()


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
    assert html.endswith("Сб, 26 ›</tg-button></tg-button-row>")
