from app.config import settings
from app.scheduler import SchedulerRuntime


class _FakeScheduler:
    def __init__(self, timezone):
        self.timezone = timezone
        self.jobs = []
        self.started = False

    def add_job(self, func, trigger, args=None, **kwargs):
        self.jobs.append({"func": func, "trigger": trigger, "args": args or [], "kwargs": kwargs})

    def start(self):
        self.started = True

    def shutdown(self, wait=False):
        self.started = False

    def get_jobs(self):
        return []


def test_scheduler_uses_configurable_daily_digest_time(monkeypatch):
    import app.scheduler as scheduler_module

    monkeypatch.setattr(settings, "daily_digest_hour", 10)
    monkeypatch.setattr(settings, "daily_digest_minute", 40)
    monkeypatch.setattr(scheduler_module, "AsyncIOScheduler", _FakeScheduler)

    runtime = SchedulerRuntime()

    async def _send(chat_id: int, text: str):
        return None

    runtime.start(_send)

    daily_job = next(job for job in runtime.scheduler.jobs if job["func"] == runtime._job_daily_digest)
    trigger_text = str(daily_job["trigger"])

    assert "hour='10'" in trigger_text
    assert "minute='40'" in trigger_text
    assert runtime.scheduler.started is True
