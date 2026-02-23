from __future__ import annotations

from app.schemas import OutfitResponse, TodayVsHistoryResponse


def _short_city(city: str) -> str:
    return city.split(",")[0].strip() if city else "your location"


def _weirdness_label(score: float) -> str:
    if score < 1.0:
        return "mostly normal"
    if score < 2.0:
        return "notable"
    if score < 3.0:
        return "clearly unusual"
    return "very unusual"


def _weirdness_explanation(score: float) -> str:
    if score < 1.0:
        return "Compared with typical weather for this date in your area, this is close to normal and within the usual day-to-day range."
    if score < 2.0:
        return "Compared with typical weather for this date in your area, this is clearly different from normal, but still within a range that happens fairly regularly."
    if score < 3.0:
        return "Compared with typical weather for this date in your area, this is clearly unusual and less common for this time of year."
    return "Compared with typical weather for this date in your area, this is highly unusual and close to rare-event territory."


def _percentile_label(percentile: float) -> str:
    if percentile <= 10:
        return "unusually cold"
    if percentile >= 90:
        return "unusually warm"
    if percentile <= 30:
        return "cooler than usual"
    if percentile >= 70:
        return "warmer than usual"
    return "near normal"


def build_daily_digest(
    city: str,
    current_temp_c: float,
    current_feels_like_c: float,
    current_wind_ms: float,
    current_humidity_pct: float,
    current_precip_mm: float,
    anomaly: TodayVsHistoryResponse,
    outfit: OutfitResponse,
    sky_summary: str | None,
    rain_risk: str,
    precip_kind_now: str,
    precip_kind_next_24h: str,
    wind_peak: float,
    memory_line: str,
    comfort_predicted_rating: float,
    comfort_bad_day_probability: float,
    comfort_model_ready: bool,
) -> str:
    city_label = _short_city(city)
    weirdness_text = _weirdness_label(anomaly.weirdness_score)
    percentile_text = _percentile_label(anomaly.temp_percentile)

    now_line = (
        f"🌡️ Now in {city_label}: {current_temp_c:.1f}°C "
        f"(feels {current_feels_like_c:.1f}°C), wind {current_wind_ms:.1f} m/s, "
        f"humidity {current_humidity_pct:.0f}%, precip {current_precip_mm:.1f} mm ({precip_kind_now})"
    )
    anomaly_line = (
        f"📊 Today vs normal: {anomaly.temp_anomaly_c:+.1f}°C | "
        f"weirdness {anomaly.weirdness_score:.1f}: {weirdness_text}"
    )
    bullets = [
        f"❄️📈 Temp percentile: {anomaly.temp_percentile:.0f}% - {percentile_text} | "
        f"Streak: {anomaly.precip_streak_days} wet days",
        f"🌤️ Sky next 24h: {sky_summary}" if sky_summary else None,
        f"🌧️ Precip next 24h: {precip_kind_next_24h}, risk {rain_risk}",
        f"💨 Wind peak next 24h: {wind_peak:.1f} m/s",
        f"🧥 Outfit now: {outfit.base_layer}, {outfit.shell}, {outfit.shoes}",
        (
            f"😌 Comfort: {comfort_predicted_rating:.2f}/5 | "
            f"Bad-day probability: {comfort_bad_day_probability:.0%} | "
            f"Model ready: {comfort_model_ready}"
        ),
    ]
    bullets = [line for line in bullets if line]
    return "\n".join([now_line, anomaly_line, *bullets, f"🕰️ {memory_line}"])


def build_now_digest(
    city: str,
    current_temp_c: float,
    current_comfort_c: float,
    current_wind_ms: float,
    current_humidity_pct: float,
    current_precip_mm: float,
    anomaly: TodayVsHistoryResponse,
    memory_line: str,
) -> str:
    city_label = _short_city(city)
    weirdness_text = _weirdness_label(anomaly.weirdness_score)
    weirdness_expl = _weirdness_explanation(anomaly.weirdness_score)
    memory_short = memory_line.replace("On this day last year: ", "", 1)

    return "\n".join(
        [
            f"{city_label} — just now",
            f"🌡️ {current_temp_c:.1f}°C (comfort {current_comfort_c:.1f}°C)",
            f"💨 {current_wind_ms:.1f} m/s · 💧 {current_humidity_pct:.0f}% · ☔ {current_precip_mm:.1f} mm",
            f"📊 Vs normal: {anomaly.temp_anomaly_c:+.1f}°C · Weirdness: {anomaly.weirdness_score:.1f} ({weirdness_text})",
            weirdness_expl,
            f"🕰️ Last year today: {memory_short}",
        ]
    )


def build_stats_digest(
    city: str,
    anomaly: TodayVsHistoryResponse,
    sky_summary: str | None,
    rain_risk: str,
    wind_peak: float,
    memory_line: str,
) -> str:
    city_label = _short_city(city)
    percentile_text = _percentile_label(anomaly.temp_percentile)
    lines = [
        f"📈 Stats for {city_label}",
        f"- Temp percentile: {anomaly.temp_percentile:.0f}% ({percentile_text})",
        f"- Wet streak: {anomaly.precip_streak_days} days",
        f"- Baseline confidence: {anomaly.confidence_note}",
    ]
    if sky_summary:
        lines.append(f"- Sky next 24h: {sky_summary}")
    lines.extend(
        [
            f"- Rain risk next 24h: {rain_risk}",
            f"- Wind peak next 24h: {wind_peak:.1f} m/s",
            f"- {memory_line}",
        ]
    )
    return "\n".join(lines)
