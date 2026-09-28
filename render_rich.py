"""
Расписание в Rich HTML (sendRichMessage, Bot API 10.1+).

Только чистые функции без I/O: данные приходят готовыми моделями ``Day``/``Lesson``,
текущее время передаётся параметром ``now`` (aware, Europe/Moscow). HTML собирается
без переводов строк между тегами. Справка по разметке — docs/telegram-rich.md.
"""

import datetime
import html
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from config import APP_TIMEZONE as TZ
from extra_schedule import MONTH_NAMES, WEEKDAY_NAMES, WEEKDAY_NAMES_SHORT

# ── Ручки вида ────────────────────────────────────────────

# Атрибуты всех таблиц расписания (булевы атрибуты Rich HTML).
TABLE_ATTRS = "compact striped"
# Выделение ближайшей пары и сегодняшнего дня. Не <mark>: на iOS в тёмной теме
# жёлтая подложка остаётся светлой, а текст становится белым — не читается.
MARK_TAG = "b"
# Уровень заголовков дня и недели.
HEADING_TAG = "h3"
# Краткий вид: первая колонка — номер пары (True) или время начала (False).
# У допзанятий номера нет — вместо него EXTRA_NUM. Подробный вид всегда со временем.
SHOW_PAIR_NUMBER = True
EXTRA_NUM = "+"
# Политика раскрытия дней недели («Эта неделя»): прошедшие свёрнуты, сегодня
# (пока пары не закончились) и будущие раскрыты. «След. неделя» раскрыта целиком.
WEEK_OPEN_PAST = False
WEEK_OPEN_TODAY = True
WEEK_OPEN_FUTURE = True
WEEK_OPEN_NEXT = True
# Суббота и воскресенье в неделе — только если в них есть пары.
WEEKEND_ONLY_WITH_LESSONS = True

TODAY_SUMMARY = "Сегодняшние пары"
EXTRA_LABEL = "доп"
# Онлайн-пара в колонке аудитории — как «ОНЛ» в классическом виде.
ONLINE_ROOM = "ОНЛ"
# На сколько дней вперёд искать ближайший учебный день.
LOOKAHEAD_DAYS = 14

WEEKDAY_ABBR: tuple[str, ...] = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")

# Навигация — ряды больших кнопок в теле сообщения (<tg-button-row>). Стиль у каждой
# кнопки: без него на iOS в тёмной теме кнопка белая с белым текстом. Обычные — primary,
# текущая (открыт сегодняшний день / текущая неделя) — success, её нажатие обновляет
# сообщение. style="link" в ряду сервер отбрасывает (проверено по эху).
NAV_ROW_ALIGN = "center"
NAV_STYLE = "primary"
NAV_CURRENT_STYLE = "success"

# Где переключатель «Подробнее» / «Кратко»: "keyboard" — inline-кнопкой под сообщением
# (её ставит бот), "link" — ссылкой под таблицей, "pill" — маленькой синей кнопкой под
# таблицей. Ссылка и «таблетка» — кнопки внутри абзаца: style="link" работает только там.
DETAILS_TOGGLE: Literal["keyboard", "link", "pill"] = "link"
TOGGLE_STYLES: dict[str, str] = {"link": "link", "pill": "primary"}
# Строка «Подробнее … группа» под таблицей дня (группа — справа, вместо подписи внизу).
TOGGLE_ROW_ATTRS = "compact"

WeekKind = Literal["this", "next", "past"]


# ── Модели ────────────────────────────────────────────────


@dataclass(frozen=True)
class Lesson:
    """Строка расписания (пара или допзанятие), уже с учётом подгрупп и изменений."""

    start: datetime.datetime | None  # aware; None — время неизвестно
    end: datetime.datetime | None
    short: str
    full: str
    room: str = ""
    teacher: str = ""
    num: int | None = None
    extra: bool = False
    cancelled: bool = False
    room_changed: bool = False
    online: bool = False
    online_url: str = ""
    note: str = ""


@dataclass(frozen=True)
class Day:
    """День расписания: строки уже отсортированы по времени."""

    date: datetime.date
    lessons: tuple[Lesson, ...] = ()


@dataclass(frozen=True)
class NavButton:
    """Кнопка навигации: callback_data до 64 байт; current — открытый сейчас день/неделя."""

    text: str
    data: str
    current: bool = False


# Ряды кнопок навигации: каждый ряд — отдельный <tg-button-row>.
NavRows = Sequence[Sequence[NavButton]]


