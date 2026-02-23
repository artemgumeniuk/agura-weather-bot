from __future__ import annotations

from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models import UserProfile
from app.services.app_logic import AppLogic


@dataclass
class BotRuntime:
    application: Application


WAITING_CITY_KEY = "waiting_for_city_name"
OUTFIT_CALLBACK_PREFIX = "outfit:"
NAV_CALLBACK_PREFIX = "nav:"
FORECAST_CALLBACK_PREFIX = "forecast:"
RATE_CALLBACK_PREFIX = "rate:"


def parse_outfit_args(args: list[str]) -> tuple[int, str]:
    mins = 15
    activity = "walking"
    if len(args) >= 1:
        mins = int(args[0])
    if len(args) >= 2:
        activity = args[1]
    if mins not in {15, 60}:
        raise ValueError("minutes must be one of 15, 60")
    if activity not in {"walking", "biking"}:
        raise ValueError("activity must be walking|biking")
    return mins, activity


def build_start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Set city", callback_data=f"{NAV_CALLBACK_PREFIX}setcity")]]
    )


def build_after_city_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Weather now", callback_data=f"{NAV_CALLBACK_PREFIX}now")],
            [InlineKeyboardButton("Forecast", callback_data=f"{NAV_CALLBACK_PREFIX}forecast")],
        ]
    )


def build_now_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🧥 Outfit", callback_data=f"{NAV_CALLBACK_PREFIX}outfit"),
                InlineKeyboardButton("📅 Forecast", callback_data=f"{NAV_CALLBACK_PREFIX}forecast"),
                InlineKeyboardButton("📈 Stats", callback_data=f"{NAV_CALLBACK_PREFIX}stats"),
                InlineKeyboardButton("⚙️ Location", callback_data=f"{NAV_CALLBACK_PREFIX}setcity"),
            ]
        ]
    )


def build_outfit_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("15 min walking", callback_data=f"{OUTFIT_CALLBACK_PREFIX}pick:15:walking")],
            [InlineKeyboardButton("60 min walking", callback_data=f"{OUTFIT_CALLBACK_PREFIX}pick:60:walking")],
            [InlineKeyboardButton("15 min biking", callback_data=f"{OUTFIT_CALLBACK_PREFIX}pick:15:biking")],
            [InlineKeyboardButton("60 min biking", callback_data=f"{OUTFIT_CALLBACK_PREFIX}pick:60:biking")],
            [InlineKeyboardButton("Close", callback_data=f"{OUTFIT_CALLBACK_PREFIX}close")],
        ]
    )


def parse_forecast_days(args: list[str]) -> int:
    if not args:
        return 1
    days = int(args[0])
    if days not in {1, 3}:
        raise ValueError("forecast days must be 1 or 3")
    return days


def build_forecast_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Forecast 1 day", callback_data=f"{FORECAST_CALLBACK_PREFIX}pick:1")],
            [InlineKeyboardButton("Forecast 3 days", callback_data=f"{FORECAST_CALLBACK_PREFIX}pick:3")],
            [InlineKeyboardButton("Close", callback_data=f"{FORECAST_CALLBACK_PREFIX}close")],
        ]
    )


def build_after_forecast_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Weather now", callback_data=f"{NAV_CALLBACK_PREFIX}now")]]
    )


def build_rate_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("1", callback_data=f"{RATE_CALLBACK_PREFIX}pick:1"),
                InlineKeyboardButton("2", callback_data=f"{RATE_CALLBACK_PREFIX}pick:2"),
                InlineKeyboardButton("3", callback_data=f"{RATE_CALLBACK_PREFIX}pick:3"),
                InlineKeyboardButton("4", callback_data=f"{RATE_CALLBACK_PREFIX}pick:4"),
                InlineKeyboardButton("5", callback_data=f"{RATE_CALLBACK_PREFIX}pick:5"),
            ]
        ]
    )


