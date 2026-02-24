from __future__ import annotations

import httpx
import os
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
_telegram_bot_url_cache: str | None = None
_telegram_lookup_attempted = False


async def _telegram_bot_url() -> str | None:
    global _telegram_bot_url_cache, _telegram_lookup_attempted

    direct_url = (settings.telegram_bot_url or "").strip()
    if direct_url:
        return direct_url

    if not settings.telegram_bot_username:
        # Fallback: resolve bot username from token once, then cache.
        if os.getenv("VERCEL") == "1" and settings.telegram_bot_token and not _telegram_lookup_attempted:
            _telegram_lookup_attempted = True
            try:
                async with httpx.AsyncClient(timeout=8) as client:
                    resp = await client.get(f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe")
                    resp.raise_for_status()
                    payload = resp.json()
                username = (payload.get("result") or {}).get("username", "")
                username = username.strip().lstrip("@")
                if username:
                    _telegram_bot_url_cache = f"https://t.me/{username}"
            except Exception:
                pass
        return _telegram_bot_url_cache

    username = settings.telegram_bot_username.strip().lstrip("@")
    if not username:
        return _telegram_bot_url_cache
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
    logo_url = (settings.app_logo_url or "").strip() or "/static/agura-frog-logo.jpg"
    favicon_url = (settings.app_logo_url or "").strip() or (
        "data:image/svg+xml,"
        "%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22%3E"
        "%3Ctext y=%2252%22 font-size=%2252%22%3E%F0%9F%90%B8%3C/text%3E%3C/svg%3E"
    )
    context: dict = {
        "title": "Agura Weather Bot",
        "telegram_bot_url": await _telegram_bot_url(),
        "logo_url": logo_url,
        "favicon_url": favicon_url,
        "user": None,
        "now_summary": None,
        "error": None,
    }
    if settings.stateless_runtime_enabled:
        return templates.TemplateResponse(request, "web_app.html", context)

    user = _single_user(session)
    context["user"] = user
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

    try:
        if settings.stateless_runtime_enabled:
            city_name, now_summary = await logic.build_now_summary_for_city(city_text)
            return templates.TemplateResponse(
                request,
                "partials/now_panel.html",
                {"user": None, "city_name": city_name, "city_query": city_name, "now_summary": now_summary},
            )

        existing = _single_user(session)
        telegram_id = existing.telegram_id if existing is not None else 1
        user = await logic.set_city(session, telegram_id=telegram_id, city=city_text)
        await logic.refresh_user_data(session, user)
        now_summary = logic.build_now_summary(session, user)
        return templates.TemplateResponse(
            request,
            "partials/now_panel.html",
            {"user": user, "city_query": user.city, "now_summary": now_summary},
        )
    except Exception as exc:
        return _render_error(request, f"Failed to set city: {exc}", status_code=400)


@router.get("/web/now", response_class=HTMLResponse)
async def web_now(request: Request, city: str | None = Query(default=None), session: Session = Depends(get_session)):
    if settings.stateless_runtime_enabled:
        city_text = (city or "").strip()
        if not city_text:
            return _render_city_form(request, "Set city first.", status_code=400)
        try:
            city_name, now_summary = await logic.build_now_summary_for_city(city_text)
            return templates.TemplateResponse(
                request,
                "partials/now_panel.html",
                {"user": None, "city_name": city_name, "city_query": city_name, "now_summary": now_summary},
            )
        except Exception as exc:
            return _render_error(request, f"Failed to build now summary: {exc}", status_code=400)

    user = _single_user(session)
    if user is None:
        return _render_city_form(request, "Set city first.", status_code=400)
    try:
        await logic.refresh_user_data(session, user)
        now_summary = logic.build_now_summary(session, user)
        return templates.TemplateResponse(
            request,
            "partials/now_panel.html",
            {"user": user, "city_query": user.city, "now_summary": now_summary},
        )
    except Exception as exc:
        return _render_error(request, f"Failed to build now summary: {exc}", status_code=400)


@router.get("/web/stats", response_class=HTMLResponse)
async def web_stats(request: Request, city: str | None = Query(default=None), session: Session = Depends(get_session)):
    if settings.stateless_runtime_enabled:
        city_text = (city or "").strip()
        if not city_text:
            return _render_city_form(request, "Set city first.", status_code=400)
        try:
            _, stats_summary = await logic.build_stats_summary_for_city(city_text)
            return templates.TemplateResponse(
                request,
                "partials/stats_block.html",
                {"stats_summary": stats_summary},
            )
        except Exception as exc:
            return _render_error(request, f"Failed to build stats: {exc}", status_code=400)

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
async def web_forecast_options(
    request: Request, city: str | None = Query(default=None), session: Session = Depends(get_session)
):
    if settings.stateless_runtime_enabled:
        city_text = (city or "").strip()
        if not city_text:
            return _render_city_form(request, "Set city first.", status_code=400)
        return templates.TemplateResponse(request, "partials/forecast_options.html", {"city_query": city_text})

    user = _single_user(session)
    if user is None:
        return _render_city_form(request, "Set city first.", status_code=400)
    return templates.TemplateResponse(request, "partials/forecast_options.html", {"city_query": user.city})


@router.get("/web/forecast", response_class=HTMLResponse)
async def web_forecast(
    request: Request,
    days: int = Query(1),
    city: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    if days not in {1, 3}:
        raise HTTPException(status_code=400, detail="days must be 1 or 3")

    if settings.stateless_runtime_enabled:
        city_text = (city or "").strip()
        if not city_text:
            return _render_city_form(request, "Set city first.", status_code=400)
        try:
            _, forecast_summary = await logic.build_forecast_digest_for_city(city_text, days)
            return templates.TemplateResponse(
                request,
                "partials/forecast_block.html",
                {"forecast_summary": forecast_summary},
            )
        except Exception as exc:
            return _render_error(request, f"Failed to build forecast: {exc}", status_code=400)

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
async def web_outfit_options(
    request: Request, city: str | None = Query(default=None), session: Session = Depends(get_session)
):
    if settings.stateless_runtime_enabled:
        city_text = (city or "").strip()
        if not city_text:
            return _render_city_form(request, "Set city first.", status_code=400)
        return templates.TemplateResponse(request, "partials/outfit_options.html", {"city_query": city_text})

    user = _single_user(session)
    if user is None:
        return _render_city_form(request, "Set city first.", status_code=400)
    return templates.TemplateResponse(request, "partials/outfit_options.html", {"city_query": user.city})


@router.get("/web/outfit", response_class=HTMLResponse)
async def web_outfit(
    request: Request,
    minutes: int = Query(15),
    activity: str = Query("walking"),
    city: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    if minutes not in {15, 60}:
        raise HTTPException(status_code=400, detail="minutes must be one of 15, 60")
    if activity not in {"walking", "biking"}:
        raise HTTPException(status_code=400, detail="activity must be walking or biking")

    if settings.stateless_runtime_enabled:
        city_text = (city or "").strip()
        if not city_text:
            return _render_city_form(request, "Set city first.", status_code=400)
        try:
            _, advice = await logic.outfit_now_for_city(city_text, minutes_outside=minutes, activity=activity)
            return templates.TemplateResponse(
                request,
                "partials/outfit_block.html",
                {"advice": advice, "minutes": minutes, "activity": activity},
            )
        except Exception as exc:
            return _render_error(request, f"Failed to build outfit: {exc}", status_code=400)

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
    if settings.stateless_runtime_enabled:
        return _render_city_form(request, "Send a city name to check weather.")
    user = _single_user(session)
    if user is None:
        return _render_city_form(request, "Send a new city name to update location.")
    city_short = user.city.split(",")[0].strip()
    return _render_city_form(request, f"Current city is {city_short}. Send a new city name to update location.")
