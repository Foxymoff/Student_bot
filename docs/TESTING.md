# Testing

This document describes how the project is checked before changes are merged or deployed.

The bot has two testing layers:

- Automated checks for code quality and selected business logic.
- Manual Telegram smoke testing for flows that require a real bot, Telegram UI, or persistent runtime state.

## Current Coverage

Automated tests currently cover helper-level behavior and selected business logic that do not require Telegram API access or production data:

- Environment allowlist parsing in `config.py`.
- User settings, notification settings, and schedule override logic in `database.py`.
- Extra class choice parsing in `extra_schedule.py`.
- Extra class keys, option deduplication, date/week selection, and formatting in `extra_schedule.py`.
- Schedule subgroup filtering, override application, gap filling, text splitting, and formatting in `handlers/schedule.py`.
- Selected group leader helper functions in `handlers/starosta.py`.
- UI message id normalization in `ui_messages.py`.

Telegram-specific flows are still validated manually with a separate test bot.

## Local Automated Checks

Install runtime and development dependencies first:

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Run the Python checks:

```bash
ruff check .
ruff format --check .
pytest -v --cov=. --cov-report=term-missing
```

For full CI parity, also run the Docker checks when Docker is available locally:

```bash
docker compose config
docker compose build
```

If the formatting check fails, apply formatting and run the checks again:

```bash
ruff format .
ruff check .
pytest -v --cov=. --cov-report=term-missing
```

Pytest configuration is stored in `pyproject.toml`. The test suite is located in `tests/`.

## Continuous Integration

GitHub Actions runs on:

- Pull requests.
- Pushes to `main`.

The CI workflow has a Python job that uses Python 3.14 and runs:

```bash
ruff check .
ruff format --check .
pytest -v --cov=. --cov-report=term-missing
```

It also has a Docker job that runs:

```bash
docker compose config
docker compose build
```

Required environment variables are stubbed in CI:

```env
BOT_TOKEN=test-token
ADMIN_PASSWORD=test-password
```

CI does not start the Telegram bot and does not call the Telegram API. The Docker job validates the Compose configuration and verifies that the image can be built.

## Test Environments

Use separate environments for local testing and production.

| Environment | Purpose | Bot token | Database |
| --- | --- | --- | --- |
| Local test | Check changes before deployment | Test bot token | Local test database |
| Production | Real users | Production bot token | Production database |

Rules:

- Do not use the production bot token locally.
- Do not use production data for local testing.
- Do not commit `.env`, bot tokens, SQLite databases, logs, or local cache files.
- Use a separate test Telegram bot for manual checks.

## Local Docker Smoke Test

Create `.env` from `.env.example` and fill it with a test bot token:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Build and start the bot:

```bash
docker compose up -d --build
```

View logs:

```bash
docker compose logs -f bot
```

Restart the bot:

```bash
docker compose restart bot
```

Stop the bot:

```bash
docker compose down
```

In Docker, `DB_DIR=/data` is configured in `docker-compose.yml`, and the SQLite database is stored in the `bot-data` volume.

## Manual Test Checklist

### Startup

- [ ] Docker image builds successfully.
- [ ] Container starts successfully.
- [ ] Logs do not contain critical errors.
- [ ] Bot responds to `/start`.

### Registration and Profile

- [ ] New user can start registration.
- [ ] User can select a group.
- [ ] User can select informatics and English subgroups.
- [ ] User can open `/profile`.
- [ ] User can change group and subgroups.
- [ ] User settings are saved after restart.

### Schedule

- [ ] User can open the schedule from the main menu.
- [ ] User can view today's schedule.
- [ ] User can view tomorrow's schedule.
- [ ] User can view the current week.
- [ ] User can view the next week.
- [ ] Even and odd weeks are detected correctly.
- [ ] Lessons are filtered by group.
- [ ] Lessons are filtered by subgroup.
- [ ] Empty schedule is handled without crashing.
- [ ] Compact and detailed schedule views work.

### Other Groups

- [ ] User can open `/groups`.
- [ ] User can view another group's schedule.
- [ ] Viewing another group does not change the user's saved profile group.

### Extra Classes

- [ ] User can open `/extra`.
- [ ] User can select extra classes.
- [ ] User can clear extra class selection.
- [ ] Extra classes can be shown as a separate section.
- [ ] Extra classes can be included in the main schedule when enabled.

### Settings and Notifications

- [ ] User can open `/settings`.
- [ ] User can switch schedule view mode.
- [ ] User can enable daily notifications.
- [ ] User can disable daily notifications.
- [ ] User can change notification time.
- [ ] Notification sound setting is saved.
- [ ] Alert settings are saved.
- [ ] Settings remain after container restart.

### Group Leader Tools

- [ ] Group leader can open the group leader panel.
- [ ] Group leader can select a date and lesson.
- [ ] Group leader can cancel a lesson.
- [ ] Group leader can change a classroom.
- [ ] Group leader can add an online lesson link.
- [ ] Group leader can add a note.
- [ ] Group leader can roll back schedule changes.
- [ ] Schedule changes are visible to students.
- [ ] Regular user cannot access group leader actions.

### Admin Tools

- [ ] Admin can receive the admin role through `/admin <password>` when allowed.
- [ ] Admin can open the admin panel.
- [ ] Admin can assign the group leader role.
- [ ] Admin can remove the group leader role.
- [ ] Regular user cannot access admin actions.
- [ ] Unknown users cannot use `/admin` when `ADMIN_USER_IDS` restricts access.

### Database Persistence

- [ ] Database is created successfully.
- [ ] User settings are saved.
- [ ] Schedule changes are saved.
- [ ] Data remains after container restart.
- [ ] Data remains after container rebuild.
- [ ] Docker volume is not removed accidentally during testing.

### Error Handling

- [ ] Invalid user actions do not crash the bot.
- [ ] Missing schedule data is handled clearly.
- [ ] Unexpected text input does not crash the bot.
- [ ] Callback actions from an outdated menu do not crash the bot.
- [ ] Errors are written to logs.

### Security

- [ ] `.env` is not committed.
- [ ] Bot tokens are not committed.
- [ ] Production database is not committed.
- [ ] Logs do not expose bot tokens.
- [ ] Logs do not expose private user data.
- [ ] Production admin access is restricted with `ADMIN_USER_IDS`.

## Before Deployment

Before deploying to production:

- [ ] Automated checks pass locally.
- [ ] CI checks pass on the pull request or `main`.
- [ ] Local test bot was checked manually.
- [ ] Docker container starts locally.
- [ ] Manual checklist is completed for changed areas.
- [ ] Logs are checked.
- [ ] No secrets are committed.
- [ ] Production database backup is created.
- [ ] Changes are merged into `main`.

## Production Smoke Test

After deployment:

- [ ] Production bot starts successfully.
- [ ] Production bot responds to `/start`.
- [ ] Existing users are still available.
- [ ] Schedule is displayed correctly.
- [ ] Notifications still work.
- [ ] Admin and group leader panels still open for authorized users.
- [ ] Logs do not contain critical errors.

## Known Gaps

- There are no automated end-to-end tests against the Telegram API.
- Manual checks are still required for Telegram UI flows.
- Scheduler behavior is validated manually.
- Database persistence is checked through Docker smoke testing.