def build_bot() -> BotRuntime | None:
    if not settings.telegram_bot_token:
        return None

    logic = AppLogic()
    app = Application.builder().token(settings.telegram_bot_token).build()

    def unauthorized(update: Update) -> bool:
        allowed = settings.telegram_allowed_user_id_int
        if allowed is None:
            return False
        uid = update.effective_user.id if update.effective_user else None
        return uid != allowed

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if unauthorized(update):
            return
        await update.message.reply_text(
            "Welcome. Start by setting your city.",
            reply_markup=build_start_keyboard(),
        )

    async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if unauthorized(update):
            return
        await update.message.reply_text(
            "Commands:\n"
            "/setcity (then send city text)\n"
            "/now\n"
            "/forecast (1 or 3 days)\n"
            "/forecast <1|3>\n"
            "/outfit (button menu)\n"
            "/outfit <15|60> <walking|biking>\n"
            "/whoami\n"
            "/admin_dups\n"
            "/admin_rmdup <user_profile_id>\n"
            "/rate <1-5>\n"
            "/comfort\n"
            "/metrics - explain anomaly metrics\n\n"
            "Metric meanings:\n"
            "- Temp anomaly: today's mean temp minus normal for this time of year.\n"
            "- Temp percentile: how warm today is vs historical days nearby in season.\n"
            "  Example: 5% = unusually cold, 95% = unusually warm.\n"
            "- Weirdness score: combined anomaly size across temp, wind, and precip.\n"
            "  Calculated from z-scores: sqrt(z_temp^2 + z_wind^2 + z_precip^2).\n"
            "- Wet streak: consecutive days with precipitation > 0 mm.\n"
            "- Wind peak 24h: strongest forecast gust in the next 24 hours.\n"
            "- Rain risk 24h: derived from forecast precipitation amount/intensity."
        )

    async def send_city_prompt(reply_fn):
        await reply_fn("Send your city name (example: Gothenburg).")

    async def send_after_city_actions(reply_fn):
        await reply_fn("City saved. What next?", reply_markup=build_after_city_keyboard())

    async def send_outfit_menu(reply_fn):
        await reply_fn("Choose time outside and activity:", reply_markup=build_outfit_keyboard())

    async def send_now_summary(reply_fn, telegram_id: int):
        with Session(engine) as session:
            user = session.exec(
                select(UserProfile).where(UserProfile.telegram_id == telegram_id)
            ).first()
            if user is None:
                await reply_fn("Set city first with /setcity")
                return
            await logic.refresh_user_data(session, user)
            msg = logic.build_now_summary(session, user)
            await reply_fn(msg, reply_markup=build_now_actions_keyboard())

    async def send_stats_summary(reply_fn, telegram_id: int):
        with Session(engine) as session:
            user = session.exec(
                select(UserProfile).where(UserProfile.telegram_id == telegram_id)
            ).first()
            if user is None:
                await reply_fn("Set city first with /setcity")
                return
            await logic.refresh_user_data(session, user)
            msg = logic.build_stats_summary(session, user)
            await reply_fn(msg)

    async def send_forecast_digest(reply_fn, telegram_id: int, days: int):
        with Session(engine) as session:
            user = session.exec(
                select(UserProfile).where(UserProfile.telegram_id == telegram_id)
            ).first()
            if user is None:
                await reply_fn("Set city first with /setcity")
                return
            await logic.refresh_user_data(session, user)
            msg = logic.build_forecast_digest(session, user, days)
            await reply_fn(msg, reply_markup=build_after_forecast_keyboard())

    async def metrics_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if unauthorized(update):
            return
        await update.message.reply_text(
            "How to read /now:\n"
            "- Temp anomaly: + means warmer than normal, - means colder.\n"
            "- Temp percentile: rank vs historical days for this season (0..100%).\n"
            "- Weirdness: combined z-score distance for temp/wind/precip.\n"
            "  ~0-1 normal, ~1-2 notable, >2 unusual.\n"
            "- Streak: current consecutive wet days (precip > 0 mm).\n"
            "- Memory: same calendar day last year at your station."
        )

    async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if unauthorized(update):
            return
        user = update.effective_user
        chat = update.effective_chat
        if user is None or chat is None:
            await update.message.reply_text("Could not resolve Telegram identity for this message.")
            return
        await update.message.reply_text(
            f"Telegram user_id={user.id}\n"
            f"chat_id={chat.id}\n"
            f"username={user.username or '-'}\n"
            f"name={(user.full_name or '').strip() or '-'}"
        )

    async def admin_dups(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if unauthorized(update):
            return
        with Session(engine) as session:
            groups = logic.duplicate_user_profile_groups(session)
        if not groups:
            await update.message.reply_text("No duplicate user_profile groups found.")
            return

        lines = ["Duplicate user_profile groups (primary = oldest row in each city):"]
        for group in groups:
            primary_id = group[0].id
            lines.append(f"City: {group[0].city} (count={len(group)})")
            for row in group:
                role = "PRIMARY" if row.id == primary_id else "duplicate"
                lines.append(
                    f"id={row.id} tg={row.telegram_id} station={row.station_id} created={row.created_at.isoformat()} {role}"
                )
        await update.message.reply_text("\n".join(lines))

    async def admin_rmdup(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /admin_rmdup <user_profile_id>")
            return
        try:
            profile_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("user_profile_id must be an integer")
            return

        with Session(engine) as session:
            try:
                removed = logic.remove_duplicate_user_profile(session, profile_id)
            except ValueError as exc:
                await update.message.reply_text(f"Not removed: {exc}")
                return
        await update.message.reply_text(
            f"Removed duplicate user_profile id={removed.id} tg={removed.telegram_id} city={removed.city}"
        )

    async def setcity(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if unauthorized(update):
            return
        if not context.args:
            context.user_data[WAITING_CITY_KEY] = True
            await send_city_prompt(update.message.reply_text)
            return
        city = " ".join(context.args)
        try:
            await update.message.reply_text("Setting city now. Please wait a few seconds...")
            with Session(engine) as session:
                user = await logic.set_city(session, update.effective_user.id, city)
                await update.message.reply_text(
                    f"City set to {user.city}\n"
                    f"provider={user.weather_provider} timezone={user.timezone}\n"
                    f"station_id={user.station_id}\n"
                    f"lat/lon={user.lat:.4f},{user.lon:.4f}"
                )
                await send_after_city_actions(update.message.reply_text)
        except Exception as exc:
            await update.message.reply_text(f"Failed to set city: {exc}")

    async def city_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if unauthorized(update):
            return
        if not context.user_data.get(WAITING_CITY_KEY):
            return

        city = (update.message.text or "").strip()
        if not city:
            await update.message.reply_text("Please send a valid city name.")
            return

        try:
            await update.message.reply_text("Setting city now. Please wait a few seconds...")
            with Session(engine) as session:
                user = await logic.set_city(session, update.effective_user.id, city)
                await update.message.reply_text(
                    f"City set to {user.city}\n"
                    f"provider={user.weather_provider} timezone={user.timezone}\n"
                    f"station_id={user.station_id}\n"
                    f"lat/lon={user.lat:.4f},{user.lon:.4f}"
                )
                await send_after_city_actions(update.message.reply_text)
        except Exception as exc:
            await update.message.reply_text(f"Failed to set city: {exc}")
        finally:
            context.user_data.pop(WAITING_CITY_KEY, None)

    async def now_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if unauthorized(update):
            return
        try:
            await send_now_summary(update.message.reply_text, update.effective_user.id)
        except Exception as exc:
            await update.message.reply_text(f"Failed to build now summary: {exc}")

    async def outfit(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if unauthorized(update):
            return
        if not context.args:
            await send_outfit_menu(update.message.reply_text)
            return

        try:
            mins, activity = parse_outfit_args(context.args)
        except ValueError as exc:
            await update.message.reply_text(f"Invalid args: {exc}")
            return

        try:
            with Session(engine) as session:
                user = session.exec(
                    select(UserProfile).where(UserProfile.telegram_id == update.effective_user.id)
                ).first()
                if user is None:
                    await update.message.reply_text("Set city first with /setcity")
                    return
                await logic.refresh_user_data(session, user)
                advice = logic.outfit_now(session, user, mins, activity)
                await update.message.reply_text(
                    f"🧥 Outfit ({mins} min, {activity}):\n"
                    f"👕 Base: {advice.base_layer}\n"
                    f"🧶 Mid: {advice.mid_layer}\n"
                    f"🛡️ Shell: {advice.shell}\n"
                    f"👟 Shoes: {advice.shoes}\n"
                    f"🧤 Extras: {', '.join(advice.extras) if advice.extras else 'none'}"
                )
        except Exception as exc:
            await update.message.reply_text(f"Failed to build outfit advice: {exc}")

    async def forecast(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Choose forecast window:", reply_markup=build_forecast_keyboard())
            return

        try:
            days = parse_forecast_days(context.args)
            await send_forecast_digest(update.message.reply_text, update.effective_user.id, days)
        except Exception as exc:
            await update.message.reply_text(f"Failed to build forecast: {exc}")

    async def nav_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if unauthorized(update):
            return
        query = update.callback_query
        if query is None or query.data is None:
            return
        await query.answer()
        if not query.data.startswith(NAV_CALLBACK_PREFIX):
            return

        action = query.data.removeprefix(NAV_CALLBACK_PREFIX)
        if action == "setcity":
            context.user_data[WAITING_CITY_KEY] = True
            await query.message.reply_text("Send your city name (example: Gothenburg).")
            return
        if action in {"now", "today"}:
            try:
                await send_now_summary(query.message.reply_text, update.effective_user.id)
            except Exception as exc:
                await query.message.reply_text(f"Failed to build now summary: {exc}")
            return
        if action == "stats":
            try:
                await send_stats_summary(query.message.reply_text, update.effective_user.id)
            except Exception as exc:
                await query.message.reply_text(f"Failed to build stats summary: {exc}")
            return
        if action == "forecast":
            await query.message.reply_text("Choose forecast window:", reply_markup=build_forecast_keyboard())
            return
        if action == "outfit":
            await send_outfit_menu(query.message.reply_text)
            return

        await query.message.reply_text("Invalid choice. Try /start.")

    async def outfit_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if unauthorized(update):
            return
        query = update.callback_query
        if query is None or query.data is None:
            return

        await query.answer()
        if not query.data.startswith(OUTFIT_CALLBACK_PREFIX):
            return

        payload = query.data.removeprefix(OUTFIT_CALLBACK_PREFIX)
        if payload == "close":
            await query.edit_message_text("Outfit menu closed.")
            return

        try:
            action, mins_raw, activity = payload.split(":", 2)
            if action != "pick":
                raise ValueError("invalid action")
            mins = int(mins_raw)
            mins, activity = parse_outfit_args([str(mins), activity])
        except (ValueError, TypeError):
            await query.edit_message_text("Invalid outfit choice. Try /outfit again.")
            return

        try:
            with Session(engine) as session:
                user = session.exec(
                    select(UserProfile).where(UserProfile.telegram_id == update.effective_user.id)
                ).first()
                if user is None:
                    await query.edit_message_text("Set city first with /setcity")
                    return
                await logic.refresh_user_data(session, user)
                advice = logic.outfit_now(session, user, mins, activity)
                await query.edit_message_text(
                    f"🧥 Outfit ({mins} min, {activity}):\n"
                    f"👕 Base: {advice.base_layer}\n"
                    f"🧶 Mid: {advice.mid_layer}\n"
                    f"🛡️ Shell: {advice.shell}\n"
                    f"👟 Shoes: {advice.shoes}\n"
                    f"🧤 Extras: {', '.join(advice.extras) if advice.extras else 'none'}"
                )
        except Exception as exc:
            await query.edit_message_text(f"Failed to build outfit advice: {exc}")

    async def forecast_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if unauthorized(update):
            return
        query = update.callback_query
        if query is None or query.data is None:
            return

        await query.answer()
        if not query.data.startswith(FORECAST_CALLBACK_PREFIX):
            return

        payload = query.data.removeprefix(FORECAST_CALLBACK_PREFIX)
        if payload == "close":
            await query.edit_message_text("Forecast menu closed.")
            return

        try:
            action, days_raw = payload.split(":", 1)
            if action != "pick":
                raise ValueError("invalid action")
            days = parse_forecast_days([days_raw])
        except (ValueError, TypeError):
            await query.edit_message_text("Invalid forecast choice. Try /forecast again.")
            return

        try:
            with Session(engine) as session:
                user = session.exec(
                    select(UserProfile).where(UserProfile.telegram_id == update.effective_user.id)
                ).first()
                if user is None:
                    await query.edit_message_text("Set city first with /setcity")
                    return
                await logic.refresh_user_data(session, user)
                msg = logic.build_forecast_digest(session, user, days)
                await query.edit_message_text(msg, reply_markup=build_after_forecast_keyboard())
        except Exception as exc:
            await query.edit_message_text(f"Failed to build forecast: {exc}")

    async def rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /rate <1-5>")
            return
        rating = int(context.args[0])
        if rating < 1 or rating > 5:
            await update.message.reply_text("Rating must be 1..5")
            return

        with Session(engine) as session:
            try:
                row = logic.add_comfort_rating(
                    session,
                    telegram_id=update.effective_user.id,
                    rating=rating,
                    activity="walking",
                    minutes_outside=30,
                    context=None,
                )
                await update.message.reply_text(f"Saved rating #{row.id} = {rating}")
            except ValueError as exc:
                await update.message.reply_text(str(exc))

    async def comfort(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if unauthorized(update):
            return
        with Session(engine) as session:
            try:
                pred = logic.predict_comfort(
                    session,
                    telegram_id=update.effective_user.id,
                    activity="walking",
                    minutes_outside=30,
                )
                await update.message.reply_text(
                    f"Predicted comfort: {pred.predicted_rating:.2f}/5\n"
                    f"Bad-day probability: {pred.bad_day_probability:.0%}\n"
                    f"Model ready: {pred.model_ready}\n"
                    f"Tips: {', '.join(pred.tailored_adjustments)}"
                )
            except ValueError as exc:
                await update.message.reply_text(str(exc))

    async def rate_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if unauthorized(update):
            return
        query = update.callback_query
        if query is None or query.data is None:
            return

        await query.answer()
        if not query.data.startswith(RATE_CALLBACK_PREFIX):
            return

        try:
            action, rating_raw = query.data.removeprefix(RATE_CALLBACK_PREFIX).split(":", 1)
            if action != "pick":
                raise ValueError("invalid action")
            rating = int(rating_raw)
            if rating < 1 or rating > 5:
                raise ValueError("rating out of range")
        except (ValueError, TypeError):
            await query.edit_message_text("Invalid rating choice. Try /rate 1..5.")
            return

        with Session(engine) as session:
            try:
                row = logic.add_comfort_rating(
                    session,
                    telegram_id=update.effective_user.id,
                    rating=rating,
                    activity="walking",
                    minutes_outside=30,
                    context=None,
                )
                await query.edit_message_text(f"Thanks, saved your comfort rating: {rating}/5 (#{row.id})")
            except ValueError as exc:
                await query.edit_message_text(str(exc))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("metrics", metrics_cmd))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("admin_dups", admin_dups))
    app.add_handler(CommandHandler("admin_rmdup", admin_rmdup))
    app.add_handler(CommandHandler("setcity", setcity))
    app.add_handler(CommandHandler("now", now_cmd))
    app.add_handler(CommandHandler("forecast", forecast))
    app.add_handler(CommandHandler("outfit", outfit))
    app.add_handler(CallbackQueryHandler(nav_choice, pattern=f"^{NAV_CALLBACK_PREFIX}"))
    app.add_handler(CallbackQueryHandler(outfit_choice, pattern=f"^{OUTFIT_CALLBACK_PREFIX}"))
    app.add_handler(CallbackQueryHandler(forecast_choice, pattern=f"^{FORECAST_CALLBACK_PREFIX}"))
    app.add_handler(CallbackQueryHandler(rate_choice, pattern=f"^{RATE_CALLBACK_PREFIX}"))
    app.add_handler(CommandHandler("rate", rate))
    app.add_handler(CommandHandler("comfort", comfort))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, city_text_input))

    return BotRuntime(application=app)
