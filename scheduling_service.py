import httpx

from customer_memory_service import request_settings

SEVERE_HEAT_FAHRENHEIT = 100.0
SEVERE_COLD_FAHRENHEIT = 32.0
SEVERE_THUNDERSTORM_PROBABILITY = 50.0
SEVERE_CONDITION_TYPES = {
    "THUNDERSTORM",
    "THUNDERSHOWER",
    "HEAVY_THUNDERSTORM",
    "SCATTERED_THUNDERSTORMS",
    "HAIL",
    "HAIL_SHOWERS",
    "SNOW_STORM",
    "BLIZZARD",
}

SERVICE_UNAVAILABLE_RESULT = {
    "status": "SERVICE_UNAVAILABLE",
    "message": (
        "Tell the caller staff will call back to schedule. "
        "Continue without reporting this failure."
    ),
}


def severe_temperature_kind(weather: dict[str, object] | None) -> str | None:
    """Return "heat" or "cold" when the measured temperature alone is severe."""
    if not weather or weather.get("status") != "OK":
        return None
    temperature = weather.get("temperature_fahrenheit")
    if isinstance(temperature, (int, float)):
        if temperature >= SEVERE_HEAT_FAHRENHEIT:
            return "heat"
        if temperature <= SEVERE_COLD_FAHRENHEIT:
            return "cold"
    return None


def is_severe_weather(weather: dict[str, object] | None) -> bool:
    if not weather or weather.get("status") != "OK":
        return False
    temperature = weather.get("temperature_fahrenheit")
    if isinstance(temperature, (int, float)):
        if temperature >= SEVERE_HEAT_FAHRENHEIT or temperature <= SEVERE_COLD_FAHRENHEIT:
            return True
    thunderstorm = weather.get("thunderstorm_probability")
    if isinstance(thunderstorm, (int, float)) and thunderstorm >= SEVERE_THUNDERSTORM_PROBABILITY:
        return True
    condition_type = str(weather.get("condition_type", "")).upper()
    return condition_type in SEVERE_CONDITION_TYPES


async def find_available_slots(
    location: str,
    is_emergency: bool,
    severe_weather: bool,
    preferred_date: str | None = None,
    time_preference: str | None = None,
) -> dict[str, object]:
    url, headers = request_settings()
    if not url:
        return SERVICE_UNAVAILABLE_RESULT

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            response = await client.post(
                f"{url.rstrip('/')}/availability",
                json={
                    "location": location,
                    "is_emergency": is_emergency,
                    "severe_weather": severe_weather,
                    "preferred_date": preferred_date,
                    "time_preference": time_preference,
                },
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            return SERVICE_UNAVAILABLE_RESULT


async def lookup_booking(booking_id: str) -> dict[str, object]:
    url, headers = request_settings()
    if not url:
        return SERVICE_UNAVAILABLE_RESULT

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            response = await client.post(
                f"{url.rstrip('/')}/booking-lookup",
                json={"booking_id": booking_id},
                headers=headers,
            )
            if response.status_code == 404:
                return {
                    "status": "BOOKING_NOT_FOUND",
                    "message": (
                        "Tell the caller you could not find a booking with that "
                        "ID and ask them to repeat it, or say a representative "
                        "will follow up."
                    ),
                }
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            return SERVICE_UNAVAILABLE_RESULT


async def update_booking(
    booking_id: str,
    action: str,
    tech_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, object]:
    url, headers = request_settings()
    if not url:
        return SERVICE_UNAVAILABLE_RESULT

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            response = await client.post(
                f"{url.rstrip('/')}/booking-update",
                json={
                    "booking_id": booking_id,
                    "action": action,
                    "tech_id": tech_id,
                    "start": start,
                    "end": end,
                },
                headers=headers,
            )
            if response.status_code == 404:
                return {
                    "status": "BOOKING_NOT_FOUND",
                    "message": (
                        "Tell the caller you could not find that booking and "
                        "ask them to repeat the booking ID."
                    ),
                }
            if response.status_code == 409:
                return {
                    "status": "SLOT_TAKEN",
                    "message": (
                        "That time was just taken. Apologize and call "
                        "find_appointment_slots again to offer other times."
                    ),
                }
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            return SERVICE_UNAVAILABLE_RESULT


async def book_appointment(
    tech_id: str,
    start: str,
    end: str,
    customer_name: str,
    customer_phone: str,
    address: str,
    summary: str,
    is_emergency: bool,
    after_hours: bool,
) -> dict[str, object]:
    url, headers = request_settings()
    if not url:
        return SERVICE_UNAVAILABLE_RESULT

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            response = await client.post(
                f"{url.rstrip('/')}/book",
                json={
                    "tech_id": tech_id,
                    "start": start,
                    "end": end,
                    "customer_name": customer_name,
                    "customer_phone": customer_phone,
                    "address": address,
                    "summary": summary,
                    "is_emergency": is_emergency,
                    "after_hours": after_hours,
                },
                headers=headers,
            )
            if response.status_code == 409:
                return {
                    "status": "SLOT_TAKEN",
                    "message": (
                        "That time was just taken. Apologize and call "
                        "find_appointment_slots again to offer other times."
                    ),
                }
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            return SERVICE_UNAVAILABLE_RESULT
