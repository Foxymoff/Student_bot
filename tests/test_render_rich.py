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
from render_rich import Day, Lesson, plural_pairs, render_day_html, render_week_html
from tests.rich_fixtures import GROUP, UNITY_EXTRA, at, day, upcoming, week

GOLDEN_DIR = Path(__file__).parent / "golden"
RICH_TEXT_LIMIT = 32768

FRIDAY = datetime.date(2026, 9, 25)
SATURDAY = datetime.date(2026, 9, 26)
SUNDAY = datetime.date(2026, 9, 27)
MONDAY = datetime.date(2026, 9, 21)


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


def _today(now: datetime.datetime) -> str:
    """«Сегодня» так же, как собирает бот: с ближайшим днём, если он нужен."""
    target = day(now.date())
    nearest = upcoming(now.date()) if render_rich.needs_upcoming(target, now) else None
    return render_day_html(target, now=now, group=GROUP, upcoming=nearest)


def _on(date: datetime.date, now: datetime.datetime, **kwargs) -> str:
    target = day(date, **kwargs)
    nearest = upcoming(date) if render_rich.needs_upcoming(target, now) else None
    return render_day_html(target, now=now, group=GROUP, upcoming=nearest)


GOLDEN_CASES = {
    "day_today_before_first": lambda: _today(at(25, 1, 22)),
    "day_today_second_pair": lambda: _today(at(25, 11, 30)),
    "day_today_break": lambda: _today(at(25, 10, 55)),
    "day_today_after_last": lambda: _today(at(25, 16, 0)),
    "day_tomorrow": lambda: _on(FRIDAY, at(24, 20, 0)),
    "day_no_pairs": lambda: _on(SUNDAY, at(26, 18, 0)),
    "day_one_pair": lambda: _on(SATURDAY, at(25, 20, 0)),
    "day_with_extra": lambda: _on(FRIDAY, at(25, 1, 22), extras=[UNITY_EXTRA]),
    "day_with_changes": lambda: _on(
        FRIDAY,
        at(25, 1, 22),
        overrides=[
            {"lesson_num": 1, "subgroup": None, "override_type": "cancel"},
            {"lesson_num": 2, "subgroup": None, "override_type": "room_change", "new_value": "420"},
            {"lesson_num": 2, "subgroup": None, "override_type": "note", "new_value": "Тест"},
            {
                "lesson_num": 3,
                "subgroup": None,
                "override_type": "online",
                "new_value": "https://meet.example.com/a?b=1&c=2",
            },
        ],
    ),
    "week_this_friday": lambda: render_week_html(
        week(MONDAY), now=at(25, 1, 22), group=GROUP, which="this"
    ),
    "week_this_saturday": lambda: render_week_html(
        week(MONDAY), now=at(26, 14, 0), group=GROUP, which="this"
    ),
    "week_this_sunday": lambda: render_week_html(
        week(MONDAY), now=at(27, 12, 0), group=GROUP, which="this"
    ),
    "week_next": lambda: render_week_html(
        week(MONDAY), now=at(18, 12, 0), group=GROUP, which="next"
    ),
    "week_month_boundary": lambda: render_week_html(
        week(datetime.date(2026, 9, 28)), now=at(30, 12, 0), group=GROUP, which="this"
    ),
}


@pytest.mark.parametrize("name", GOLDEN_CASES)
def test_golden(name):
    html = GOLDEN_CASES[name]()
    check_html(html)
    assert_golden(name, html)


def test_reference_day_matches_spec():
    html = _today(at(25, 1, 22))

    assert html.startswith(
        "<h3>Пятница, 25 сентября</h3>"
        '<p>3 пары, 09:20–15:00 · начало <tg-time unix="1790317200" format="r">'
        "в 09:20</tg-time></p>"
        "<table compact striped>"
        '<tr><td>09:20</td><td><mark>МДК 04.02</mark></td><td align="right">501</td></tr>'
        '<tr><td>11:00</td><td>История</td><td align="right">КЗ</td></tr>'
        '<tr><td>13:30</td><td>Ин. тех.</td><td align="right">КЗ</td></tr>'
        "</table>"
        "<details><summary>Полные названия и преподаватели</summary><table compact striped>"
        '<tr><td valign="top">09:20–10:50</td><td><b>Обеспечение качества функционирования'
        " компьютерных систем</b><br><i>Павлович Е.М.</i></td>"
        '<td align="right" valign="top">501</td></tr>'
    )
    assert html.endswith(f"</table></details><footer>{GROUP}</footer>")


