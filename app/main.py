from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI

from app.api import router as api_router
from app.bot import BotRuntime, build_bot
from app.db import init_db
from app.scheduler import SchedulerRuntime
from app.web import router as web_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    stale_logic_file = Path(__file__).with_name("app_logic.py")
    if stale_logic_file.exists():
        logger.warning(
            "Found stale path %s; runtime uses app/services/app_logic.py",
            stale_logic_file,
        )

    bot_runtime: BotRuntime | None = build_bot()
    scheduler_runtime = SchedulerRuntime()

    if bot_runtime is not None:
        await bot_runtime.application.initialize()
        await bot_runtime.application.start()
        await bot_runtime.application.updater.start_polling()

        async def send_message(chat_id: int, text: str, **kwargs):
            return await bot_runtime.application.bot.send_message(chat_id=chat_id, text=text, **kwargs)

        scheduler_runtime.start(send_message)
        app.state.bot_runtime = bot_runtime
    else:
        async def noop_send(chat_id: int, text: str, **kwargs):
            return None

        scheduler_runtime.start(noop_send)

    app.state.scheduler_runtime = scheduler_runtime

    try:
        yield
    finally:
        await scheduler_runtime.stop()
        if bot_runtime is not None:
            await bot_runtime.application.updater.stop()
            await bot_runtime.application.stop()
            await bot_runtime.application.shutdown()


app = FastAPI(title="Weather Dashboard Bot", lifespan=lifespan)
app.include_router(web_router)
app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
