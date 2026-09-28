"""
Обработчик блока «Расписание»: краткий / подробный вид, подгруппы, overrides.
"""

import datetime
import html as _html
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InputRichMessage, Message

from config import (
    APP_TIMEZONE,
    DATA_DIR,
    GROUP_FILES,
    GROUPS,
    PAIR_TIMES,
    ROOM_SHORT,
    SUBJECT_FULL,
    SUBJECT_SHORT,
    app_now,
    app_today,
    is_english_subject,
    rich_enabled,
)
from database import get_overrides, get_user
from extra_schedule import get_extras_for_date, parse_extra_choices
from handlers.start import push_nav
from keyboards import (
    back_kb,
    course_select_kb,
    other_group_select_kb,
    schedule_collapse_kb,
    schedule_detail_kb,
    schedule_nav_kb,
    schedule_period_reply_kb,
)
from message_style import HTML_PARSE_MODE, register_required_text, title, titled
from render_rich import (
    LOOKAHEAD_DAYS,
    WEEKDAY_ABBR,
    Day,
    Lesson,
    NavButton,
    NavRows,
    WeekKind,
    has_lessons,
    needs_upcoming,
    render_day_html,
    render_week_html,
)
from ui_messages import (
    add_ui_messages,
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
    course = State()
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


def _full_name(subject: str) -> str:
    """Полное название предмета для подробного вида (без кодов МДК/цифр)."""
    return SUBJECT_FULL.get(subject, subject)


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
            elif is_english_subject(subject_low):
                if subgroup != sg_eng:
                    continue
            else:
                if subgroup != sg_inf:
                    continue

        subgroups = lesson.get("subgroups")
        if subgroups:
            if is_english_subject(lesson.get("subject", "")):
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


def _added_lesson(ov: dict) -> dict:
    """Синтезировать пару, добавленную старостой на пустой слот."""
    num = int(ov.get("lesson_num") or 0)
    return {
        "num": num,
        "subject": str(ov.get("new_value") or "").strip() or f"Пара {num}",
        # Если для номера пары нет стандартного времени звонков — прочерк,
        # чтобы не висел пустой разделитель.
        "time": PAIR_TIMES.get(num) or "—",
        "_added": True,
    }


def _apply_overrides(lessons: list[dict], overrides: list[dict]) -> list[dict]:
    """Наложить изменения (overrides) на пары."""
    override_map: dict[int, list[dict]] = {}
    for ov in overrides:
        num = ov["lesson_num"]
        override_map.setdefault(num, []).append(ov)

    # Пары, добавленные старостой на пустые слоты (тип "add"), которых нет в JSON.
    existing_nums = {lesson.get("num") for lesson in lessons}
    injected = [
        _added_lesson(ov)
        for ov in overrides
        if ov.get("override_type") == "add" and int(ov.get("lesson_num") or 0) not in existing_nums
    ]
    if injected:
        lessons = [*lessons, *injected]

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
                elif ov_type == "rename":
                    new_subject = str(ov.get("new_value") or "").strip()
                    if new_subject:
                        lesson["subject"] = new_subject
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


def _has_added_override(overrides: list[dict] | None) -> bool:
    """Есть ли среди overrides добавленная старостой пара (тип 'add')."""
    return any(ov.get("override_type") == "add" for ov in (overrides or []))


def _fill_gaps(lessons: list[dict]) -> list[dict]:
    """Заполнить пустые слоты (окна и ведущие пары) прочерками.

    Если день начинается со 2-й пары (или позже), недостающие пары показываем
    начиная с 1-й. «Нулевую» пару (разговоры/классный час) не выдумываем — она
    попадает в вывод только если реально есть в расписании.
    """
    if not lessons:
        return []
    nums = [lesson["num"] for lesson in lessons]
    max_num = max(nums)
    # Пол диапазона: 1-я пара, но если есть «нулевая» — начинаем с неё.
    start = min(min(nums), 1)
    lesson_map = {lesson["num"]: lesson for lesson in lessons}
    result = []
    for n in range(start, max_num + 1):
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

    if not lessons and not extras and not _has_added_override(overrides):
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

    if not lessons and not extras and not _has_added_override(overrides):
        return f"{header}\nВыходной 🎉"

    filtered = _filter_by_subgroup(lessons, sg_inf, sg_eng)
    if overrides:
        filtered = _apply_overrides(filtered, overrides)
    filtered = _fill_gaps(filtered)

    blocks: list[str] = []
    for lesson in filtered:
        if lesson.get("_empty"):
            blocks.append(f"{lesson.get('num', 0)} —")
            continue

        cancelled = lesson.get("_cancelled", False)
        num = str(lesson.get("num", 0))
        subj = _esc(_full_name(lesson.get("subject", "")))
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


# ── Модели для rich-рендера (render_rich.py) ─────────────

_CLOCK_RE = re.compile(r"(\d{1,2}):(\d{2})")


def _parse_times(
    value: object, target_date: datetime.date
) -> tuple[datetime.datetime | None, datetime.datetime | None]:
    """«09:20-10:50» → aware-время начала и конца на дату (конца может не быть)."""
    moments = []
    for hour, minute in _CLOCK_RE.findall(str(value or ""))[:2]:
        if int(hour) > 23 or int(minute) > 59:
            break
        moments.append(
            datetime.datetime.combine(
                target_date, datetime.time(int(hour), int(minute)), tzinfo=APP_TIMEZONE
            )
        )
    start = moments[0] if moments else None
    end = moments[1] if len(moments) > 1 else None
    return start, end


def _rich_lesson(lesson: dict, target_date: datetime.date) -> Lesson:
    """Пара после фильтра подгрупп и overrides → строка rich-расписания."""
    num = lesson.get("num")
    start, end = _parse_times(lesson.get("time") or PAIR_TIMES.get(num), target_date)
    subject = str(lesson.get("subject") or "")
    return Lesson(
        start=start,
        end=end,
        short=_short_name(subject),
        full=_full_name(subject),
        room=_short_room(_lesson_room(lesson)),
        teacher=str(lesson.get("_sg_teacher") or lesson.get("teacher") or ""),
        num=num if isinstance(num, int) else None,
        cancelled=bool(lesson.get("_cancelled")),
        room_changed=bool(lesson.get("_room_changed")),
        online=bool(lesson.get("_online")),
        online_url=str(lesson.get("_online_link") or ""),
        note=str(lesson.get("_note") or ""),
    )


def _rich_extra(extra: dict, target_date: datetime.date) -> Lesson:
    """Выбранное допзанятие → строка rich-расписания."""
    subject = str(extra.get("subject") or extra.get("type") or "Доп. занятие")
    start, end = _parse_times(extra.get("time"), target_date)
    return Lesson(
        start=start,
        end=end,
        short=_short_name(subject),
        full=_full_name(subject),
        room=_short_room(extra.get("room") or ""),
        teacher=str(extra.get("teacher") or ""),
        extra=True,
        note=str(extra.get("note") or ""),
    )


def build_rich_day(
    lessons: list[dict],
    target_date: datetime.date,
    sg_inf: int = 1,
    sg_eng: int = 1,
    overrides: list[dict] | None = None,
    extras: list[dict] | None = None,
) -> Day:
    """Собрать день для rich-рендера: та же фильтрация и overrides, что у классики.

    Пустые слоты (окна) не выводим — время начала и так показывает порядок.
    """
    filtered = _filter_by_subgroup(lessons, sg_inf, sg_eng)
    if overrides:
        filtered = _apply_overrides(filtered, overrides)
    rows = [_rich_lesson(lesson, target_date) for lesson in filtered]
    rows += [_rich_extra(extra, target_date) for extra in extras or []]
    rows.sort(key=lambda row: (row.start is None, row.start.timestamp() if row.start else 0))
    return Day(date=target_date, lessons=tuple(rows))


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


# ── Отправка: новый (rich) или классический вид ──────────

ClassicMessages = list[tuple[str, InlineKeyboardMarkup | None]]
RichView = Callable[[], Awaitable[str]]
ClassicView = Callable[[], Awaitable[ClassicMessages]]

LEGACY_BUTTON_TEXT = "Расписание обновилось — присылаю его в новом виде"


async def get_rich_day(
    group_name: str,
    target_date: datetime.date,
    sg_inf: int = 1,
    sg_eng: int = 1,
    extra_choices: list[str] | None = None,
) -> Day:
    """День для rich-рендера (с overrides и выбранными допами)."""
    lessons = get_lessons_for_date(group_name, target_date)
    overrides = await get_overrides(group_name, target_date.isoformat())
    extras = get_extras_for_date(group_name, target_date, extra_choices or [])
    return build_rich_day(lessons, target_date, sg_inf, sg_eng, overrides, extras)


async def find_upcoming_day(
    group_name: str,
    after: datetime.date,
    sg_inf: int = 1,
    sg_eng: int = 1,
    extra_choices: list[str] | None = None,
) -> Day | None:
    """Ближайший учебный день после даты (не дальше LOOKAHEAD_DAYS)."""
    for offset in range(1, LOOKAHEAD_DAYS + 1):
        target_date = after + datetime.timedelta(days=offset)
        day = await get_rich_day(group_name, target_date, sg_inf, sg_eng, extra_choices)
        if has_lessons(day):
            return day
    return None


async def render_rich_day(
    group_name: str,
    target_date: datetime.date,
    sg_inf: int = 1,
    sg_eng: int = 1,
    extra_choices: list[str] | None = None,
    *,
    lead: str | None = None,
    nav: NavRows = (),
    detailed: bool = False,
) -> str:
    """Rich HTML на день; ближайший учебный день ищем, только если он нужен."""
    now = app_now()
    day = await get_rich_day(group_name, target_date, sg_inf, sg_eng, extra_choices)
    upcoming = None
    if needs_upcoming(day, now):
        upcoming = await find_upcoming_day(group_name, target_date, sg_inf, sg_eng, extra_choices)
    return render_day_html(
        day, now=now, group=group_name, upcoming=upcoming, lead=lead, nav=nav, detailed=detailed
    )


async def render_rich_week(
    group_name: str,
    monday: datetime.date,
    sg_inf: int,
    sg_eng: int,
    extra_choices: list[str] | None,
    which: WeekKind,
    nav: NavRows = (),
) -> str:
    """Rich HTML на неделю с понедельника."""
    days = [
        await get_rich_day(
            group_name, monday + datetime.timedelta(days=i), sg_inf, sg_eng, extra_choices
        )
        for i in range(7)
    ]
    return render_week_html(days, now=app_now(), group=group_name, which=which, nav=nav)


async def classic_week_messages(
    group_name: str,
    monday: datetime.date,
    sg_inf: int,
    sg_eng: int,
    compact: bool,
    extra_choices: list[str] | None,
) -> ClassicMessages:
    """Классическая неделя: дни через пустую строку, при превышении лимита — частями."""
    today = app_today()
    parts = []
    for i in range(7):
        d = monday + datetime.timedelta(days=i)
        text = await get_schedule_for_date_short(
            group_name, d, sg_inf, sg_eng, compact, extra_choices
        )
        if d == today:
            text = text.replace("</b>", "  ⬅️</b>", 1)
        parts.append(text)

    full_text = "\n\n".join(parts)
    chunks = _split_text(full_text, 4000) if len(full_text) > 4000 else [full_text]
    return [(chunk, None) for chunk in chunks]


async def send_schedule(
    bot: Bot,
    chat_id: int,
    user: dict | None,
    *,
    rich: RichView,
    classic: ClassicView,
    rich_markup: InlineKeyboardMarkup | None = None,
    disable_notification: bool | None = None,
) -> list[Message]:
    """Отправить расписание в новом виде, а если он выключен или отклонён — в классическом.

    Откатываемся только на TelegramBadRequest (сервер не принял разметку); сетевые
    и прочие ошибки пробрасываем. rich_markup — навигация клавиатурой (NAV_IN_BODY=False).
    """
    if rich_enabled(user):
        html = await rich()
        try:
            sent = await bot.send_rich_message(
                chat_id=chat_id,
                rich_message=InputRichMessage(html=html, skip_entity_detection=True),
                reply_markup=rich_markup,
                disable_notification=disable_notification,
            )
            return [sent]
        except TelegramBadRequest as exc:
            logger.error(
                "sendRichMessage отклонён (%s), отправляю классический вид. HTML: %s",
                exc,
                html[:500],
            )
    return [
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=markup,
            parse_mode=HTML_PARSE_MODE,
            disable_notification=disable_notification,
        )
        for text, markup in await classic()
    ]