# ── Статусная строка ──────────────────────────────────────


def _status(now: datetime.datetime, date: datetime.date = FRIDAY) -> str:
    html = render_day_html(day(date), now=now, group=GROUP)
    return re.search(r"<p>(.*?)</p>", html).group(1)


def _tg(hour: int, minute: int) -> str:
    unix = int(at(25, hour, minute).timestamp())
    return f'<tg-time unix="{unix}" format="r">в {hour:02d}:{minute:02d}</tg-time>'


@pytest.mark.parametrize(
    ("now", "status"),
    [
        (at(24, 20, 0), f"начало {_tg(9, 20)}"),  # день в будущем
        (at(25, 1, 22), f"начало {_tg(9, 20)}"),  # сегодня до первой пары
        (at(25, 9, 20), f"сейчас МДК 04.02, конец {_tg(10, 50)}"),  # начало первой
        (at(25, 11, 30), f"сейчас История, конец {_tg(12, 30)}"),  # идёт вторая
        (at(25, 10, 50), f"следующая {_tg(11, 0)}"),  # перемена, конец первой
        (at(25, 12, 45), f"следующая {_tg(13, 30)}"),  # большая перемена
    ],
)
def test_status_line(now, status):
    assert _status(now) == f"3 пары, 09:20–15:00 · {status}"


def test_after_last_pair_shows_next_study_day():
    html = _today(at(25, 15, 0))

    assert "<p>Пары на сегодня закончились.</p>" in html
    assert "<details><summary>Сегодняшние пары</summary><table" in html
    assert "<h3>Суббота, 26 сентября</h3><p>1 пара, 11:00–12:30 · начало" in html
    assert "<mark>" not in html


def test_nearest_pair_marked_only_today():
    assert "<mark>История</mark>" in _today(at(25, 10, 55))
    assert "<mark>" not in _on(FRIDAY, at(24, 20, 0))


def test_empty_day_without_upcoming():
    html = render_day_html(Day(SUNDAY), now=at(26, 18, 0), group=GROUP)

    assert html == f"<h3>Воскресенье, 27 сентября</h3><p>Пар нет.</p><footer>{GROUP}</footer>"


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


def test_extra_is_italic_marked_and_counted_separately():
    html = _on(FRIDAY, at(25, 1, 22), extras=[UNITY_EXTRA])

    assert "<p>3 пары + 1 доп, 09:20–18:20 · начало" in html
    assert '<tr><td>16:50</td><td><i>UNITY</i> · доп</td><td align="right">501</td></tr>' in html
    assert "<b><i>Разработка игр на движке UNITY</i></b> · доп<br><i>Павлович Е.М.</i>" in html


def test_changes_cancel_room_online_note():
    html = GOLDEN_CASES["day_with_changes"]()

    # Отменённая пара зачёркнута и не входит в счётчик и статус.
    assert html.startswith(
        f"<h3>Пятница, 25 сентября</h3><p>2 пары, 11:00–15:00 · начало {_tg(11, 0)}</p>"
    )
    assert '<td><s>МДК 04.02</s></td><td align="right"><s>501</s></td>' in html
    # В кратком виде — просто текущая аудитория, отметки только в подробностях.
    assert '<td><mark>История</mark></td><td align="right">420</td>' in html
    assert '<td align="right" valign="top"><b>420</b></td>' in html
    assert "<br><i>Хайруллина Д.Х.</i><br><i>Тест</i>" in html
    # Онлайн: в колонке аудитории текст, ссылка — абзацем внутри details.
    assert '<td>Ин. тех.</td><td align="right">онлайн</td>' in html
    assert (
        '<p>13:30 · Ин. тех. · онлайн: <a href="https://meet.example.com/a?b=1&amp;c=2">'
        "https://meet.example.com/a?b=1&amp;c=2</a></p></details>"
    ) in html


