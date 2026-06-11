"""
Панель старосты: дата -> пара -> действие с парой.
"""

import datetime
import html as _html
import logging
import re
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import ROOM_SHORT, SUBJECT_SHORT, app_today
from database import (
    add_override,
    delete_lesson_overrides,
    get_lesson_overrides,
    get_overrides,
    get_user,
    get_users_by_group,
)
from handlers.schedule import MONTH_NAMES, WEEKDAY_NAMES_SHORT, get_lessons_for_date
from keyboards import (
    alert_delete_kb,
    main_menu_kb,
    main_menu_only_kb,
    starosta_confirm_kb,
    starosta_day_lessons_kb,
    starosta_input_back_kb,
    starosta_lesson_actions_kb,
    starosta_week_dates_kb,
)
from message_style import HTML_PARSE_MODE, MAIN_MENU_TEXT, no_access_text, title, titled
from ui_messages import delete_user_message, replace_ui_messages

logger = logging.getLogger(__name__)
router = Router()

ROOM_MAX_LEN = 40
NOTE_MAX_LEN = 250
ONLINE_LINK_MAX_LEN = 300

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")

WEEKDAY_BUTTONS: dict[int, str] = {
    0: "пн",
    1: "вт",
    2: "ср",
    3: "чт",
    4: "пт",
    5: "сб",
}


class StarostaAction(StatesGroup):
    waiting_room = State()
    waiting_link = State()
    waiting_note = State()


def _esc(value: object) -> str:
    """HTML-экранирование."""
    return _html.escape(str(value))


def _clean_single_line(value: object, max_len: int) -> tuple[str | None, str | None]:
    """Очистить пользовательский ввод для хранения в БД и вывода в Telegram."""
    text = _CONTROL_CHARS_RE.sub("", str(value or ""))
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if not text:
        return None, "Значение не может быть пустым."
    if len(text) > max_len:
        return None, f"Слишком длинно. Максимум {max_len} символов."
    return text, None


def _validate_room(value: object) -> tuple[str | None, str | None]:
    """Проверить новую аудиторию."""
    return _clean_single_line(value, ROOM_MAX_LEN)


def _validate_note(value: object) -> tuple[str | None, str | None]:
    """Проверить примечание к паре."""
    return _clean_single_line(value, NOTE_MAX_LEN)


def _validate_online_link(value: object) -> tuple[str | None, str | None]:
    """Проверить онлайн-ссылку перед сохранением и рассылкой."""
    text = str(value or "").strip()
    if not text:
        return None, "Ссылка не может быть пустой."
    if len(text) > ONLINE_LINK_MAX_LEN:
        return None, f"Ссылка слишком длинная. Максимум {ONLINE_LINK_MAX_LEN} символов."
    if _CONTROL_CHARS_RE.search(text) or any(char.isspace() for char in text):
        return None, "Ссылка не должна содержать пробелы или переносы строк."

    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None, "Нужна ссылка вида https://example.com."

    return text, None


def _short_name(subject: object) -> str:
    """Короткое название предмета."""
    value = str(subject or "")
    return SUBJECT_SHORT.get(value, value)


def _short_room(room: object) -> str:
    """Короткая аудитория."""
    value = str(room or "")
    return ROOM_SHORT.get(value, value)


def _date_text(target_date: datetime.date) -> str:
    """Дата для текстов: '2 июня · вторник'."""
    return f"{target_date.day} {MONTH_NAMES[target_date.month]} · {WEEKDAY_NAMES_SHORT[target_date.weekday()]}"


def _date_button_text(target_date: datetime.date) -> str:
    """Дата для inline-кнопки."""
    return f"{target_date.strftime('%d.%m')} · {WEEKDAY_BUTTONS[target_date.weekday()]}"


def _week_dates(next_week: bool) -> list[datetime.date]:
    """Пн-Сб текущей или следующей учебной недели."""
    today = app_today()
    monday = today - datetime.timedelta(days=today.weekday())
    if next_week:
        monday += datetime.timedelta(weeks=1)
    return [monday + datetime.timedelta(days=offset) for offset in range(6)]


def _subgroup_token(subgroup: int | None) -> str:
    """Подгруппа для callback_data."""
    return "all" if subgroup is None else str(subgroup)


