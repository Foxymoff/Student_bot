from ui_messages import _normalise_ids, collect_ui_message_ids


def test_normalise_ids_flattens_deduplicates_and_ignores_invalid_values():
    assert _normalise_ids([1, "2", [2, "3", "bad"], None, "", []]) == [1, 2, 3]


def test_collect_ui_message_ids_combines_current_and_legacy_keys():
    data = {
        "ui_msg_ids": [1, "2"],
        "last_bot_msg": "2",
        "last_schedule_msg": 4,
        "last_extra_msg": "bad",
    }

    assert collect_ui_message_ids(data) == [1, 2, 4]
