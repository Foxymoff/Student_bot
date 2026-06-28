import datetime

from handlers.starosta import _date_text, _parse_subgroup


def test_parse_subgroup_returns_none_for_all():
    assert _parse_subgroup("all") is None


def test_parse_subgroup_returns_number_for_valid_value():
    assert _parse_subgroup("1") == 1
    assert _parse_subgroup("2") == 2


def test_parse_subgroup_returns_none_for_invalid_value():
    assert _parse_subgroup("") is None
    assert _parse_subgroup("abc") is None


def test_date_text_contains_day_number():
    result = _date_text(datetime.date(2026, 6, 2))

    assert "2" in result
