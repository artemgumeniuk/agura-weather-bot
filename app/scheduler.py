from __future__ import annotations

import asyncio
from datetime import datetime
import hashlib
import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings
from app.db import engine
from app.models import DailyDigestLog, UserProfile
from app.bot import build_now_actions_keyboard
from app.services.app_logic import AppLogic

logger = logging.getLogger(__name__)


class SchedulerRuntime:
    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone=settings.default_timezone)
        self.logic = AppLogic()

    def start(self, send_message_fn):
        self.scheduler.add_job(self._job_ingest, CronTrigger(hour=0, minute=20))
        self.scheduler.add_job(self._job_recompute, CronTrigger(hour=0, minute=40))
        # Guard job: runs every minute and ensures daily digest is sent once/day after scheduled time.
        self.scheduler.add_job(
            self._job_daily_guard,
            CronTrigger(minute="*"),
            args=[send_message_fn],
            coalesce=True,
            max_instances=1,
        )
        self.scheduler.add_job(
            self._job_daily_digest,
            CronTrigger(hour=settings.daily_digest_hour, minute=settings.daily_digest_minute),
            args=[send_message_fn],
            misfire_grace_time=3600,
            coalesce=True,
            max_instances=1,
        )
        self.scheduler.add_job(
            self._job_history_warmup,
            CronTrigger(minute="*/30"),
            coalesce=True,
            max_instances=1,
        )
        self.scheduler.add_job(self._job_backfill_weekly, CronTrigger(day_of_week="sun", hour=2, minute=15))
        self.scheduler.start()
        for job in self.scheduler.get_jobs():
            logger.info("Scheduler job registered: %s next_run=%s", job.func.__name__, job.next_run_time)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            loop.create_task(self._run_startup_catchup(send_message_fn))

    async def stop(self):
        self.scheduler.shutdown(wait=False)

    async def _job_ingest(self):
        with Session(engine) as session:
            users = list(session.exec(select(UserProfile)).all())
            for user in users:
                await self.logic.refresh_user_data(session, user)

    async def _job_recompute(self):
        with Session(engine) as session:
            users = list(session.exec(select(UserProfile)).all())
            for user in users:
                self.logic.today_vs_history(session, user)

    async def _job_daily_digest(self, send_message_fn):
        with Session(engine) as session:
            users = list(session.exec(select(UserProfile)).all())
            for user in users:
                try:
                    user_tz = ZoneInfo(user.timezone or settings.default_timezone)
                except Exception:
                    user_tz = ZoneInfo(settings.default_timezone)
                now_local = datetime.now(user_tz)
                if not (
                    now_local.hour == settings.daily_digest_hour
                    and now_local.minute == settings.daily_digest_minute
                ):
                    continue
                today_local = now_local.date()
                already_sent = session.exec(
                    select(DailyDigestLog).where(
                        DailyDigestLog.telegram_id == user.telegram_id,
                        DailyDigestLog.date == today_local,
                    )
                ).first()
                if already_sent is not None:
                    continue
                try:
                    await self.logic.refresh_user_data(session, user)
                    payload = self.logic.build_now_summary(session, user)
                except Exception:
                    logger.exception("Scheduler daily digest build failed for chat_id=%s", user.telegram_id)
                    continue

                try:
                    digest_msg = await send_message_fn(
                        chat_id=user.telegram_id,
                        text=payload,
                        reply_markup=build_now_actions_keyboard(),
                    )
                    logger.info(
                        "Scheduler digest sent chat_id=%s message_id=%s",
                        user.telegram_id,
                        getattr(digest_msg, "message_id", None),
                    )
                except Exception:
                    logger.exception("Scheduler digest send failed for chat_id=%s", user.telegram_id)
                    continue

                try:
                    checkin_msg = await send_message_fn(
                        chat_id=user.telegram_id,
                        text="Quick check-in: how comfortable was yesterday's weather for you?",
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton("1", callback_data="rate:pick:1"),
                                    InlineKeyboardButton("2", callback_data="rate:pick:2"),
                                    InlineKeyboardButton("3", callback_data="rate:pick:3"),
                                    InlineKeyboardButton("4", callback_data="rate:pick:4"),
                                    InlineKeyboardButton("5", callback_data="rate:pick:5"),
                                ]
                            ]
                        ),
                    )
                    logger.info(
                        "Scheduler check-in sent chat_id=%s message_id=%s",
                        user.telegram_id,
                        getattr(checkin_msg, "message_id", None),
                    )
                except Exception:
                    logger.exception("Scheduler check-in send failed for chat_id=%s", user.telegram_id)

                digest_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                self.logic.log_daily_digest(session, user.telegram_id, digest_hash, for_date=today_local)

    async def _job_backfill_weekly(self):
        with Session(engine) as session:
            users = list(session.exec(select(UserProfile)).all())
            for user in users:
                await self.logic.warmup_user_history(session, user)

    async def _job_history_warmup(self):
        with Session(engine) as session:
            users = list(
                session.exec(
                    select(UserProfile)
                    .where(UserProfile.history_ready == False)  # noqa: E712
                    .limit(settings.history_warmup_batch_size)
                ).all()
            )
            for user in users:
                try:
                    await self.logic.warmup_user_history(session, user)
                except Exception:
                    logger.exception("History warmup failed for user %s", user.telegram_id)

    async def _job_daily_guard(self, send_message_fn):
        await self._job_daily_digest(send_message_fn)

    async def _run_startup_catchup(self, send_message_fn):
        logger.info("Startup catch-up running")
        await self._job_daily_digest(send_message_fn)
