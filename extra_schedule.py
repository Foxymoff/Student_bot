"""
Загрузка, выбор и форматирование расписания доп. занятий из extra JSON.
"""

import datetime
import hashlib
import html as _html
import json
import logging
from pathlib import Path

from config import (
    BASE_DIR,
    DATA_DIR,
    EXTRA_DATA_DIR,
    EXTRA_GROUP_FILES,
    ROOM_SHORT,
    SUBJECT_SHORT,
    app_today,
)

logger = logging.getLogger(__name__)

WEEKDAY_NAMES: list[str] = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]

WEEKDAY_NAMES_SHORT: dict[int, str] = {
    0: "понедельник",
    1: "вторник",
    2: "среда",
    3: "четверг",
    4: "пятница",
    5: "суббота",
    6: "воскресенье",
}

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


def _esc(text: str) -> str:
    """HTML-экранирование текста."""
    return _html.escape(str(text))


def _short_name(subject: str) -> str:
    """Сокращение длинных названий предметов."""
    return SUBJECT_SHORT.get(subject, subject)


def _short_room(room: str | None) -> str:
    """Сокращение аудиторий."""
    if not room:
        return ""
    return ROOM_SHORT.get(room, room)


def _date_header(target_date: datetime.date) -> str:
    """Красивый заголовок даты: '5 марта · среда'."""
    return (
        f"{target_date.day} {MONTH_NAMES[target_date.month]}"
        f" · {WEEKDAY_NAMES_SHORT[target_date.weekday()]}"
    )


def _get_week_type(target_date: datetime.date | None = None) -> str:
    """Определить тип недели: 'even' (чётная) или 'odd' (нечётная)."""
    if target_date is None:
        target_date = app_today()
    week_number = target_date.isocalendar()[1]
    return "odd" if week_number % 2 == 0 else "even"


def _extra_path_candidates(filename: str) -> list[Path]:
    """Пути, где может лежать extra JSON."""
    return [
        EXTRA_DATA_DIR / filename,
        DATA_DIR / filename,
        BASE_DIR / filename,
        Path.cwd() / "data" / filename,
        Path.cwd() / filename,
    ]


def _load_extra_schedule(group_name: str) -> dict:
    """Загрузить JSON доп. занятий для группы."""
    filename = EXTRA_GROUP_FILES.get(str(group_name).strip())
    if not filename:
        return {}

    checked: set[Path] = set()
    for path in _extra_path_candidates(filename):
        if path in checked:
            continue
        checked.add(path)
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f)

    logger.error("Файл доп. занятий не найден для группы %s: %s", group_name, filename)
    return {}


def _identity(extra: dict) -> dict[str, str]:
    """Поля, которые определяют выбранный пользователем курс доп. занятия."""
    return {
        "type": str(extra.get("type") or "").strip(),
        "subject": str(extra.get("subject") or "").strip(),
        "teacher": str(extra.get("teacher") or "").strip(),
        "note": str(extra.get("note") or "").strip(),
    }


