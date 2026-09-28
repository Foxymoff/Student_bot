"""Rich HTML расписания: golden-снапшоты, статусы, экранирование, валидность, длина.

Перегенерировать снапшоты: UPDATE_GOLDEN=1 pytest tests/test_render_rich.py
"""

import datetime
import itertools
import os
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

import extra_schedule
import render_rich
from config import APP_TIMEZONE, GROUPS
from handlers import schedule
from render_rich import (
    Day,
    Lesson,
    NavButton,
    nav_html,
    plural_pairs,
    render_day_html,
    render_week_html,
)
from tests.rich_fixtures import (
    ADDED_AND_RENAMED,
    ALL_CANCELLED,
    CASES,
    FRIDAY,
    GROUP,
    MONDAY,
    SUNDAY,
    UNITY_EXTRA,
    at,
    day,
    day_html,
    today_html,
    week,
)

GOLDEN_DIR = Path(__file__).parent / "golden"
RICH_TEXT_LIMIT = 32768


# ── Инструменты проверки ──────────────────────────────────

_BLOCK_BREAK_RE = re.compile(
    r"(</(?:h3|p|footer|tr|table|details|summary)>|<table[^>]*>|<details[^>]*>)"
)


def pretty(html: str) -> str:
    """Перенос строки после блочных тегов — чтобы диффы снапшотов читались."""
    return _BLOCK_BREAK_RE.sub(r"\1\n", html)


