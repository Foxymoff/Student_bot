"""
Клавиатуры бота: reply-кнопки и inline-кнопки.
"""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from config import ENG_SUBGROUPS, GROUPS

# ── Reply-клавиатуры ──────────────────────────────────────


def main_menu_kb(role: str = "student", show_extra_button: bool = True) -> ReplyKeyboardMarkup:
    """Главное меню бота (зависит от роли)."""
    link_row = [KeyboardButton(text="🔗 Полезные ссылки")]
    if show_extra_button:
        link_row.append(KeyboardButton(text="📌 Доп. занятия"))
    rows = [
        [KeyboardButton(text="📅 Расписание")],
        link_row,
    ]
    if role == "starosta":
        rows.append([KeyboardButton(text="📋 Староста")])
    elif role == "admin":
        rows.append([KeyboardButton(text="📋 Староста"), KeyboardButton(text="⚙️ Админ")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def back_kb() -> ReplyKeyboardMarkup:
    """Клавиатура с кнопкой Назад."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Назад")]],
        resize_keyboard=True,
        is_persistent=True,
    )


def main_menu_only_kb() -> ReplyKeyboardMarkup:
    """Клавиатура быстрого выхода в главное меню."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🏠 Главное меню")]],
        resize_keyboard=True,
        is_persistent=True,
    )


# ── Inline-клавиатуры ─────────────────────────────────────


def group_select_kb(prefix: str = "group", include_back: bool = False) -> InlineKeyboardMarkup:
    """Выбор группы (prefix задаёт callback-префикс)."""
    buttons = [[InlineKeyboardButton(text=g, callback_data=f"{prefix}:{g}")] for g in GROUPS]
    if include_back:
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="profile:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def other_group_select_kb(current_group: str) -> InlineKeyboardMarkup:
    """Выбор другой группы для просмотра расписания."""
    buttons = [
        [InlineKeyboardButton(text=g, callback_data=f"other_group:{g}")]
        for g in GROUPS
        if g != current_group
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def subgroup_select_kb(
    subject_key: str,
    prefix: str = "sg",
    include_back: bool = False,
) -> InlineKeyboardMarkup:
    """Выбор подгруппы (1 или 2)."""
    buttons = [
        [
            InlineKeyboardButton(text="Подгруппа 1", callback_data=f"{prefix}:{subject_key}:1"),
            InlineKeyboardButton(text="Подгруппа 2", callback_data=f"{prefix}:{subject_key}:2"),
        ]
    ]
    if include_back:
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="profile:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def eng_subgroup_select_kb(
    group_name: str,
    prefix: str = "sg",
    include_back: bool = False,
) -> InlineKeyboardMarkup:
    """Выбор подгруппы по английскому с названиями уровней и преподавателей."""
    labels = ENG_SUBGROUPS.get(group_name, {1: "Подгруппа 1", 2: "Подгруппа 2"})
    buttons = [
        [InlineKeyboardButton(text=labels[1], callback_data=f"{prefix}:eng:1")],
        [InlineKeyboardButton(text=labels[2], callback_data=f"{prefix}:eng:2")],
    ]
    if include_back:
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="profile:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def schedule_period_reply_kb() -> ReplyKeyboardMarkup:
    """Выбор периода расписания (reply-кнопки)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Сегодня"), KeyboardButton(text="Завтра")],
            [KeyboardButton(text="Эта неделя"), KeyboardButton(text="След. неделя")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def schedule_detail_kb(date_iso: str) -> InlineKeyboardMarkup:
    """Кнопка 'Подробнее' под кратким расписанием."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📖 Подробнее", callback_data=f"schedule_detail:{date_iso}")]
        ]
    )


def schedule_collapse_kb(date_iso: str) -> InlineKeyboardMarkup:
    """Кнопка 'Свернуть' под подробным расписанием."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Свернуть", callback_data=f"schedule_collapse:{date_iso}"
                )
            ]
        ]
    )


def extra_detail_kb() -> InlineKeyboardMarkup:
    """Кнопка 'Подробнее' под кратким расписанием доп. занятий."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📖 Подробнее", callback_data="extra_detail")]]
    )


