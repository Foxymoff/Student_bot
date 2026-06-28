from extra_schedule import parse_extra_choices


def test_parse_extra_choices_returns_empty_list_for_none():
    assert parse_extra_choices(None) == []


def test_parse_extra_choices_returns_empty_list_for_empty_string():
    assert parse_extra_choices("") == []


def test_parse_extra_choices_returns_list_for_valid_json():
    assert parse_extra_choices('["math", "english"]') == ["math", "english"]


def test_parse_extra_choices_returns_empty_list_for_invalid_json():
    assert parse_extra_choices("not-json") == []
