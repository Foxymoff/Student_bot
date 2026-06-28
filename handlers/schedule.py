"""
Обработчик блока «Расписание»: краткий / подробный вид, подгруппы, overrides.
"""

import datetime
import html as _html
import json
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import DATA_DIR, GROUP_FILES, GROUPS, ROOM_SHORT, SUBJECT_SHORT, app_today
from database import get_overrides, get_user
from extra_schedule import get_extras_for_date, parse_extra_choices
from handlers.start import push_nav
from keyboards import (
    back_kb,
    other_group_select_kb,
    schedule_collapse_kb,
    schedule_detail_kb,
    schedule_period_reply_kb,
)
from message_style import HTML_PARSE_MODE, register_required_text, title, titled
from ui_messages import (
    clear_ui_messages,
    delete_user_message,
    register_ui_messages,
    replace_ui_messages,
)

logger = logging.getLogger(__name__)
router = Router()

# Русские названия дней недели (Monday=0 … Sunday=6)
WEEKDAY_NAMES: list[str] = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]

# Русские названия месяцев (родительный падеж)
MONTH_NAMES: dict[int, str] = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}

WEEKDAY_NAMES_SHORT: dict[int, str] = {
    0: "понедельник",
    1: "вторник",
    2: "среда",
    3: "четверг",
    4: "пятница",
    5: "суббота",
    6: "воскресенье",
}


class ScheduleNav(StatesGroup):
    group = State()
    period = State()


# ── Утилиты ──────────────────────────────────────────────


def _load_schedule(group_name: str) -> dict:
    """Загрузить JSON расписания для группы."""
    filename = GROUP_FILES.get(group_name)
    if not filename:
        return {}
    path = DATA_DIR / filename
    if not path.exists():
        logger.error("Файл расписания не найден: %s", path)
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _get_week_type(target_date: datetime.date | None = None) -> str:
    """Определить тип недели: 'even' (чётная) или 'odd' (нечётная)."""
    if target_date is None:
        target_date = app_today()
    week_number = target_date.isocalendar()[1]
    return "odd" if week_number % 2 == 0 else "even"


def _short_name(subject: str) -> str:
    """Сокращение длинных названий предметов."""
    return SUBJECT_SHORT.get(subject, subject)


def _short_room(room: str | None) -> str:
    """Сокращение аудиторий."""
    if not room:
        return ""
    return ROOM_SHORT.get(room, room)


def _date_header(target_date: datetime.date) -> str:
    """Красивый заголовок даты: '5 марта · среда'"""
    day = target_date.day
    month = MONTH_NAMES[target_date.month]
    weekday = WEEKDAY_NAMES_SHORT[target_date.weekday()]
    return f"{day} {month} · {weekday}"


def _filter_by_subgroup(lessons: list[dict], sg_inf: int, sg_eng: int) -> list[dict]:
    """Отфильтровать пары по подгруппам пользователя."""
    result = []
    for lesson in lessons:
        subgroup = lesson.get("subgroup")
        if subgroup is not None:
            subject_low = lesson.get("subject", "").lower()
            if "информатик" in subject_low:
                if subgroup != sg_inf:
                    continue
            elif "иностранн" in subject_low or "английск" in subject_low:
                if subgroup != sg_eng:
                    continue
            else:
                if subgroup != sg_inf:
                    continue

        subgroups = lesson.get("subgroups")
        if subgroups:
            subject_low = lesson.get("subject", "").lower()
            if "иностранн" in subject_low or "английск" in subject_low:
                user_sg = sg_eng
            else:
                user_sg = sg_inf
            for sg in subgroups:
                if sg.get("group") == user_sg:
                    lesson = {
                        **lesson,
                        "_sg_group": user_sg,
                        "_sg_room": sg.get("room", ""),
                        "_sg_teacher": sg.get("teacher", ""),
                    }
                    break

        result.append(lesson)
    return result


def _override_subgroup(override: dict) -> int | None:
    """Подгруппа, к которой относится override."""
    value = override.get("subgroup")
    if value in (None, ""):
        return None
    return int(value)