def test_missing_room_and_teacher():
    lesson = Lesson(
        start=at(25, 9, 20), end=at(25, 10, 50), short="Физика", full="Физика", room="", teacher=""
    )
    html = render_day_html(Day(FRIDAY, (lesson,)), now=at(24, 20, 0), group=GROUP)

    assert '<td>Физика</td><td align="right"></td>' in html
    assert "<td><b>Физика</b></td>" in html


def test_not_http_online_link_is_plain_text():
    lesson = Lesson(
        start=at(25, 9, 20),
        end=at(25, 10, 50),
        short="Физика",
        full="Физика",
        online=True,
        online_url="javascript:alert(1)",
    )
    html = render_day_html(Day(FRIDAY, (lesson,)), now=at(25, 1, 0), group=GROUP)

    check_html(html)
    assert "<a " not in html
    assert "онлайн: javascript:alert(1)</p>" in html


def test_all_cancelled_day():
    cancel = [{"lesson_num": n, "subgroup": None, "override_type": "cancel"} for n in range(1, 4)]
    html = _on(FRIDAY, at(25, 1, 22), overrides=cancel)

    check_html(html)
    assert "<p>Все пары отменены. Ближайшие: суббота, 26 сентября, начало" in html
    assert html.count("<s>") == 12  # название и аудитория, в кратком и подробном виде


def test_escaping_teacher_and_subject():
    lesson = Lesson(
        start=at(25, 9, 20),
        end=at(25, 10, 50),
        short="C++ & <Py>",
        full="C++ & <Py> «полное»",
        room="<1>",
        teacher="Иванов <b>& Ко",
    )
    html = render_day_html(Day(FRIDAY, (lesson,)), now=at(25, 1, 0), group="A&B")

    text = check_html(html)
    assert "<i>Иванов &lt;b&gt;&amp; Ко</i>" in html
    assert "Иванов <b>& Ко" in text
    assert "C++ & <Py>" in text
    assert "<footer>A&amp;B</footer>" in html


# ── Неделя ────────────────────────────────────────────────


def test_week_open_policy_this_week():
    html = render_week_html(week(MONDAY), now=at(23, 12, 45), group=GROUP, which="this")

    assert "<h3>Неделя 21–26 сентября</h3>" in html
    assert "<details><summary>Пн, 21 сентября · 3 пары</summary>" in html
    assert "<details><summary>Вт, 22 сентября · 3 пары</summary>" in html
    assert "<details open><summary><mark>Ср, 23 сентября · сегодня</mark></summary>" in html
    assert "<details open><summary>Чт, 24 сентября · 4 пары</summary>" in html
    assert "<details open><summary>Сб, 26 сентября · 1 пара</summary>" in html
    assert "Вс, 27" not in html  # воскресенье без пар не показываем
    assert "<mark>Физ. культ.</mark>" in html  # ближайшая пара внутри сегодняшнего дня


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
    assert "<mark>" not in html


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
        note="Принести ноутбук и зарядку, будет контрольная работа",
    )


def test_heaviest_week_and_day_fit_limit():
    days = [
        Day(MONDAY + datetime.timedelta(days=i), tuple(_heavy_lesson(MONDAY, n) for n in range(5)))
        for i in range(6)
    ]
    week_html = render_week_html(days, now=at(21, 1, 0), group=GROUP, which="this")
    day_html = render_day_html(days[0], now=at(21, 1, 0), group=GROUP)

    check_html(week_html)
    check_html(day_html)
    assert len(week_html) < RICH_TEXT_LIMIT // 4
    assert len(day_html) < RICH_TEXT_LIMIT // 4


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
                check_html(render_day_html(target, now=now, group=group, upcoming=nearest))