def extra_collapse_kb() -> InlineKeyboardMarkup:
    """Кнопка 'Свернуть' под подробным расписанием доп. занятий."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📋 Свернуть", callback_data="extra_collapse")]]
    )


def extra_select_kb(
    options: list[dict],
    selected_keys: set[str] | list[str],
    prefix: str = "extra",
    include_back: bool = False,
) -> InlineKeyboardMarkup:
    """Мультивыбор доп. занятий."""
    selected = set(selected_keys)
    buttons: list[list[InlineKeyboardButton]] = []
    for index, option in enumerate(options):
        mark = "✅" if option["_key"] in selected else "⬜"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{mark} {option['_label']}",
                    callback_data=f"{prefix}:toggle:{index}",
                )
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(text="✅ Готово", callback_data=f"{prefix}:done"),
        ]
    )
    buttons.append(
        [
            InlineKeyboardButton(text="Без доп. занятий", callback_data=f"{prefix}:none"),
        ]
    )
    if include_back:
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="profile:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def extra_display_kb(prefix: str = "extra_display") -> InlineKeyboardMarkup:
    """Выбор, где показывать доп. занятия."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 В расписании", callback_data=f"{prefix}:1")],
            [InlineKeyboardButton(text="📌 Отдельной кнопкой", callback_data=f"{prefix}:0")],
        ]
    )


def daily_notify_kb(prefix: str = "daily_notify") -> InlineKeyboardMarkup:
    """Выбор, нужно ли ежедневное уведомление."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да", callback_data=f"{prefix}:1")],
            [InlineKeyboardButton(text="Нет", callback_data=f"{prefix}:0")],
        ]
    )


def daily_time_back_kb(callback_data: str) -> InlineKeyboardMarkup:
    """Назад с экрана ввода времени ежедневного уведомления."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=callback_data)]]
    )


def daily_notify_sound_kb(prefix: str = "daily_sound") -> InlineKeyboardMarkup:
    """Выбор звука для ежедневного уведомления."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔔 Со звуком", callback_data=f"{prefix}:1")],
            [InlineKeyboardButton(text="🔕 Без звука", callback_data=f"{prefix}:0")],
        ]
    )


def settings_menu_kb(
    compact: bool,
    extra_in_schedule: bool,
    daily_notify_enabled: bool = False,
    daily_notify_time: str = "08:00",
    change_alert_enabled: bool = False,
) -> InlineKeyboardMarkup:
    """Главное inline-меню настроек."""
    view_label = "Компактный" if compact else "Колонки"
    extra_label = "в расписании" if extra_in_schedule else "отдельной кнопкой"
    notify_label = daily_notify_time if daily_notify_enabled else "выкл."
    alert_label = "вкл." if change_alert_enabled else "выкл."
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"📱 Вид расписания: {view_label}", callback_data="settings:view"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"📌 Доп. занятия: {extra_label}", callback_data="settings:extra"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"☀️ Ежедневное расписание: {notify_label}", callback_data="settings:daily"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🚨 Алерты изменений: {alert_label}", callback_data="settings:alert"
                )
            ],
            [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="settings:main")],
        ]
    )


def profile_menu_kb() -> InlineKeyboardMarkup:
    """Меню учебного профиля."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎓 Сменить группу", callback_data="profile:group")],
            [InlineKeyboardButton(text="👥 Сменить подгруппы", callback_data="profile:subgroups")],
            [InlineKeyboardButton(text="📌 Изменить доп. занятия", callback_data="profile:extra")],
            [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="profile:main")],
        ]
    )


def settings_view_kb(compact: bool) -> InlineKeyboardMarkup:
    """Настройки компактного/колоночного режима."""
    toggle_text = "Переключить на колонки" if compact else "Переключить на компактный"
    toggle_data = "settings:compact:0" if compact else "settings:compact:1"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle_text, callback_data=toggle_data)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:back")],
        ]
    )


def settings_extra_display_kb(extra_in_schedule: bool) -> InlineKeyboardMarkup:
    """Настройки отображения доп. занятий."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=("✅ В расписании" if extra_in_schedule else "В расписании"),
                    callback_data="settings:extra_display:1",
                )
            ],
            [
                InlineKeyboardButton(
                    text=("✅ Отдельной кнопкой" if not extra_in_schedule else "Отдельной кнопкой"),
                    callback_data="settings:extra_display:0",
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:back")],
        ]
    )


def settings_daily_notify_kb(enabled: bool, sound: bool) -> InlineKeyboardMarkup:
    """Настройки ежедневного уведомления."""
    buttons: list[list[InlineKeyboardButton]] = []
    if enabled:
        buttons.extend(
            [
                [InlineKeyboardButton(text="Выключить", callback_data="settings:daily_enabled:0")],
                [InlineKeyboardButton(text="Изменить время", callback_data="settings:daily_time")],
                [
                    InlineKeyboardButton(
                        text=("🔔 Со звуком" if sound else "🔕 Без звука"),
                        callback_data=f"settings:daily_sound:{0 if sound else 1}",
                    )
                ],
            ]
        )
    else:
        buttons.append(
            [InlineKeyboardButton(text="Включить", callback_data="settings:daily_enabled:1")]
        )
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def settings_change_alert_kb(enabled: bool, sound: bool) -> InlineKeyboardMarkup:
    """Настройки алертов об изменениях расписания."""
    buttons: list[list[InlineKeyboardButton]] = []
    if enabled:
        buttons.extend(
            [
                [InlineKeyboardButton(text="Выключить", callback_data="settings:alert_enabled:0")],
                [
                    InlineKeyboardButton(
                        text=("🔔 Со звуком" if sound else "🔕 Без звука"),
                        callback_data=f"settings:alert_sound:{0 if sound else 1}",
                    )
                ],
            ]
        )
    else:
        buttons.append(
            [InlineKeyboardButton(text="Включить", callback_data="settings:alert_enabled:1")]
        )
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def alert_delete_kb() -> InlineKeyboardMarkup:
    """Кнопка удаления алерта из чата."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Скрыть", callback_data="alert:delete")]]
    )


