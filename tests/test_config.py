import pytest

from config import _parse_int_set


def test_parse_int_set_returns_empty_set_for_empty_value():
    assert _parse_int_set("") == set()
    assert _parse_int_set(" , ; ") == set()


def test_parse_int_set_supports_commas_semicolons_and_spaces():
    assert _parse_int_set("123, 456;789") == {123, 456, 789}


def test_parse_int_set_deduplicates_values():
    assert _parse_int_set("123,123; 123") == {123}


def test_parse_int_set_rejects_non_numeric_values():
    with pytest.raises(ValueError, match="ADMIN_USER_IDS"):
        _parse_int_set("123, not-a-number")