# ── Живое сообщение: навигация по дням и неделям ─────────

# Кнопки навигации в теле rich-сообщения (<tg-button-row>). False — inline-клавиатурой
# под сообщением (на случай клиентов, которые не показывают кнопки в теле).
NAV_IN_BODY = True
NAV_PREFIX = "rs"
NAV_DAY = "d"  # день, краткая таблица
NAV_DAY_FULL = "f"  # день, подробная таблица
NAV_WEEK = "w"
NAV_KINDS = (NAV_DAY, NAV_DAY_FULL, NAV_WEEK)
CLASSIC_NAV_TEXT = "Включён классический вид — присылаю расписание обычным сообщением"


def nav_data(kind: str, target_date: datetime.date, group_name: str) -> str:
    """callback_data навигации: rs:d:2026-09-25:ИСП-25-2 (до 64 байт)."""
    return f"{NAV_PREFIX}:{kind}:{target_date.isoformat()}:{group_name}"


def parse_nav_data(data: str) -> tuple[str, datetime.date, str] | None:
    """Разобрать callback_data навигации; None — устаревшая или чужая кнопка."""
    parts = data.split(":", 3)
    if len(parts) != 4 or parts[0] != NAV_PREFIX or parts[1] not in NAV_KINDS:
        return None
    try:
        target_date = datetime.date.fromisoformat(parts[2])
    except ValueError:
        return None
    if parts[3] not in GROUPS:
        return None
    return parts[1], target_date, parts[3]


