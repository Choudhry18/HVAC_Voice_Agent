import math
import os

import httpx


SERVICE_LOCATIONS = (
    {
        "name": "Downtown San Antonio",
        "latitude": 29.4241,
        "longitude": -98.4936,
    },
    {
        "name": "Stone Oak",
        "latitude": 29.6505,
        "longitude": -98.4495,
    },
    {
        "name": "Alamo Ranch",
        "latitude": 29.4867,
        "longitude": -98.7106,
    },
)
SERVICE_RADIUS_MILES = 35.0


def distance_miles(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    earth_radius_miles = 3958.8
    latitude_delta = math.radians(latitude_b - latitude_a)
    longitude_delta = math.radians(longitude_b - longitude_a)
    value = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(math.radians(latitude_a))
        * math.cos(math.radians(latitude_b))
        * math.sin(longitude_delta / 2) ** 2
    )
    return earth_radius_miles * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


async def check_service_location(address: str) -> dict[str, object]:
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return {
            "status": "SERVICE_UNAVAILABLE",
            "message": "Retry once. If the retry fails, keep the address as given and continue.",
        }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(
                "https://addressvalidation.googleapis.com/v1:validateAddress",
                json={
                    "address": {
                        "regionCode": "US",
                        "addressLines": [address],
                    },
                    "enableUspsCass": True,
                },
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": api_key,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return {
                "status": "SERVICE_UNAVAILABLE",
                "message": "Retry once. If the retry fails, keep the address as given and continue.",
            }

    payload = response.json()
    result = payload.get("result")
    if not result:
        return {
            "status": "NOT_FOUND",
            "message": "Ask the caller to repeat the full street address, city, state, and ZIP code.",
        }

    verdict = result.get("verdict", {})
    validated_address = result.get("address", {})
    geocode = result.get("geocode", {})
    location = geocode.get("location", {})
    action = verdict.get("possibleNextAction")
    if not action:
        action = (
            "ACCEPT"
            if verdict.get("addressComplete") and location.get("latitude") is not None
            else "FIX"
        )

    components = validated_address.get("addressComponents", [])
    unit = next(
        (
            component.get("componentName", {}).get("text")
            for component in components
            if component.get("componentType") == "subpremise"
        ),
        None,
    )
    corrected_components = [
        {
            "type": component.get("componentType"),
            "value": component.get("componentName", {}).get("text"),
            "inferred": component.get("inferred", False),
            "spell_corrected": component.get("spellCorrected", False),
            "replaced": component.get("replaced", False),
        }
        for component in components
        if component.get("inferred")
        or component.get("spellCorrected")
        or component.get("replaced")
    ]
    metadata = result.get("metadata", {})
    validation = {
        "status": action,
        "original_address": address,
        "address_metadata": {
            "business": metadata.get("business"),
            "residential": metadata.get("residential"),
            "po_box": metadata.get("poBox"),
        },
        "standardized_address": validated_address.get("formattedAddress"),
        "unit": unit,
        "missing_components": validated_address.get("missingComponentTypes", []),
        "unconfirmed_components": validated_address.get(
            "unconfirmedComponentTypes", []
        ),
        "unresolved_words": validated_address.get("unresolvedTokens", []),
        "corrected_components": corrected_components,
        "validation_granularity": verdict.get("validationGranularity"),
        "geocode_granularity": verdict.get("geocodeGranularity"),
        "confirmation_required": True,
        "response_id": payload.get("responseId"),
    }

    if action == "FIX" or location.get("latitude") is None:
        return {
            **validation,
            "message": "Ask the caller for the missing or suspicious address information.",
        }
    if action == "CONFIRM_ADD_SUBPREMISES":
        return {
            **validation,
            "message": "Ask whether the address has an apartment or suite number.",
        }

    latitude = float(location["latitude"])
    longitude = float(location["longitude"])
    locations = [
        {
            **service_location,
            "distance_miles": distance_miles(
                latitude,
                longitude,
                service_location["latitude"],
                service_location["longitude"],
            ),
        }
        for service_location in SERVICE_LOCATIONS
    ]
    nearest = min(locations, key=lambda item: item["distance_miles"])
    distance = round(nearest["distance_miles"], 1)
    serviceable = distance <= SERVICE_RADIUS_MILES
    return {
        **validation,
        "latitude": latitude,
        "longitude": longitude,
        "place_id": geocode.get("placeId"),
        "nearest_location": nearest["name"],
        "distance_miles": distance,
        "service_radius_miles": SERVICE_RADIUS_MILES,
        "serviceability": (
            "SERVICEABLE" if serviceable else "OUTSIDE_SERVICE_AREA"
        ),
        "message": "Read the standardized address and ask the caller to confirm it.",
    }