# ── Хелперы ───────────────────────────────────────────────


def esc(value: object, *, quote: bool = False) -> str:
    """Экранировать текст (quote=False) или значение атрибута (quote=True)."""
    return html.escape(str(value), quote=quote)


def hhmm(dt: datetime.datetime | None) -> str:
    """Время пары обычным текстом HH:MM (в часовом поясе расписания)."""
    return dt.astimezone(TZ).strftime("%H:%M") if dt else "—"


def tg_time_rel(dt: datetime.datetime, fallback: str | None = None) -> str:
    """Относительное время («через 8 часов»); только format="r", текст внутри — фолбэк."""
    text = fallback if fallback is not None else f"в {hhmm(dt)}"
    unix = int(dt.timestamp())
    return f'<tg-time unix="{unix}" format="r">{esc(text)}</tg-time>'


def plural_pairs(n: int) -> str:
    """«1 пара», «2 пары», «5 пар», «11 пар», «21 пара»."""
    if n % 10 == 1 and n % 100 != 11:
        word = "пара"
    elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        word = "пары"
    else:
        word = "пар"
    return f"{n} {word}"


def _wrap(tag: str, inner: str) -> str:
    return f"<{tag}>{inner}</{tag}>"


def _day_title(date: datetime.date) -> str:
    """«Пятница, 25 сентября»."""
    return f"{WEEKDAY_NAMES[date.weekday()]}, {date.day} {MONTH_NAMES[date.month]}"


def _day_label(date: datetime.date) -> str:
    """«Пн, 21 сентября»."""
    return f"{WEEKDAY_ABBR[date.weekday()]}, {date.day} {MONTH_NAMES[date.month]}"


def _date_range(first: datetime.date, last: datetime.date) -> str:
    """«21–25 сентября» или «28 сентября – 2 октября»."""
    if first.month == last.month:
        return f"{first.day}–{last.day} {MONTH_NAMES[last.month]}"
    return f"{first.day} {MONTH_NAMES[first.month]} – {last.day} {MONTH_NAMES[last.month]}"


def _active(day: Day) -> list[Lesson]:
    """Неотменённые строки дня."""
    return [lesson for lesson in day.lessons if not lesson.cancelled]


def _timed(day: Day) -> list[Lesson]:
    """Неотменённые строки с известным временем начала, по времени."""
    return sorted(
        (lesson for lesson in _active(day) if lesson.start is not None),
        key=lambda lesson: lesson.start,
    )


def _end_of(lesson: Lesson) -> datetime.datetime:
    return lesson.end or lesson.start


def has_lessons(day: Day) -> bool:
    """Учебный ли день: есть хотя бы одна неотменённая строка."""
    return bool(_active(day))


def _local_now(now: datetime.datetime) -> datetime.datetime:
    return now.astimezone(TZ)


def _is_today(day: Day, now: datetime.datetime) -> bool:
    return day.date == _local_now(now).date()


def _finished(day: Day, now: datetime.datetime) -> bool:
    """Пары этого дня уже закончились (сегодня после последней или день в прошлом)."""
    today = _local_now(now).date()
    if day.date < today:
        return True
    timed = _timed(day)
    if day.date > today or not timed:
        return False
    return now >= max(_end_of(lesson) for lesson in timed)


def needs_upcoming(day: Day, now: datetime.datetime) -> bool:
    """Нужен ли рендеру ближайший учебный день (день пустой или пары уже прошли)."""
    return not has_lessons(day) or (_is_today(day, now) and _finished(day, now))


def _nearest(day: Day, now: datetime.datetime) -> Lesson | None:
    """Ближайшая пара сегодня: идущая или следующая."""
    if not _is_today(day, now):
        return None
    for lesson in _timed(day):
        if now < _end_of(lesson):
            return lesson
    return None


def _count_label(day: Day) -> str:
    """«3 пары», «3 пары + 1 доп», «1 доп»."""
    active = _active(day)
    extras = sum(1 for lesson in active if lesson.extra)
    pairs = len(active) - extras
    if pairs and extras:
        return f"{plural_pairs(pairs)} + {extras} {EXTRA_LABEL}"
    if extras:
        return f"{extras} {EXTRA_LABEL}"
    return plural_pairs(pairs)


def _pair_ref(lesson: Lesson) -> str:
    """«1 пары» или «доп. занятия» — для статуса «начало … / конец …»."""
    if lesson.extra or lesson.num is None:
        return "доп. занятия"
    return f"{lesson.num} пары"


