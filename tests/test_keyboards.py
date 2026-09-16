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


from keyboards import starosta_pair_actions_kb  # noqa: E402


def _cb_set(kb):
    return {b.callback_data for row in kb.inline_keyboard for b in row}


def test_starosta_pair_actions_has_rename_online_cancel():
    cbs = _cb_set(starosta_pair_actions_kb(is_added=False))
    for action in ("room", "rename", "online", "cancel", "note", "rollback"):
        assert f"starosta_action:{action}" in cbs


def test_starosta_pair_actions_parity_added_gets_online_and_cancel():
    # Добавленная пара теперь имеет тот же набор действий, что и обычная.
    regular = _cb_set(starosta_pair_actions_kb(is_added=False))
    added = _cb_set(starosta_pair_actions_kb(is_added=True))
    assert regular == added
    assert "starosta_action:online" in added
    assert "starosta_action:cancel" in added


def test_starosta_pair_actions_last_button_label_differs():
    regular = starosta_pair_actions_kb(is_added=False)
    added = starosta_pair_actions_kb(is_added=True)
    labels_regular = [b.text for row in regular.inline_keyboard for b in row]
    labels_added = [b.text for row in added.inline_keyboard for b in row]
    assert any("Откатить" in t for t in labels_regular)
    assert any("Удалить пару" in t for t in labels_added)
