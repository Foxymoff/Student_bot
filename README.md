# Student Bot

[![CI](https://github.com/Foxymoff/Student_bot/actions/workflows/ci.yml/badge.svg)](https://github.com/Foxymoff/Student_bot/actions/workflows/ci.yml)

Telegram bot for students that provides schedule access, group and subgroup selection, extra classes, notifications, and role-based tools for group leaders and administrators.

## Problem

Students often have to check schedules, subgroup-specific classes, extra lessons, and last-minute changes across different sources. This bot centralizes schedule access in Telegram and helps students quickly get relevant information for their group, subgroup, and selected extra classes.

The project also gives group leaders a simple way to publish schedule changes, such as cancelled lessons, classroom updates, online links, and notes.

## What This Project Demonstrates

- Building an asynchronous Telegram bot with `aiogram 3`.
- Storing user settings and schedule overrides in SQLite.
- Working with structured JSON schedule data.
- Role-based access for students, group leaders, and administrators.
- Dockerized deployment with persistent bot data.
- Automated linting, formatting, tests, and Docker build checks through GitHub Actions.

## Features

- View the schedule for today, tomorrow, the current week, or the next week.
- Detect even and odd academic weeks automatically.
- Filter lessons by informatics and English subgroups.
- View another group's schedule without changing the user profile.
- Select extra classes and show them separately or inside the main schedule.
- Switch between compact and detailed schedule output.
- Configure personal daily schedule notifications.
- Receive alerts about schedule changes.
- Use group leader tools to update lessons quickly.
- Use admin tools to assign and remove group leaders.
- Open useful campus and sports complex links from Telegram.

## Supported Groups

- `ИСП-25-1`
- `ИСП-25-2`
- `МР-25`

Schedule files are configured in [config.py](config.py):

- main schedules: `data/isp_25_1.json`, `data/isp_25_2.json`, `data/mr_25.json`
- extra classes: `data/isp_25_1_extra.json`, `data/isp_25_2_extra.json`, `data/mr_25_extra.json`

## Tech Stack

- Python 3.11+
- aiogram 3
- SQLite with aiosqlite
- APScheduler
- python-dotenv
- Docker and Docker Compose
- Ruff
- Pytest
- GitHub Actions

## Local Setup

Clone the repository and open the project directory:

```bash
git clone https://github.com/Foxymoff/Student_bot.git
cd Student_bot
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it.

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Create an environment file from the example:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Fill in `.env`:

```env
BOT_TOKEN=123456:telegram-bot-token
ADMIN_PASSWORD=strong-admin-password
ADMIN_USER_IDS=123456789
```

Run the bot:

```bash
python main.py
```

On the first run, the bot creates `bot.db` in the project directory unless `DB_DIR` is set.

## Environment Variables

| Variable | Required | Description |
| --- | --- | --- |
| `BOT_TOKEN` | Yes | Telegram bot token from [@BotFather](https://t.me/BotFather). |
| `ADMIN_PASSWORD` | No | Password for the `/admin <password>` command. If it is not set, password-based admin access is disabled. |
| `ADMIN_USER_IDS` | No | Comma-separated Telegram user IDs allowed to use `/admin`. Recommended for production. |
| `DB_DIR` | No | Directory where `bot.db` is created. Useful for Docker volumes. |
| `EXTRA_DATA_DIR` | No | Directory with extra class JSON files. Defaults to `data/`. |

## Running with Docker

Build and start the container:

```bash
docker compose up -d --build
```

View logs:

```bash
docker compose logs -f bot
```

Stop the bot:

```bash
docker compose down
```

In Docker, the database is stored in the `bot-data` volume because `docker-compose.yml` sets `DB_DIR=/data`.

## Bot Commands and Sections

| Command / Button | Description |
| --- | --- |
| `/start` | Initial registration, group selection, and subgroup selection. |
| `/profile` | Study profile: group, subgroups, and extra classes. |
| `/groups` | View another group's schedule. |
| `/settings` | Schedule view, extra classes, daily notifications, and alerts. |
| `/help` | Contact information for questions and bug reports. |
| `/extra` | Shortcut for extra class settings through the profile flow. |
| `/admin <password>` | Grant admin access to the current user. |
| `📅 Расписание` | Schedule for the selected period. |
| `📌 Доп. занятия` | Weekly schedule for selected extra classes. |
| `🔗 Полезные ссылки` | Links to campus services. |
| `📋 Староста` | Schedule editing panel for group leaders and admins. |
| `⚙️ Админ` | Assign and remove group leaders. |

## Roles

- `student` - regular user who can view schedules and manage personal settings.
- `starosta` - group leader who can cancel lessons, change classrooms, add online links, and add notes for their group.
- `admin` - user who can assign and remove group leaders and also access group leader tools.

Admin access can be granted with `/admin <password>` when `ADMIN_PASSWORD` is set.
For a public bot, `ADMIN_USER_IDS` should also be configured so the password cannot be used from unknown Telegram accounts.
After the first admin is created, `ADMIN_PASSWORD` can be removed and new group leaders can be managed through the admin panel.

## Project Structure

```text
.
├── data/                  # JSON files with main schedules and extra classes
├── docs/                  # testing and project documentation
├── handlers/              # command, button, and callback handlers
│   ├── admin.py           # admin panel
│   ├── extra.py           # extra classes
│   ├── info.py            # informational sections
│   ├── schedule.py        # main schedule views
│   ├── starosta.py        # group leader panel
│   └── start.py           # registration, profile, and settings
├── tests/                 # pytest test suite
├── config.py              # settings, groups, paths, dictionaries
├── database.py            # SQLite schema and queries
├── extra_schedule.py      # loading and formatting extra classes
├── keyboards.py           # reply and inline keyboards
├── main.py                # application entry point
├── scheduler.py           # background daily notifications
├── Dockerfile
└── docker-compose.yml
```

## Schedule Data Format

The main schedule is stored as JSON and separated by academic week type:

```json
{
  "group": "ИСП-25-1",
  "weeks": {
    "even": {
      "Понедельник": {
        "lessons": []
      }
    },
    "odd": {}
  }
}
```

Extra class files use a similar structure, but store classes in an `extra` array instead of `lessons`.

## Testing and Code Quality

The project uses Ruff for linting and formatting, and Pytest for automated tests.

Run all local checks before opening a pull request:

```bash
ruff check .
ruff format --check .
pytest -v
```

Apply formatting if needed:

```bash
ruff format .
```

Automated tests currently cover selected helper functions and business logic that do not require Telegram API access or production data. Telegram-specific flows are checked through manual smoke testing with a separate test bot.

Additional manual testing notes are available in [docs/TESTING.md](docs/TESTING.md).

## Continuous Integration

GitHub Actions CI runs on pull requests and pushes to `main`.

The CI workflow checks:

- Ruff linting.
- Ruff formatting.
- Pytest test suite.
- Docker Compose configuration.
- Docker image build.

This helps catch linting, formatting, test, and Docker build failures before changes are merged.

## Development Workflow

The project follows a simple contribution workflow:

1. Create an issue or define a task.
2. Create a separate branch.
3. Make changes.
4. Run local checks.
5. Open a pull request.
6. Wait for CI checks.
7. Merge into `main`.

## Project Status

The project is actively being improved.

Current focus:

- Improving code quality.
- Expanding automated tests.
- Maintaining CI checks.
- Improving project structure and documentation.

The bot is designed for practical student schedule access and is developed with incremental improvements instead of claiming full production readiness.