def _lesson_target_subgroup(lesson: dict) -> int | None:
    """Подгруппа уже отфильтрованной пары."""
    value = lesson.get("_sg_group", lesson.get("subgroup"))
    if value in (None, ""):
        return None
    return int(value)


def _lesson_room(lesson: dict) -> str:
    """Текущая аудитория пары с учётом подгруппы."""
    return str(lesson.get("_sg_room") or lesson.get("room") or "")


def _same_room(left: object, right: object) -> bool:
    """Сравнить аудитории без лишних пробелов по краям."""
    return str(left or "").strip() == str(right or "").strip()


def _append_note_marker(base: str, has_note: bool) -> str:
    """Добавить маркер примечания к короткому статусу пары."""
    if not has_note:
        return base
    if not base:
        return "ПР❕"
    separator = "· " if base.endswith(("❕", "❗️")) else " · "
    return f"{base}{separator}ПР❕"


def _lesson_short_status(lesson: dict, include_note: bool = True) -> str:
    """Короткий статус пары для расписания с учетом приоритета изменений."""
    if lesson.get("_cancelled"):
        base = "ОТМ❗️"
    elif lesson.get("_online"):
        base = "ОНЛ❕"
    else:
        room = lesson.get("_sg_room") or lesson.get("room") or ""
        base = _short_room(room)
        if lesson.get("_room_changed"):
            base = f"{base}❕"
    return _append_note_marker(base, include_note and bool(lesson.get("_note")))


def _apply_overrides(lessons: list[dict], overrides: list[dict]) -> list[dict]:
    """Наложить изменения (overrides) на пары."""
    override_map: dict[int, list[dict]] = {}
    for ov in overrides:
        num = ov["lesson_num"]
        override_map.setdefault(num, []).append(ov)

    result = []
    for lesson in lessons:
        num = lesson.get("num")
        if num in override_map:
            lesson = dict(lesson)
            original_room = _lesson_room(lesson)
            for ov in override_map[num]:
                ov_subgroup = _override_subgroup(ov)
                if ov_subgroup is not None and _lesson_target_subgroup(lesson) != ov_subgroup:
                    continue
                ov_type = ov["override_type"]
                if ov_type == "cancel":
                    lesson["_cancelled"] = True
                    lesson["_override_comment"] = ov.get("comment", "Пара отменена")
                elif ov_type == "room_change":
                    new_room = ov.get("new_value", lesson.get("room", ""))
                    lesson["room"] = new_room
                    if lesson.get("_sg_room"):
                        lesson["_sg_room"] = new_room
                    if _same_room(_lesson_room(lesson), original_room):
                        lesson.pop("_original_room", None)
                        lesson.pop("_room_changed", None)
                    else:
                        lesson["_original_room"] = original_room
                        lesson["_override_comment"] = ov.get("comment", "Аудитория изменена")
                        lesson["_room_changed"] = True
                        lesson["_has_override"] = True
                elif ov_type == "online":
                    lesson["_online"] = True
                    lesson["_online_link"] = ov.get("new_value", "")
                    lesson["_override_comment"] = ov.get("comment", "Онлайн")
                    lesson["_has_override"] = True
                elif ov_type == "note":
                    note = str(ov.get("new_value") or ov.get("comment") or "").strip()
                    if note:
                        lesson["_note"] = note
                        lesson["_has_override"] = True
                elif ov_type == "reorder":
                    new_num = int(ov.get("new_value", num))
                    lesson["num"] = new_num
                    lesson["_override_comment"] = ov.get("comment", "Перенос")
                    lesson["_has_override"] = True
        result.append(lesson)
    return result


def _fill_gaps(lessons: list[dict]) -> list[dict]:
    """Заполнить пустые слоты (окна) между парами."""
    if not lessons:
        return []
    nums = [lesson["num"] for lesson in lessons]
    min_num = min(nums)
    max_num = max(nums)
    lesson_map = {lesson["num"]: lesson for lesson in lessons}
    result = []
    for n in range(min_num, max_num + 1):
        if n in lesson_map:
            result.append(lesson_map[n])
        else:
            result.append({"num": n, "_empty": True})
    return result


# ── Форматирование ────────────────────────────────────────


def _esc(text: str) -> str:
    """HTML-экранирование текста."""
    return _html.escape(text)


