from datetime import date

from app.schemas import OutfitResponse, TodayVsHistoryResponse
from app.services.digest import build_daily_digest, build_now_digest


def _sample_anomaly() -> TodayVsHistoryResponse:
    return TodayVsHistoryResponse(
        date=date(2026, 2, 20),
        station_id=71420,
        temp_anomaly_c=-6.8,
        temp_percentile=6.0,
        precip_streak_days=0,
        z_temp=-1.7,
        z_wind=0.4,
        z_precip=0.2,
        weirdness_score=1.8,
        baseline_years=30,
        confidence_note="high",
    )


def _sample_outfit() -> OutfitResponse:
    return OutfitResponse(
        base_layer="thermal base layer",
        mid_layer="insulating fleece or wool",
        shell="insulated waterproof shell",
        shoes="waterproof shoes",
        extras=["gloves", "beanie"],
        rationale=[],
    )


def test_build_daily_digest_emoji_format_and_memory_line():
    text = build_daily_digest(
        city="Göteborg, Västra Götalands län, Sverige",
        current_temp_c=-0.8,
        current_feels_like_c=-7.9,
        current_wind_ms=9.4,
        current_humidity_pct=82.0,
        current_precip_mm=0.8,
        anomaly=_sample_anomaly(),
        outfit=_sample_outfit(),
        sky_summary="mostly cloudy",
        rain_risk="high",
        precip_kind_now="snow",
        precip_kind_next_24h="mixed",
        wind_peak=16.2,
        memory_line="On this day last year: -0.0°C, wind 3.4 m/s, precip 0.0 mm",
        comfort_predicted_rating=2.0,
        comfort_bad_day_probability=0.65,
        comfort_model_ready=False,
    )

    lines = text.splitlines()
    assert lines[0].startswith("🌡️ ")
    assert lines[1].startswith("📊 ")
    assert lines[2].startswith("❄️📈 ")
    assert lines[3].startswith("🌤️ ")
    assert lines[4].startswith("🌧️ ")
    assert lines[5].startswith("💨 ")
    assert lines[6].startswith("🧥 ")
    assert lines[7].startswith("😌 ")
    assert lines[8].startswith("🕰️ On this day last year:")
    assert "Memory:" not in text
    assert "precip 0.8 mm (snow)" in lines[0]
    assert "Precip next 24h: mixed, risk high" in lines[4]


def test_build_daily_digest_fallback_last_year_line_without_memory_word():
    text = build_daily_digest(
        city="Göteborg",
        current_temp_c=0.0,
        current_feels_like_c=-2.0,
        current_wind_ms=3.0,
        current_humidity_pct=60.0,
        current_precip_mm=0.0,
        anomaly=_sample_anomaly(),
        outfit=_sample_outfit(),
        sky_summary="partly cloudy",
        rain_risk="low",
        precip_kind_now="none",
        precip_kind_next_24h="none",
        wind_peak=5.0,
        memory_line="No same-date observation last year yet",
        comfort_predicted_rating=3.0,
        comfort_bad_day_probability=0.15,
        comfort_model_ready=False,
    )

    assert "Memory:" not in text
    assert "🕰️ No same-date observation last year yet" in text


def test_build_now_digest_shape_and_weirdness_explanation():
    text = build_now_digest(
        city="Göteborg, Västra Götalands län, Sverige",
        current_temp_c=1.5,
        current_comfort_c=-1.0,
        current_wind_ms=2.2,
        current_humidity_pct=99.0,
        current_precip_mm=0.0,
        anomaly=TodayVsHistoryResponse(
            date=date(2026, 2, 20),
            station_id=71420,
            temp_anomaly_c=-1.2,
            temp_percentile=35.0,
            precip_streak_days=3,
            z_temp=-0.5,
            z_wind=0.3,
            z_precip=1.2,
            weirdness_score=1.4,
            baseline_years=30,
            confidence_note="high",
        ),
        memory_line="On this day last year: 4.1°C, wind 2.1 m/s, precip 0.0 mm",
    )
    lines = text.splitlines()
    assert lines[0] == "Göteborg — just now"
    assert lines[1] == "🌡️ 1.5°C (comfort -1.0°C)"
    assert lines[2] == "💨 2.2 m/s · 💧 99% · ☔ 0.0 mm"
    assert lines[3] == "📊 Vs normal: -1.2°C · Weirdness: 1.4 (notable)"
    assert lines[4] == (
        "Compared with typical weather for this date in your area, "
        "this is clearly different from normal, but still within a range that happens fairly regularly."
    )
    assert lines[5] == "🕰️ Last year today: 4.1°C, wind 2.1 m/s, precip 0.0 mm"


def test_build_now_digest_weirdness_explanation_boundaries():
    template = {
        "city": "Göteborg",
        "current_temp_c": 0.0,
        "current_comfort_c": -1.0,
        "current_wind_ms": 1.0,
        "current_humidity_pct": 70.0,
        "current_precip_mm": 0.0,
        "memory_line": "On this day last year: 0.0°C, wind 0.0 m/s, precip 0.0 mm",
    }
    for score, expected in [
        (0.9, "this is close to normal and within the usual day-to-day range."),
        (1.0, "this is clearly different from normal, but still within a range that happens fairly regularly."),
        (1.9, "this is clearly different from normal, but still within a range that happens fairly regularly."),
        (2.0, "this is clearly unusual and less common for this time of year."),
        (2.9, "this is clearly unusual and less common for this time of year."),
        (3.0, "this is highly unusual and close to rare-event territory."),
    ]:
        text = build_now_digest(
            **template,
            anomaly=TodayVsHistoryResponse(
                date=date(2026, 2, 20),
                station_id=1,
                temp_anomaly_c=0.0,
                temp_percentile=50.0,
                precip_streak_days=0,
                z_temp=0.0,
                z_wind=0.0,
                z_precip=0.0,
                weirdness_score=score,
                baseline_years=10,
                confidence_note="",
            ),
        )
        assert expected in text