def _status(day: Day, now: datetime.datetime) -> str | None:
    """Статус на момент генерации: «начало через …» (до первой пары), дальше
    «конец 2 пары через …» и «начало 3 пары через …» на перемене."""
    timed = _timed(day)
    if not timed:
        return None
    today = _local_now(now).date()
    first = timed[0]
    if day.date > today or (day.date == today and now < first.start):
        return f"начало {tg_time_rel(first.start)}"
    if day.date < today:
        return None
    for lesson in timed:
        if lesson.start <= now < _end_of(lesson):
            return f"конец {esc(_pair_ref(lesson))} {tg_time_rel(_end_of(lesson))}"
    for lesson in timed:
        if now < lesson.start:
            return f"начало {esc(_pair_ref(lesson))} {tg_time_rel(lesson.start)}"
    return None


def _status_line(day: Day, now: datetime.datetime) -> str:
    """«09:20–15:00 · начало <tg-time …>»; число пар и так видно по таблице."""
    timed = _timed(day)
    text = ""
    if timed:
        last_end = max(_end_of(lesson) for lesson in timed)
        text = f"{hhmm(timed[0].start)}–{hhmm(last_end)}"
    status = _status(day, now)
    if status:
        text = f"{text} · {status}" if text else status
    return _wrap("p", text) if text else ""


# ── Таблицы ───────────────────────────────────────────────


def _td(inner: str, *, align: str | None = None, valign: str | None = None) -> str:
    attrs = ""
    if align:
        attrs += f' align="{esc(align, quote=True)}"'
    if valign:
        attrs += f' valign="{esc(valign, quote=True)}"'
    return f"<td{attrs}>{inner}</td>"


def _table(rows: list[str]) -> str:
    return f"<table {TABLE_ATTRS}>{''.join(rows)}</table>"


def _room_text(lesson: Lesson) -> str:
    return ONLINE_ROOM if lesson.online else lesson.room


def _first_cell(lesson: Lesson) -> str:
    """Номер пары (у допзанятия — EXTRA_NUM) или время начала — см. SHOW_PAIR_NUMBER."""
    if not SHOW_PAIR_NUMBER:
        return hhmm(lesson.start)
    if lesson.extra:
        return EXTRA_NUM
    return "—" if lesson.num is None else str(lesson.num)


def _short_row(lesson: Lesson, *, marked: bool) -> str:
    """Строка краткой таблицы: номер пары | короткое название | аудитория."""
    name = esc(lesson.short)
    if lesson.extra:
        name = _wrap("i", name)
    if marked:
        name = _wrap(MARK_TAG, name)
    room = esc(_room_text(lesson))
    if lesson.cancelled:
        name = _wrap("s", name)
        room = _wrap("s", room) if room else ""
    if lesson.extra:
        name += f" · {EXTRA_LABEL}"
    return "<tr>" + _td(esc(_first_cell(lesson))) + _td(name) + _td(room, align="right") + "</tr>"


def _full_time(lesson: Lesson, *, marked: bool) -> str:
    """Начало и конец в две строки одной ячейки — узкая колонка, названия меньше переносятся."""
    lines = [hhmm(lesson.start)]
    if lesson.start and lesson.end:
        lines.append(hhmm(lesson.end))
    if marked:
        lines = [_wrap(MARK_TAG, line) for line in lines]
    return "<br>".join(lines)


def _full_row(lesson: Lesson, *, marked: bool) -> str:
    """Строка подробной таблицы: время | полное название, преподаватель | аудитория."""
    name = esc(lesson.full)
    if lesson.extra:
        name = _wrap("i", name)
    if lesson.cancelled:
        name = _wrap("s", name)
    cell = _wrap("b", name)
    if lesson.extra:
        cell += f" · {EXTRA_LABEL}"
    if lesson.teacher:
        cell += "<br>" + _wrap("i", esc(lesson.teacher))
    if lesson.note:
        cell += "<br>" + _wrap("i", esc(lesson.note))
    room = esc(_room_text(lesson))
    if lesson.cancelled and room:
        room = _wrap("s", room)
    elif lesson.room_changed and room and not lesson.online:
        room = _wrap("b", room)
    time_text = _full_time(lesson, marked=marked)
    return (
        "<tr>"
        + _td(time_text, valign="top")
        + _td(cell)
        + _td(room, align="right", valign="top")
        + "</tr>"
    )


