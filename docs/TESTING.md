# Testing

This document describes how the bot is tested before deployment.

## Environments

The project uses two separate environments:

| Environment | Purpose | Bot token | Database |
|---|---|---|---|
| Local test | Check changes before deployment | Test bot token | Local test database |
| Production | Real users | Production bot token | Production database |

The test bot and the production bot must use different Telegram tokens.

Production data must not be used for local testing.

## Local test process

1. Change the code locally.
2. Build and start the bot in Docker.
3. Test the bot manually through the test Telegram bot.
4. Check container logs.
5. If everything works, merge the changes into `main`.
6. Deploy the updated `main` branch to the server.
7. Check the production bot after deployment.

## Local commands

Start the bot:

```bash
docker compose up -d --build
```

View logs:

```bash
docker compose logs -f
```

Restart the bot:

```bash
docker compose restart
```

Stop the bot:

```bash
docker compose down
```

## Manual test checklist

### Startup

- [ ] Docker image builds successfully.
- [ ] Container starts successfully.
- [ ] Logs do not contain critical errors.
- [ ] Bot responds to `/start`.

### Registration

- [ ] New user can start the bot.
- [ ] User can select a group.
- [ ] User can select a subgroup.
- [ ] User settings are saved.
- [ ] User settings remain after container restart.

### Schedule

- [ ] User can view today's schedule.
- [ ] User can view tomorrow's schedule.
- [ ] Even and odd weeks are detected correctly.
- [ ] Lessons are filtered by group.
- [ ] Lessons are filtered by subgroup.
- [ ] Empty schedule is handled correctly.
- [ ] Schedule text is displayed correctly.

### Notifications

- [ ] User can enable notifications.
- [ ] User can disable notifications.
- [ ] User can change notification time.
- [ ] Notifications are sent at the selected time.
- [ ] Disabled notifications are not sent.
- [ ] Notification settings remain after container restart.

### Group leader features

- [ ] Group leader can open the group leader menu.
- [ ] Group leader can cancel a lesson.
- [ ] Group leader can change a classroom.
- [ ] Group leader can add an online lesson link.
- [ ] Schedule changes are visible to students.
- [ ] Regular user cannot access group leader actions.

### Admin features

- [ ] Admin can open the admin menu.
- [ ] Admin can assign the group leader role.
- [ ] Admin can remove the group leader role.
- [ ] Regular user cannot access admin actions.

### Database

- [ ] Database is created successfully.
- [ ] User settings are saved.
- [ ] Schedule changes are saved.
- [ ] Data remains after container restart.
- [ ] Data remains after container rebuild.

### Error handling

- [ ] Invalid user actions do not crash the bot.
- [ ] Missing schedule data is handled correctly.
- [ ] Unexpected text input does not crash the bot.
- [ ] Errors are written to logs.

### Security

- [ ] `.env` is not committed.
- [ ] Bot tokens are not committed.
- [ ] Production database is not committed.
- [ ] Logs do not expose bot tokens.
- [ ] Logs do not expose private user data.

## Before deployment

Before deploying to production:

- [ ] Local test bot was checked.
- [ ] Docker container starts locally.
- [ ] Manual checklist is completed.
- [ ] Logs are checked.
- [ ] No secrets are committed.
- [ ] Production database backup is created.
- [ ] Changes are merged into `main`.

## Production smoke test

After deployment:

- [ ] Production bot starts successfully.
- [ ] Production bot responds to `/start`.
- [ ] Existing users are still available.
- [ ] Schedule is displayed correctly.
- [ ] Notifications still work.
- [ ] Logs do not contain critical errors.

## Current status

Testing is currently manual.

Automated tests will be added later.