def assert_golden(name: str, html: str) -> None:
    path = GOLDEN_DIR / f"{name}.html"
    actual = pretty(html)
    if os.getenv("UPDATE_GOLDEN") == "1":
        GOLDEN_DIR.mkdir(exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    assert path.exists(), f"нет снапшота {path.name}: запусти с UPDATE_GOLDEN=1"
    assert actual == path.read_text(encoding="utf-8")


ALLOWED_TAGS: dict[str, set[str]] = {
    "h3": set(),
    "p": set(),
    "footer": set(),
    "table": {"compact", "striped", "bordered"},
    "tr": set(),
    "td": {"align", "valign"},
    "details": {"open"},
    "summary": set(),
    "b": set(),
    "i": set(),
    "s": set(),
    "mark": set(),
    "br": set(),
    "a": {"href"},
    "tg-time": {"unix", "format"},
    "tg-button-row": {"align"},
    "tg-button": {"type", "style", "data"},
}
VOID_TAGS = {"br", "hr"}


class _Checker(HTMLParser):
    """Белый список тегов и атрибутов, всё закрыто, ссылок в ячейках нет."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAGS:
            self.errors.append(f"тег <{tag}> не из белого списка")
            return
        for name, _value in attrs:
            if name not in ALLOWED_TAGS[tag]:
                self.errors.append(f"атрибут {name} у <{tag}>")
        if tag == "tg-time" and dict(attrs).get("format") != "r":
            self.errors.append("tg-time не с format=r")
        if tag == "a" and "td" in self.stack:
            self.errors.append("ссылка в ячейке таблицы")
        if tag == "tg-button":
            attrs_map = dict(attrs)
            if attrs_map.get("type") == "disabled":
                if set(attrs_map) != {"type"}:
                    self.errors.append("у неактивной кнопки лишние атрибуты")
            elif attrs_map.get("type") != "callback_data" or not attrs_map.get("data"):
                self.errors.append("tg-button не callback_data")
            elif len(attrs_map["data"].encode()) > 64:
                self.errors.append("callback_data длиннее 64 байт")
            if self.stack[-1:] not in (["tg-button-row"], ["p"]):
                self.errors.append("tg-button вне tg-button-row и абзаца")
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag not in VOID_TAGS:
            self.errors.append(f"самозакрытый <{tag}/>")

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            self.errors.append(f"закрывающий </{tag}>")
        elif not self.stack or self.stack.pop() != tag:
            self.errors.append(f"лишний или не тот </{tag}>")

    def handle_data(self, data):
        self.text.append(data)


_EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")


def check_html(html: str) -> str:
    """Проверить разметку и вернуть видимый текст."""
    checker = _Checker()
    checker.feed(html)
    checker.close()
    assert checker.errors == []
    assert checker.stack == [], f"не закрыты: {checker.stack}"
    assert "\n" not in html, "HTML собирается без переводов строк"
    assert "<p></p>" not in html, "пустой абзац"
    assert not _EMOJI_RE.search(html), "эмодзи в теле сообщения"
    return "".join(checker.text)


# ── Golden-снапшоты ───────────────────────────────────────


@pytest.mark.parametrize("name", CASES)
def test_golden(name):
    html = CASES[name]()
    check_html(html)
    assert_golden(name, html)


def _tg(hour: int, minute: int, day: int = 25) -> str:
    unix = int(at(day, hour, minute).timestamp())
    return f'<tg-time unix="{unix}" format="r">в {hour:02d}:{minute:02d}</tg-time>'


def test_reference_day_short():
    html = today_html(at(25, 1, 22))

    assert html == (
        "<h3>Пятница, 25 сентября</h3>"
        f"<p>09:20–15:00 · начало {_tg(9, 20)}</p>"
        "<table compact striped>"
        '<tr><td>1</td><td><b>МДК 04.02</b></td><td align="right">501</td></tr>'
        '<tr><td>2</td><td>История</td><td align="right">КЗ</td></tr>'
        '<tr><td>3</td><td>Ин. тех.</td><td align="right">КЗ</td></tr>'
        "</table>"
        f"<footer>{GROUP}</footer>"
    )


def test_reference_day_detailed():
    html = today_html(at(25, 1, 22), detailed=True)

    assert html.startswith(
        "<h3>Пятница, 25 сентября</h3>"
        f"<p>09:20–15:00 · начало {_tg(9, 20)}</p>"
        "<table compact striped>"
        '<tr><td valign="top"><b>09:20</b><br><b>10:50</b></td><td><b>Обеспечение качества'
        " функционирования компьютерных систем</b><br><i>Павлович Е.М.</i></td>"
        '<td align="right" valign="top">501</td></tr>'
    )
    assert html.count("<table") == 1  # одна таблица, без блока с подробностями
    assert "<details" not in html


# ── Статусная строка ──────────────────────────────────────


def _status(now: datetime.datetime, date: datetime.date = FRIDAY) -> str:
    html = render_day_html(day(date), now=now, group=GROUP)
    return re.search(r"<p>(.*?)</p>", html).group(1)


@pytest.mark.parametrize(
    ("now", "status"),
    [
        (at(24, 20, 0), f"начало {_tg(9, 20)}"),  # день в будущем
        (at(25, 1, 22), f"начало {_tg(9, 20)}"),  # сегодня до первой пары
        (at(25, 9, 20), f"конец 1 пары {_tg(10, 50)}"),  # началась первая
        (at(25, 11, 30), f"конец 2 пары {_tg(12, 30)}"),  # идёт вторая
        (at(25, 10, 50), f"начало 2 пары {_tg(11, 0)}"),  # перемена
        (at(25, 12, 45), f"начало 3 пары {_tg(13, 30)}"),  # большая перемена
    ],
)
def test_status_line(now, status):
    # Числа пар в статусе нет — его и так видно по таблице.
    assert _status(now) == f"09:20–15:00 · {status}"


def test_status_for_extra_has_no_pair_number():
    extra = Lesson(
        start=at(25, 16, 50), end=at(25, 18, 20), short="UNITY", full="UNITY", extra=True
    )
    html = render_day_html(Day(FRIDAY, (extra,)), now=at(25, 17, 0), group=GROUP)

    assert f"<p>16:50–18:20 · конец доп. занятия {_tg(18, 20)}</p>" in html


def test_after_last_pair_shows_next_study_day():
    html = today_html(at(25, 15, 0))

    assert "<p>Пары на сегодня закончились.</p>" in html
    assert "<details><summary>Сегодняшние пары</summary><table" in html
    assert f"<h3>Суббота, 26 сентября</h3><p>11:00–12:30 · начало {_tg(11, 0, 26)}" in html
    assert "<b>" not in html  # ближайшая пара не сегодня — без выделения


def test_nearest_pair_marked_only_today():
    assert "<td><b>История</b></td>" in today_html(at(25, 10, 55))
    assert '<td valign="top"><b>11:00</b><br><b>12:30</b></td>' in today_html(
        at(25, 10, 55), detailed=True
    )
    assert "<b>" not in day_html(FRIDAY, at(24, 20, 0))


def test_empty_day_without_upcoming():
    html = render_day_html(Day(SUNDAY), now=at(26, 18, 0), group=GROUP)

    assert html == f"<h3>Воскресенье, 27 сентября</h3><p>Пар нет.</p><footer>{GROUP}</footer>"


def test_empty_day_points_to_next_study_day():
    assert day_html(SUNDAY, at(26, 18, 0)) == (
        "<h3>Воскресенье, 27 сентября</h3>"
        "<p>Пар нет. Ближайшие: понедельник, 28 сентября, начало "
        f"{_tg(9, 20, 28)}</p>"
        f"<footer>{GROUP}</footer>"
    )


def test_lead_for_daily_notify():
    html = render_day_html(day(FRIDAY), now=at(25, 8, 0), group=GROUP, lead="Расписание на сегодня")

    assert html.startswith("<p><b>Расписание на сегодня</b></p><h3>Пятница, 25 сентября</h3>")


# ── Склонение ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("n", "text"),
    [
        (1, "1 пара"),
        (2, "2 пары"),
        (4, "4 пары"),
        (5, "5 пар"),
        (11, "11 пар"),
        (12, "12 пар"),
        (21, "21 пара"),
        (22, "22 пары"),
        (25, "25 пар"),
    ],
)
def test_plural_pairs(n, text):
    assert plural_pairs(n) == text


# ── Допзанятия, изменения, граничные случаи ───────────────


def test_extra_is_italic_marked_with_plus():
    short = day_html(FRIDAY, at(25, 1, 22), extras=[UNITY_EXTRA])
    full = day_html(FRIDAY, at(25, 1, 22), extras=[UNITY_EXTRA], detailed=True)

    assert "<p>09:20–18:20 · начало <tg-time" in short
    assert '<tr><td>+</td><td><i>UNITY</i> · доп</td><td align="right">501</td></tr>' in short
    assert (
        '<tr><td valign="top">16:50<br>18:20</td><td><b><i>Разработка игр на движке UNITY</i></b>'
        " · доп<br><i>Павлович Е.М.</i><br><i>группа 1</i></td>"
    ) in full


def test_changes_short_shows_only_current_state():
    html = CASES["day_with_changes"]()

    # Отменённая пара зачёркнута и не участвует в статусе.
    assert html.startswith(f"<h3>Пятница, 25 сентября</h3><p>11:00–15:00 · начало {_tg(11, 0)}")
    assert '<td>1</td><td><s>МДК 04.02</s></td><td align="right"><s>501</s></td>' in html
    # В кратком виде — просто текущая аудитория, отметки и ссылки только в подробном.
    assert '<td>2</td><td><b>История</b></td><td align="right">420</td>' in html
    assert '<td>3</td><td>Ин. тех.</td><td align="right">ОНЛ</td>' in html
    assert "<a " not in html
    assert "ноутбук" not in html


def test_changes_detailed_shows_marks_note_and_link():
    html = CASES["full_with_changes"]()

    assert '<td align="right" valign="top"><b>420</b></td>' in html
    assert "<br><i>Хайруллина Д.Х.</i><br><i>Принести ноутбук</i>" in html
    assert '<td align="right" valign="top">ОНЛ</td>' in html
    assert (
        '<p>13:30 · Ин. тех. · онлайн: <a href="https://meet.example.com/a?b=1&amp;c=2">'
        "https://meet.example.com/a?b=1&amp;c=2</a></p><footer>"
    ) in html


def test_added_and_renamed_pairs():
    html = CASES["full_added_and_renamed"]()
    short = day_html(FRIDAY, at(25, 1, 22), overrides=ADDED_AND_RENAMED)

    assert "<td><b>История России</b><br><i>Хайруллина Д.Х.</i></td>" in html
    # Добавленная пара: время из сетки звонков, без преподавателя и аудитории.
    assert (
        '<tr><td valign="top">15:10<br>16:40</td><td><b>Пересдача</b></td>'
        '<td align="right" valign="top"></td></tr>'
    ) in html
    assert '<tr><td>4</td><td>Пересдача</td><td align="right"></td></tr>' in short
    assert "<p>09:20–16:40 · начало <tg-time" in short


def test_missing_room_and_teacher():
    lesson = Lesson(start=at(25, 9, 20), end=at(25, 10, 50), short="Физика", full="Физика", num=1)
    short = render_day_html(Day(FRIDAY, (lesson,)), now=at(24, 20, 0), group=GROUP)
    full = render_day_html(Day(FRIDAY, (lesson,)), now=at(24, 20, 0), group=GROUP, detailed=True)

    assert '<td>1</td><td>Физика</td><td align="right"></td>' in short
    assert "<td><b>Физика</b></td>" in full


def test_not_http_online_link_is_plain_text():
    lesson = Lesson(
        start=at(25, 9, 20),
        end=at(25, 10, 50),
        short="Физика",
        full="Физика",
        num=1,
        online=True,
        online_url="javascript:alert(1)",
    )
    html = render_day_html(Day(FRIDAY, (lesson,)), now=at(25, 1, 0), group=GROUP, detailed=True)

    check_html(html)
    assert "<a " not in html
    assert "онлайн: javascript:alert(1)</p>" in html


def test_all_cancelled_day():
    for detailed in (False, True):
        html = day_html(FRIDAY, at(25, 1, 22), overrides=ALL_CANCELLED, detailed=detailed)

        check_html(html)
        assert "<p>Все пары отменены. Ближайшие: суббота, 26 сентября, начало <tg-time" in html
        assert html.count("<s>") == 6  # название и аудитория каждой пары


def test_escaping_teacher_and_subject():
    lesson = Lesson(
        start=at(25, 9, 20),
        end=at(25, 10, 50),
        short="C++ & <Py>",
        full="C++ & <Py> «полное»",
        room="<1>",
        teacher="Иванов <b>& Ко",
        num=1,
    )
    for detailed in (False, True):
        html = render_day_html(
            Day(FRIDAY, (lesson,)), now=at(25, 1, 0), group="A&B", detailed=detailed
        )
        text = check_html(html)
        assert "C++ & <Py>" in text
        assert "<footer>A&amp;B</footer>" in html
    assert "<i>Иванов &lt;b&gt;&amp; Ко</i>" in html
    assert "Иванов <b>& Ко" in text


# ── Неделя ────────────────────────────────────────────────


def test_week_open_policy_this_week():
    html = render_week_html(week(MONDAY), now=at(23, 12, 45), group=GROUP, which="this")

    assert "<h3>Неделя 21–26 сентября</h3>" in html
    assert "<details><summary>Пн, 21 сентября · 3 пары</summary>" in html
    assert "<details><summary>Вт, 22 сентября · 3 пары</summary>" in html
    assert "<details open><summary><b>Ср, 23 сентября · сегодня</b></summary>" in html
    assert "<details open><summary>Чт, 24 сентября · 4 пары</summary>" in html
    assert "<details open><summary>Сб, 26 сентября · 1 пара</summary>" in html
    assert "Вс, 27" not in html  # воскресенье без пар не показываем
    assert "<td>3</td><td><b>Физ. культ.</b></td>" in html  # ближайшая пара сегодня


def test_week_day_without_pairs_and_ended_week():
    days = week(MONDAY)
    days[2] = Day(days[2].date)  # среда без пар
    html = render_week_html(days, now=at(27, 12, 0), group=GROUP, which="this")

    assert "<p>Эта неделя закончилась.</p>" in html
    assert "<p>Ср, 23 сентября · пар нет</p>" in html
    assert "<details open>" not in html


def test_week_next_all_open():
    html = render_week_html(week(MONDAY), now=at(18, 12, 0), group=GROUP, which="next")

    assert html.count("<details open>") == 6
    assert "<b>" not in html


def test_week_heading_across_months():
    html = render_week_html(
        week(datetime.date(2026, 9, 28)), now=at(30, 12, 0), group=GROUP, which="this"
    )

    assert html.startswith("<h3>Неделя 28 сентября – 3 октября</h3>")


# ── Длина и реальные данные ───────────────────────────────


def _heavy_lesson(date: datetime.date, num: int) -> Lesson:
    start = datetime.datetime.combine(date, datetime.time(8 + num * 2), tzinfo=APP_TIMEZONE)
    name = "Проектирование и разработка информационных систем с элементами ИИ " * 2
    return Lesson(
        start=start,
        end=start + datetime.timedelta(minutes=90),
        short=name[:40],
        full=name.strip(),
        room="Конференц-зал",
        teacher="Константинопольский-Преображенский А.А.",
        num=num + 1,
        note="Принести ноутбук и зарядку, будет контрольная работа",
    )


def test_heaviest_week_and_day_fit_limit():
    days = [
        Day(MONDAY + datetime.timedelta(days=i), tuple(_heavy_lesson(MONDAY, n) for n in range(5)))
        for i in range(6)
    ]
    pages = [
        render_week_html(days, now=at(21, 1, 0), group=GROUP, which="this"),
        render_day_html(days[0], now=at(21, 1, 0), group=GROUP),
        render_day_html(days[0], now=at(21, 1, 0), group=GROUP, detailed=True),
    ]

    for html in pages:
        check_html(html)
        assert len(html) < RICH_TEXT_LIMIT // 4


def test_all_real_schedules_render_valid_html():
    """Все группы × 2 недели × подгруппы, со всеми допами: разметка валидна."""
    start = datetime.date(2026, 9, 21)
    for group, sg_inf, sg_eng in itertools.product(GROUPS, (1, 2), (1, 2)):
        keys = [extra_schedule.make_extra_key(x) for x in extra_schedule.get_extra_options(group)]
        for monday in (start, start + datetime.timedelta(weeks=1)):
            days = []
            for offset in range(7):
                date = monday + datetime.timedelta(days=offset)
                days.append(
                    schedule.build_rich_day(
                        schedule.get_lessons_for_date(group, date),
                        date,
                        sg_inf,
                        sg_eng,
                        [],
                        extra_schedule.get_extras_for_date(group, date, keys),
                    )
                )
            now = datetime.datetime.combine(monday, datetime.time(12), tzinfo=APP_TIMEZONE)
            week_html = render_week_html(days, now=now, group=group, which="this")
            check_html(week_html)
            assert len(week_html) < RICH_TEXT_LIMIT // 4
            for index, target in enumerate(days):
                nearest = next((d for d in days[index + 1 :] if d.lessons), None)
                for detailed in (False, True):
                    check_html(
                        render_day_html(
                            target, now=now, group=group, upcoming=nearest, detailed=detailed
                        )
                    )


# ── Кнопки навигации (живое сообщение) ────────────────────


def test_nav_inline_links_accent_and_disabled():
    html = nav_html(
        [
            [
                NavButton("‹ <вчера>", 'rs:"x"&y'),
                NavButton("Сегодня", "rs:t", accent=True),
                NavButton("Эта неделя", disabled=True),
            ]
        ]
    )

    # Обычные — ссылками, заливка только у акцента, текущая — неактивна.
    assert html == (
        '<p><tg-button type="callback_data" style="link" data="rs:&quot;x&quot;&amp;y">'
        "‹ &lt;вчера&gt;</tg-button> · "
        '<tg-button type="callback_data" style="primary" data="rs:t">Сегодня</tg-button> · '
        '<tg-button type="disabled">Эта неделя</tg-button></p>'
    )
    check_html(html)
    assert nav_html([]) == nav_html([[]]) == ""


def test_nav_rows_become_separate_lines():
    html = nav_html([[NavButton("a", "rs:a")], [NavButton("b", "rs:b")]])

    assert html.count("<p>") == 2
    check_html(html)


def test_nav_row_layout(monkeypatch):
    monkeypatch.setattr(render_rich, "NAV_LAYOUT", "row")

    html = nav_html([[NavButton("‹ Чт, 24", "rs:a"), NavButton("Сегодня", "rs:b", accent=True)]])

    # В ряду link отбрасывается сервером — обычные primary, акцент success.
    assert html == (
        '<tg-button-row align="center">'
        '<tg-button type="callback_data" style="primary" data="rs:a">‹ Чт, 24</tg-button>'
        '<tg-button type="callback_data" style="success" data="rs:b">Сегодня</tg-button>'
        "</tg-button-row>"
    )
    check_html(html)


def test_nav_goes_last_in_day_and_week():
    buttons = [[NavButton("Сегодня", disabled=True)], [NavButton("Вся неделя", "rs:w")]]
    pages = [
        render_day_html(day(FRIDAY), now=at(25, 1, 22), group=GROUP, nav=buttons),
        render_day_html(day(FRIDAY), now=at(25, 1, 22), group=GROUP, nav=buttons, detailed=True),
        render_week_html(week(MONDAY), now=at(25, 1, 22), group=GROUP, nav=buttons),
    ]

    for html in pages:
        check_html(html)
        assert html.endswith(f"<footer>{GROUP}</footer>{nav_html(buttons)}")


def test_week_lead_for_other_group():
    html = render_week_html(week(MONDAY), now=at(25, 1, 22), group="МР-25", lead="МР-25")

    assert html.startswith("<p><b>МР-25</b></p><h3>Неделя")


def test_past_week_is_collapsed_without_ended_note():
    html = render_week_html(week(MONDAY), now=at(2, 12, 0, month=10), group=GROUP, which="past")

    assert "<details open>" not in html
    assert "Эта неделя закончилась" not in html
    assert "<b>" not in html


def test_no_mark_tag_anywhere():
    """<mark> на iOS в тёмной теме не читается — выделяем жирным."""
    for build in CASES.values():
        assert "<mark>" not in build()