def _parse_subgroup(value: str | None) -> int | None:
    """Разобрать подгруппу из callback_data."""
    if not value or value == "all":
        return None
    return int(value)


def _selected_pair(data: dict) -> tuple[str, int, int | None] | None:
    """Текущая выбранная пара из FSM."""
    date_iso = data.get("starosta_date")
    lesson_num = data.get("starosta_lesson_num")
    if not date_iso or lesson_num in (None, ""):
        return None
    return str(date_iso), int(lesson_num), _parse_subgroup(str(data.get("starosta_subgroup") or "all"))


def _lesson_room(lesson: dict) -> str:
    """Аудитория пары с учетом подгруппы."""
    return str(lesson.get("_sg_room") or lesson.get("room") or "")


def _lesson_subject(lesson: dict, lesson_num: int) -> str:
    """Название пары."""
    return str(lesson.get("subject") or f"Пара {lesson_num}")


def _lesson_scope(subgroup: int | None) -> str:
    """Подпись подгруппы."""
    return "" if subgroup is None else f" ({subgroup} подгр.)"


def _is_english_lesson(lesson: dict) -> bool:
    """Является ли пара английским."""
    subject = str(lesson.get("subject") or "").lower()
    return bool(lesson.get("subgroups")) or "иностранн" in subject or "английск" in subject


def _user_matches_subgroup(user: dict, lesson: dict, subgroup: int | None) -> bool:
    """Проверить, нужно ли пользователю отправлять подгрупповой алерт."""
    if subgroup is None:
        return True
    field = "subgroup_en" if _is_english_lesson(lesson) else "subgroup_cs"
    return int(user.get(field) or 1) == subgroup


def _lesson_entries(lessons: list[dict]) -> list[dict]:
    """Развернуть пары в кнопки с учетом подгрупп."""
    entries: list[dict] = []
    for lesson in lessons:
        subgroups = lesson.get("subgroups") or []
        if subgroups:
            for subgroup in subgroups:
                group = subgroup.get("group")
                entries.append({
                    **lesson,
                    "_target_subgroup": int(group),
                    "_sg_room": subgroup.get("room", ""),
                    "_sg_teacher": subgroup.get("teacher", ""),
                })
            continue

        subgroup = lesson.get("subgroup")
        entries.append({
            **lesson,
            "_target_subgroup": int(subgroup) if subgroup not in (None, "") else None,
        })
    return entries


def _find_lesson(group_name: str, target_date: datetime.date, lesson_num: int, subgroup: int | None = None) -> dict:
    """Найти пару по номеру и подгруппе."""
    for lesson in _lesson_entries(get_lessons_for_date(group_name, target_date)):
        if int(lesson.get("num", 0)) != lesson_num:
            continue
        if lesson.get("_target_subgroup") == subgroup:
            return lesson
    return {}


def _same_room(left: object, right: object) -> bool:
    """Сравнить аудитории без лишних пробелов."""
    return str(left or "").strip() == str(right or "").strip()


def _pair_status(lesson: dict, overrides: list[dict]) -> dict:
    """Итоговые статусы пары для панели старосты."""
    original_room = _lesson_room(lesson)
    room = original_room
    status = {
        "has_changes": bool(overrides),
        "cancelled": False,
        "online": False,
        "online_link": "",
        "room": room,
        "room_changed": False,
        "note": "",
    }

    for override in overrides:
        override_type = override.get("override_type")
        if override_type == "cancel":
            status["cancelled"] = True
        elif override_type == "room_change":
            room = str(override.get("new_value") or "")
            status["room"] = room
            status["room_changed"] = not _same_room(room, original_room)
        elif override_type == "online":
            status["online"] = True
            status["online_link"] = str(override.get("new_value") or "")
        elif override_type == "note":
            status["note"] = str(override.get("new_value") or override.get("comment") or "")

    return status


def _append_note_marker(base: str, has_note: bool) -> str:
    """Добавить маркер примечания в согласованном формате."""
    if not has_note:
        return base
    separator = "· " if base.endswith(("❕", "❗️")) else " · "
    return f"{base}{separator}ПР❕"


