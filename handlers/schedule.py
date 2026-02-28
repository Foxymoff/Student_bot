"""
Обработчик блока «Расписание»: сегодня / завтра / на неделю.
"""

import json
import logging
import datetime
from pathlib import Path

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from config import DATA_DIR, GROUP_FILES
from database import get_user
from keyboards import schedule_period_kb, back_to_menu_kb

logger = logging.getLogger(__name__)
router = Router()

# Русские названия дней недели (Monday=0 … Sunday=6)
WEEKDAY_NAMES: list[str] = [
    "Понедельник", "Вторник", "Среда", "Четверг",
    "Пятница", "Суббота", "Воскресенье",
]

# Эмодзи-номера пар
_NUM_EMOJI: dict[int, str] = {
    0: "0⃣", 1: "1⃣", 2: "2⃣", 3: "3⃣",
    4: "4⃣", 5: "5⃣", 6: "6⃣",
}

# Ключевое слово (lowercase) → эмодзи предмета
_SUBJECT_EMOJI: dict[str, str] = {
    "математик": "📐",
    "информатик": "💻",
    "физик": "🔬",
    "хими": "🧪",
    "биологи": "🌿",
    "литератур": "📖",
    "русский язык": "📝",
    "истори": "📜",
    "обществознани": "📚",
    "иностранный": "🇬🇧",
    "английский": "🇬🇧",
    "физкультур": "🏃",
    "разговоры": "💬",
    "цифров": "⚙️",
    "компьютерн": "🖥",
    "моделирован": "🖥",
    "инженерн": "⚙️",
    "мастерск": "🎨",
    "бизнес": "💼",
    "игр": "🎮",
    "godot": "🎮",
}


def _subject_emoji(subject: str) -> str:
    """Подобрать эмодзи по названию предмета."""
    low = subject.lower()
    for keyword, emoji in _SUBJECT_EMOJI.items():
        if keyword in low:
            return emoji
    return "📖"


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
        target_date = datetime.date.today()
    week_number = target_date.isocalendar()[1]
    return "odd" if week_number % 2 == 0 else "even"


def _format_lesson(lesson: dict) -> str:
    """Форматировать одну пару в текстовую строку."""
    num = lesson.get("num", "?")
    time = lesson.get("time", "")
    subject = lesson.get("subject", "")
    lesson_type = lesson.get("type")
    room = lesson.get("room", "")
    teacher = lesson.get("teacher", "")

    num_em = _NUM_EMOJI.get(num, f"[{num}]")
    subj_em = _subject_emoji(subject)
    type_str = f" ({lesson_type})" if lesson_type else ""

    subgroup = lesson.get("subgroup")
    sg_str = f" · подгр. {subgroup}" if subgroup else ""

    subgroups = lesson.get("subgroups")

    lines = [
        f"{num_em}  {time}",
        f"{subj_em}  {subject}{type_str}{sg_str}",
    ]

    if subgroups:
        for sg in subgroups:
            sg_room = sg.get("room", "?")
            sg_teacher = sg.get("teacher", "?")
            lines.append(f"     📍 подгр. {sg['group']}: {sg_room} · {sg_teacher}")
    else:
        parts = []
        if room:
            parts.append(room)
        if teacher:
            parts.append(teacher)
        if parts:
            lines.append(f"     📍 {' · '.join(parts)}")

    return "\n".join(lines)


def _format_extra(extra: dict) -> str:
    """Форматировать одно доп.занятие."""
    etype = extra.get("type", "")
    time = extra.get("time", "")
    subject = extra.get("subject", "")
    room = extra.get("room", "")
    teacher = extra.get("teacher", "")
    note = extra.get("note", "")

    label = f"{etype}: " if etype else ""
    note_str = f" ({note})" if note else ""

    lines = [f"⭐  {time} · {label}{subject}{note_str}"]

    parts = []
    if room:
        parts.append(room)
    if teacher:
        parts.append(teacher)
    if parts:
        lines.append(f"      📍 {' · '.join(parts)}")

    return "\n".join(lines)


def format_day_schedule(data: dict, day_name: str, week_type: str) -> str:
    """Сформировать текст расписания на один день."""
    week_data = data.get("weeks", {}).get(week_type, {})
    day_data = week_data.get(day_name, {})
    lessons = day_data.get("lessons", [])
    extras = day_data.get("extra", [])

    if not lessons and not extras:
        return f"📌 *{day_name}*\n\nВыходной, отдыхай 🎉"

    lines = [f"📌 *{day_name}*"]

    if lessons:
        lines.append("")
        for i, lesson in enumerate(lessons):
            lines.append(_format_lesson(lesson))
            if i < len(lessons) - 1:
                lines.append("")
    else:
        lines.append("\nПар нет.")

    if extras:
        lines.append("")
        lines.append("┈ ┈ ┈ доп. занятия ┈ ┈ ┈")
        for extra in extras:
            lines.append(_format_extra(extra))
        lines.append("_по желанию_")

    return "\n".join(lines)


def get_schedule_for_date(group_name: str, target_date: datetime.date) -> str:
    """Получить расписание для группы на конкретную дату."""
    data = _load_schedule(group_name)
    if not data:
        return "Расписание для вашей группы не найдено."

    weekday_index = target_date.weekday()  # 0=Пн … 6=Вс
    day_name = WEEKDAY_NAMES[weekday_index]
    week_type = _get_week_type(target_date)
    week_label = "чётная" if week_type == "even" else "нечётная"

    header = f"📆 {target_date.strftime('%d.%m.%Y')} · {week_label} неделя\n"
    body = format_day_schedule(data, day_name, week_type)
    return header + "\n" + body


