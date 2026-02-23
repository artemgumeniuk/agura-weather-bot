from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.db import get_session
from app.models import UserProfile
from app.schemas import (
    ComfortPredictResponse,
    ComfortRatingRequest,
    OutfitResponse,
    TodayVsHistoryResponse,
)
from app.services.app_logic import AppLogic

router = APIRouter(prefix="/api", tags=["weather"])
logic = AppLogic()


def _single_user(session: Session) -> UserProfile:
    user = session.exec(select(UserProfile).order_by(UserProfile.created_at)).first()
    if user is None:
        raise HTTPException(status_code=400, detail="No user configured. Use /setcity in Telegram.")
    return user


@router.get("/dashboard/today-vs-history", response_model=TodayVsHistoryResponse)
async def today_vs_history(session: Session = Depends(get_session)):
    user = _single_user(session)
    try:
        await logic.refresh_user_data(session, user)
        return logic.today_vs_history(session, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/outfit", response_model=OutfitResponse)
async def outfit(
    minutes_outside: int = Query(30, ge=10, le=180),
    activity: str = Query("walking", pattern="^(standing|walking|running)$"),
    session: Session = Depends(get_session),
):
    user = _single_user(session)
    try:
        await logic.refresh_user_data(session, user)
        return logic.outfit_now(session, user, minutes_outside=minutes_outside, activity=activity)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/comfort/rating")
async def add_rating(payload: ComfortRatingRequest, session: Session = Depends(get_session)):
    user = _single_user(session)
    try:
        entity = logic.add_comfort_rating(
            session,
            telegram_id=user.telegram_id,
            rating=payload.rating,
            activity=payload.activity,
            minutes_outside=payload.minutes_outside,
            context=payload.context,
        )
        return {"id": entity.id, "status": "ok"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/comfort/predict", response_model=ComfortPredictResponse)
async def predict_comfort(
    activity: str = Query("walking", pattern="^(standing|walking|running)$"),
    minutes_outside: int = Query(30, ge=10, le=180),
    session: Session = Depends(get_session),
):
    user = _single_user(session)
    try:
        await logic.refresh_user_data(session, user)
        return logic.predict_comfort(
            session,
            telegram_id=user.telegram_id,
            activity=activity,
            minutes_outside=minutes_outside,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
