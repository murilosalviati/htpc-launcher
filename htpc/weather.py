# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Simple weather for the top bar: where the TV is, and what it is like outside.

  * Location: a Brazilian CEP (looked up on ViaCEP) or a city name, both turned
    into coordinates by Open-Meteo's geocoding. City precision is enough.
  * Conditions: Open-Meteo's current temperature, weather code and day/night.

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


@dataclass
class Conditions:
    temperature: int   # rounded, in the unit that was asked for
    kind: str          # clear, partly, cloudy, fog, rain, storm, snow
    is_day: bool

    @property
    def icon(self):
        """Icon file name in launcher/icons/."""
        if self.kind in ("clear", "partly"):
            return f"weather-{self.kind}-{'day' if self.is_day else 'night'}.svg"
        return f"weather-{self.kind}.svg"


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


def current(latitude, longitude, unit="celsius", fetch=http_json):
    """Conditions right now. unit: "celsius" or "fahrenheit". Raises Unreachable."""
    params = {"latitude": latitude, "longitude": longitude,
              "current": "temperature_2m,weather_code,is_day",
              "temperature_unit": "fahrenheit" if unit == "fahrenheit" else "celsius"}
    data = fetch(f"{FORECAST}?{urllib.parse.urlencode(params)}")
    try:
        now = data["current"]
        return Conditions(round(now["temperature_2m"]), kind_for_code(int(now["weather_code"])),
                          bool(now.get("is_day", 1)))
    except (KeyError, TypeError, ValueError) as e:
        raise Unreachable(f"unexpected answer: {e}") from e