# ── Староста ──────────────────────────────────────────────


def starosta_week_dates_kb(dates: list[dict], next_week: bool) -> InlineKeyboardMarkup:
    """Выбор учебного дня для панели старосты."""
    buttons = [
        [InlineKeyboardButton(text=item["_label"], callback_data=f"starosta_day:{item['date']}")]
        for item in dates
    ]
    switch_text = "Текущая неделя" if next_week else "Следующая неделя"
    switch_value = 0 if next_week else 1
    buttons.append(
        [InlineKeyboardButton(text=switch_text, callback_data=f"starosta_week:{switch_value}")]
    )
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="starosta_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def starosta_day_lessons_kb(lessons: list[dict]) -> InlineKeyboardMarkup:
    """Пары выбранного дня в панели старосты."""
    buttons = [
        [InlineKeyboardButton(text=lesson["_label"], callback_data=lesson["_callback"])]
        for lesson in lessons
    ]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="starosta_dates")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def starosta_lesson_actions_kb() -> InlineKeyboardMarkup:
    """Действия с выбранной парой."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Изменить аудиторию", callback_data="starosta_action:room"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔗 Добавить ссылку на онлайн", callback_data="starosta_action:online"
                )
            ],
            [InlineKeyboardButton(text="❌ Отменить пару", callback_data="starosta_action:cancel")],
            [
                InlineKeyboardButton(
                    text="📝 Добавить примечание", callback_data="starosta_action:note"
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Откатить изменения", callback_data="starosta_action:rollback"
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="starosta_back:lessons")],
        ]
    )


def starosta_input_back_kb() -> InlineKeyboardMarkup:
    """Назад из экрана ввода значения для пары."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="starosta_back:actions")]
        ]
    )


def starosta_confirm_kb(prefix: str) -> InlineKeyboardMarkup:
    """Подтверждение действия с парой."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data=f"{prefix}:yes"),
                InlineKeyboardButton(text="Нет", callback_data=f"{prefix}:no"),
            ]
        ]
    )


# ── Админ ─────────────────────────────────────────────────


def admin_menu_kb() -> InlineKeyboardMarkup:
    """Меню администратора."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👑 Назначить старосту", callback_data="admin:set_starosta"
                )
            ],
            [InlineKeyboardButton(text="🚫 Снять старосту", callback_data="admin:remove_starosta")],
        ]
    )


def _admin_user_label(user: dict) -> str:
    """Подпись пользователя в админских списках."""
    name = str(user.get("_display_name") or "").strip()
    if not name:
        username = str(user.get("username") or "").strip()
        if username:
            name = f"@{username.lstrip('@')}"
    if not name:
        first_name = str(user.get("first_name") or "").strip()
        last_name = str(user.get("last_name") or "").strip()
        name = " ".join(part for part in (first_name, last_name) if part)
    if not name:
        name = f"ID {user['user_id']}"

    if len(name) > 32:
        name = f"{name[:31]}…"
    return f"{name} · {user['group_name']}"


def admin_users_kb(users: list[dict]) -> InlineKeyboardMarkup:
    """Список пользователей для назначения старостой."""
    buttons = []
    for u in users:
        label = _admin_user_label(u)
        buttons.append(
            [InlineKeyboardButton(text=label, callback_data=f"admin_set_starosta:{u['user_id']}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_starostas_kb(users: list[dict]) -> InlineKeyboardMarkup:
    """Список старост для снятия."""
    buttons = []
    for u in users:
        label = _admin_user_label(u)
        buttons.append(
            [InlineKeyboardButton(text=label, callback_data=f"admin_rm_starosta:{u['user_id']}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)
