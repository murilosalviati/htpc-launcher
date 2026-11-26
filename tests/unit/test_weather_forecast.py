from htpc import weather

ANSWER = {
    "current": {"time": "2026-11-26T14:15", "temperature_2m": 24.6, "weather_code": 2, "is_day": 1},
    "hourly": {"time": [f"2026-11-26T{h:02d}:00" for h in range(24)] + [f"2026-11-27T{h:02d}:00" for h in range(24)],
               "temperature_2m": [20 + h % 10 for h in range(48)], "weather_code": [61] * 48,
               "is_day": [1 if 6 <= h % 24 < 19 else 0 for h in range(48)],
               "precipitation_probability": [40] * 48},
    "daily": {"time": ["2026-11-26", "2026-11-27"], "weather_code": [2, 95],
              "temperature_2m_max": [28.4, 30.2], "temperature_2m_min": [17.6, 19.1],
              "sunrise": ["2026-11-26T05:12", "2026-11-27T05:12"], "sunset": ["2026-11-26T18:41", "2026-11-27T18:42"],
              "precipitation_probability_max": [10, 80]},
}


def test_forecast_comes_with_the_current_weather():
    urls = []
    c = weather.current(-22.9, -47.0, fetch=lambda url: urls.append(url) or ANSWER)
    assert c.temperature == 25 and c.kind == "partly"
    f = c.forecast
    assert f.hours[0].hour == 14 and len(f.hours) == weather.HOURS + 1
    assert f.hours[-1].hour == 2 and f.hours[0].kind == "rain" and f.hours[0].rain == 40
    assert [(d.date, d.low, d.high, d.kind, d.rain) for d in f.days] == [
        ("2026-11-26", 18, 28, "partly", 10), ("2026-11-27", 19, 30, "storm", 80)]
    assert (f.sunrise, f.sunset) == ("05:12", "18:41")
    assert "daily=" in urls[0] and "timezone=auto" in urls[0]


def test_without_a_forecast_the_current_weather_still_comes():
    c = weather.current(0, 0, fetch=lambda url: {"current": {"temperature_2m": 10, "weather_code": 0, "is_day": 0}})
    assert c.temperature == 10 and c.forecast is None and c.icon == "weather-clear-night.svg"
