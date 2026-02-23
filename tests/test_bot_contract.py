import pytest

from app.bot import (
    FORECAST_CALLBACK_PREFIX,
    NAV_CALLBACK_PREFIX,
    OUTFIT_CALLBACK_PREFIX,
    build_after_city_keyboard,
    build_after_forecast_keyboard,
    build_forecast_keyboard,
    build_now_actions_keyboard,
    build_outfit_keyboard,
    build_start_keyboard,
    parse_forecast_days,
    parse_outfit_args,
)


def test_parse_outfit_args_defaults():
    assert parse_outfit_args([]) == (15, "walking")


def test_parse_outfit_args_valid():
    assert parse_outfit_args(["60", "biking"]) == (60, "biking")


def test_parse_outfit_args_invalid_minutes():
    with pytest.raises(ValueError):
        parse_outfit_args(["25", "walking"])


def test_parse_outfit_args_invalid_activity():
    with pytest.raises(ValueError):
        parse_outfit_args(["15", "running"])


def test_build_start_keyboard_has_only_setcity():
    keyboard = build_start_keyboard().inline_keyboard
    assert len(keyboard) == 1
    assert len(keyboard[0]) == 1
    assert keyboard[0][0].text == "Set city"
    assert keyboard[0][0].callback_data == f"{NAV_CALLBACK_PREFIX}setcity"


def test_build_after_city_keyboard_has_weather_now_and_forecast():
    keyboard = build_after_city_keyboard().inline_keyboard
    callbacks = [row[0].callback_data for row in keyboard]
    assert callbacks == [f"{NAV_CALLBACK_PREFIX}now", f"{NAV_CALLBACK_PREFIX}forecast"]
    assert keyboard[0][0].text == "Weather now"
    assert keyboard[1][0].text == "Forecast"


def test_build_now_actions_keyboard_has_four_buttons_in_one_row():
    keyboard = build_now_actions_keyboard().inline_keyboard
    assert len(keyboard) == 1
    assert len(keyboard[0]) == 4
    assert [btn.callback_data for btn in keyboard[0]] == [
        f"{NAV_CALLBACK_PREFIX}outfit",
        f"{NAV_CALLBACK_PREFIX}forecast",
        f"{NAV_CALLBACK_PREFIX}stats",
        f"{NAV_CALLBACK_PREFIX}setcity",
    ]


def test_outfit_buttons_are_minute_explicit():
    keyboard = build_outfit_keyboard().inline_keyboard
    labels = [row[0].text for row in keyboard[:-1]]
    assert all(" min " in label for label in labels)
    assert labels == ["15 min walking", "60 min walking", "15 min biking", "60 min biking"]
    assert keyboard[-1][0].callback_data == f"{OUTFIT_CALLBACK_PREFIX}close"


def test_parse_forecast_days_defaults_and_valid():
    assert parse_forecast_days([]) == 1
    assert parse_forecast_days(["3"]) == 3


def test_parse_forecast_days_invalid():
    with pytest.raises(ValueError):
        parse_forecast_days(["2"])


def test_build_forecast_keyboard_options():
    keyboard = build_forecast_keyboard().inline_keyboard
    labels = [row[0].text for row in keyboard]
    callbacks = [row[0].callback_data for row in keyboard]
    assert labels == ["Forecast 1 day", "Forecast 3 days", "Close"]
    assert callbacks == [
        f"{FORECAST_CALLBACK_PREFIX}pick:1",
        f"{FORECAST_CALLBACK_PREFIX}pick:3",
        f"{FORECAST_CALLBACK_PREFIX}close",
    ]


def test_build_after_forecast_keyboard_has_weather_now():
    keyboard = build_after_forecast_keyboard().inline_keyboard
    assert len(keyboard) == 1
    assert len(keyboard[0]) == 1
    assert keyboard[0][0].text == "Weather now"
    assert keyboard[0][0].callback_data == f"{NAV_CALLBACK_PREFIX}now"