def _nav_day_label(target_date: datetime.date) -> str:
    """«Чт, 24»."""
    return f"{WEEKDAY_ABBR[target_date.weekday()]}, {target_date.day}"


def day_nav(
    target_date: datetime.date, group_name: str, today: datetime.date, *, detailed: bool = False
) -> list[list[NavButton]]:
    """‹ вчера | Сегодня | завтра ›, ниже — «Вся неделя» и «Подробнее» / «Кратко».

    Листание дней сохраняет вид таблицы (краткий или подробный).
    """
    kind = NAV_DAY_FULL if detailed else NAV_DAY
    prev_day = target_date - datetime.timedelta(days=1)
    next_day = target_date + datetime.timedelta(days=1)
    toggle = (
        NavButton("Кратко", nav_data(NAV_DAY, target_date, group_name))
        if detailed
        else NavButton("Подробнее", nav_data(NAV_DAY_FULL, target_date, group_name))
    )
    return [
        [
            NavButton(f"‹ {_nav_day_label(prev_day)}", nav_data(kind, prev_day, group_name)),
            NavButton("Сегодня", nav_data(kind, today, group_name), active=target_date == today),
            NavButton(f"{_nav_day_label(next_day)} ›", nav_data(kind, next_day, group_name)),
        ],
        [NavButton("Вся неделя", nav_data(NAV_WEEK, _monday(target_date), group_name)), toggle],
    ]