def _extra_short_parts(extra: dict) -> tuple[str, str, str]:
    """Краткие поля доп. занятия для строки расписания."""
    subject = _short_name(str(extra.get("subject") or extra.get("type") or "Доп. занятие"))
    time_str = str(extra.get("time") or "")
    room = _short_room(extra.get("room") or "")
    return subject, time_str, room


def _format_extra_detailed_blocks(extras: list[dict]) -> list[str]:
    """Форматировать доп. занятия для подробного вида расписания."""
    blocks = []
    for ex in extras:
        subject = _esc(_short_name(str(ex.get("subject") or ex.get("type") or "Доп. занятие")))
        block = [f"+ {subject}"]
        if ex.get("time"):
            time_room = _esc(str(ex["time"]))
            if ex.get("room"):
                time_room += f" · {_esc(_short_room(ex['room']))}"
            block.append(f"  {time_room}")
        elif ex.get("room"):
            block.append(f"  {_esc(_short_room(ex['room']))}")
        if ex.get("teacher"):
            block.append(f"  {_esc(ex['teacher'])}")
        if ex.get("note"):
            block.append(f"  {_esc(ex['note'])}")
        blocks.append("\n".join(block))
    return blocks


def _selected_extra_keys(user: dict, include_extras: bool) -> list[str]:
    """Вернуть выбранные допы, если пользователь включил их в расписание."""
    if not include_extras:
        return []
    return parse_extra_choices(user.get("extra_choices"))


def _extras_enabled(user: dict) -> bool:
    """Включены ли допы внутри основного расписания."""
    return bool(user.get("extra_in_schedule"))


def _is_other_schedule(data: dict) -> bool:
    """Открыто ли расписание другой группы."""
    return data.get("schedule_context") == "other" and bool(data.get("schedule_group_name"))


def _schedule_group_name(user: dict, data: dict) -> str:
    """Группа, расписание которой сейчас показываем."""
    if _is_other_schedule(data):
        return str(data["schedule_group_name"])
    return str(user["group_name"])


def _schedule_extra_keys(user: dict, data: dict) -> list[str]:
    """Допы показываем только для своей группы, где у пользователя есть выбор."""
    if _is_other_schedule(data):
        return []
    return _selected_extra_keys(user, _extras_enabled(user))


def _period_header(label: str, data: dict) -> str:
    """Заголовок выбранного периода с группой для чужого расписания."""
    clean_label = label.rstrip(":")
    if _is_other_schedule(data):
        return f"{title(str(data['schedule_group_name']))}\n\n{_esc(clean_label)}"
    return title(clean_label)


def format_day_short(
    lessons: list[dict],
    target_date: datetime.date,
    sg_inf: int = 1,
    sg_eng: int = 1,
    overrides: list[dict] | None = None,
    extras: list[dict] | None = None,
    compact: bool = False,
) -> str:
    """Краткий вид расписания на день (HTML)."""
    header = f"<b>{_esc(_date_header(target_date))}</b>"

    if not lessons and not extras:
        return f"{header}\nВыходной 🎉"

    filtered = _filter_by_subgroup(lessons, sg_inf, sg_eng)
    if overrides:
        filtered = _apply_overrides(filtered, overrides)
    filtered = _fill_gaps(filtered)

    # Собираем строки: (номер, предмет, аудитория)
    rows: list[tuple[str, str, str]] = []
    for lesson in filtered:
        num = str(lesson.get("num", 0))
        if lesson.get("_empty"):
            rows.append((num, "—", ""))
        elif lesson.get("_cancelled"):
            rows.append((num, "—", _lesson_short_status(lesson)))
        else:
            subj = _short_name(lesson.get("subject", ""))
            rows.append((num, subj, _lesson_short_status(lesson)))

    extra_rows = [_extra_short_parts(extra) for extra in (extras or [])]
    code_lines = []
    if compact:
        # Компактный режим: разделитель · вместо колонок
        for num, subj, room in rows:
            line = f"{num} {_esc(subj)}"
            if room:
                line += f" · {_esc(room)}"
            code_lines.append(line)
        for subj, time_str, room in extra_rows:
            parts = [f"+ {_esc(subj)}"]
            if time_str:
                parts.append(_esc(time_str))
            if room:
                parts.append(_esc(room))
            code_lines.append(" · ".join(parts))
    else:
        # Колонки с выравниванием в моноширинном блоке
        extra_labels = [
            f"{subj} · {time_str}" if time_str else subj for subj, time_str, _room in extra_rows
        ]
        max_subj = max(
            [len(row[1]) for row in rows] + [len(label) for label in extra_labels],
            default=0,
        )
        for num, subj, room in rows:
            padded = subj.ljust(max_subj)
            code_lines.append(f"{num} {_esc(padded)}  {_esc(room)}")
        for label, (_subj, _time_str, room) in zip(extra_labels, extra_rows, strict=False):
            padded = label.ljust(max_subj)
            code_lines.append(f"+ {_esc(padded)}  {_esc(room)}")

    result = f"{header}\n<code>{chr(10).join(code_lines)}</code>"

    return result


