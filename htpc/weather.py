# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Simple weather for the top bar: where the TV is, and what it is like outside.

  * Location: a Brazilian CEP (looked up on ViaCEP) or a city name, both turned
    into coordinates by Open-Meteo's geocoding. City precision is enough.
  * Conditions: Open-Meteo's current temperature, weather code and day/night,
    and in the same answer the next hours, the next days, sunrise and sunset.

Both services are free and need no account or key. Nothing here touches the
UI or the operating system: every function takes a `fetch(url) -> dict` so the
tests can answer without a network. Calls block, so the launcher runs them in
a thread.
"""

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import __version__

VIACEP = "https://viacep.com.br/ws/{cep}/json/"
GEOCODING = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 10

# Brazilian states: UF -> name as Open-Meteo's geocoding writes it (admin1).
STATES = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia",
    "CE": "Ceará", "DF": "Federal District", "ES": "Espírito Santo", "GO": "Goiás",
    "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro",
    "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul", "RO": "Rondônia",
    "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo", "SE": "Sergipe",
    "TO": "Tocantins",
}
DF_NAMES = ("federal district", "distrito federal")


class NotFound(LookupError):
    """The CEP or city does not exist."""


class Unreachable(OSError):
    """The service could not be reached (no internet, service down...)."""


@dataclass
class Place:
    name: str          # what the settings show, e.g. "Campinas, SP"
    latitude: float
    longitude: float


def icon_for(kind, is_day=True):
    """Icon file name in launcher/icons/ for a kind of weather."""
    if kind in ("clear", "partly"):
        return f"weather-{kind}-{'day' if is_day else 'night'}.svg"
    return f"weather-{kind}.svg"


@dataclass
class Hour:
    hour: int          # 0..23, local time
    temperature: int
    kind: str
    is_day: bool
    rain: int = None   # chance of rain, %

    @property
    def icon(self):
        return icon_for(self.kind, self.is_day)


@dataclass
class Day:
    date: str          # YYYY-MM-DD
    low: int
    high: int
    kind: str
    rain: int = None   # highest chance of rain that day, %

    @property
    def icon(self):
        return icon_for(self.kind)


@dataclass
class Forecast:
    hours: list        # [Hour], from the current hour on
    days: list         # [Day], today first
    sunrise: str = ""  # "06:12", today
    sunset: str = ""


@dataclass
class Conditions:
    temperature: int   # rounded, in the unit that was asked for
    kind: str          # clear, partly, cloudy, fog, rain, storm, snow
    is_day: bool
    forecast: Forecast = None

    @property
    def icon(self):
        """Icon file name in launcher/icons/."""
        return icon_for(self.kind, self.is_day)


def http_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": f"htpc-launcher/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as e:
        raise Unreachable(str(e)) from e


# --- location -----------------------------------------------------------------------

def cep_digits(text):
    """The 8 digits of a CEP ("13010-001", "13010001", "13.010-001"), else None."""
    digits = re.sub(r"[\s.\-]", "", text or "")
    return digits if re.fullmatch(r"\d{8}", digits) else None


def _same(a, b):
    return (a or "").casefold() == (b or "").casefold()


def find_place(query, language="en", fetch=http_json):
    """CEP or city name -> Place. Raises NotFound or Unreachable."""
    query = (query or "").strip()
    if not query:
        raise NotFound(query)
    cep = cep_digits(query)
    if cep:
        data = fetch(VIACEP.format(cep=cep))
        if not data or str(data.get("erro", "")).lower() == "true" or not data.get("localidade"):
            raise NotFound(query)
        return _geocode(data["localidade"], language, fetch, uf=data.get("uf", "").upper())
    return _geocode(query, language, fetch)


def _geocode(name, language, fetch, uf=None):
    params = {"name": name, "count": 10, "language": "pt" if language.startswith("pt") else "en",
              "format": "json"}
    if uf:
        params["countryCode"] = "BR"
    results = fetch(f"{GEOCODING}?{urllib.parse.urlencode(params)}").get("results") or []
    if uf:
        # Several towns share a name: keep the one in the CEP's state.
        state = STATES.get(uf, "")
        in_state = [r for r in results if _same(r.get("admin1"), state)
                    or (uf == "DF" and (r.get("admin1") or "").casefold() in DF_NAMES)]
        exact = [r for r in in_state if _same(r.get("name"), name)]
        results = exact or in_state
    if not results:
        raise NotFound(name)
    r = results[0]
    if uf:
        label = f"{r['name']}, {uf}"
    elif r.get("country_code") == "BR":
        uf_of = next((k for k, v in STATES.items() if _same(v, r.get("admin1"))), None)
        label = f"{r['name']}, {uf_of}" if uf_of else r["name"]
    else:
        label = ", ".join(x for x in (r["name"], r.get("admin1") or r.get("country")) if x)
    return Place(label, float(r["latitude"]), float(r["longitude"]))


# --- conditions -----------------------------------------------------------------------

def kind_for_code(code):
    """WMO weather code (what Open-Meteo returns) -> one of our icon kinds."""
    if code in (0, 1):
        return "clear"
    if code == 2:
        return "partly"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "storm"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    return "cloudy"


HOURS = 12        # hours shown after the current one
DAYS = 6          # today and the next five


def current(latitude, longitude, unit="celsius", fetch=http_json):
    """Conditions right now, with the forecast. unit: "celsius" or "fahrenheit".
    Raises Unreachable."""
    params = {"latitude": latitude, "longitude": longitude,
              "current": "temperature_2m,weather_code,is_day",
              "hourly": "temperature_2m,weather_code,is_day,precipitation_probability",
              "daily": "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,"
                       "precipitation_probability_max",
              "timezone": "auto", "forecast_days": DAYS,
              "temperature_unit": "fahrenheit" if unit == "fahrenheit" else "celsius"}
    data = fetch(f"{FORECAST}?{urllib.parse.urlencode(params)}")
    try:
        now = data["current"]
        conditions = Conditions(round(now["temperature_2m"]), kind_for_code(int(now["weather_code"])),
                                bool(now.get("is_day", 1)))
    except (KeyError, TypeError, ValueError) as e:
        raise Unreachable(f"unexpected answer: {e}") from e
    try:
        conditions.forecast = _forecast(data, now.get("time", ""))
    except (KeyError, TypeError, ValueError, IndexError):
        conditions.forecast = None   # the current weather still shows
    return conditions


def _pct(values, i):
    v = (values or [None] * (i + 1))[i]
    return None if v is None else round(v)


def _forecast(data, now):
    hourly, daily = data.get("hourly"), data.get("daily")
    if not hourly or not daily:
        return None
    this_hour = now[:13]   # "2026-11-26T14"
    times = hourly["time"]
    start = next((i for i, t in enumerate(times) if t[:13] >= this_hour), 0) if this_hour else 0
    hours = [Hour(int(times[i][11:13]), round(hourly["temperature_2m"][i]),
                  kind_for_code(int(hourly["weather_code"][i])), bool(hourly["is_day"][i]),
                  _pct(hourly.get("precipitation_probability"), i))
             for i in range(start, min(len(times), start + HOURS + 1))]
    days = [Day(daily["time"][i], round(daily["temperature_2m_min"][i]), round(daily["temperature_2m_max"][i]),
                kind_for_code(int(daily["weather_code"][i])), _pct(daily.get("precipitation_probability_max"), i))
            for i in range(len(daily["time"]))]
    sunrise, sunset = (daily.get("sunrise") or [""])[0], (daily.get("sunset") or [""])[0]
    return Forecast(hours, days, sunrise[11:16], sunset[11:16])
