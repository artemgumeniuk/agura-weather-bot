# Weather Bot Handoff Summary

## Current Status
- Bot is running on Raspberry Pi in Docker (`weather-bot` service).
- Core button flows implemented:
  - `/start` shows only `Set city`.
  - After city is set: `Weather today` + `Forecast`.
  - After `/today`: `Outfit` + `Forecast`.
- `/setcity` now sends immediate progress feedback:
  - `Setting city now. Please wait a few seconds...`
- `/today` digest updated:
  - emoji formatting
  - no `Memory:` prefix
  - includes `Sky next 24h: ...`
- `/outfit` updated:
  - options are `15 min walking`, `60 min walking`, `15 min biking`, `60 min biking`.
- `/forecast` added:
  - button menu (`Forecast 1 day`, `Forecast 3 days`)
  - typed args (`/forecast 1`, `/forecast 3`)
  - includes per-day sky text (`sky sunny/partly cloudy/...`).
- Scheduler 07:30 digest job is configured and logs show it executed.

## Important Investigation Finding
- There are two Telegram user profiles in DB (`user_profile`) for Gothenburg.
- `daily_digest_log` has entries around 07:30 for both user IDs.
- This suggests cron fired, but delivery visibility may be tied to account/chat mismatch or duplicate profile confusion.

## Repo Structure (Key Paths)
- `app/main.py`: FastAPI app + bot + scheduler startup
- `app/bot.py`: Telegram handlers, button flows, command wiring
- `app/scheduler.py`: cron jobs (`00:20`, `00:40`, `07:30`, weekly backfill)
- `app/services/app_logic.py`: orchestration, today/forecast digest generation
- `app/services/digest.py`: `/today` message formatting
- `app/services/weather_service.py`: forecast/obs ingestion + anomaly computations
- `app/services/external.py`: SMHI + geocoding clients
- `app/models.py`: SQLModel tables (`user_profile`, `obs_daily`, `forecast_hourly`, etc.)
- `app/api.py`: REST endpoints
- `tests/test_bot_contract.py`: bot parsing/keyboard tests
- `tests/test_digest.py`: digest formatting tests
- `docker-compose.yml`: runtime service config
- `Dockerfile`: build image

## Raspberry Pi Deployment Workflow
1. Sync files via `rsync` to:
   - `agura@agurabot:~/weather-dashboard-bot`
2. Rebuild/restart container:
   - `cd ~/weather-dashboard-bot`
   - `sudo docker compose up -d --build --force-recreate weather-bot`
3. Check status/logs:
   - `sudo docker compose ps`
   - `sudo docker compose logs --tail=50 weather-bot`

## Known Pitfalls
- There are two similarly named logic files on Pi:
  - `app/app_logic.py` (stale/confusing)
  - `app/services/app_logic.py` (actual imported runtime file)
- Always update `app/services/app_logic.py` for bot logic.
- Local shell may not have `pytest`; compile checks were used frequently.

## Recommended Next Tasks
1. Add `/whoami` command to print current Telegram ID in chat.
2. Add explicit scheduler send logging (`chat_id`, Telegram `message_id`, exception details).
3. Add admin command to list/remove duplicate `user_profile` rows safely.
4. Remove/avoid stale `app/app_logic.py` confusion path.