def _monday(target_date: datetime.date) -> datetime.date:
    return target_date - datetime.timedelta(days=target_date.weekday())


def week_nav(monday: datetime.date, group_name: str, today: datetime.date) -> list[list[NavButton]]:
    """‹ Пред. | Эта неделя | След. ›, ниже — «Ко дню» (сегодня или понедельник недели)."""
    this_monday = _monday(today)
    week = datetime.timedelta(weeks=1)
    day = today if monday == this_monday else monday
    return [
        [
            NavButton("‹ Пред.", nav_data(NAV_WEEK, monday - week, group_name)),
            NavButton(
                "Эта неделя",
                nav_data(NAV_WEEK, this_monday, group_name),
                active=monday == this_monday,
            ),
            NavButton("След. ›", nav_data(NAV_WEEK, monday + week, group_name)),
        ],
        [NavButton("Ко дню", nav_data(NAV_DAY, day, group_name))],
    ]


def _week_kind(monday: datetime.date, today: datetime.date) -> WeekKind:
    this_monday = _monday(today)
    if monday == this_monday:
        return "this"
    return "next" if monday > this_monday else "past"


@dataclass(frozen=True)
class ScheduleViews:
    """Расписание в обоих видах; считается только тот, что отправится."""

    rich: RichView
    classic: ClassicView
    markup: InlineKeyboardMarkup | None = None  # навигация клавиатурой (NAV_IN_BODY=False)


