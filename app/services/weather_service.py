from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete
from sqlmodel import Session, select

from app.models import ForecastHourly, ObsDaily, UserProfile
from app.services.anomaly import (
    compute_precip_streak,
    mean,
    percentile_rank,
    seasonal_window,
    stddev,
    z_score,
)
from app.services.providers.router import ProviderRouter


class WeatherService:
    def __init__(self) -> None:
        self.providers = ProviderRouter()

    async def ingest_forecast(self, session: Session, user: UserProfile) -> list[ForecastHourly]:
        provider = self.providers.provider_for_name(user.weather_provider)
        rows = await provider.fetch_forecast(lat=user.lat, lon=user.lon)
        session.exec(delete(ForecastHourly).where(ForecastHourly.location_key == user.location_key))
        created: list[ForecastHourly] = []
        for row in rows:
            entity = ForecastHourly(
                location_key=user.location_key,
                provider=user.weather_provider,
                lat=user.lat,
                lon=user.lon,
                valid_time=row.valid_time,
                t=row.t,
                ws=row.ws,
                gust=row.gust,
                r=row.r,
                tp=row.tp,
                pmean=row.pmean,
            )
            session.add(entity)
            created.append(entity)
        session.commit()
        return created

    async def ingest_latest_obs(self, session: Session, user: UserProfile) -> None:
        # Derive a daily observation-like row from nearest forecast horizon to keep flow snappy.
        now_row = closest_forecast_row(session, user.location_key, lat=user.lat, lon=user.lon)
        if now_row is None:
            rows = await self.ingest_forecast(session, user)
            if not rows:
                return
            now_row = closest_forecast_row(session, user.location_key, lat=user.lat, lon=user.lon)
            if now_row is None:
                return

        today = date.today()
        entity = session.exec(
            select(ObsDaily).where(ObsDaily.location_key == user.location_key, ObsDaily.date == today)
        ).first()
        if entity is None:
            entity = ObsDaily(
                station_id=user.station_id,
                location_key=user.location_key,
                provider=user.weather_provider,
                date=today,
            )
        entity.station_id = user.station_id
        entity.provider = user.weather_provider
        entity.t_mean = now_row.t
        entity.t_min = now_row.t
        entity.t_max = now_row.t
        entity.ws_mean = now_row.ws
        entity.precip_sum = now_row.tp
        entity.rh_mean = now_row.r
        session.add(entity)
        session.commit()

    async def import_history(
        self,
        session: Session,
        user: UserProfile,
        start_date: date,
        end_date: date,
    ) -> int:
        provider = self.providers.provider_for_name(user.weather_provider)
        rows = await provider.fetch_daily_history(user.lat, user.lon, start_date=start_date, end_date=end_date)
        created = 0
        for row in rows:
            exists = session.exec(
                select(ObsDaily).where(ObsDaily.location_key == user.location_key, ObsDaily.date == row.date)
            ).first()
            if exists is None:
                exists = ObsDaily(
                    station_id=user.station_id,
                    location_key=user.location_key,
                    provider=user.weather_provider,
                    date=row.date,
                )
                created += 1
            exists.station_id = user.station_id
            exists.provider = user.weather_provider
            exists.t_mean = row.t_mean
            exists.ws_mean = row.ws_mean
            exists.precip_sum = row.precip_sum
            exists.rh_mean = row.rh_mean
            session.add(exists)
        session.commit()
        return created

    async def warmup_history(self, session: Session, user: UserProfile, years: int) -> int:
        today = date.today()
        start = today - timedelta(days=max(5, years) * 365)
        return await self.import_history(session, user, start_date=start, end_date=today)

    def compute_today_vs_history(self, session: Session, user: UserProfile) -> dict:
        today = date.today()
        all_rows = list(
            session.exec(select(ObsDaily).where(ObsDaily.location_key == user.location_key)).all()
        )
        if not all_rows and user.station_id is not None:
            # Legacy fallback for pre-migration rows.
            all_rows = list(session.exec(select(ObsDaily).where(ObsDaily.station_id == user.station_id)).all())
        if not all_rows:
            return {
                "date": today,
                "station_id": user.station_id,
                "location_key": user.location_key,
                "provider": user.weather_provider,
                "temp_anomaly_c": 0.0,
                "temp_percentile": 50.0,
                "precip_streak_days": 0,
                "z_temp": 0.0,
                "z_wind": 0.0,
                "z_precip": 0.0,
                "weirdness_score": 0.0,
                "baseline_years": 0,
                "confidence_note": "history baseline warming up",
            }

        today_row = next((r for r in all_rows if r.date == today), None)
        if today_row is None:
            today_row = max(all_rows, key=lambda r: r.date)
            today = today_row.date

        history = [r for r in all_rows if r.date < today and r.t_mean is not None]
        if not history:
            return {
                "date": today,
                "station_id": user.station_id,
                "location_key": user.location_key,
                "provider": user.weather_provider,
                "temp_anomaly_c": 0.0,
                "temp_percentile": 50.0,
                "precip_streak_days": compute_precip_streak(all_rows, today),
                "z_temp": 0.0,
                "z_wind": 0.0,
                "z_precip": 0.0,
                "weirdness_score": 0.0,
                "baseline_years": 0,
                "confidence_note": "history baseline warming up",
            }

        years = max(1, min(30, (today - min(h.date for h in history)).days // 365))
        start = today - timedelta(days=years * 365)
        candidate_history = [h for h in history if h.date >= start]
        if len(candidate_history) < 365 * 3:
            candidate_history = history

        doy = today.timetuple().tm_yday
        seasonal = seasonal_window(candidate_history, doy, width_days=7) or candidate_history

        t_hist = [x.t_mean for x in seasonal if x.t_mean is not None]
        w_hist = [x.ws_mean for x in seasonal if x.ws_mean is not None]
        p_hist = [x.precip_sum for x in seasonal if x.precip_sum is not None]

        t_today = float(today_row.t_mean or 0.0)
        w_today = float(today_row.ws_mean or 0.0)
        p_today = float(today_row.precip_sum or 0.0)

        t_mean = mean(t_hist) if t_hist else 0.0
        w_mean = mean(w_hist) if w_hist else 0.0
        p_mean = mean(p_hist) if p_hist else 0.0

        z_temp = z_score(t_today, t_mean, stddev(t_hist) if t_hist else 0.0)
        z_wind = z_score(w_today, w_mean, stddev(w_hist) if w_hist else 0.0)
        z_precip = z_score(p_today, p_mean, stddev(p_hist) if p_hist else 0.0)

        weirdness = (z_temp**2 + z_wind**2 + z_precip**2) ** 0.5
        streak = compute_precip_streak(all_rows, today)
        confidence = "high" if years >= 10 else ("medium" if years >= 5 else "low")
        return {
            "date": today,
            "station_id": user.station_id,
            "location_key": user.location_key,
            "provider": user.weather_provider,
            "temp_anomaly_c": t_today - t_mean,
            "temp_percentile": percentile_rank(sorted(t_hist), t_today) if t_hist else 50.0,
            "precip_streak_days": streak,
            "z_temp": z_temp,
            "z_wind": z_wind,
            "z_precip": z_precip,
            "weirdness_score": weirdness,
            "baseline_years": years,
            "confidence_note": f"{confidence} confidence baseline using ~{years} years",
        }


def _rows_for_location(session: Session, location_key: str, lat: float | None, lon: float | None) -> list[ForecastHourly]:
    rows = list(
        session.exec(
            select(ForecastHourly)
            .where(ForecastHourly.location_key == location_key)
            .order_by(ForecastHourly.valid_time)
        ).all()
    )
    if rows:
        return rows
    if lat is None or lon is None:
        return []
    return list(
        session.exec(
            select(ForecastHourly)
            .where(ForecastHourly.lat == lat, ForecastHourly.lon == lon)
            .order_by(ForecastHourly.valid_time)
        ).all()
    )


def closest_forecast_row(
    session: Session,
    location_key: str,
    lat: float | None = None,
    lon: float | None = None,
) -> ForecastHourly | None:
    now = datetime.now(UTC)
    rows = _rows_for_location(session, location_key, lat, lon)
    if not rows:
        return None

    def _to_utc(dt: datetime) -> datetime:
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)

    return min(rows, key=lambda x: abs((_to_utc(x.valid_time) - now).total_seconds()))


def next_24h_rows(
    session: Session,
    location_key: str,
    lat: float | None = None,
    lon: float | None = None,
) -> list[ForecastHourly]:
    rows = _rows_for_location(session, location_key, lat, lon)
    if not rows:
        return []
    now = datetime.now(UTC)

    def _to_utc(dt: datetime) -> datetime:
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)

    return [row for row in rows if 0 <= (_to_utc(row.valid_time) - now).total_seconds() <= 24 * 3600]


def get_user_by_telegram(session: Session, telegram_id: int) -> UserProfile | None:
    return session.exec(
        select(UserProfile)
        .where(UserProfile.telegram_id == telegram_id)
        .order_by(UserProfile.created_at.desc(), UserProfile.id.desc())
    ).first()
