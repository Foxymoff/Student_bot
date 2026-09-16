from keyboards import ADMIN_LIST_LIMIT, admin_users_kb


def _students(n: int) -> list[dict]:
    return [{"user_id": i, "group_name": "ИСП-25-2", "role": "student"} for i in range(n)]


def test_admin_users_kb_small_list_has_no_overflow_button():
    kb = admin_users_kb(_students(5))
    assert len(kb.inline_keyboard) == 5
    assert all(row[0].callback_data.startswith("admin_set_starosta:") for row in kb.inline_keyboard)


def test_admin_users_kb_caps_and_routes_overflow_to_search():
    total = ADMIN_LIST_LIMIT + 31
    kb = admin_users_kb(_students(total))

    # Ровно лимит плиток + одна кнопка-подсказка, значит клавиатура не упрётся
    # в лимит Telegram на число кнопок.
    assert len(kb.inline_keyboard) == ADMIN_LIST_LIMIT + 1
    last = kb.inline_keyboard[-1][0]
    assert last.callback_data == "admin:search"
    assert "31" in last.text
