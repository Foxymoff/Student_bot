import json

import aiosqlite
import pytest
import pytest_asyncio

import database

GROUP_A = "ИСП-25-1"
GROUP_B = "ИСП-25-2"


@pytest_asyncio.fixture
async def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "bot.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    await database.init_db()
    return db_path


@pytest.mark.asyncio
async def test_add_user_keeps_extra_settings_for_same_group(temp_db):
    await database.add_user(1, GROUP_A)
    await database.update_user_extra_choices(1, ["extra-a", "extra-b"])
    await database.update_user_extra_in_schedule(1, True)

    await database.add_user(1, GROUP_A)

    user = await database.get_user(1)
    assert json.loads(user["extra_choices"]) == ["extra-a", "extra-b"]
    assert user["extra_in_schedule"] == 1


@pytest.mark.asyncio
async def test_add_user_resets_extra_settings_when_group_changes(temp_db):
    await database.add_user(1, GROUP_A)
    await database.update_user_extra_choices(1, ["extra-a"])
    await database.update_user_extra_in_schedule(1, True)

    await database.add_user(1, GROUP_B)

    user = await database.get_user(1)
    assert user["group_name"] == GROUP_B
    assert json.loads(user["extra_choices"]) == []
    assert user["extra_in_schedule"] == 0


@pytest.mark.asyncio
async def test_update_user_daily_notify_disable_clears_last_sent_date(temp_db):
    await database.add_user(1, GROUP_A)
    await database.update_user_daily_notify(1, True, "09:30", False)
    await database.mark_user_daily_notify_sent(1, "2026-07-01")

    await database.update_user_daily_notify(1, False)

    user = await database.get_user(1)
    assert user["daily_notify_enabled"] == 0
    assert user["daily_notify_last_date"] is None
    assert user["daily_notify_time"] == "09:30"
    assert user["daily_notify_sound"] == 0


@pytest.mark.asyncio
async def test_lesson_overrides_are_filtered_and_deleted_by_subgroup(temp_db):
    await database.add_override(GROUP_A, "2026-07-01", 1, "room_change", "101", subgroup=1)
    await database.add_override(GROUP_A, "2026-07-01", 1, "room_change", "202", subgroup=2)
    await database.add_override(GROUP_A, "2026-07-01", 1, "note", "general note")

    subgroup_one = await database.get_lesson_overrides(GROUP_A, "2026-07-01", 1, subgroup=1)
    subgroup_two = await database.get_lesson_overrides(GROUP_A, "2026-07-01", 1, subgroup=2)
    common = await database.get_lesson_overrides(GROUP_A, "2026-07-01", 1)

    assert [override["new_value"] for override in subgroup_one] == ["101"]
    assert [override["new_value"] for override in subgroup_two] == ["202"]
    assert [override["new_value"] for override in common] == ["general note"]

    deleted = await database.delete_lesson_overrides(GROUP_A, "2026-07-01", 1, subgroup=1)

    assert deleted == 1
    assert await database.get_lesson_overrides(GROUP_A, "2026-07-01", 1, subgroup=1) == []
    assert await database.get_lesson_overrides(GROUP_A, "2026-07-01", 1, subgroup=2)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"group_name": "UNKNOWN"}, "Неизвестная группа"),
        ({"date": "bad-date"}, "Invalid isoformat"),
        ({"override_type": "bad-type"}, "Некорректный тип"),
        ({"lesson_num": 0}, "Номер пары"),
        ({"subgroup": 3}, "Некорректная подгруппа"),
    ],
)
async def test_add_override_validates_input(temp_db, kwargs, message):
    params = {
        "group_name": GROUP_A,
        "date": "2026-07-01",
        "lesson_num": 1,
        "override_type": "note",
        "new_value": "test",
        "subgroup": None,
    }
    params.update(kwargs)

    with pytest.raises(ValueError, match=message):
        await database.add_override(**params)


@pytest.mark.asyncio
async def test_pending_alerts_expire_after_24h(temp_db):
    # Свежий алерт ещё не истёк.
    await database.add_pending_alert(100, 555)
    assert await database.get_expired_alerts() == []

    # Ставим ему возраст 25 часов — теперь он должен попасть в устаревшие.
    async with aiosqlite.connect(temp_db) as db:
        await db.execute(
            "UPDATE pending_alerts SET created_at = datetime('now', '-25 hours') "
            "WHERE user_id = ? AND message_id = ?",
            (100, 555),
        )
        await db.commit()

    expired = await database.get_expired_alerts()
    assert len(expired) == 1
    assert expired[0]["user_id"] == 100
    assert expired[0]["message_id"] == 555

    await database.delete_pending_alerts([expired[0]["id"]])
    assert await database.get_expired_alerts() == []


@pytest.mark.asyncio
async def test_delete_pending_alert_removes_specific_row(temp_db):
    await database.add_pending_alert(1, 10)
    await database.add_pending_alert(1, 11)

    await database.delete_pending_alert(1, 10)

    async with aiosqlite.connect(temp_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT message_id FROM pending_alerts WHERE user_id = 1")
        rows = [r["message_id"] for r in await cursor.fetchall()]
    assert rows == [11]


@pytest.mark.asyncio
async def test_delete_pending_alerts_empty_is_noop(temp_db):
    await database.add_pending_alert(1, 10)
    await database.delete_pending_alerts([])

    async with aiosqlite.connect(temp_db) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM pending_alerts")
        (count,) = await cursor.fetchone()
    assert count == 1