def _pair_status_label(lesson: dict, status: dict) -> str:
    """Короткий статус пары в списке пар."""
    if status["cancelled"]:
        base = "ОТМ❗️"
    elif status["online"]:
        base = "ОНЛ❕"
    else:
        room = _short_room(status.get("room") or _lesson_room(lesson) or "-")
        base = f"{room}❕" if status.get("room_changed") else room
    return _append_note_marker(base, bool(status.get("note")))


def _pair_action_text(
    target_date: datetime.date,
    lesson_num: int,
    subgroup: int | None,
    lesson: dict,
    status: dict,
) -> str:
    """Текст меню действий с парой."""
    subject = _esc(_short_name(_lesson_subject(lesson, lesson_num)))
    lines = [
        title("Действие с парой"),
        "",
        _esc(_date_text(target_date)),
        f"{lesson_num} пара · {subject}{_esc(_lesson_scope(subgroup))}",
        "",
    ]

    lines.append(f"Статус · {_esc(_pair_status_label(lesson, status))}")
    visible_details = False
    if status.get("cancelled"):
        lines.append("Отмена · активна")
        visible_details = True
    if status.get("online"):
        lines.append("Онлайн · активен")
        visible_details = True
    if status.get("room_changed"):
        lines.append(f"Аудитория · {_esc(_short_room(status.get('room') or '-'))}")
        visible_details = True

    if status.get("online_link"):
        lines.append(f"Ссылка · {_esc(status['online_link'])}")
        visible_details = True
    if status.get("note"):
        lines.append(f"Примечание · {_esc(status['note'])}")
        visible_details = True
    if not visible_details:
        lines.append("Изменений нет")

    lines.extend(["", "Выбери действие."])
    return "\n".join(lines)


def _input_text(title_text: str, target_date: datetime.date, lesson_num: int, subgroup: int | None, lesson: dict, body: str) -> str:
    """Текст экрана ввода."""
    subject = _esc(_short_name(_lesson_subject(lesson, lesson_num)))
    return titled(
        title_text,
        f"{_esc(_date_text(target_date))}\n"
        f"{lesson_num} пара · {subject}{_esc(_lesson_scope(subgroup))}\n\n"
        f"{body}",
    )


def _confirm_text(title_text: str, target_date: datetime.date, lesson_num: int, subgroup: int | None, lesson: dict, body: str) -> str:
    """Текст подтверждения действия."""
    subject = _esc(_short_name(_lesson_subject(lesson, lesson_num)))
    return titled(
        title_text,
        f"{_esc(_date_text(target_date))}\n"
        f"{lesson_num} пара · {subject}{_esc(_lesson_scope(subgroup))}\n\n"
        f"{body}",
    )


def _starosta_body_id(data: dict) -> int | None:
    """ID сообщения с inline-экраном старосты."""
    ids = data.get("ui_msg_ids") or []
    return int(ids[-1]) if ids else None


async def _edit_starosta_body(
    message: Message,
    state: FSMContext,
    text: str,
    reply_markup=None,
) -> bool:
    """Отредактировать текущий inline-экран старосты."""
    data = await state.get_data()
    body_id = _starosta_body_id(data)
    if not body_id and getattr(message, "reply_markup", None) is not None:
        body_id = message.message_id
        await state.update_data(ui_msg_ids=[body_id], ui_screen="starosta")
    if not body_id:
        return False
    try:
        await message.bot.edit_message_text(
            text,
            message.chat.id,
            body_id,
            reply_markup=reply_markup,
            parse_mode=HTML_PARSE_MODE,
        )
        return True
    except Exception as exc:
        if "message is not modified" in str(exc).lower():
            return True
        logger.warning("Не удалось отредактировать панель старосты %s: %s", body_id, exc)
        return False


async def _show_starosta_body(
    message: Message,
    state: FSMContext,
    text: str,
    reply_markup=None,
) -> None:
    """Показать inline-экран старосты, заменяя старый при fallback."""
    if await _edit_starosta_body(message, state, text, reply_markup):
        return

    sent = await message.answer(text, reply_markup=reply_markup, parse_mode=HTML_PARSE_MODE)
    await replace_ui_messages(
        message.bot,
        message.chat.id,
        state,
        [sent.message_id],
        screen="starosta",
        last_bot_msg=sent.message_id,
    )