def _nav_parts(rows: NavRows) -> tuple[NavRows, InlineKeyboardMarkup | None]:
    """Кнопки в тело сообщения или в inline-клавиатуру — по NAV_IN_BODY."""
    if NAV_IN_BODY:
        return rows, None
    return [], schedule_nav_kb(rows)


def _viewer(user: dict, group_name: str) -> tuple[int, int, bool, list[str]]:
    """Подгруппы, компактный режим и допы пользователя; допы — только для своей группы."""
    sg_inf, sg_eng = _subgroups(user)
    compact = bool(user.get("compact_mode"))
    own = group_name == user.get("group_name")
    extra_keys = _selected_extra_keys(user, _extras_enabled(user)) if own else []
    return sg_inf, sg_eng, compact, extra_keys


def day_views(
    user: dict,
    group_name: str,
    target_date: datetime.date,
    *,
    detailed: bool = False,
    lead: str | None = None,
    classic_header: str | None = None,
) -> ScheduleViews:
    """День: rich с навигацией (краткий или подробный) или классика с «Подробнее»."""
    sg_inf, sg_eng, compact, extra_keys = _viewer(user, group_name)
    nav, markup = _nav_parts(day_nav(target_date, group_name, app_today(), detailed=detailed))

    async def rich() -> str:
        return await render_rich_day(
            group_name,
            target_date,
            sg_inf,
            sg_eng,
            extra_keys,
            lead=lead,
            nav=nav,
            detailed=detailed,
        )

    async def classic() -> ClassicMessages:
        text = await get_schedule_for_date_short(
            group_name, target_date, sg_inf, sg_eng, compact, extra_keys
        )
        if classic_header:
            text = f"{classic_header}\n\n{text}"
        return [(text, schedule_detail_kb(target_date.isoformat()))]

    return ScheduleViews(rich, classic, markup)


def week_views(user: dict, group_name: str, monday: datetime.date) -> ScheduleViews:
    """Неделя с понедельника: rich-аккордеон с навигацией или классика."""
    sg_inf, sg_eng, compact, extra_keys = _viewer(user, group_name)
    today = app_today()
    nav, markup = _nav_parts(week_nav(monday, group_name, today))
    which = _week_kind(monday, today)

    async def rich() -> str:
        return await render_rich_week(
            group_name, monday, sg_inf, sg_eng, extra_keys, which, nav=nav
        )

    async def classic() -> ClassicMessages:
        return await classic_week_messages(group_name, monday, sg_inf, sg_eng, compact, extra_keys)

    return ScheduleViews(rich, classic, markup)


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
            # Только именованные аргументы: в aiogram 3.x второй позиционный —
            # business_connection_id, а не chat_id.
            await message.bot.edit_message_text(
                label,
                chat_id=message.chat.id,
                message_id=msg_id,
                parse_mode=HTML_PARSE_MODE,
            )
        except Exception:
            pass


def _subgroups(user: dict) -> tuple[int, int]:
    """Подгруппы пользователя: информатика, английский."""
    return user.get("subgroup_cs", 1) or 1, user.get("subgroup_en", 1) or 1


def _day_views(user: dict, data: dict, target_date: datetime.date) -> ScheduleViews:
    """День для группы из текущего экрана (своя или чужая)."""
    return day_views(user, _schedule_group_name(user, data), target_date)


def _week_views(user: dict, data: dict, monday: datetime.date) -> ScheduleViews:
    """Неделя для группы из текущего экрана (своя или чужая)."""
    return week_views(user, _schedule_group_name(user, data), monday)


async def _send_views(bot: Bot, chat_id: int, user: dict, views: ScheduleViews) -> list[Message]:
    return await send_schedule(
        bot, chat_id, user, rich=views.rich, classic=views.classic, rich_markup=views.markup
    )


