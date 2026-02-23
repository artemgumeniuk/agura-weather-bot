from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OutfitInput:
    t: float
    ws: float
    gust: float
    r: float
    tp: float
    pmean: float | None
    minutes_outside: int
    activity: str


def comfort_temperature(t: float, ws: float, r: float) -> float:
    # Practical approximation: wind-chill for cold, heat-index-like proxy for warm.
    if t <= 10:
        return 13.12 + 0.6215 * t - 11.37 * (ws * 3.6) ** 0.16 + 0.3965 * t * (ws * 3.6) ** 0.16
    if t >= 24:
        return t + 0.05 * (r - 40)
    return t


def precip_risk_bucket(tp: float, pmean: float | None) -> int:
    intensity = pmean if pmean is not None else tp
    if tp <= 0.05 and intensity <= 0.05:
        return 0
    if tp <= 0.6 and intensity <= 0.6:
        return 1
    if tp <= 2.5 and intensity <= 2.5:
        return 2
    return 3


def build_outfit_advice(payload: OutfitInput) -> dict:
    ctemp = comfort_temperature(payload.t, payload.ws, payload.r)
    risk = precip_risk_bucket(payload.tp, payload.pmean)

    activity_adjust = {"running": 4.0, "walking": 0.0, "standing": -4.0}.get(payload.activity, 0.0)
    exposure_adjust = -2.0 if payload.minutes_outside >= 60 else (0.0 if payload.minutes_outside <= 30 else -1.0)
    effective = ctemp + activity_adjust + exposure_adjust

    if effective <= -5:
        base = "thermal base layer"
        mid = "insulating fleece or wool"
        shell = "insulated waterproof shell"
    elif effective < 5:
        base = "long-sleeve base layer"
        mid = "light fleece"
        shell = "windproof shell"
    elif effective < 14:
        base = "breathable long-sleeve"
        mid = "optional light sweater"
        shell = "light jacket"
    else:
        base = "t-shirt base"
        mid = "no mid layer"
        shell = "packable light shell"

    shoes = "waterproof shoes" if risk >= 1 else "normal shoes"
    extras: list[str] = []
    if effective < 5:
        extras.extend(["gloves", "beanie"])
    if payload.ws >= 10 or payload.gust >= 14:
        extras.append("windproof outer layer")
    if effective > 16 and risk == 0:
        extras.append("sunglasses")

    rationale = [
        f"comfort temp {effective:.1f}°C (raw {payload.t:.1f}°C)",
        f"wind {payload.ws:.1f} m/s gust {payload.gust:.1f} m/s",
        f"precip risk bucket {risk}",
        f"exposure {payload.minutes_outside} min, activity {payload.activity}",
    ]

    return {
        "base_layer": base,
        "mid_layer": mid,
        "shell": shell,
        "shoes": shoes,
        "extras": extras,
        "rationale": rationale,
    }
