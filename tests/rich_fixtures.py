"""Фикстуры rich-расписания в формате data/*.json (копия ИСП-25-2 на сентябрь 2026).

Копия, а не чтение data/: golden-снапшоты не должны меняться при правке расписания.
"""

import datetime
from collections.abc import Callable

import render_rich
from config import APP_TIMEZONE
from handlers import schedule
from render_rich import Day, render_day_html, render_week_html

GROUP = "ИСП-25-2"


def at(day: int, hour: int, minute: int, month: int = 9) -> datetime.datetime:
    """Момент 2026-{month}-{day} HH:MM по Москве."""
    return datetime.datetime(2026, month, day, hour, minute, tzinfo=APP_TIMEZONE)


def _lesson(num: int, subject: str, room: str | None, teacher: str | None, **extra) -> dict:
    return {
        "num": num,
        "time": schedule.PAIR_TIMES[num],
        "subject": subject,
        "type": None,
        "room": room,
        "teacher": teacher,
        **extra,
    }


MDK_01 = "МДК 04.01. Внедр. и подд. комп. сист."
MDK_02 = "МДК 04.02 Обесп. кач. функц. комп. сист."
DISCRETE = "Дискр. матем. с эл. мат. лог."
ARCH = "Арх. апп. Средств"
ALGO = "Осн. алг. и прогр."
INFO_TECH = "Ин. тех. / Адап. ин. тех. в проф. д."
ENGLISH_SUBGROUPS = [
    {"group": 1, "room": "112", "teacher": "Юсупова Л.Р."},
    {"group": 2, "room": "420", "teacher": "Шарафутдинова А.И."},
]

# Чётная неделя (ключ "even") по дням недели: Пн=0 … Вс=6.
EVEN_WEEK: dict[int, list[dict]] = {
    0: [
        _lesson(1, MDK_01, "501", "Гинзбург М.П."),
        _lesson(2, DISCRETE, "420", "Жеколдина Р.Р."),
        _lesson(3, ARCH, "501", "Гинзбург М.П."),
    ],
    1: [
        _lesson(1, ARCH, "420", "Гинзбург М.П."),
        _lesson(2, MDK_02, "501", "Павлович Е.М."),
        _lesson(3, "Ин. яз. в проф. деят.", None, None, subgroups=ENGLISH_SUBGROUPS),
    ],
    2: [
        _lesson(1, ALGO, "501", "Павлович Е.М."),
        _lesson(2, MDK_01, "420", "Гинзбург М.П."),
        _lesson(3, "Физ. культ.", "Спорткомплекс", "Галимова А.А."),
    ],
    3: [
        _lesson(1, ALGO, "501", "Павлович Е.М."),
        _lesson(2, "Числ. Методы", "421", "Жеколдина Р.Р."),
        _lesson(3, "Эл. высш. матем.", "421", "Жеколдина Р.Р."),
        _lesson(4, DISCRETE, "421", "Жеколдина Р.Р."),
    ],
    # Эталонный день: пятница, 25 сентября 2026.
    4: [
        _lesson(1, MDK_02, "501", "Павлович Е.М."),
        _lesson(2, "История", "Конференц-зал", "Хайруллина Д.Х."),
        _lesson(3, INFO_TECH, "Конференц-зал", "Павлович Е.М."),
    ],
    5: [_lesson(2, MDK_01, "501", "Гинзбург М.П.")],
    6: [],
}

# Нечётная неделя (ключ "odd").
ODD_WEEK: dict[int, list[dict]] = {
    **EVEN_WEEK,
    2: [*EVEN_WEEK[2], _lesson(4, "КУРАТОРСКИЙ ЧАС", "421", "Русскова О.Б.")],
    4: [
        _lesson(1, ALGO, "501", "Павлович Е.М."),
        _lesson(2, INFO_TECH, "501", "Павлович Е.М."),
        _lesson(3, "История", "112", "Хайруллина Д.Х."),
    ],
}

UNITY_EXTRA = {
    "type": "Доп.занятие",
    "time": "16:50-18:20",
    "subject": "Разработка игр на движке UNITY",
    "room": "501",
    "teacher": "Павлович Е.М.",
    "note": "группа 1",
}


def lessons_for(date: datetime.date) -> list[dict]:
    """Пары на дату по той же чётности, что и в боте."""
    week = EVEN_WEEK if schedule._get_week_type(date) == "even" else ODD_WEEK
    return [dict(lesson) for lesson in week[date.weekday()]]


def day(
    date: datetime.date,
    *,
    overrides: list[dict] | None = None,
    extras: list[dict] | None = None,
) -> Day:
    return schedule.build_rich_day(
        lessons_for(date), date, sg_inf=1, sg_eng=1, overrides=overrides, extras=extras
    )


def week(monday: datetime.date) -> list[Day]:
    return [day(monday + datetime.timedelta(days=i)) for i in range(7)]


def upcoming(after: datetime.date) -> Day | None:
    """Ближайший учебный день после даты — как ищет бот."""
    for offset in range(1, 15):
        candidate = day(after + datetime.timedelta(days=offset))
        if any(not lesson.cancelled for lesson in candidate.lessons):
            return candidate
    return None


# ── Случаи для golden-снапшотов и scripts/rich_preview.py ─