async def _replace_with_main_menu(message: Message, state: FSMContext, user: dict | None) -> None:
    """Вернуться в главное меню."""
    role = user.get("role", "student") if user else "student"
    sent = await message.answer(
        MAIN_MENU_TEXT,
        reply_markup=main_menu_kb(role, not bool(user and user.get("extra_in_schedule"))),
        parse_mode=HTML_PARSE_MODE,
    )
    await replace_ui_messages(
        message.bot,
        message.chat.id,
        state,
        [sent.message_id],
        screen="main_menu",
        clear_state=True,
        last_bot_msg=sent.message_id,
    )


async def _render_dates(message: Message, state: FSMContext, next_week: bool = False) -> None:
    """Показать выбор дат."""
    await state.set_state(None)
    dates = [
        {"date": day.isoformat(), "_label": _date_button_text(day)}
        for day in _week_dates(next_week)
    ]
    await _show_starosta_body(
        message,
        state,
        titled("Панель старосты", "Выбери дату."),
        starosta_week_dates_kb(dates, next_week),
    )
    await state.update_data(
        _starosta_screen="dates",
        starosta_next_week=1 if next_week else 0,
        starosta_date=None,
        starosta_lesson_num=None,
        starosta_subgroup=None,
    )


async def _render_lessons(message: Message, state: FSMContext, user: dict, date_iso: str) -> None:
    """Показать пары выбранного дня."""
    await state.set_state(None)
    target_date = datetime.date.fromisoformat(date_iso)
    lessons = get_lessons_for_date(user["group_name"], target_date)
    overrides = await get_overrides(user["group_name"], date_iso)
    lesson_buttons = []

    for lesson in _lesson_entries(lessons):
        lesson_num = int(lesson.get("num", 0))
        subgroup = lesson.get("_target_subgroup")
        lesson_overrides = [
            override for override in overrides
            if int(override.get("lesson_num") or 0) == lesson_num
            and (override.get("subgroup") in (None, "") if subgroup is None else int(override.get("subgroup") or 0) == subgroup)
        ]
        status = _pair_status(lesson, lesson_overrides)
        subject = _short_name(_lesson_subject(lesson, lesson_num))
        scope = _lesson_scope(subgroup)
        status_label = _pair_status_label(lesson, status)
        lesson_buttons.append({
            "_label": f"{lesson_num}. {subject}{scope} · {status_label}",
            "_callback": f"starosta_pick:{date_iso}:{lesson_num}:{_subgroup_token(subgroup)}",
        })

    body = f"{_esc(_date_text(target_date))}\n\n"
    body += "Выбери пару." if lesson_buttons else "Пар на эту дату нет."
    await _show_starosta_body(
        message,
        state,
        titled("Пары", body),
        starosta_day_lessons_kb(lesson_buttons),
    )
    await state.update_data(
        _starosta_screen="lessons",
        starosta_date=date_iso,
        starosta_lesson_num=None,
        starosta_subgroup=None,
    )


async def _render_actions(message: Message, state: FSMContext, user: dict, date_iso: str, lesson_num: int, subgroup: int | None) -> None:
    """Показать действия с выбранной парой."""
    await state.set_state(None)
    target_date = datetime.date.fromisoformat(date_iso)
    lesson = _find_lesson(user["group_name"], target_date, lesson_num, subgroup)
    overrides = await get_lesson_overrides(user["group_name"], date_iso, lesson_num, subgroup)
    status = _pair_status(lesson, overrides)
    await _show_starosta_body(
        message,
        state,
        _pair_action_text(target_date, lesson_num, subgroup, lesson, status),
        starosta_lesson_actions_kb(),
    )
    await state.update_data(
        _starosta_screen="actions",
        starosta_date=date_iso,
        starosta_lesson_num=lesson_num,
        starosta_subgroup=_subgroup_token(subgroup),
    )


async def _render_current_actions(message: Message, state: FSMContext, user: dict) -> None:
    """Вернуться к меню действий текущей пары."""
    selected = _selected_pair(await state.get_data())
    if not selected:
        await _render_dates(message, state)
        return
    date_iso, lesson_num, subgroup = selected
    await _render_actions(message, state, user, date_iso, lesson_num, subgroup)