def get_schedule_for_week(group_name: str) -> str:
    """Получить расписание на текущую неделю (Пн–Вс)."""
    data = _load_schedule(group_name)
    if not data:
        return "Расписание для вашей группы не найдено."

    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    week_type = _get_week_type(today)
    week_label = "чётная" if week_type == "even" else "нечётная"

    parts = [f"📆 *Расписание на неделю* · {week_label}\n"]

    for i in range(7):
        day_date = monday + datetime.timedelta(days=i)
        day_name = WEEKDAY_NAMES[i]
        date_str = day_date.strftime("%d.%m")

        # Подменяем день с датой в заголовке дня
        day_data_raw = data.get("weeks", {}).get(week_type, {}).get(day_name, {})
        lessons = day_data_raw.get("lessons", [])
        extras = day_data_raw.get("extra", [])

        marker = "  ⬅️" if day_date == today else ""

        if not lessons and not extras:
            parts.append(f"━━━━━━━━━━━━━━━━━━")
            parts.append(f"📌 *{day_name}* · {date_str}{marker}")
            parts.append("")
            parts.append("Выходной, отдыхай 🎉")
            parts.append("")
        else:
            parts.append(f"━━━━━━━━━━━━━━━━━━")
            day_text = format_day_schedule(data, day_name, week_type)
            # Заменяем заголовок дня, добавляя дату
            day_text = day_text.replace(
                f"📌 *{day_name}*",
                f"📌 *{day_name}* · {date_str}{marker}",
                1,
            )
            parts.append(day_text)
            parts.append("")

    return "\n".join(parts)


def get_schedule_for_next_week(group_name: str) -> str:
    """Получить расписание на следующую неделю (Пн–Вс)."""
    data = _load_schedule(group_name)
    if not data:
        return "Расписание для вашей группы не найдено."

    today = datetime.date.today()
    # Понедельник следующей недели
    next_monday = today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(weeks=1)
    week_type = _get_week_type(next_monday)
    week_label = "чётная" if week_type == "even" else "нечётная"

    parts = [f"📆 *Расписание на след. неделю* · {week_label}\n"]

    for i in range(7):
        day_date = next_monday + datetime.timedelta(days=i)
        day_name = WEEKDAY_NAMES[i]
        date_str = day_date.strftime("%d.%m")

        day_data_raw = data.get("weeks", {}).get(week_type, {}).get(day_name, {})
        lessons = day_data_raw.get("lessons", [])
        extras = day_data_raw.get("extra", [])

        if not lessons and not extras:
            parts.append(f"━━━━━━━━━━━━━━━━━━")
            parts.append(f"📌 *{day_name}* · {date_str}")
            parts.append("")
            parts.append("Выходной, отдыхай 🎉")
            parts.append("")
        else:
            parts.append(f"━━━━━━━━━━━━━━━━━━")
            day_text = format_day_schedule(data, day_name, week_type)
            day_text = day_text.replace(
                f"📌 *{day_name}*",
                f"📌 *{day_name}* · {date_str}",
                1,
            )
            parts.append(day_text)
            parts.append("")

    return "\n".join(parts)


# ── Хендлеры ──────────────────────────────────────────────


@router.message(F.text == "📅 Расписание")
async def on_schedule_menu(message: Message) -> None:
    """Кнопка «Расписание» в главном меню."""
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся: /start")
        return
    await message.answer(
        "Выбери период:", reply_markup=schedule_period_kb()
    )


@router.callback_query(F.data == "schedule:today")
async def on_schedule_today(callback: CallbackQuery) -> None:
    """Расписание на сегодня."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Сначала зарегистрируйся: /start", show_alert=True)
        return
    today = datetime.date.today()
    text = get_schedule_for_date(user["group_name"], today)
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=back_to_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "schedule:tomorrow")
async def on_schedule_tomorrow(callback: CallbackQuery) -> None:
    """Расписание на завтра."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Сначала зарегистрируйся: /start", show_alert=True)
        return
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    text = get_schedule_for_date(user["group_name"], tomorrow)
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=back_to_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "schedule:week")
async def on_schedule_week(callback: CallbackQuery) -> None:
    """Расписание на неделю."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Сначала зарегистрируйся: /start", show_alert=True)
        return
    text = get_schedule_for_week(user["group_name"])
    # Разбиваем на части, если текст слишком длинный для одного сообщения
    if len(text) > 4000:
        parts = _split_text(text, 4000)
        for i, part in enumerate(parts):
            kb = back_to_menu_kb() if i == len(parts) - 1 else None
            await callback.message.answer(part, parse_mode="Markdown", reply_markup=kb)
    else:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=back_to_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "schedule:next_week")
async def on_schedule_next_week(callback: CallbackQuery) -> None:
    """Расписание на следующую неделю."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Сначала зарегистрируйся: /start", show_alert=True)
        return
    text = get_schedule_for_next_week(user["group_name"])
    if len(text) > 4000:
        parts = _split_text(text, 4000)
        for i, part in enumerate(parts):
            kb = back_to_menu_kb() if i == len(parts) - 1 else None
            await callback.message.answer(part, parse_mode="Markdown", reply_markup=kb)
    else:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=back_to_menu_kb())
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