async def _send_screen(
    message: Message,
    state: FSMContext,
    user: dict,
    views: ScheduleViews,
) -> None:
    """Очистить чат, отправить расписание и запомнить ID."""
    await _cleanup(message, state)
    data = await state.get_data()
    header_id = data.get("last_bot_msg")
    sent = await _send_views(message.bot, message.chat.id, user, views)
    await register_ui_messages(
        state,
        [header_id, *(msg.message_id for msg in sent)],
        screen="schedule",
        last_bot_msg=header_id,
        last_schedule_msg=sent[-1].message_id if sent else None,
    )


async def _open_live_schedule(
    message: Message, state: FSMContext, user: dict, group_name: str, *, other: bool = False
) -> None:
    """Новый вид: сразу сегодняшний день живым сообщением, внизу только «⬅️ Назад».

    Периоды переключаются кнопками в самом сообщении; клавиатура выбора периода
    нужна только классическому виду.
    """
    context = {"schedule_context": "other", "schedule_group_name": group_name} if other else {}
    header = await message.answer(
        _period_header("Расписание:", context), reply_markup=back_kb(), parse_mode=HTML_PARSE_MODE
    )
    views = day_views(user, group_name, app_today())
    sent = await _send_views(message.bot, message.chat.id, user, views)
    await replace_ui_messages(
        message.bot,
        message.chat.id,
        state,
        [header.message_id, *(msg.message_id for msg in sent)],
        screen="schedule",
        clear_state=True,
        last_bot_msg=header.message_id,
        last_schedule_msg=sent[-1].message_id if sent else None,
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
        titled("Курс", "Выбери курс."),
        reply_markup=course_select_kb("other_course"),
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
    await state.set_state(ScheduleNav.course)
    await state.update_data(schedule_context="other")


# ── Хендлеры ──────────────────────────────────────────────


@router.message(Command("groups"))
async def cmd_other_groups(message: Message, state: FSMContext) -> None:
    """Команда /groups — посмотреть расписание другой группы."""
    await delete_user_message(message)
    await show_other_group_select(message, state)


@router.callback_query(ScheduleNav.course, F.data.startswith("other_course:"))
async def on_other_course_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Курс выбран → показываем группы этого курса для чужого расписания."""
    course = callback.data.split(":", 1)[1]
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    await state.update_data(other_course=course)
    await state.set_state(ScheduleNav.group)
    await callback.message.edit_text(
        titled("Группа", f"Курс · {course}\n\nВыбери группу."),
        reply_markup=other_group_select_kb(user["group_name"], course=course),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer()


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

    await callback.answer()
    if rich_enabled(user):
        await _open_live_schedule(callback.message, state, user, group_name, other=True)
    else:
        sent = await callback.message.answer(
            titled(str(group_name), "Выбери период."),
            reply_markup=schedule_period_reply_kb(),
            parse_mode=HTML_PARSE_MODE,
        )
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
    if rich_enabled(user):
        await _open_live_schedule(message, state, user, user["group_name"])
    else:
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
    await push_nav(state, "schedule_period")
    await _update_period_header(message, state, _period_header("Сегодня:", data))
    await _send_screen(message, state, user, _day_views(user, data, app_today()))


@router.message(ScheduleNav.period, F.text == "Завтра")
async def on_schedule_tomorrow(message: Message, state: FSMContext) -> None:
    """Расписание на завтра."""
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer(register_required_text(), parse_mode=HTML_PARSE_MODE)
        return
    data = await state.get_data()
    tomorrow = app_today() + datetime.timedelta(days=1)
    await push_nav(state, "schedule_period")
    await _update_period_header(message, state, _period_header("Завтра:", data))
    await _send_screen(message, state, user, _day_views(user, data, tomorrow))


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
    await push_nav(state, "schedule_period")
    await _update_period_header(message, state, _period_header("Эта неделя:", data))
    await _send_screen(message, state, user, _week_views(user, data, monday))


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
    await push_nav(state, "schedule_period")
    await _update_period_header(message, state, _period_header("След. неделя:", data))
    await _send_screen(message, state, user, _week_views(user, data, next_monday))


async def _answer_legacy_button(
    callback: CallbackQuery, state: FSMContext, user: dict, date_iso: str, *, detailed: bool
) -> None:
    """«Подробнее / Свернуть» на старом сообщении у пользователя с новым видом.

    Старое сообщение не конвертируем: снимаем с него кнопки и присылаем новое.
    """
    await callback.answer(LEGACY_BUTTON_TEXT)
    old = callback.message
    if old is None:
        return
    try:
        await callback.bot.edit_message_reply_markup(
            chat_id=old.chat.id, message_id=old.message_id, reply_markup=None
        )
    except TelegramBadRequest:
        pass  # кнопок уже нет или сообщение слишком старое
    try:
        target_date = datetime.date.fromisoformat(date_iso)
    except ValueError:
        return
    data = await state.get_data()
    views = day_views(user, _schedule_group_name(user, data), target_date, detailed=detailed)
    sent = await _send_views(callback.bot, old.chat.id, user, views)
    await add_ui_messages(state, [msg.message_id for msg in sent])


@router.callback_query(F.data.startswith("schedule_detail:"))
async def on_schedule_detail(callback: CallbackQuery, state: FSMContext) -> None:
    """Развернуть подробный вид (классика) или ответить на старую кнопку (новый вид)."""
    date_iso = callback.data.split(":", 1)[1]
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    if rich_enabled(user):
        await _answer_legacy_button(callback, state, user, date_iso, detailed=True)
        return
    target_date = datetime.date.fromisoformat(date_iso)
    data = await state.get_data()
    sg_inf, sg_eng = _subgroups(user)
    group_name = _schedule_group_name(user, data)
    extra_keys = _schedule_extra_keys(user, data)
    text = await get_schedule_for_date_detailed(group_name, target_date, sg_inf, sg_eng, extra_keys)
    await callback.message.edit_text(
        text, reply_markup=schedule_collapse_kb(date_iso), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("schedule_collapse:"))
async def on_schedule_collapse(callback: CallbackQuery, state: FSMContext) -> None:
    """Свернуть в краткий вид (классика) или ответить на старую кнопку (новый вид)."""
    date_iso = callback.data.split(":", 1)[1]
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    if rich_enabled(user):
        await _answer_legacy_button(callback, state, user, date_iso, detailed=False)
        return
    target_date = datetime.date.fromisoformat(date_iso)
    data = await state.get_data()
    sg_inf, sg_eng = _subgroups(user)
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


@router.callback_query(F.data.startswith(f"{NAV_PREFIX}:"))
async def on_schedule_nav(callback: CallbackQuery, state: FSMContext) -> None:
    """Навигация в живом сообщении: перерисовать день или неделю на месте."""
    parsed = parse_nav_data(callback.data)
    if parsed is None:
        await callback.answer("Кнопка устарела — открой расписание заново")
        return
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    kind, target_date, group_name = parsed
    if kind == NAV_WEEK:
        views = week_views(user, group_name, _monday(target_date))
    else:
        views = day_views(user, group_name, target_date, detailed=kind == NAV_DAY_FULL)
    old = callback.message
    if old is None:
        await callback.answer("Сообщение недоступно — открой расписание заново")
        return

    if not rich_enabled(user):
        # Переключился на классику после отправки: rich не трогаем, присылаем обычное.
        await callback.answer(CLASSIC_NAV_TEXT)
        sent = await _send_views(callback.bot, old.chat.id, user, views)
        await add_ui_messages(state, [msg.message_id for msg in sent])
        return

    html = await views.rich()
    try:
        await callback.bot.edit_message_text(
            chat_id=old.chat.id,
            message_id=old.message_id,
            rich_message=InputRichMessage(html=html, skip_entity_detection=True),
            reply_markup=views.markup,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            await callback.answer("Расписание актуально")
            return
        logger.warning("Не удалось обновить расписание на месте (%s), отправляю новым", exc)
        await callback.answer()

        async def same_html() -> str:
            return html

        sent = await send_schedule(
            callback.bot,
            old.chat.id,
            user,
            rich=same_html,
            classic=views.classic,
            rich_markup=views.markup,
        )
        await add_ui_messages(state, [msg.message_id for msg in sent])
        return

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