def format_day_detailed(
    lessons: list[dict],
    target_date: datetime.date,
    sg_inf: int = 1,
    sg_eng: int = 1,
    overrides: list[dict] | None = None,
    extras: list[dict] | None = None,
) -> str:
    """Подробный вид расписания на день (HTML)."""
    header = f"<b>{_esc(_date_header(target_date))}</b>"

    if not lessons and not extras:
        return f"{header}\nВыходной 🎉"

    filtered = _filter_by_subgroup(lessons, sg_inf, sg_eng)
    if overrides:
        filtered = _apply_overrides(filtered, overrides)

    blocks: list[str] = []
    for lesson in filtered:
        if lesson.get("_empty"):
            continue

        cancelled = lesson.get("_cancelled", False)
        num = str(lesson.get("num", 0))
        subj = _esc(_short_name(lesson.get("subject", "")))
        time_str = _esc(lesson.get("time", "-"))
        room = _esc(_lesson_short_status(lesson, include_note=False) or "-")
        teacher = _esc(lesson.get("_sg_teacher") or lesson.get("teacher") or "-")
        note = lesson.get("_note")

        if cancelled:
            block = [
                f"{num} <s>{subj}</s>",
                f"  {time_str} · {room}",
                f"  {teacher}",
            ]
        else:
            block = [
                f"{num} {subj}",
                f"  {time_str} · {room}",
                f"  {teacher}",
            ]
            online_link = lesson.get("_online_link")
            if online_link:
                block.append(f"  онлайн: {_esc(online_link)}")
        if note:
            block.append(f"  примечание: {_esc(str(note))}")

        blocks.append("\n".join(block))

    if extras:
        blocks.extend(_format_extra_detailed_blocks(extras))

    code_content = "\n\n".join(blocks)
    result = f"{header}\n<code>{code_content}</code>"

    return result


# ── Публичные функции для scheduler ──────────────────────


def get_lessons_for_date(group_name: str, target_date: datetime.date) -> list[dict]:
    """Получить список пар из JSON для группы на дату."""
    data = _load_schedule(group_name)
    if not data:
        return []
    weekday_index = target_date.weekday()
    day_name = WEEKDAY_NAMES[weekday_index]
    week_type = _get_week_type(target_date)
    week_data = data.get("weeks", {}).get(week_type, {})
    day_data = week_data.get(day_name, {})
    return day_data.get("lessons", [])


async def get_schedule_for_date_short(
    group_name: str,
    target_date: datetime.date,
    sg_inf: int = 1,
    sg_eng: int = 1,
    compact: bool = False,
    extra_choices: list[str] | None = None,
) -> str:
    """Получить краткое расписание на дату (с overrides)."""
    lessons = get_lessons_for_date(group_name, target_date)
    overrides = await get_overrides(group_name, target_date.isoformat())
    extras = get_extras_for_date(group_name, target_date, extra_choices or [])
    return format_day_short(lessons, target_date, sg_inf, sg_eng, overrides, extras, compact)


async def get_schedule_for_date_detailed(
    group_name: str,
    target_date: datetime.date,
    sg_inf: int = 1,
    sg_eng: int = 1,
    extra_choices: list[str] | None = None,
) -> str:
    """Получить подробное расписание на дату (с overrides)."""
    lessons = get_lessons_for_date(group_name, target_date)
    overrides = await get_overrides(group_name, target_date.isoformat())
    extras = get_extras_for_date(group_name, target_date, extra_choices or [])
    return format_day_detailed(lessons, target_date, sg_inf, sg_eng, overrides, extras)


