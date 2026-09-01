import os

import httpx


async def get_current_weather(
    latitude: float, longitude: float
) -> dict[str, object]:
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return {
            "status": "SERVICE_UNAVAILABLE",
            "message": "Continue without weather data.",
        }

    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return {
            "status": "INVALID_LOCATION",
            "message": "Continue without weather data.",
        }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                "https://weather.googleapis.com/v1/currentConditions:lookup",
                params={
                    "key": api_key,
                    "location.latitude": latitude,
                    "location.longitude": longitude,
                    "unitsSystem": "IMPERIAL",
                    "languageCode": "en",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return {
                "status": "SERVICE_UNAVAILABLE",
                "message": "Continue without weather data.",
            }

    weather_condition = payload.get("weatherCondition", {})
    condition_description = weather_condition.get("description", {})
    precipitation = payload.get("precipitation", {})
    precipitation_probability = precipitation.get("probability", {})

    return {
        "status": "OK",
        "current_time": payload.get("currentTime"),
        "time_zone": payload.get("timeZone", {}).get("id"),
        "is_daytime": payload.get("isDaytime"),
        "condition": condition_description.get("text"),
        "condition_type": weather_condition.get("type"),
        "temperature_fahrenheit": payload.get("temperature", {}).get("degrees"),
        "feels_like_fahrenheit": payload.get("feelsLikeTemperature", {}).get(
            "degrees"
        ),
        "heat_index_fahrenheit": payload.get("heatIndex", {}).get("degrees"),
        "wind_chill_fahrenheit": payload.get("windChill", {}).get("degrees"),
        "relative_humidity": payload.get("relativeHumidity"),
        "precipitation_probability": precipitation_probability.get("percent"),
        "thunderstorm_probability": payload.get("thunderstormProbability"),
    }