def _change_alert_text(
    kind: str,
    target_date: datetime.date,
    lesson_num: int,
    lesson: dict,
    new_room: str | None = None,
    subgroup: int | None = None,
) -> str:
    """Сформировать текст срочного алерта."""
    subject = _esc(lesson.get("subject") or f"Пара {lesson_num}")
    scope = _esc(_lesson_scope(subgroup))
    date_text = _esc(_date_text(target_date).replace(" · ", ", "))

    if kind == "cancel":
        return (
            f"⛔️ <b>ОТМЕНА ПАРЫ</b> на {date_text}\n\n"
            f"{lesson_num} пара · <b>{subject}</b>{scope}"
        )

    if kind == "online":
        link = _esc(new_room or "-")
        return (
            f"🔗 <b>ОНЛАЙН-ЗАНЯТИЕ</b> на {date_text}\n\n"
            f"{lesson_num} пара · <b>{subject}</b>{scope}\n"
            f"Ссылка: <b>{link}</b>"
        )

    room = _esc(new_room or "-")
    return (
        f"⚠️ <b>ИЗМЕНЕНИЕ АУДИТОРИИ</b> на {date_text}\n\n"
        f"{lesson_num} пара · <b>{subject}</b>{scope}\n"
        f"Аудитория: <b>{room}</b>"
    )


async def _send_change_alerts(
    bot,
    group_name: str,
    date_iso: str,
    lesson_num: int,
    kind: str,
    new_room: str | None = None,
    subgroup: int | None = None,
) -> None:
    """Отправить алерт всем пользователям группы, у которых он включен."""
    try:
        target_date = datetime.date.fromisoformat(date_iso)
    except ValueError:
        logger.warning("Некорректная дата для алерта: %s", date_iso)
        return

    lesson = _find_lesson(group_name, target_date, lesson_num, subgroup)
    text = _change_alert_text(kind, target_date, lesson_num, lesson, new_room, subgroup)
    users = await get_users_by_group(group_name)
    for user in users:
        if not user.get("change_alert_enabled"):
            continue
        if not _user_matches_subgroup(user, lesson, subgroup):
            continue
        try:
            await bot.send_message(
                user["user_id"],
                text,
                reply_markup=alert_delete_kb(),
                parse_mode=HTML_PARSE_MODE,
                disable_notification=not bool(user.get("change_alert_sound", 1)),
            )
        except Exception as exc:
            logger.warning("Не удалось отправить алерт пользователю %s: %s", user.get("user_id"), exc)


@router.callback_query(F.data == "alert:delete")
async def on_alert_delete(callback: CallbackQuery) -> None:
    """Удалить алерт по кнопке пользователя."""
    try:
        await callback.message.delete()
    except Exception:
        await callback.answer("Не получилось · уведомление не удалено", show_alert=True)
        return
    await callback.answer()


@router.message(F.text == "🏠 Главное меню")
async def on_starosta_main_reply(message: Message, state: FSMContext) -> None:
    """Быстрый выход из панели старосты."""
    await delete_user_message(message)
    user = await get_user(message.from_user.id)
    await state.set_state(None)
    await _replace_with_main_menu(message, state, user)


@router.message(F.text == "📋 Староста")
async def on_starosta_menu(message: Message, state: FSMContext) -> None:
    """Открыть панель старосты."""
    user = await get_user(message.from_user.id)
    if not user or user.get("role") not in ("starosta", "admin"):
        await message.answer(no_access_text(), parse_mode=HTML_PARSE_MODE)
        return

    await delete_user_message(message)
    header = await message.answer(title("Панель старосты"), reply_markup=main_menu_only_kb(), parse_mode=HTML_PARSE_MODE)
    body = await message.answer(
        titled("Панель старосты", "Выбери дату."),
        reply_markup=starosta_week_dates_kb(
            [{"date": day.isoformat(), "_label": _date_button_text(day)} for day in _week_dates(False)],
            False,
        ),
        parse_mode=HTML_PARSE_MODE,
    )
    await replace_ui_messages(
        message.bot,
        message.chat.id,
        state,
        [header.message_id, body.message_id],
        screen="starosta",
        clear_state=True,
        last_bot_msg=header.message_id,
    )
    await state.update_data(
        _starosta_screen="dates",
        starosta_next_week=0,
        starosta_date=None,
        starosta_lesson_num=None,
        starosta_subgroup=None,
    )


