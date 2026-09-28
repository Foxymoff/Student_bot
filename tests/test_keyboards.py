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


from keyboards import settings_menu_kb, settings_view_kb  # noqa: E402


def test_settings_view_kb_is_only_compact_toggle():
    assert _cb_set(settings_view_kb(True)) == {"settings:compact:0", "settings:back"}
    assert _cb_set(settings_view_kb(False)) == {"settings:compact:1", "settings:back"}


def test_settings_menu_view_row_only_for_classic():
    classic = settings_menu_kb(True, classic=True)
    rich = settings_menu_kb(True, classic=False)

    assert classic.inline_keyboard[0][0].text == "📱 Вид расписания: Компактный"
    assert "settings:view" not in _cb_set(rich)  # у нового вида настроек вида нет


from keyboards import main_menu_kb, schedule_period_reply_kb  # noqa: E402


def test_main_menu_without_links_and_extras():
    student = [b.text for row in main_menu_kb().keyboard for b in row]
    admin = [b.text for row in main_menu_kb("admin").keyboard for b in row]

    assert student == ["📅 Расписание"]  # ссылки — в меню команд (/links), кружки — в расписании
    assert admin == ["📅 Расписание", "📋 Староста", "⚙️ Админ"]


def test_settings_menu_has_no_extra_display_row():
    kb = settings_menu_kb(False)

    assert not any(
        b.callback_data.startswith("settings:extra") for row in kb.inline_keyboard for b in row
    )


def test_reply_accent_buttons_are_primary_and_text_unchanged():
    menu = main_menu_kb()
    period = schedule_period_reply_kb()

    assert (menu.keyboard[0][0].text, menu.keyboard[0][0].style) == ("📅 Расписание", "primary")
    assert (period.keyboard[0][0].text, period.keyboard[0][0].style) == ("Сегодня", "primary")
    assert period.keyboard[0][1].style is None
    assert period.keyboard[2][0].text == "⬅️ Назад"


def test_settings_kb_maps_user_fields_to_labels():
    """Порядок позиционных аргументов settings_menu_kb: сдвиг ломает подписи меню."""
    from handlers.start import _settings_kb

    user = {
        "compact_mode": 1,
        "daily_notify_enabled": 1,
        "daily_notify_time": "09:30",
        "change_alert_enabled": 1,
        "daily_notify_target": "tomorrow",
        "classic_view": 1,
    }
    labels = [row[0].text for row in _settings_kb(user).inline_keyboard]

    assert labels == [
        "📱 Вид расписания: Компактный",
        "🔔 Ежедневное расписание: 🌙 09:30",
        "🚨 Алерты изменений: вкл.",
        "⬅️ Главное меню",
    ]
    # Новый вид: пункта «Вид расписания» нет, остальное на местах.
    rich_labels = [row[0].text for row in _settings_kb({**user, "classic_view": 0}).inline_keyboard]
    assert rich_labels == labels[1:]