def _online_link(lesson: Lesson) -> str:
    """Ссылка на онлайн-пару отдельным абзацем (в ячейки таблиц ссылки не ставим)."""
    url = lesson.online_url.strip()
    if url.lower().startswith(("https://", "http://")):
        link = f'<a href="{esc(url, quote=True)}">{esc(url)}</a>'
    else:
        link = esc(url)
    return _wrap("p", f"{hhmm(lesson.start)} · {esc(lesson.short)} · онлайн: {link}")


def _details(summary: str, body: str, *, is_open: bool = False) -> str:
    opening = "<details open>" if is_open else "<details>"
    return f"{opening}<summary>{summary}</summary>{body}</details>"


def _day_table(day: Day, now: datetime.datetime, *, detailed: bool, links: bool = True) -> str:
    """Одна таблица дня: краткая или подробная; в подробной — ссылки онлайн-пар под ней."""
    nearest = _nearest(day, now)
    if not detailed:
        return _table([_short_row(lesson, marked=lesson is nearest) for lesson in day.lessons])
    html_parts = [_table([_full_row(lesson, marked=lesson is nearest) for lesson in day.lessons])]
    if links:
        html_parts += [
            _online_link(lesson)
            for lesson in day.lessons
            if lesson.online and lesson.online_url and not lesson.cancelled
        ]
    return "".join(html_parts)


def _button(button: NavButton, style: str) -> str:
    data = esc(button.data, quote=True)
    text = esc(button.text)
    return f'<tg-button type="callback_data" style="{style}" data="{data}">{text}</tg-button>'


def _nav_row(buttons: Sequence[NavButton]) -> str:
    items = "".join(
        _button(button, NAV_CURRENT_STYLE if button.current else NAV_STYLE) for button in buttons
    )
    return f'<tg-button-row align="{NAV_ROW_ALIGN}">{items}</tg-button-row>'


def nav_html(rows: NavRows) -> str:
    """Ряды кнопок навигации в теле сообщения; пусто, если кнопок нет."""
    return "".join(_nav_row(row) for row in rows if row)


def under_table_html(
    toggle: NavButton | None, style: Literal["link", "pill"], group_text: str | None
) -> str:
    """Строка под таблицей: слева «Подробнее» / «Кратко», справа курсивом группа.

    Группу показываем только у чужой группы — своё расписание подписи не требует.
    Выровнять части абзаца влево и вправо нельзя, поэтому при группе это таблица
    из одной строки без полос (кнопка в ячейке сохраняется — проверено по эху).
    """
    button = _button(toggle, TOGGLE_STYLES[style]) if toggle is not None else ""
    if not group_text:
        return _wrap("p", button) if button else ""
    cells = _td(button) + _td(_wrap("i", esc(group_text)), align="right")
    return f"<table {TOGGLE_ROW_ATTRS}><tr>{cells}</tr></table>"


# ── День ──────────────────────────────────────────────────


def _heading(text: str) -> str:
    return _wrap(HEADING_TAG, esc(text))


def _upcoming_hint(upcoming: Day | None) -> str:
    """« Ближайшие: понедельник, 28 сентября, начало <tg-time …>»."""
    if upcoming is None or not has_lessons(upcoming):
        return ""
    date = upcoming.date
    weekday = WEEKDAY_NAMES_SHORT[date.weekday()]
    hint = f" Ближайшие: {weekday}, {date.day} {MONTH_NAMES[date.month]}"
    timed = _timed(upcoming)
    if not timed:
        return esc(hint)
    return f"{esc(hint)}, начало {tg_time_rel(timed[0].start)}"


def _day_body(day: Day, now: datetime.datetime, upcoming: Day | None, *, detailed: bool) -> str:
    """Заголовок, статус и таблица одного дня (краткая или подробная)."""
    parts = [_heading(_day_title(day.date))]
    if not has_lessons(day):
        lead = "Все пары отменены." if day.lessons else "Пар нет."
        parts.append(_wrap("p", esc(lead) + _upcoming_hint(upcoming)))
        if day.lessons:
            parts.append(_day_table(day, now, detailed=detailed))
        return "".join(parts)

    if _is_today(day, now) and _finished(day, now):
        parts.append(_wrap("p", "Пары на сегодня закончились."))
        today_table = _day_table(day, now, detailed=detailed, links=False)
        parts.append(_details(esc(TODAY_SUMMARY), today_table))
        if upcoming is not None and has_lessons(upcoming):
            parts.append(_day_body(upcoming, now, None, detailed=detailed))
        return "".join(parts)

    parts.append(_status_line(day, now))
    parts.append(_day_table(day, now, detailed=detailed))
    return "".join(parts)


