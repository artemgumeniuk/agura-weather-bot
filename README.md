# Weather Dashboard Bot

Telegram-first weather anomaly dashboard with global weather support (Open-Meteo default, SMHI optional for Sweden).

## Features
- Today vs history anomaly stats (temp anomaly, percentile, streaks, weirdness)
- Outfit recommendations from forecast + exposure/activity
- Daily Telegram memory digest at 07:30 (local timezone, configurable)
- Personal comfort model after 10 ratings
- Functional web flow: set city, view compact now summary, and open Outfit/Forecast/Stats/Location panes
- Stateless web mode for serverless hosting (Vercel)

## Quick start
1. Create venv and install:
   - `python3.12 -m venv .venv`
   - `source .venv/bin/activate`
   - `pip install -e .[dev]`
2. Configure env in `.env` (see `.env.example`).
3. Run API:
   - `uvicorn app.main:app --reload`
4. Open dashboard:
   - `http://127.0.0.1:8000/`
5. Optional Telegram web CTA config:
   - `TELEGRAM_BOT_USERNAME=<your_bot_username>`

## Vercel stateless web mode
Set:
- `WEB_STATELESS_MODE=true`
- `WEATHER_PROVIDER_DEFAULT=openmeteo`
- `WEATHER_PROVIDER_SWEDEN=openmeteo` (optional; keep `smhi` if you want Sweden fallback)

Deploy using `vercel.json` + `api/index.py` included in this repo.

## Telegram commands
- `/start`
- `/setcity <city text>`
- `/now`
- `/outfit <15|60> <walking|biking>`
- `/rate <1-5>`
- `/comfort`
- `/help`

## Raspberry Pi deployment
Use Docker Compose:
- `docker compose up -d --build`

## Cron test override
To test scheduler delivery at a temporary time, set in `.env`:
- `DAILY_DIGEST_HOUR=10`
- `DAILY_DIGEST_MINUTE=40`

Then restart:
- `docker compose up -d --build --force-recreate weather-bot`
