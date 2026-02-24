from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import init_db
from app.web import router as web_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    stateless_mode = settings.stateless_runtime_enabled
    if not stateless_mode:
        init_db()
    stale_logic_file = Path(__file__).with_name("app_logic.py")
    if stale_logic_file.exists():
        logger.warning(
            "Found stale path %s; runtime uses app/services/app_logic.py",
            stale_logic_file,
        )

    bot_runtime = None
    scheduler_runtime = None
    if not stateless_mode:
        from app.bot import BOT_COMMANDS, build_bot
        from app.scheduler import SchedulerRuntime

        bot_runtime = build_bot()
        scheduler_runtime = SchedulerRuntime()

    if bot_runtime is not None and scheduler_runtime is not None:
        await bot_runtime.application.initialize()
        await bot_runtime.application.bot.set_my_commands(BOT_COMMANDS)
        await bot_runtime.application.start()
        await bot_runtime.application.updater.start_polling()

        async def send_message(chat_id: int, text: str, **kwargs):
            return await bot_runtime.application.bot.send_message(chat_id=chat_id, text=text, **kwargs)

        scheduler_runtime.start(send_message)
        app.state.bot_runtime = bot_runtime
    elif scheduler_runtime is not None:
        async def noop_send(chat_id: int, text: str, **kwargs):
            return None

        scheduler_runtime.start(noop_send)

    app.state.scheduler_runtime = scheduler_runtime

    try:
        yield
    finally:
        if scheduler_runtime is not None:
            await scheduler_runtime.stop()
        if bot_runtime is not None:
            await bot_runtime.application.updater.stop()
            await bot_runtime.application.stop()
            await bot_runtime.application.shutdown()


app = FastAPI(title="Weather Dashboard Bot", lifespan=lifespan)
app.include_router(web_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
if not settings.stateless_runtime_enabled:
    from app.api import router as api_router

    app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