@router.callback_query(F.data == "starosta_main")
async def on_starosta_main(callback: CallbackQuery, state: FSMContext) -> None:
    """Inline-выход в главное меню."""
    user = await get_user(callback.from_user.id)
    await _replace_with_main_menu(callback.message, state, user)
    await callback.answer()


@router.callback_query(F.data.startswith("starosta_week:"))
async def on_starosta_week(callback: CallbackQuery, state: FSMContext) -> None:
    """Переключить текущую/следующую неделю."""
    user = await get_user(callback.from_user.id)
    if not user or user.get("role") not in ("starosta", "admin"):
        await callback.answer("Нет доступа", show_alert=True)
        return
    next_week = bool(int(callback.data.split(":", 1)[1]))
    await _render_dates(callback.message, state, next_week)
    await callback.answer()


@router.callback_query(F.data == "starosta_dates")
async def on_starosta_dates(callback: CallbackQuery, state: FSMContext) -> None:
    """Вернуться к выбору дат."""
    user = await get_user(callback.from_user.id)
    if not user or user.get("role") not in ("starosta", "admin"):
        await callback.answer("Нет доступа", show_alert=True)
        return
    data = await state.get_data()
    await _render_dates(callback.message, state, bool(data.get("starosta_next_week")))
    await callback.answer()


@router.callback_query(F.data.startswith("starosta_day:"))
async def on_starosta_day(callback: CallbackQuery, state: FSMContext) -> None:
    """Показать пары выбранной даты."""
    user = await get_user(callback.from_user.id)
    if not user or user.get("role") not in ("starosta", "admin"):
        await callback.answer("Нет доступа", show_alert=True)
        return
    date_iso = callback.data.split(":", 1)[1]
    await _render_lessons(callback.message, state, user, date_iso)
    await callback.answer()


