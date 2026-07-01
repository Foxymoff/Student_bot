import datetime

import extra_schedule
from extra_schedule import (
    format_extra_day,
    get_extra_options,
    get_extra_week,
    get_extras_for_date,
    make_extra_key,
)

EXTRA_A = {
    "type": "club",
    "subject": "Компьютерное моделирование",
    "time": "16:00-17:00",
    "room": "Спорткомплекс",
    "teacher": "Teacher A",
    "note": "группа A",
}

EXTRA_A_SAME_IDENTITY = {
    **EXTRA_A,
    "time": "18:00-19:00",
    "room": "Конференц-зал",
}

EXTRA_B = {
    "type": "club",
    "subject": "Медиа-мастерская",
    "time": "17:00-18:00",
    "room": "Школа",
    "teacher": "Teacher B",
    "note": "группа B",
}


def test_make_extra_key_is_stable_for_same_course_identity():
    assert make_extra_key(EXTRA_A) == make_extra_key(EXTRA_A_SAME_IDENTITY)


def test_make_extra_key_changes_when_course_identity_changes():
    changed = {**EXTRA_A, "teacher": "Another teacher"}

    assert make_extra_key(EXTRA_A) != make_extra_key(changed)


def test_get_extra_options_deduplicates_options_by_key(monkeypatch):
    monkeypatch.setattr(
        extra_schedule,
        "_load_extra_schedule",
        lambda _group_name: {
            "weeks": {
                "even": {
                    "Понедельник": {
                        "extra": [EXTRA_A, EXTRA_A_SAME_IDENTITY, EXTRA_B],
                    }
                }
            }
        },
    )

    options = get_extra_options("ИСП-25-1")

    assert len(options) == 2
    assert [option["_key"] for option in options] == [
        make_extra_key(EXTRA_A),
        make_extra_key(EXTRA_B),
    ]


def test_get_extra_week_returns_only_selected_options(monkeypatch):
    monkeypatch.setattr(
        extra_schedule,
        "_load_extra_schedule",
        lambda _group_name: {
            "weeks": {
                "even": {
                    "Понедельник": {"extra": [EXTRA_A]},
                    "Вторник": {"extra": [EXTRA_B]},
                }
            }
        },
    )

    result = get_extra_week("ИСП-25-1", [make_extra_key(EXTRA_B)])

    assert len(result) == 1
    assert result[0][0] == "Вторник"
    assert result[0][1][0]["_key"] == make_extra_key(EXTRA_B)


def test_get_extras_for_date_uses_week_type_and_weekday(monkeypatch):
    monkeypatch.setattr(extra_schedule, "_get_week_type", lambda _date: "even")
    monkeypatch.setattr(
        extra_schedule,
        "_load_extra_schedule",
        lambda _group_name: {
            "weeks": {
                "even": {"Понедельник": {"extra": [EXTRA_A]}},
                "odd": {"Понедельник": {"extra": [EXTRA_B]}},
            }
        },
    )

    result = get_extras_for_date(
        "ИСП-25-1",
        datetime.date(2026, 7, 6),
        [make_extra_key(EXTRA_A), make_extra_key(EXTRA_B)],
    )

    assert len(result) == 1
    assert result[0]["_key"] == make_extra_key(EXTRA_A)


def test_format_extra_day_escapes_html_and_shortens_room():
    result = format_extra_day(
        [
            {
                "subject": "A <B>",
                "time": "16:00",
                "room": "Спорткомплекс",
                "teacher": "T & C",
                "note": "x < y",
            }
        ],
        datetime.date(2026, 7, 6),
    )

    assert "A &lt;B&gt;" in result
    assert "СК" in result
    assert "T &amp; C" in result
    assert "x &lt; y" in result