def make_extra_key(extra: dict) -> str:
    """Стабильный короткий ключ доп. занятия для хранения в профиле."""
    payload = json.dumps(_identity(extra), ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def extra_label(extra: dict) -> str:
    """Человекочитаемая подпись доп. занятия для выбора."""
    subject = _short_name(str(extra.get("subject") or extra.get("type") or "Доп. занятие"))
    parts = [subject]
    if extra.get("note"):
        time_str = str(extra.get("time") or "").split("-", 1)[0].strip()
        parts.append(time_str or str(extra["note"]).replace("группа", "гр."))
    return " · ".join(parts)


def _normalize_extra(extra: dict) -> dict:
    """Добавить служебные поля к доп. занятию."""
    item = dict(extra)
    item["_key"] = make_extra_key(extra)
    item["_label"] = extra_label(extra)
    return item


def parse_extra_choices(value: object) -> list[str]:
    """Разобрать сохранённые ключи доп. занятий из SQLite."""
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return [part for part in value.split(",") if part]
    if not isinstance(parsed, list):
        return []
    return [str(v) for v in parsed]


def get_extra_options(group_name: str) -> list[dict]:
    """Получить уникальный список доп. занятий для выбора пользователем."""
    data = _load_extra_schedule(group_name)
    result: list[dict] = []
    seen: set[str] = set()

    for week_data in data.get("weeks", {}).values():
        for day_data in week_data.values():
            for extra in day_data.get("extra", []):
                item = _normalize_extra(extra)
                key = item["_key"]
                if key in seen:
                    continue
                seen.add(key)
                result.append(item)

    return result


def get_extra_week(
    group_name: str,
    selected_keys: list[str] | set[str],
) -> list[tuple[str, list[dict]]]:
    """Получить цикличное недельное расписание выбранных доп. занятий."""
    if not selected_keys:
        return []

    data = _load_extra_schedule(group_name)
    if not data:
        return []

    weeks = data.get("weeks", {})
    week_data = {}
    for candidate in (weeks.get("even"), weeks.get("odd"), *weeks.values()):
        if not candidate:
            continue
        if any(candidate.get(day, {}).get("extra") for day in WEEKDAY_NAMES):
            week_data = candidate
            break
    selected = set(selected_keys)
    result: list[tuple[str, list[dict]]] = []

    for day_name in WEEKDAY_NAMES:
        raw_extras = week_data.get(day_name, {}).get("extra", [])
        extras = [
            item
            for item in (_normalize_extra(extra) for extra in raw_extras)
            if item["_key"] in selected
        ]
        if extras:
            result.append((day_name, extras))

    return result


def get_extras_for_date(
    group_name: str,
    target_date: datetime.date,
    selected_keys: list[str] | set[str],
) -> list[dict]:
    """Получить выбранные пользователем доп. занятия на дату."""
    if not selected_keys:
        return []

    data = _load_extra_schedule(group_name)
    if not data:
        return []

    week_type = _get_week_type(target_date)
    day_name = WEEKDAY_NAMES[target_date.weekday()]
    selected = set(selected_keys)
    raw_extras = data.get("weeks", {}).get(week_type, {}).get(day_name, {}).get("extra", [])
    return [
        item
        for item in (_normalize_extra(extra) for extra in raw_extras)
        if item["_key"] in selected
    ]


def format_extra_day(
    extras: list[dict],
    target_date: datetime.date,
    has_choices: bool = True,
) -> str:
    """Сформировать расписание доп. занятий на день."""
    header = f"<b>{_esc(_date_header(target_date))}</b>"
    if not has_choices:
        return f"{header}\nТы пока не выбрал доп. занятия.\nИзменить выбор можно через /extra"
    if not extras:
        return f"{header}\nВыбранных доп. занятий нет."

    blocks: list[str] = []
    for extra in extras:
        subject = _esc(_short_name(str(extra.get("subject") or extra.get("type") or "")))
        block = [f"📌 <b>{subject}</b>"]
        if extra.get("time"):
            block.append(f"Время: {_esc(extra['time'])}")
        if extra.get("room"):
            block.append(f"Аудитория: {_esc(_short_room(extra['room']))}")
        if extra.get("teacher"):
            block.append(f"Преподаватель: {_esc(extra['teacher'])}")
        if extra.get("note"):
            block.append(f"Примечание: {_esc(extra['note'])}")
        blocks.append("\n".join(block))

    return f"{header}\n" + "\n\n".join(blocks)


def format_extra_week_short(
    extra_week: list[tuple[str, list[dict]]], has_choices: bool = True
) -> str:
    """Сформировать краткое цикличное расписание выбранных доп. занятий."""
    if not has_choices:
        return "Ты пока не выбрал доп. занятия.\nИзменить выбор можно через /extra"
    if not extra_week:
        return "В выбранных доп. занятиях на неделе нет расписания."

    day_blocks: list[str] = []
    for day_name, extras in extra_week:
        rows = []
        for index, extra in enumerate(extras, start=1):
            subject = _short_name(str(extra.get("subject") or extra.get("type") or ""))
            room = _short_room(extra.get("room") or "")
            row = f"{index} {_esc(subject)}"
            if room:
                row += f"  {_esc(room)}"
            rows.append(row)
        day_blocks.append(f"<b>{_esc(day_name)}:</b>\n<code>{chr(10).join(rows)}</code>")

    return "\n\n".join(day_blocks)


def format_extra_week_detailed(
    extra_week: list[tuple[str, list[dict]]], has_choices: bool = True
) -> str:
    """Сформировать подробное цикличное расписание выбранных доп. занятий."""
    if not has_choices:
        return "Ты пока не выбрал доп. занятия.\nИзменить выбор можно через /extra"
    if not extra_week:
        return "В выбранных доп. занятиях на неделе нет расписания."

    day_blocks: list[str] = []
    for day_name, extras in extra_week:
        blocks = []
        for index, extra in enumerate(extras, start=1):
            subject = _esc(_short_name(str(extra.get("subject") or extra.get("type") or "")))
            time_str = _esc(str(extra.get("time") or "-"))
            room = _esc(_short_room(extra.get("room") or "-"))
            teacher = _esc(str(extra.get("teacher") or "-"))
            blocks.append(
                "\n".join(
                    [
                        f"{index} {subject}",
                        f"  {time_str} · {room}",
                        f"  {teacher}",
                    ]
                )
            )
        day_blocks.append(f"<b>{_esc(day_name)}:</b>\n<code>{(chr(10) * 2).join(blocks)}</code>")

    return "\n\n".join(day_blocks)


def format_extra_week(extra_week: list[tuple[str, list[dict]]], has_choices: bool = True) -> str:
    """Обратная совместимость: по умолчанию краткий вид."""
    return format_extra_week_short(extra_week, has_choices)
