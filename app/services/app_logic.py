from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import delete
from sqlmodel import Session, select

from app.config import settings
from app.models import ComfortModelMeta, ComfortRating, DailyDigestLog, ForecastHourly, ObsDaily, UserProfile
from app.schemas import ComfortPredictResponse, OutfitResponse, TodayVsHistoryResponse
from app.services.anomaly import compute_precip_streak, mean, percentile_rank, seasonal_window, stddev, z_score
from app.services.comfort import ComfortModelService
from app.services.digest import build_daily_digest, build_now_digest, build_stats_digest
from app.services.external import GeocoderClient, SmhiObsClient
from app.services.outfit import OutfitInput, build_outfit_advice, comfort_temperature
from app.services.providers.router import ProviderRouter
from app.services.weather_service import WeatherService, closest_forecast_row, next_24h_rows


def _sky_label(avg_humidity: float, precip_total: float) -> str:
    if precip_total >= 2.0 or avg_humidity >= 90:
        return "overcast"
    if precip_total >= 0.5 or avg_humidity >= 80:
        return "mostly cloudy"
    if avg_humidity >= 65:
        return "partly cloudy"
    if avg_humidity >= 45:
        return "mostly sunny"
    return "sunny"


def _precip_kind_label(avg_temp_c: float, precip_total_mm: float) -> str:
    if precip_total_mm < 0.1:
        return "none"
    if avg_temp_c <= -0.5:
        return "snow"
    if avg_temp_c >= 1.5:
        return "rain"
    return "mixed"


def _synthetic_station_id(lat: float, lon: float) -> int:
    # Backward-compatible deterministic id for non-station providers.
    lat_i = int(round((lat + 90.0) * 1000))
    lon_i = int(round((lon + 180.0) * 1000))
    return 900000000 + (lat_i * 1000000) + lon_i