def _group_text(
    group: str | None, updated_at: datetime.datetime | None, now: datetime.datetime
) -> str | None:
    """«{группа} · данные на HH:MM»; без группы (своё расписание) — ничего."""
    if not group:
        return None
    text = group
    if updated_at is not None:
        local = updated_at.astimezone(TZ)
        if local.date() == _local_now(now).date():
            text += f" · данные на {local:%H:%M}"
        else:
            text += f" · данные на {local:%d.%m, %H:%M}"
    return text


def render_day_html(
    day: Day,
    *,
    now: datetime.datetime,
    group: str | None,
    updated_at: datetime.datetime | None = None,
    upcoming: Day | None = None,
    lead: str | None = None,
    nav: NavRows = (),
    detailed: bool = False,
    toggle: NavButton | None = None,
    toggle_style: Literal["link", "pill"] | None = None,
) -> str:
    """Расписание на день: одна таблица, краткая или подробная (detailed).

    upcoming — ближайший учебный день после ``day`` (для пустого дня и для «сегодня»
    после последней пары, см. needs_upcoming); lead — подпись над заголовком
    (например, «Расписание на сегодня» в ежедневной рассылке); nav — кнопки в конце;
    toggle — «Подробнее» / «Кратко» под таблицей (стиль — toggle_style или DETAILS_TOGGLE);
    group — подпись справа под таблицей, только для чужой группы (None — без подписи).
    """
    parts = []
    if lead:
        parts.append(_wrap("p", _wrap("b", esc(lead))))
    parts.append(_day_body(day, now, upcoming, detailed=detailed))
    style = toggle_style or (DETAILS_TOGGLE if DETAILS_TOGGLE in TOGGLE_STYLES else "link")
    toggle = toggle if day.lessons else None  # без таблицы переключать нечего
    parts.append(under_table_html(toggle, style, _group_text(group, updated_at, now)))
    parts.append(nav_html(nav))
    return "".join(parts)


# ── Неделя ────────────────────────────────────────────────


def _week_day(day: Day, now: datetime.datetime, which: WeekKind) -> str:
    """Один день недели: details с таблицей или абзац «пар нет»."""
    today = _is_today(day, now)
    label = _day_label(day.date)
    if not day.lessons:
        if today:
            return _wrap("p", _wrap(MARK_TAG, esc(f"{label} · сегодня")) + " · пар нет")
        return _wrap("p", esc(f"{label} · пар нет"))

    if today:
        summary = _wrap(MARK_TAG, esc(f"{label} · сегодня"))
    elif has_lessons(day):
        summary = esc(f"{label} · {_count_label(day)}")
    else:
        summary = esc(f"{label} · пары отменены")

    if which == "next":
        is_open = WEEK_OPEN_NEXT
    elif which == "past":
        is_open = False
    elif day.date < _local_now(now).date():
        is_open = WEEK_OPEN_PAST
    elif today:
        is_open = WEEK_OPEN_TODAY and not _finished(day, now)
    else:
        is_open = WEEK_OPEN_FUTURE
    return _details(summary, _day_table(day, now, detailed=False), is_open=is_open)


def render_week_html(
    days: list[Day],
    *,
    now: datetime.datetime,
    group: str | None,
    updated_at: datetime.datetime | None = None,
    which: WeekKind = "this",
    nav: NavRows = (),
) -> str:
    """Неделя аккордеоном: день — свёрнутый или раскрытый details.

    which: "this" — текущая неделя, "next" — будущая (всё раскрыто),
    "past" — прошедшая (всё свёрнуто); nav — кнопки в конце.
    """
    shown = [
        day
        for day in sorted(days, key=lambda d: d.date)
        if day.date.weekday() < 5 or not WEEKEND_ONLY_WITH_LESSONS or day.lessons
    ]
    parts = []
    if shown:
        parts.append(_heading(f"Неделя {_date_range(shown[0].date, shown[-1].date)}"))
    today = _local_now(now).date()
    if which == "this" and shown and all(day.date < today for day in shown):
        parts.append(_wrap("p", "Эта неделя закончилась."))
    parts.extend(_week_day(day, now, which) for day in shown)
    parts.append(under_table_html(None, "link", _group_text(group, updated_at, now)))
    parts.append(nav_html(nav))
    return "".join(parts)