FRIDAY = datetime.date(2026, 9, 25)
SATURDAY = datetime.date(2026, 9, 26)
SUNDAY = datetime.date(2026, 9, 27)
MONDAY = datetime.date(2026, 9, 21)

CHANGES = [
    {"lesson_num": 1, "subgroup": None, "override_type": "cancel"},
    {"lesson_num": 2, "subgroup": None, "override_type": "room_change", "new_value": "420"},
    {"lesson_num": 2, "subgroup": None, "override_type": "note", "new_value": "Принести ноутбук"},
    {
        "lesson_num": 3,
        "subgroup": None,
        "override_type": "online",
        "new_value": "https://meet.example.com/a?b=1&c=2",
    },
]
# Староста переименовал пару и добавил пару на пустой слот (4-я, 15:10).
ADDED_AND_RENAMED = [
    {"lesson_num": 2, "subgroup": None, "override_type": "rename", "new_value": "История России"},
    {"lesson_num": 4, "subgroup": None, "override_type": "add", "new_value": "Пересдача"},
]
ALL_CANCELLED = [
    {"lesson_num": n, "subgroup": None, "override_type": "cancel"} for n in range(1, 4)
]


def day_html(
    date: datetime.date, now: datetime.datetime, *, nav=(), detailed: bool = False, **kwargs
) -> str:
    """День так же, как собирает бот: с ближайшим учебным днём, если он нужен."""
    target = day(date, **kwargs)
    nearest = upcoming(date) if render_rich.needs_upcoming(target, now) else None
    return render_day_html(
        target, now=now, group=GROUP, upcoming=nearest, nav=nav, detailed=detailed
    )


def today_html(now: datetime.datetime, *, detailed: bool = False) -> str:
    return day_html(now.date(), now, detailed=detailed)


def week_html(monday: datetime.date, now: datetime.datetime, which: str, nav=()) -> str:
    return render_week_html(week(monday), now=now, group=GROUP, which=which, nav=nav)


def _full(date: datetime.date, now: datetime.datetime, **kwargs) -> str:
    return day_html(date, now, detailed=True, **kwargs)


CASES: dict[str, Callable[[], str]] = {
    # Краткий вид: номер пары | короткое название | аудитория.
    "day_today_before_first": lambda: today_html(at(25, 1, 22)),
    "day_today_second_pair": lambda: today_html(at(25, 11, 30)),
    "day_today_break": lambda: today_html(at(25, 10, 55)),
    "day_today_after_last": lambda: today_html(at(25, 16, 0)),
    "day_tomorrow": lambda: day_html(FRIDAY, at(24, 20, 0)),
    "day_no_pairs": lambda: day_html(SUNDAY, at(26, 18, 0)),
    "day_one_pair": lambda: day_html(SATURDAY, at(25, 20, 0)),
    "day_with_extra": lambda: day_html(FRIDAY, at(25, 1, 22), extras=[UNITY_EXTRA]),
    "day_with_changes": lambda: day_html(FRIDAY, at(25, 1, 22), overrides=CHANGES),
    # Подробный вид: время | полное название, преподаватель | аудитория.
    "full_today_before_first": lambda: today_html(at(25, 1, 22), detailed=True),
    "full_today_second_pair": lambda: today_html(at(25, 11, 30), detailed=True),
    "full_today_break": lambda: today_html(at(25, 10, 55), detailed=True),
    "full_today_after_last": lambda: today_html(at(25, 16, 0), detailed=True),
    "full_tomorrow": lambda: _full(FRIDAY, at(24, 20, 0)),
    "full_one_pair": lambda: _full(SATURDAY, at(25, 20, 0)),
    "full_with_extra": lambda: _full(FRIDAY, at(25, 1, 22), extras=[UNITY_EXTRA]),
    "full_with_changes": lambda: _full(FRIDAY, at(25, 1, 22), overrides=CHANGES),
    "full_added_and_renamed": lambda: _full(FRIDAY, at(25, 1, 22), overrides=ADDED_AND_RENAMED),
    "full_all_cancelled": lambda: _full(FRIDAY, at(25, 1, 22), overrides=ALL_CANCELLED),
    # Неделя аккордеоном.
    "week_this_friday": lambda: week_html(MONDAY, at(25, 1, 22), "this"),
    "week_this_saturday": lambda: week_html(MONDAY, at(26, 14, 0), "this"),
    "week_this_sunday": lambda: week_html(MONDAY, at(27, 12, 0), "this"),
    "week_next": lambda: week_html(MONDAY, at(18, 12, 0), "next"),
    "week_month_boundary": lambda: week_html(datetime.date(2026, 9, 28), at(30, 12, 0), "this"),
    # Живое сообщение: кнопки навигации в теле.
    "day_with_nav": lambda: day_html(
        FRIDAY, at(25, 1, 22), nav=schedule.day_nav(FRIDAY, GROUP, FRIDAY)
    ),
    "full_with_nav": lambda: _full(
        FRIDAY, at(25, 1, 22), nav=schedule.day_nav(FRIDAY, GROUP, FRIDAY, detailed=True)
    ),
    "week_past_with_nav": lambda: week_html(
        datetime.date(2026, 9, 14),
        at(25, 1, 22),
        "past",
        nav=schedule.week_nav(datetime.date(2026, 9, 14), GROUP, FRIDAY),
    ),
}
