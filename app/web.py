from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.config import settings
from app.db import get_session
from app.models import UserProfile
from app.services.app_logic import AppLogic

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="app/templates")
logic = AppLogic()


def _telegram_bot_url() -> str | None:
    if not settings.telegram_bot_username:
        return None
    username = settings.telegram_bot_username.strip().lstrip("@")
    if not username:
        return None
    return f"https://t.me/{username}"


def _single_user(session: Session) -> UserProfile | None:
    return session.exec(select(UserProfile).order_by(UserProfile.created_at)).first()


def _render_city_form(
    request: Request,
    message: str | None = None,
    status_code: int = 200,
):
    return templates.TemplateResponse(
        request,
        "partials/city_form.html",
        {"message": message},
        status_code=status_code,
    )


def _render_error(
    request: Request,
    error: str,
    status_code: int = 400,
):
    return templates.TemplateResponse(
        request,
        "partials/error_block.html",
        {"error": error},
        status_code=status_code,
    )


@router.get("/", response_class=HTMLResponse)
async def web_app(request: Request, session: Session = Depends(get_session)):
    user = session.exec(select(UserProfile).order_by(UserProfile.created_at)).first()
    context: dict = {
        "title": "Weather Web Bot",
        "telegram_bot_url": _telegram_bot_url(),
        "user": user,
        "now_summary": None,
        "error": None,
    }

    if user is None:
        return templates.TemplateResponse(request, "web_app.html", context)

    try:
        await logic.refresh_user_data(session, user)
        context["now_summary"] = logic.build_now_summary(session, user)
        return templates.TemplateResponse(request, "web_app.html", context)
    except Exception as exc:
        context["error"] = str(exc)
        return templates.TemplateResponse(request, "web_app.html", context)


@router.post("/web/set-city", response_class=HTMLResponse)
async def web_set_city(
    request: Request,
    city: str = Form(...),
    session: Session = Depends(get_session),
):
    city_text = city.strip()
    if not city_text:
        return _render_city_form(request, "Please enter a city name.", status_code=400)

    existing = _single_user(session)
    telegram_id = existing.telegram_id if existing is not None else 1

    try:
        user = await logic.set_city(session, telegram_id=telegram_id, city=city_text)
        await logic.refresh_user_data(session, user)
        now_summary = logic.build_now_summary(session, user)
        return templates.TemplateResponse(
            request,
            "partials/now_panel.html",
            {"user": user, "now_summary": now_summary},
        )
    except Exception as exc:
        return _render_error(request, f"Failed to set city: {exc}", status_code=400)


@router.get("/web/now", response_class=HTMLResponse)
async def web_now(request: Request, session: Session = Depends(get_session)):
    user = _single_user(session)
    if user is None:
        return _render_city_form(request, "Set city first.", status_code=400)
    try:
        await logic.refresh_user_data(session, user)
        now_summary = logic.build_now_summary(session, user)
        return templates.TemplateResponse(
            request,
            "partials/now_panel.html",
            {"user": user, "now_summary": now_summary},
        )
    except Exception as exc:
        return _render_error(request, f"Failed to build now summary: {exc}", status_code=400)


@router.get("/web/stats", response_class=HTMLResponse)
async def web_stats(request: Request, session: Session = Depends(get_session)):
    user = _single_user(session)
    if user is None:
        return _render_city_form(request, "Set city first.", status_code=400)
    try:
        await logic.refresh_user_data(session, user)
        stats_summary = logic.build_stats_summary(session, user)
        return templates.TemplateResponse(
            request,
            "partials/stats_block.html",
            {"stats_summary": stats_summary},
        )
    except Exception as exc:
        return _render_error(request, f"Failed to build stats: {exc}", status_code=400)


@router.get("/web/forecast/options", response_class=HTMLResponse)
async def web_forecast_options(request: Request, session: Session = Depends(get_session)):
    if _single_user(session) is None:
        return _render_city_form(request, "Set city first.", status_code=400)
    return templates.TemplateResponse(request, "partials/forecast_options.html", {})


@router.get("/web/forecast", response_class=HTMLResponse)
async def web_forecast(
    request: Request,
    days: int = Query(1),
    session: Session = Depends(get_session),
):
    if days not in {1, 3}:
        raise HTTPException(status_code=400, detail="days must be 1 or 3")
    user = _single_user(session)
    if user is None:
        return _render_city_form(request, "Set city first.", status_code=400)
    try:
        await logic.refresh_user_data(session, user)
        forecast_summary = logic.build_forecast_digest(session, user, days)
        return templates.TemplateResponse(
            request,
            "partials/forecast_block.html",
            {"forecast_summary": forecast_summary},
        )
    except Exception as exc:
        return _render_error(request, f"Failed to build forecast: {exc}", status_code=400)


@router.get("/web/outfit/options", response_class=HTMLResponse)
async def web_outfit_options(request: Request, session: Session = Depends(get_session)):
    if _single_user(session) is None:
        return _render_city_form(request, "Set city first.", status_code=400)
    return templates.TemplateResponse(request, "partials/outfit_options.html", {})


@router.get("/web/outfit", response_class=HTMLResponse)
async def web_outfit(
    request: Request,
    minutes: int = Query(15),
    activity: str = Query("walking"),
    session: Session = Depends(get_session),
):
    if minutes not in {15, 60}:
        raise HTTPException(status_code=400, detail="minutes must be one of 15, 60")
    if activity not in {"walking", "biking"}:
        raise HTTPException(status_code=400, detail="activity must be walking or biking")
    user = _single_user(session)
    if user is None:
        return _render_city_form(request, "Set city first.", status_code=400)
    try:
        await logic.refresh_user_data(session, user)
        advice = logic.outfit_now(session, user, minutes_outside=minutes, activity=activity)
        return templates.TemplateResponse(
            request,
            "partials/outfit_block.html",
            {"advice": advice, "minutes": minutes, "activity": activity},
        )
    except Exception as exc:
        return _render_error(request, f"Failed to build outfit: {exc}", status_code=400)


@router.post("/web/location", response_class=HTMLResponse)
async def web_location(request: Request, session: Session = Depends(get_session)):
    user = _single_user(session)
    if user is None:
        return _render_city_form(request, "Send a new city name to update location.")
    city_short = user.city.split(",")[0].strip()
    return _render_city_form(request, f"Current city is {city_short}. Send a new city name to update location.")
