import requests

from .base import Skill, register

WEATHER_CODES = {
    0: "clear skies",
    1: "mostly clear skies",
    2: "partly cloudy skies",
    3: "overcast conditions",
    45: "foggy conditions",
    48: "freezing fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "moderate rain",
    65: "heavy rain",
    71: "light snow",
    73: "moderate snow",
    75: "heavy snow",
    80: "rain showers",
    81: "heavy rain showers",
    82: "violent rain showers",
    95: "a thunderstorm",
    96: "a thunderstorm with hail",
    99: "a severe thunderstorm with hail",
}


@register
class Weather(Skill):
    name = "weather"
    description = 'Get the current weather for a city. args: {"city": "city name"}'

    def execute(self, args):
        city = (args or {}).get("city", "").strip()
        if not city:
            return "Which city would you like the weather for, sir?"
        try:
            geo = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1},
                timeout=10,
            )
            geo.raise_for_status()
            results = geo.json().get("results")
            if not results:
                return f"I couldn't find a city called {city}, sir."
            location = results[0]
            forecast = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": location["latitude"],
                    "longitude": location["longitude"],
                    "current": "temperature_2m,weather_code,wind_speed_10m",
                },
                timeout=10,
            )
            forecast.raise_for_status()
            current = forecast.json().get("current", {})
        except requests.RequestException:
            return "I couldn't reach the weather service, sir."
        temperature = current.get("temperature_2m")
        code = current.get("weather_code")
        wind = current.get("wind_speed_10m")
        conditions = WEATHER_CODES.get(code, "unremarkable conditions")
        return (
            f"In {location['name']}, it's {round(temperature)} degrees with {conditions}, "
            f"and winds at {round(wind)} kilometres per hour, sir."
        )