class AppLogic:
    def __init__(self) -> None:
        self.weather = WeatherService()
        self.providers = ProviderRouter()
        # Backward-compat hooks used by older tests and custom overrides.
        self.geocoder = GeocoderClient()
        self.obs_client = SmhiObsClient()

    async def set_city(self, session: Session, telegram_id: int, city: str) -> UserProfile:
        if type(self.geocoder).__name__ != "GeocoderClient" or type(self.obs_client).__name__ != "SmhiObsClient":
            lat, lon, display_name = await self.geocoder.geocode_city(city)
            station_id = await self.obs_client.nearest_station(lat, lon)
            resolved = type("ResolvedGeo", (), {})()
            resolved.display_name = display_name
            resolved.lat = lat
            resolved.lon = lon
            resolved.station_id = station_id
            resolved.timezone = settings.default_timezone
            resolved.country_code = "SE"
            resolved.provider_location_key = f"smhi:station:{station_id}"
            provider = self.providers.provider_for_name("smhi")
        else:
            geo = await self.providers.geocode_city(city)
            provider = self.providers.provider_for_country(geo.country_code)
            resolved = geo
            if provider.provider_name != geo.provider:
                resolved = await provider.geocode_city(city)

        station_id_value = resolved.station_id
        if station_id_value is None:
            station_id_value = _synthetic_station_id(resolved.lat, resolved.lon)

        user = session.exec(select(UserProfile).where(UserProfile.telegram_id == telegram_id)).first()
        if user is None:
            user = UserProfile(
                telegram_id=telegram_id,
                city=resolved.display_name,
                lat=resolved.lat,
                lon=resolved.lon,
                station_id=station_id_value,
                timezone=resolved.timezone or settings.default_timezone,
                weather_provider=provider.provider_name,
                location_key=resolved.provider_location_key,
                country_code=resolved.country_code,
                history_ready=False,
            )
        else:
            user.city = resolved.display_name
            user.lat = resolved.lat
            user.lon = resolved.lon
            user.station_id = station_id_value
            user.timezone = resolved.timezone or settings.default_timezone
            user.weather_provider = provider.provider_name
            user.location_key = resolved.provider_location_key
            user.country_code = resolved.country_code
            user.history_ready = False
            user.history_last_refreshed_at = None

        session.add(user)
        session.commit()
        session.refresh(user)

        # Prime caches for immediate dashboard/bot use.
        await self._ingest_forecast_compat(session, user)
        await self._ingest_latest_obs_compat(session, user)

        return user

    async def refresh_user_data(self, session: Session, user: UserProfile) -> None:
        if not user.location_key:
            if user.station_id is not None and (user.weather_provider or "smhi") == "smhi":
                user.location_key = f"smhi:station:{user.station_id}"
            else:
                user.location_key = f"{user.weather_provider or 'openmeteo'}:{user.lat:.4f},{user.lon:.4f}"
            session.add(user)
            session.commit()
            session.refresh(user)
        await self._ingest_forecast_compat(session, user)
        await self._ingest_latest_obs_compat(session, user)

    async def warmup_user_history(self, session: Session, user: UserProfile) -> int:
        years_candidates = [settings.history_warmup_years, 10, 5]
        imported = 0
        for years in years_candidates:
            imported = await self.weather.warmup_history(session, user, years=max(5, years))
            baseline = self.weather.compute_today_vs_history(session, user)
            if baseline.get("baseline_years", 0) >= min(10, years):
                break
        user.history_ready = True
        user.history_last_refreshed_at = datetime.now(UTC)
        session.add(user)
        session.commit()
        return imported

    async def _ingest_forecast_compat(self, session: Session, user: UserProfile) -> None:
        if type(self.weather).__name__ == "WeatherService":
            await self.weather.ingest_forecast(session, user)
            return
        try:
            await self.weather.ingest_forecast(session, user.lat, user.lon)
        except TypeError:
            await self.weather.ingest_forecast(session, user)

    async def _ingest_latest_obs_compat(self, session: Session, user: UserProfile) -> None:
        if type(self.weather).__name__ == "WeatherService":
            await self.weather.ingest_latest_obs(session, user)
            return
        if user.station_id is not None:
            await self.weather.ingest_latest_obs(session, user.station_id)
            return
        await self.weather.ingest_latest_obs(session, user)

    def today_vs_history(self, session: Session, user: UserProfile) -> TodayVsHistoryResponse:
        if type(self.weather).__name__ == "WeatherService":
            payload = self.weather.compute_today_vs_history(session, user)
        else:
            payload = self.weather.compute_today_vs_history(session, user.station_id)
            payload.setdefault("location_key", user.location_key)
            payload.setdefault("provider", user.weather_provider)
        return TodayVsHistoryResponse.model_validate(payload)

    def outfit_now(
        self, session: Session, user: UserProfile, minutes_outside: int, activity: str
    ) -> OutfitResponse:
        row = closest_forecast_row(session, user.location_key, lat=user.lat, lon=user.lon)
        if row is None:
            raise ValueError("No forecast rows found. Refresh data first.")

        advice = build_outfit_advice(
            OutfitInput(
                t=row.t,
                ws=row.ws,
                gust=row.gust,
                r=row.r,
                tp=row.tp,
                pmean=row.pmean,
                minutes_outside=minutes_outside,
                activity=activity,
            )
        )
        return OutfitResponse.model_validate(advice)

    def add_comfort_rating(
        self,
        session: Session,
        telegram_id: int,
        rating: int,
        activity: str,
        minutes_outside: int,
        context: dict | None,
    ) -> ComfortRating:
        user = session.exec(select(UserProfile).where(UserProfile.telegram_id == telegram_id)).first()
        if user is None:
            raise ValueError("Set city first with /setcity")
        row = closest_forecast_row(session, user.location_key, lat=user.lat, lon=user.lon)
        if row is None:
            raise ValueError("No forecast available for rating snapshot")

        snapshot = {
            "t": row.t,
            "ws": row.ws,
            "gust": row.gust,
            "r": row.r,
            "tp": row.tp,
            "pmean": row.pmean,
            "comfort_temp": comfort_temperature(row.t, row.ws, row.r),
        }
        if context:
            snapshot.update(context)

        entity = ComfortRating(
            telegram_id=telegram_id,
            rating=rating,
            activity=activity,
            minutes_outside=minutes_outside,
            weather_feature_snapshot=snapshot,
        )
        session.add(entity)
        session.commit()
        session.refresh(entity)
        return entity

    def predict_comfort(
        self, session: Session, telegram_id: int, activity: str, minutes_outside: int
    ) -> ComfortPredictResponse:
        user = session.exec(select(UserProfile).where(UserProfile.telegram_id == telegram_id)).first()
        if user is None:
            raise ValueError("Set city first with /setcity")
        row = closest_forecast_row(session, user.location_key, lat=user.lat, lon=user.lon)
        if row is None:
            raise ValueError("No forecast available")

        sample = {
            "t": row.t,
            "ws": row.ws,
            "gust": row.gust,
            "r": row.r,
            "tp": row.tp,
            "pmean": row.pmean,
            "comfort_temp": comfort_temperature(row.t, row.ws, row.r),
        }

        records = list(
            session.exec(
                select(ComfortRating)
                .where(ComfortRating.telegram_id == telegram_id)
                .order_by(ComfortRating.ts)
            ).all()
        )

        trainer = ComfortModelService()
        rows = [
            (r.weather_feature_snapshot, r.activity, r.minutes_outside, r.rating)
            for r in records
        ]
        fitted = trainer.fit(rows)
        pred = trainer.predict(sample, activity=activity, minutes_outside=minutes_outside)

        meta = session.exec(
            select(ComfortModelMeta).where(ComfortModelMeta.telegram_id == telegram_id)
        ).first()
        if meta is None:
            meta = ComfortModelMeta(telegram_id=telegram_id)
        meta.sample_count = len(rows)
        meta.trained_at = datetime.now(UTC) if fitted else None
        meta.metrics = {"model_ready": fitted}
        session.add(meta)
        session.commit()

        return ComfortPredictResponse(
            predicted_rating=pred.predicted_rating,
            bad_day_probability=pred.bad_day_probability,
            tailored_adjustments=pred.tailored_adjustments,
            model_ready=pred.model_ready,
        )

    def memory_line(self, session: Session, user: UserProfile) -> str:
        today = date.today()
        try:
            target = today.replace(year=today.year - 1)
        except ValueError:
            # Leap-day fallback.
            target = today.replace(month=2, day=28, year=today.year - 1)

        from app.models import ObsDaily

        hit = session.exec(
            select(ObsDaily).where(ObsDaily.location_key == user.location_key, ObsDaily.date == target)
        ).first()
        if hit is None and user.station_id is not None:
            hit = session.exec(
                select(ObsDaily).where(ObsDaily.station_id == user.station_id, ObsDaily.date == target)
            ).first()
        if hit is None:
            return "No same-date observation last year yet"
        return (
            f"On this day last year: {hit.t_mean or 0.0:.1f}°C, "
            f"wind {hit.ws_mean or 0.0:.1f} m/s, precip {hit.precip_sum or 0.0:.1f} mm"
        )

    def build_today_digest(self, session: Session, user: UserProfile) -> str:
        anomaly = self.today_vs_history(session, user)
        outfit = self.outfit_now(session, user, 30, "walking")
        now_row = closest_forecast_row(session, user.location_key, lat=user.lat, lon=user.lon)
        if now_row is None:
            raise ValueError("No forecast available for digest")

        rows = next_24h_rows(session, user.location_key, lat=user.lat, lon=user.lon)
        rain_total = sum(r.tp for r in rows)
        wind_peak = max((r.gust for r in rows), default=0.0)
        rain_risk = "low" if rain_total < 0.3 else ("moderate" if rain_total < 2.0 else "high")
        avg_humidity = (sum(r.r for r in rows) / len(rows)) if rows else float(now_row.r)
        avg_temp_24h = (sum(r.t for r in rows) / len(rows)) if rows else float(now_row.t)
        precip_kind_now = _precip_kind_label(now_row.t, now_row.tp)
        precip_kind_next_24h = _precip_kind_label(avg_temp_24h, rain_total)
        sky_summary = _sky_label(avg_humidity, rain_total)
        comfort = self.predict_comfort(
            session,
            telegram_id=user.telegram_id,
            activity="walking",
            minutes_outside=30,
        )

        memory = self.memory_line(session, user)
        digest = build_daily_digest(
            city=user.city,
            current_temp_c=now_row.t,
            current_feels_like_c=comfort_temperature(now_row.t, now_row.ws, now_row.r),
            current_wind_ms=now_row.ws,
            current_humidity_pct=now_row.r,
            current_precip_mm=now_row.tp,
            anomaly=anomaly,
            outfit=outfit,
            sky_summary=sky_summary,
            rain_risk=rain_risk,
            precip_kind_now=precip_kind_now,
            precip_kind_next_24h=precip_kind_next_24h,
            wind_peak=wind_peak,
            memory_line=memory,
            comfort_predicted_rating=comfort.predicted_rating,
            comfort_bad_day_probability=comfort.bad_day_probability,
            comfort_model_ready=comfort.model_ready,
        )
        return digest

    def build_now_summary(self, session: Session, user: UserProfile) -> str:
        anomaly = self.today_vs_history(session, user)
        now_row = closest_forecast_row(session, user.location_key, lat=user.lat, lon=user.lon)
        if now_row is None:
            raise ValueError("No forecast available for now summary")

        memory = self.memory_line(session, user)
        return build_now_digest(
            city=user.city,
            current_temp_c=now_row.t,
            current_comfort_c=comfort_temperature(now_row.t, now_row.ws, now_row.r),
            current_wind_ms=now_row.ws,
            current_humidity_pct=now_row.r,
            current_precip_mm=now_row.tp,
            anomaly=anomaly,
            memory_line=memory,
        )

    def build_stats_summary(self, session: Session, user: UserProfile) -> str:
        anomaly = self.today_vs_history(session, user)
        now_row = closest_forecast_row(session, user.location_key, lat=user.lat, lon=user.lon)
        if now_row is None:
            raise ValueError("No forecast available for stats")
        rows = next_24h_rows(session, user.location_key, lat=user.lat, lon=user.lon)
        rain_total = sum(r.tp for r in rows)
        rain_risk = "low" if rain_total < 0.3 else ("moderate" if rain_total < 2.0 else "high")
        wind_peak = max((r.gust for r in rows), default=0.0)
        avg_humidity = (sum(r.r for r in rows) / len(rows)) if rows else float(now_row.r)
        sky_summary = _sky_label(avg_humidity, rain_total)
        memory = self.memory_line(session, user)
        return build_stats_digest(
            city=user.city,
            anomaly=anomaly,
            sky_summary=sky_summary,
            rain_risk=rain_risk,
            wind_peak=wind_peak,
            memory_line=memory,
        )

    def build_forecast_digest(
        self, session: Session, user: UserProfile, days: int, sky_labels: dict[date, str] | None = None
    ) -> str:
        if days not in {1, 3}:
            raise ValueError("forecast days must be 1 or 3")

        rows = list(
            session.exec(
                select(ForecastHourly)
                .where(ForecastHourly.location_key == user.location_key)
                .order_by(ForecastHourly.valid_time)
            ).all()
        )
        if not rows:
            rows = list(
                session.exec(
                    select(ForecastHourly)
                    .where(ForecastHourly.lat == user.lat, ForecastHourly.lon == user.lon)
                    .order_by(ForecastHourly.valid_time)
                ).all()
            )
        if not rows:
            raise ValueError("No forecast available")

        start_day = date.today() + timedelta(days=1)
        end_day = start_day + timedelta(days=days)
        grouped: dict[date, list[ForecastHourly]] = defaultdict(list)
        for row in rows:
            day = row.valid_time.date()
            if start_day <= day < end_day:
                grouped[day].append(row)

        if not grouped:
            raise ValueError("No forecast rows available for the requested window")

        title = "📅 Forecast for tomorrow" if days == 1 else "📅 Forecast for next 3 days"
        lines = [title]
        for day in sorted(grouped.keys()):
            bucket = grouped[day]
            t_min = min(r.t for r in bucket)
            t_max = max(r.t for r in bucket)
            rain_total = sum(r.tp for r in bucket)
            wind_peak = max(r.gust for r in bucket)
            avg_temp = sum(r.t for r in bucket) / len(bucket)
            avg_humidity = sum(r.r for r in bucket) / len(bucket)
            rain_level = "low" if rain_total < 0.3 else ("moderate" if rain_total < 2.0 else "high")
            precip_kind = _precip_kind_label(avg_temp, rain_total)
            sky_text = sky_labels.get(day) if sky_labels and day in sky_labels else _sky_label(avg_humidity, rain_total)
            lines.append(
                f"- {day.strftime('%a %d %b')}: {t_min:.1f}..{t_max:.1f}°C, "
                f"precip {rain_total:.1f} mm ({precip_kind}, {rain_level} risk), "
                f"wind peak {wind_peak:.1f} m/s, sky {sky_text}"
            )
        return "\n".join(lines)

    async def _resolve_stateless_city(self, city: str) -> tuple[SimpleNamespace, list]:
        geo = await self.providers.geocode_city(city)
        provider = self.providers.provider_for_country(geo.country_code)
        resolved = geo
        if provider.provider_name != geo.provider:
            resolved = await provider.geocode_city(city)
        rows = await provider.fetch_forecast(resolved.lat, resolved.lon)
        if not rows:
            raise ValueError("No forecast available")
        station_id_value = resolved.station_id or _synthetic_station_id(resolved.lat, resolved.lon)
        user_like = SimpleNamespace(
            city=resolved.display_name,
            lat=resolved.lat,
            lon=resolved.lon,
            station_id=station_id_value,
            timezone=resolved.timezone or settings.default_timezone,
            weather_provider=provider.provider_name,
            location_key=resolved.provider_location_key,
            country_code=resolved.country_code,
        )
        return user_like, rows

    def _anomaly_from_stateless_data(
        self,
        user_like: SimpleNamespace,
        today_row: ObsDaily,
        history_rows: list[ObsDaily],
    ) -> TodayVsHistoryResponse:
        today = today_row.date
        all_rows = sorted(history_rows + [today_row], key=lambda r: r.date)
        history = [r for r in all_rows if r.date < today and r.t_mean is not None]
        if not history:
            return TodayVsHistoryResponse.model_validate(
                {
                    "date": today,
                    "station_id": user_like.station_id,
                    "location_key": user_like.location_key,
                    "provider": user_like.weather_provider,
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
            )
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
        confidence = "high" if years >= 10 else ("medium" if years >= 5 else "low")
        return TodayVsHistoryResponse.model_validate(
            {
                "date": today,
                "station_id": user_like.station_id,
                "location_key": user_like.location_key,
                "provider": user_like.weather_provider,
                "temp_anomaly_c": t_today - t_mean,
                "temp_percentile": percentile_rank(sorted(t_hist), t_today) if t_hist else 50.0,
                "precip_streak_days": compute_precip_streak(all_rows, today),
                "z_temp": z_temp,
                "z_wind": z_wind,
                "z_precip": z_precip,
                "weirdness_score": (z_temp**2 + z_wind**2 + z_precip**2) ** 0.5,
                "baseline_years": years,
                "confidence_note": f"{confidence} confidence baseline using ~{years} years",
            }
        )

    async def _history_rows_stateless(self, user_like: SimpleNamespace) -> list[ObsDaily]:
        provider = self.providers.provider_for_name(user_like.weather_provider)
        today = date.today()
        for years in [settings.history_warmup_years, 10, 5]:
            start = today - timedelta(days=max(5, years) * 365)
            rows = await provider.fetch_daily_history(user_like.lat, user_like.lon, start_date=start, end_date=today)
            if len(rows) >= 365 * 3 or years == 5:
                return [
                    ObsDaily(
                        station_id=user_like.station_id,
                        location_key=user_like.location_key,
                        provider=user_like.weather_provider,
                        date=r.date,
                        t_mean=r.t_mean,
                        ws_mean=r.ws_mean,
                        precip_sum=r.precip_sum,
                        rh_mean=r.rh_mean,
                    )
                    for r in rows
                ]
        return []

    @staticmethod
    def _closest_forecast_point(rows: list):
        now = datetime.now(UTC)
        return min(rows, key=lambda r: abs((r.valid_time - now).total_seconds()))

    async def build_now_summary_for_city(self, city: str) -> tuple[str, str]:
        user_like, rows = await self._resolve_stateless_city(city)
        now_row = self._closest_forecast_point(rows)
        history_rows = await self._history_rows_stateless(user_like)
        today_row = ObsDaily(
            station_id=user_like.station_id,
            location_key=user_like.location_key,
            provider=user_like.weather_provider,
            date=date.today(),
            t_mean=now_row.t,
            ws_mean=now_row.ws,
            precip_sum=now_row.tp,
            rh_mean=now_row.r,
        )
        anomaly = self._anomaly_from_stateless_data(user_like, today_row=today_row, history_rows=history_rows)
        try:
            target = date.today().replace(year=date.today().year - 1)
        except ValueError:
            target = date.today().replace(month=2, day=28, year=date.today().year - 1)
        hit = next((r for r in history_rows if r.date == target), None)
        memory = (
            f"On this day last year: {hit.t_mean or 0.0:.1f}°C, wind {hit.ws_mean or 0.0:.1f} m/s, precip {hit.precip_sum or 0.0:.1f} mm"
            if hit
            else "No same-date observation last year yet"
        )
        return (
            user_like.city,
            build_now_digest(
                city=user_like.city,
                current_temp_c=now_row.t,
                current_comfort_c=comfort_temperature(now_row.t, now_row.ws, now_row.r),
                current_wind_ms=now_row.ws,
                current_humidity_pct=now_row.r,
                current_precip_mm=now_row.tp,
                anomaly=anomaly,
                memory_line=memory,
            ),
        )

    async def build_stats_summary_for_city(self, city: str) -> tuple[str, str]:
        user_like, rows = await self._resolve_stateless_city(city)
        now_row = self._closest_forecast_point(rows)
        history_rows = await self._history_rows_stateless(user_like)
        today_row = ObsDaily(
            station_id=user_like.station_id,
            location_key=user_like.location_key,
            provider=user_like.weather_provider,
            date=date.today(),
            t_mean=now_row.t,
            ws_mean=now_row.ws,
            precip_sum=now_row.tp,
            rh_mean=now_row.r,
        )
        anomaly = self._anomaly_from_stateless_data(user_like, today_row=today_row, history_rows=history_rows)
        next_rows = [r for r in rows if 0 <= (r.valid_time - datetime.now(UTC)).total_seconds() <= 24 * 3600]
        rain_total = sum(r.tp for r in next_rows)
        rain_risk = "low" if rain_total < 0.3 else ("moderate" if rain_total < 2.0 else "high")
        wind_peak = max((r.gust for r in next_rows), default=0.0)
        avg_humidity = (sum(r.r for r in next_rows) / len(next_rows)) if next_rows else now_row.r
        sky_summary = _sky_label(avg_humidity, rain_total)
        try:
            target = date.today().replace(year=date.today().year - 1)
        except ValueError:
            target = date.today().replace(month=2, day=28, year=date.today().year - 1)
        hit = next((r for r in history_rows if r.date == target), None)
        memory = (
            f"On this day last year: {hit.t_mean or 0.0:.1f}°C, wind {hit.ws_mean or 0.0:.1f} m/s, precip {hit.precip_sum or 0.0:.1f} mm"
            if hit
            else "No same-date observation last year yet"
        )
        return (
            user_like.city,
            build_stats_digest(
                city=user_like.city,
                anomaly=anomaly,
                sky_summary=sky_summary,
                rain_risk=rain_risk,
                wind_peak=wind_peak,
                memory_line=memory,
            ),
        )

    async def build_forecast_digest_for_city(self, city: str, days: int) -> tuple[str, str]:
        if days not in {1, 3}:
            raise ValueError("forecast days must be 1 or 3")
        user_like, rows = await self._resolve_stateless_city(city)
        start_day = date.today() + timedelta(days=1)
        end_day = start_day + timedelta(days=days)
        grouped: dict[date, list] = defaultdict(list)
        for row in rows:
            day = row.valid_time.date()
            if start_day <= day < end_day:
                grouped[day].append(row)
        if not grouped:
            raise ValueError("No forecast rows available for the requested window")
        title = "📅 Forecast for tomorrow" if days == 1 else "📅 Forecast for next 3 days"
        lines = [title]
        for day in sorted(grouped.keys()):
            bucket = grouped[day]
            t_min = min(r.t for r in bucket)
            t_max = max(r.t for r in bucket)
            rain_total = sum(r.tp for r in bucket)
            wind_peak = max(r.gust for r in bucket)
            avg_temp = sum(r.t for r in bucket) / len(bucket)
            avg_humidity = sum(r.r for r in bucket) / len(bucket)
            rain_level = "low" if rain_total < 0.3 else ("moderate" if rain_total < 2.0 else "high")
            precip_kind = _precip_kind_label(avg_temp, rain_total)
            sky_text = _sky_label(avg_humidity, rain_total)
            lines.append(
                f"- {day.strftime('%a %d %b')}: {t_min:.1f}..{t_max:.1f}°C, "
                f"precip {rain_total:.1f} mm ({precip_kind}, {rain_level} risk), "
                f"wind peak {wind_peak:.1f} m/s, sky {sky_text}"
            )
        return user_like.city, "\n".join(lines)

    async def outfit_now_for_city(self, city: str, minutes_outside: int, activity: str) -> tuple[str, OutfitResponse]:
        user_like, rows = await self._resolve_stateless_city(city)
        now_row = self._closest_forecast_point(rows)
        advice = build_outfit_advice(
            OutfitInput(
                t=now_row.t,
                ws=now_row.ws,
                gust=now_row.gust,
                r=now_row.r,
                tp=now_row.tp,
                pmean=now_row.pmean,
                minutes_outside=minutes_outside,
                activity=activity,
            )
        )
        return user_like.city, OutfitResponse.model_validate(advice)

    def log_daily_digest(
        self,
        session: Session,
        telegram_id: int,
        payload_hash: str,
        for_date: date | None = None,
    ) -> None:
        row = DailyDigestLog(
            telegram_id=telegram_id,
            date=for_date or date.today(),
            payload_hash=payload_hash,
        )
        session.add(row)
        session.commit()

    def duplicate_user_profile_groups(self, session: Session) -> list[list[UserProfile]]:
        users = list(session.exec(select(UserProfile).order_by(UserProfile.created_at, UserProfile.id)).all())
        grouped: dict[str, list[UserProfile]] = defaultdict(list)
        for user in users:
            key = user.city.strip().lower()
            grouped[key].append(user)
        return [rows for rows in grouped.values() if len(rows) > 1]

    def remove_duplicate_user_profile(self, session: Session, profile_id: int) -> UserProfile:
        row = session.get(UserProfile, profile_id)
        if row is None:
            raise ValueError(f"user_profile id={profile_id} not found")

        target_city_key = row.city.strip().lower()
        same_city_rows = [
            user
            for user in session.exec(select(UserProfile).order_by(UserProfile.created_at, UserProfile.id)).all()
            if user.city.strip().lower() == target_city_key
        ]
        if len(same_city_rows) < 2:
            raise ValueError("profile is not in a duplicate city group")

        keeper = same_city_rows[0]
        if keeper.id == row.id:
            raise ValueError(f"refusing to delete primary profile id={row.id}; remove a newer duplicate instead")

        # Remove user-specific history tied to this telegram id.
        session.exec(delete(ComfortRating).where(ComfortRating.telegram_id == row.telegram_id))
        session.exec(delete(ComfortModelMeta).where(ComfortModelMeta.telegram_id == row.telegram_id))
        session.exec(delete(DailyDigestLog).where(DailyDigestLog.telegram_id == row.telegram_id))
        session.delete(row)
        session.commit()
        return row
