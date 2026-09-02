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
    property_type: str = "residential",
    service_code: str | None = None,
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
                    "property_type": property_type,
                    "service_code": service_code,
                    "preferred_date": preferred_date,
                    "time_preference": time_preference,
                },
                headers=headers,
            )
            if response.status_code in {400, 404} and property_type == "commercial":
                return {
                    "status": "STAFF_REVIEW",
                    "message": (
                        "No qualified commercial time is available. Collect the "
                        "remaining details, save a commercial request, and tell "
                        "the caller that staff will follow up."
                    ),
                }
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
    property_type: str = "residential",
    service_code: str | None = None,
    classification_confidence: float | None = None,
    business_name: str = "",
    site_contact_name: str = "",
    site_contact_phone: str = "",
    issue_description: str = "",
    equipment_details: str = "",
    operational_impact: str = "",
    access_notes: str = "",
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
                    "property_type": property_type,
                    "service_code": service_code,
                    "classification_confidence": classification_confidence,
                    "business_name": business_name,
                    "site_contact_name": site_contact_name,
                    "site_contact_phone": site_contact_phone,
                    "issue_description": issue_description,
                    "equipment_details": equipment_details,
                    "operational_impact": operational_impact,
                    "access_notes": access_notes,
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
            if response.status_code == 400 and property_type == "commercial":
                return {
                    "status": "STAFF_REVIEW",
                    "message": (
                        "Do not book this commercial request. Save it for staff "
                        "review and tell the caller that staff will follow up."
                    ),
                }
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            return SERVICE_UNAVAILABLE_RESULT


async def classify_commercial_service(
    issue_description: str,
) -> dict[str, object]:
    url, headers = request_settings()
    if not url:
        return {
            "status": "STAFF_REVIEW",
            "service_code": "other_or_unclear",
            "confidence": 0.0,
            "message": "Collect the commercial request for staff review.",
        }

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.post(
                f"{url.rstrip('/')}/classify-commercial-service",
                json={"issue_description": issue_description},
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            return {
                "status": "STAFF_REVIEW",
                "service_code": "other_or_unclear",
                "confidence": 0.0,
                "message": "Collect the commercial request for staff review.",
            }


async def save_commercial_request(
    business_name: str,
    site_contact_name: str,
    site_contact_phone: str,
    address: str,
    issue_description: str,
    service_code: str = "other_or_unclear",
    classification_confidence: float = 0.0,
    equipment_details: str = "",
    operational_impact: str = "",
    access_notes: str = "",
    preferred_time: str = "",
) -> dict[str, object]:
    url, headers = request_settings()
    if not url:
        return SERVICE_UNAVAILABLE_RESULT

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            response = await client.post(
                f"{url.rstrip('/')}/commercial-request",
                json={
                    "business_name": business_name,
                    "site_contact_name": site_contact_name,
                    "site_contact_phone": site_contact_phone,
                    "address": address,
                    "issue_description": issue_description,
                    "service_code": service_code,
                    "classification_confidence": classification_confidence,
                    "equipment_details": equipment_details,
                    "operational_impact": operational_impact,
                    "access_notes": access_notes,
                    "preferred_time": preferred_time,
                },
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            return SERVICE_UNAVAILABLE_RESULT