# ── Вспомогательная навигация ────────────────────────────


async def _cleanup(message: Message, state: FSMContext) -> None:
    """Удалить сообщение пользователя и предыдущие сообщения бота."""
    await delete_user_message(message)
    data = await state.get_data()
    header_id = data.get("last_bot_msg")
    await clear_ui_messages(message.bot, message.chat.id, state, exclude_ids=[header_id])
    if header_id:
        await register_ui_messages(
            state,
            [header_id],
            screen="schedule_period",
            last_bot_msg=header_id,
            last_schedule_msg=None,
        )


async def _update_period_header(message: Message, state: FSMContext, label: str) -> None:
    """Изменить текст сообщения «Выбери период:» на выбранный период."""
    data = await state.get_data()
    msg_id = data.get("last_bot_msg")
    if msg_id:
        try:
            await message.bot.edit_message_text(
                label,
                message.chat.id,
                msg_id,
                parse_mode=HTML_PARSE_MODE,
            )
        except Exception:
            pass


async def _send_schedule(message: Message, state: FSMContext, text: str, date_iso: str) -> None:
    """Очистить чат, отправить расписание и запомнить ID."""
    await _cleanup(message, state)
    data = await state.get_data()
    header_id = data.get("last_bot_msg")
    sent = await message.answer(text, reply_markup=schedule_detail_kb(date_iso), parse_mode="HTML")
    await register_ui_messages(
        state,
        [header_id, sent.message_id],
        screen="schedule",
        last_bot_msg=header_id,
        last_schedule_msg=sent.message_id,
    )


async def show_other_group_select(message: Message, state: FSMContext) -> None:
    """Показать выбор другой группы с reply-кнопкой Назад."""
    user = await get_user(message.from_user.id)
    if not user:
        sent = await message.answer(register_required_text(), parse_mode=HTML_PARSE_MODE)
        await replace_ui_messages(
            message.bot,
            message.chat.id,
            state,
            [sent.message_id],
            screen="system",
            clear_state=True,
            last_bot_msg=sent.message_id,
        )
        return

    header = await message.answer(
        title("Расписание другой группы"), reply_markup=back_kb(), parse_mode=HTML_PARSE_MODE
    )
    body = await message.answer(
        titled("Группа", "Выбери группу."),
        reply_markup=other_group_select_kb(user["group_name"]),
        parse_mode=HTML_PARSE_MODE,
    )
    await replace_ui_messages(
        message.bot,
        message.chat.id,
        state,
        [header.message_id, body.message_id],
        screen="other_group_select",
        clear_state=True,
        last_bot_msg=header.message_id,
        last_schedule_msg=body.message_id,
    )
    await push_nav(state, "main_menu")
    await state.set_state(ScheduleNav.group)
    await state.update_data(schedule_context="other")


# ── Хендлеры ──────────────────────────────────────────────


@router.message(Command("groups"))
async def cmd_other_groups(message: Message, state: FSMContext) -> None:
    """Команда /groups — посмотреть расписание другой группы."""
    await delete_user_message(message)
    await show_other_group_select(message, state)


