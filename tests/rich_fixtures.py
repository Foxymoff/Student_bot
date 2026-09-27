"""Фикстуры rich-расписания в формате data/*.json (копия ИСП-25-2 на сентябрь 2026).

Копия, а не чтение data/: golden-снапшоты не должны меняться при правке расписания.
"""

import datetime

from config import APP_TIMEZONE
from handlers import schedule
from render_rich import Day

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
