"""
Загрузка и выбор доп. занятий из extra JSON (показываются в основном расписании).
"""

import datetime
import hashlib
import json
import logging
from pathlib import Path

from config import (
    BASE_DIR,
    DATA_DIR,
    EXTRA_DATA_DIR,
    EXTRA_GROUP_FILES,
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


def _short_name(subject: str) -> str:
    """Сокращение длинных названий предметов."""
    return SUBJECT_SHORT.get(subject, subject)


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
        return []
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