@router.callback_query(ScheduleNav.group, F.data.startswith("other_group:"))
async def on_other_group_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбор группы для просмотра чужого расписания."""
    group_name = callback.data.split(":", 1)[1]
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    if group_name == user["group_name"] or group_name not in GROUPS:
        await callback.answer("Выбери другую группу.", show_alert=True)
        return

    sent = await callback.message.answer(
        titled(str(group_name), "Выбери период."),
        reply_markup=schedule_period_reply_kb(),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer()
    await replace_ui_messages(
        callback.bot,
        callback.message.chat.id,
        state,
        [sent.message_id],
        screen="schedule_period",
        clear_state=True,
        last_bot_msg=sent.message_id,
        last_schedule_msg=None,
    )
    await push_nav(state, "other_group_select")
    await state.set_state(ScheduleNav.period)
    await state.update_data(
        schedule_context="other",
        schedule_group_name=group_name,
    )


@router.message(F.text == "📅 Расписание")
async def on_schedule_menu(message: Message, state: FSMContext) -> None:
    """Кнопка «Расписание» в главном меню."""
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer(register_required_text(), parse_mode=HTML_PARSE_MODE)
        return
    await delete_user_message(message)
    sent = await message.answer(
        titled("Расписание", "Выбери период."),
        reply_markup=schedule_period_reply_kb(),
        parse_mode=HTML_PARSE_MODE,
    )
    await replace_ui_messages(
        message.bot,
        message.chat.id,
        state,
        [sent.message_id],
        screen="schedule_period",
        clear_state=True,
        last_bot_msg=sent.message_id,
        last_schedule_msg=None,
    )
    await push_nav(state, "main_menu")
    await state.set_state(ScheduleNav.period)


@router.message(ScheduleNav.period, F.text == "Сегодня")
async def on_schedule_today(message: Message, state: FSMContext) -> None:
    """Расписание на сегодня."""
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer(register_required_text(), parse_mode=HTML_PARSE_MODE)
        return
    data = await state.get_data()
    today = app_today()
    sg_inf = user.get("subgroup_cs", 1) or 1
    sg_eng = user.get("subgroup_en", 1) or 1
    compact = bool(user.get("compact_mode"))
    group_name = _schedule_group_name(user, data)
    extra_keys = _schedule_extra_keys(user, data)
    await push_nav(state, "schedule_period")
    await _update_period_header(message, state, _period_header("Сегодня:", data))
    text = await get_schedule_for_date_short(group_name, today, sg_inf, sg_eng, compact, extra_keys)
    await _send_schedule(message, state, text, today.isoformat())


@router.message(ScheduleNav.period, F.text == "Завтра")
async def on_schedule_tomorrow(message: Message, state: FSMContext) -> None:
    """Расписание на завтра."""
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer(register_required_text(), parse_mode=HTML_PARSE_MODE)
        return
    data = await state.get_data()
    tomorrow = app_today() + datetime.timedelta(days=1)
    sg_inf = user.get("subgroup_cs", 1) or 1
    sg_eng = user.get("subgroup_en", 1) or 1
    compact = bool(user.get("compact_mode"))
    group_name = _schedule_group_name(user, data)
    extra_keys = _schedule_extra_keys(user, data)
    await push_nav(state, "schedule_period")
    await _update_period_header(message, state, _period_header("Завтра:", data))
    text = await get_schedule_for_date_short(
        group_name, tomorrow, sg_inf, sg_eng, compact, extra_keys
    )
    await _send_schedule(message, state, text, tomorrow.isoformat())


@router.message(ScheduleNav.period, F.text == "Эта неделя")
async def on_schedule_week(message: Message, state: FSMContext) -> None:
    """Расписание на текущую неделю."""
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer(register_required_text(), parse_mode=HTML_PARSE_MODE)
        return
    data = await state.get_data()
    today = app_today()
    monday = today - datetime.timedelta(days=today.weekday())
    sg_inf = user.get("subgroup_cs", 1) or 1
    sg_eng = user.get("subgroup_en", 1) or 1
    compact = bool(user.get("compact_mode"))
    group_name = _schedule_group_name(user, data)
    extra_keys = _schedule_extra_keys(user, data)

    await push_nav(state, "schedule_period")
    await _update_period_header(message, state, _period_header("Эта неделя:", data))
    await _cleanup(message, state)
    data = await state.get_data()
    header_id = data.get("last_bot_msg")

    parts = []
    for i in range(7):
        d = monday + datetime.timedelta(days=i)
        text = await get_schedule_for_date_short(group_name, d, sg_inf, sg_eng, compact, extra_keys)
        if d == today:
            text = text.replace("</b>", "  ⬅️</b>", 1)
        parts.append(text)

    full_text = "\n\n".join(parts)
    if len(full_text) > 4000:
        chunks = _split_text(full_text, 4000)
        sent_ids = []
        for chunk in chunks:
            sent = await message.answer(chunk, parse_mode="HTML")
            sent_ids.append(sent.message_id)
        await register_ui_messages(
            state,
            [header_id, *sent_ids],
            screen="schedule",
            last_bot_msg=header_id,
            last_schedule_msg=sent_ids[-1] if sent_ids else None,
        )
    else:
        sent = await message.answer(full_text, parse_mode="HTML")
        await register_ui_messages(
            state,
            [header_id, sent.message_id],
            screen="schedule",
            last_bot_msg=header_id,
            last_schedule_msg=sent.message_id,
        )


@router.message(ScheduleNav.period, F.text == "След. неделя")
async def on_schedule_next_week(message: Message, state: FSMContext) -> None:
    """Расписание на следующую неделю."""
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer(register_required_text(), parse_mode=HTML_PARSE_MODE)
        return
    data = await state.get_data()
    today = app_today()
    next_monday = today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(weeks=1)
    sg_inf = user.get("subgroup_cs", 1) or 1
    sg_eng = user.get("subgroup_en", 1) or 1
    compact = bool(user.get("compact_mode"))
    group_name = _schedule_group_name(user, data)
    extra_keys = _schedule_extra_keys(user, data)

    await push_nav(state, "schedule_period")
    await _update_period_header(message, state, _period_header("След. неделя:", data))
    await _cleanup(message, state)
    data = await state.get_data()
    header_id = data.get("last_bot_msg")

    parts = []
    for i in range(7):
        d = next_monday + datetime.timedelta(days=i)
        text = await get_schedule_for_date_short(group_name, d, sg_inf, sg_eng, compact, extra_keys)
        parts.append(text)

    full_text = "\n\n".join(parts)
    if len(full_text) > 4000:
        chunks = _split_text(full_text, 4000)
        sent_ids = []
        for chunk in chunks:
            sent = await message.answer(chunk, parse_mode="HTML")
            sent_ids.append(sent.message_id)
        await register_ui_messages(
            state,
            [header_id, *sent_ids],
            screen="schedule",
            last_bot_msg=header_id,
            last_schedule_msg=sent_ids[-1] if sent_ids else None,
        )
    else:
        sent = await message.answer(full_text, parse_mode="HTML")
        await register_ui_messages(
            state,
            [header_id, sent.message_id],
            screen="schedule",
            last_bot_msg=header_id,
            last_schedule_msg=sent.message_id,
        )


@router.callback_query(F.data.startswith("schedule_detail:"))
async def on_schedule_detail(callback: CallbackQuery, state: FSMContext) -> None:
    """Развернуть подробный вид (edit_message_text)."""
    date_iso = callback.data.split(":", 1)[1]
    target_date = datetime.date.fromisoformat(date_iso)
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    data = await state.get_data()
    sg_inf = user.get("subgroup_cs", 1) or 1
    sg_eng = user.get("subgroup_en", 1) or 1
    group_name = _schedule_group_name(user, data)
    extra_keys = _schedule_extra_keys(user, data)
    text = await get_schedule_for_date_detailed(group_name, target_date, sg_inf, sg_eng, extra_keys)
    await callback.message.edit_text(
        text, reply_markup=schedule_collapse_kb(date_iso), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("schedule_collapse:"))
async def on_schedule_collapse(callback: CallbackQuery, state: FSMContext) -> None:
    """Свернуть обратно в краткий вид (edit_message_text)."""
    date_iso = callback.data.split(":", 1)[1]
    target_date = datetime.date.fromisoformat(date_iso)
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    data = await state.get_data()
    sg_inf = user.get("subgroup_cs", 1) or 1
    sg_eng = user.get("subgroup_en", 1) or 1
    compact = bool(user.get("compact_mode"))
    group_name = _schedule_group_name(user, data)
    extra_keys = _schedule_extra_keys(user, data)
    text = await get_schedule_for_date_short(
        group_name, target_date, sg_inf, sg_eng, compact, extra_keys
    )
    await callback.message.edit_text(
        text, reply_markup=schedule_detail_kb(date_iso), parse_mode="HTML"
    )
    await callback.answer()


def _split_text(text: str, max_len: int) -> list[str]:
    """Разбить длинный текст на части по пустым строкам."""
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_len:
            parts.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    if current:
        parts.append(current)
    return parts