@router.callback_query(F.data.startswith("starosta_pick:"))
async def on_starosta_pick(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбрать пару."""
    user = await get_user(callback.from_user.id)
    if not user or user.get("role") not in ("starosta", "admin"):
        await callback.answer("Нет доступа", show_alert=True)
        return
    _, date_iso, lesson_num, subgroup_raw = callback.data.split(":")
    await _render_actions(callback.message, state, user, date_iso, int(lesson_num), _parse_subgroup(subgroup_raw))
    await callback.answer()


@router.callback_query(F.data.startswith("starosta_back:"))
async def on_starosta_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Inline-навигация назад внутри панели старосты."""
    user = await get_user(callback.from_user.id)
    if not user or user.get("role") not in ("starosta", "admin"):
        await callback.answer("Нет доступа", show_alert=True)
        return
    target = callback.data.split(":", 1)[1]
    data = await state.get_data()
    if target == "actions":
        await _render_current_actions(callback.message, state, user)
    elif target == "lessons" and data.get("starosta_date"):
        await _render_lessons(callback.message, state, user, str(data["starosta_date"]))
    else:
        await _render_dates(callback.message, state, bool(data.get("starosta_next_week")))
    await callback.answer()


@router.callback_query(F.data.startswith("starosta_action:"))
async def on_starosta_action(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбрать действие с парой."""
    user = await get_user(callback.from_user.id)
    if not user or user.get("role") not in ("starosta", "admin"):
        await callback.answer("Нет доступа", show_alert=True)
        return

    selected = _selected_pair(await state.get_data())
    if not selected:
        await callback.answer("Выбери пару заново", show_alert=True)
        await _render_dates(callback.message, state)
        return

    date_iso, lesson_num, subgroup = selected
    target_date = datetime.date.fromisoformat(date_iso)
    lesson = _find_lesson(user["group_name"], target_date, lesson_num, subgroup)
    action = callback.data.split(":", 1)[1]

    if action == "room":
        await state.set_state(StarostaAction.waiting_room)
        await state.update_data(_starosta_screen="room_input")
        await _show_starosta_body(
            callback.message,
            state,
            _input_text("Новая аудитория", target_date, lesson_num, subgroup, lesson, "Введи номер аудитории."),
            starosta_input_back_kb(),
        )
    elif action == "online":
        await state.set_state(StarostaAction.waiting_link)
        await state.update_data(_starosta_screen="online_input")
        await _show_starosta_body(
            callback.message,
            state,
            _input_text("Онлайн-занятие", target_date, lesson_num, subgroup, lesson, "Вставь ссылку."),
            starosta_input_back_kb(),
        )
    elif action == "note":
        await state.set_state(StarostaAction.waiting_note)
        await state.update_data(_starosta_screen="note_input")
        await _show_starosta_body(
            callback.message,
            state,
            _input_text("Примечание", target_date, lesson_num, subgroup, lesson, "Введи текст примечания."),
            starosta_input_back_kb(),
        )
    elif action == "cancel":
        await state.set_state(None)
        await state.update_data(_starosta_screen="cancel_confirm")
        await _show_starosta_body(
            callback.message,
            state,
            _confirm_text("Отменить пару?", target_date, lesson_num, subgroup, lesson, "Подтверди действие."),
            starosta_confirm_kb("starosta_cancel"),
        )
    elif action == "rollback":
        overrides = await get_lesson_overrides(user["group_name"], date_iso, lesson_num, subgroup)
        if not overrides:
            await callback.answer("Изменений для отката нет", show_alert=True)
            return
        await state.set_state(None)
        await state.update_data(_starosta_screen="rollback_confirm")
        await _show_starosta_body(
            callback.message,
            state,
            _confirm_text("Откатить изменения?", target_date, lesson_num, subgroup, lesson, "Будут сняты все изменения этой пары."),
            starosta_confirm_kb("starosta_rollback"),
        )

    await callback.answer()


@router.callback_query(F.data.startswith("starosta_cancel:"))
async def on_starosta_cancel_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    """Подтверждение отмены пары."""
    user = await get_user(callback.from_user.id)
    if not user or user.get("role") not in ("starosta", "admin"):
        await callback.answer("Нет доступа", show_alert=True)
        return
    decision = callback.data.split(":", 1)[1]
    if decision != "yes":
        await _render_current_actions(callback.message, state, user)
        await callback.answer()
        return

    selected = _selected_pair(await state.get_data())
    if not selected:
        await callback.answer("Выбери пару заново", show_alert=True)
        return
    date_iso, lesson_num, subgroup = selected
    await add_override(
        user["group_name"],
        date_iso,
        lesson_num,
        "cancel",
        comment="Пара отменена старостой",
        created_by=callback.from_user.id,
        subgroup=subgroup,
    )
    await _send_change_alerts(callback.bot, user["group_name"], date_iso, lesson_num, "cancel", subgroup=subgroup)
    await _render_current_actions(callback.message, state, user)
    await callback.answer("Готово · пара отменена", show_alert=True)


@router.callback_query(F.data.startswith("starosta_rollback:"))
async def on_starosta_rollback_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    """Подтверждение полного отката изменений пары."""
    user = await get_user(callback.from_user.id)
    if not user or user.get("role") not in ("starosta", "admin"):
        await callback.answer("Нет доступа", show_alert=True)
        return
    decision = callback.data.split(":", 1)[1]
    if decision != "yes":
        await _render_current_actions(callback.message, state, user)
        await callback.answer()
        return

    selected = _selected_pair(await state.get_data())
    if not selected:
        await callback.answer("Выбери пару заново", show_alert=True)
        return
    date_iso, lesson_num, subgroup = selected
    removed = await delete_lesson_overrides(user["group_name"], date_iso, lesson_num, subgroup)
    await _render_current_actions(callback.message, state, user)
    if removed:
        await callback.answer("Готово · изменения сняты", show_alert=True)
    else:
        await callback.answer("Изменений для отката нет", show_alert=True)


@router.message(StarostaAction.waiting_room)
async def on_room_input(message: Message, state: FSMContext) -> None:
    """Ввод новой аудитории."""
    user = await get_user(message.from_user.id)
    if not user:
        await state.clear()
        return
    await delete_user_message(message)

    selected = _selected_pair(await state.get_data())
    if not selected:
        await state.set_state(None)
        return
    date_iso, lesson_num, subgroup = selected
    target_date = datetime.date.fromisoformat(date_iso)
    lesson = _find_lesson(user["group_name"], target_date, lesson_num, subgroup)
    new_room, error = _validate_room(message.text)
    if error:
        await _show_starosta_body(
            message,
            state,
            _input_text("Новая аудитория", target_date, lesson_num, subgroup, lesson, f"{error}\n\nВведи номер аудитории."),
            starosta_input_back_kb(),
        )
        return

    await add_override(
        user["group_name"],
        date_iso,
        lesson_num,
        "room_change",
        new_value=new_room,
        comment="Аудитория изменена",
        created_by=message.from_user.id,
        subgroup=subgroup,
    )
    await _send_change_alerts(message.bot, user["group_name"], date_iso, lesson_num, "room_change", new_room, subgroup)
    await _render_current_actions(message, state, user)


@router.message(StarostaAction.waiting_link)
async def on_link_input(message: Message, state: FSMContext) -> None:
    """Ввод онлайн-ссылки."""
    user = await get_user(message.from_user.id)
    if not user:
        await state.clear()
        return
    await delete_user_message(message)

    selected = _selected_pair(await state.get_data())
    if not selected:
        await state.set_state(None)
        return
    date_iso, lesson_num, subgroup = selected
    target_date = datetime.date.fromisoformat(date_iso)
    lesson = _find_lesson(user["group_name"], target_date, lesson_num, subgroup)
    link, error = _validate_online_link(message.text)
    if error:
        await _show_starosta_body(
            message,
            state,
            _input_text("Онлайн-занятие", target_date, lesson_num, subgroup, lesson, f"{error}\n\nВставь ссылку."),
            starosta_input_back_kb(),
        )
        return

    await add_override(
        user["group_name"],
        date_iso,
        lesson_num,
        "online",
        new_value=link,
        comment="Онлайн-занятие",
        created_by=message.from_user.id,
        subgroup=subgroup,
    )
    await _send_change_alerts(message.bot, user["group_name"], date_iso, lesson_num, "online", link, subgroup)
    await _render_current_actions(message, state, user)


@router.message(StarostaAction.waiting_note)
async def on_note_input(message: Message, state: FSMContext) -> None:
    """Ввод примечания."""
    user = await get_user(message.from_user.id)
    if not user:
        await state.clear()
        return
    await delete_user_message(message)

    selected = _selected_pair(await state.get_data())
    if not selected:
        await state.set_state(None)
        return
    date_iso, lesson_num, subgroup = selected
    target_date = datetime.date.fromisoformat(date_iso)
    lesson = _find_lesson(user["group_name"], target_date, lesson_num, subgroup)
    note, error = _validate_note(message.text)
    if error:
        await _show_starosta_body(
            message,
            state,
            _input_text("Примечание", target_date, lesson_num, subgroup, lesson, f"{error}\n\nВведи текст примечания."),
            starosta_input_back_kb(),
        )
        return

    await add_override(
        user["group_name"],
        date_iso,
        lesson_num,
        "note",
        new_value=note,
        comment="Примечание",
        created_by=message.from_user.id,
        subgroup=subgroup,
    )
    await _render_current_actions(message, state, user)


async def handle_starosta_back(message: Message, state: FSMContext) -> bool:
    """Совместимость со старой reply-кнопкой Назад."""
    data = await state.get_data()
    if data.get("ui_screen") != "starosta":
        return False
    user = await get_user(message.from_user.id)
    screen = data.get("_starosta_screen")
    if screen == "dates":
        await _replace_with_main_menu(message, state, user)
        return True
    if screen in {"lessons", "actions", "room_input", "online_input", "note_input", "cancel_confirm", "rollback_confirm"}:
        date_iso = data.get("starosta_date")
        if screen == "lessons" or not date_iso:
            await _render_dates(message, state, bool(data.get("starosta_next_week")))
        elif screen == "actions":
            await _render_lessons(message, state, user, str(date_iso))
        else:
            await _render_current_actions(message, state, user)
        return True
    await _replace_with_main_menu(message, state, user)
    return True
