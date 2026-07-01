import datetime

from handlers import schedule


def test_filter_by_subgroup_uses_subject_specific_subgroups():
    lessons = [
        {"num": 1, "subject": "Информатика", "subgroup": 1},
        {"num": 1, "subject": "Информатика", "subgroup": 2},
        {"num": 2, "subject": "Иностранный язык", "subgroup": 1},
        {"num": 2, "subject": "Иностранный язык", "subgroup": 2},
        {"num": 3, "subject": "История"},
        {
            "num": 4,
            "subject": "Математика",
            "subgroups": [
                {"group": 1, "room": "101", "teacher": "Teacher 1"},
                {"group": 2, "room": "202", "teacher": "Teacher 2"},
            ],
        },
    ]

    result = schedule._filter_by_subgroup(lessons, sg_inf=1, sg_eng=2)

    assert [lesson["num"] for lesson in result] == [1, 2, 3, 4]
    assert result[0]["subgroup"] == 1
    assert result[1]["subgroup"] == 2
    assert result[3]["_sg_group"] == 1
    assert result[3]["_sg_room"] == "101"
    assert result[3]["_sg_teacher"] == "Teacher 1"


def test_apply_overrides_respects_subgroups_and_sets_flags():
    lessons = [
        {"num": 1, "subject": "Информатика", "subgroup": 1, "room": "101"},
        {"num": 1, "subject": "Информатика", "subgroup": 2, "room": "201"},
        {"num": 2, "subject": "История", "room": "301"},
    ]
    overrides = [
        {
            "lesson_num": 1,
            "subgroup": 2,
            "override_type": "room_change",
            "new_value": "202",
            "comment": "room changed",
        },
        {
            "lesson_num": 1,
            "subgroup": 1,
            "override_type": "note",
            "new_value": "bring laptop",
        },
        {
            "lesson_num": 2,
            "subgroup": None,
            "override_type": "cancel",
            "comment": "cancelled",
        },
    ]

    result = schedule._apply_overrides(lessons, overrides)

    assert result[0]["room"] == "101"
    assert result[0]["_note"] == "bring laptop"
    assert result[1]["room"] == "202"
    assert result[1]["_original_room"] == "201"
    assert result[1]["_room_changed"] is True
    assert result[2]["_cancelled"] is True
    assert result[2]["_override_comment"] == "cancelled"


def test_fill_gaps_adds_empty_lessons_between_existing_numbers():
    result = schedule._fill_gaps(
        [
            {"num": 1, "subject": "First"},
            {"num": 3, "subject": "Third"},
        ]
    )

    assert result == [
        {"num": 1, "subject": "First"},
        {"num": 2, "_empty": True},
        {"num": 3, "subject": "Third"},
    ]


def test_format_day_short_escapes_html_and_includes_extras():
    result = schedule.format_day_short(
        [{"num": 1, "subject": "Math <A>", "room": "101"}],
        datetime.date(2026, 7, 6),
        extras=[{"subject": "Extra & Class", "time": "16:00", "room": "Спорткомплекс"}],
        compact=True,
    )

    assert "Math &lt;A&gt;" in result
    assert "Extra &amp; Class" in result
    assert "СК" in result
    assert "<A>" not in result


def test_format_day_detailed_applies_online_and_note_overrides():
    result = schedule.format_day_detailed(
        [
            {
                "num": 1,
                "subject": "Math",
                "time": "09:00",
                "room": "101",
                "teacher": "Teacher",
            }
        ],
        datetime.date(2026, 7, 6),
        overrides=[
            {
                "lesson_num": 1,
                "subgroup": None,
                "override_type": "online",
                "new_value": "https://example.com?a=1&b=2",
            },
            {
                "lesson_num": 1,
                "subgroup": None,
                "override_type": "note",
                "new_value": "read <chapter>",
            },
        ],
    )

    assert "ОНЛ" in result
    assert "https://example.com?a=1&amp;b=2" in result
    assert "read &lt;chapter&gt;" in result


def test_split_text_splits_long_text_without_dropping_lines():
    chunks = schedule._split_text("line1\nline2\nline3", max_len=11)

    assert chunks == ["line1\nline2", "line3"]
