import os

import httpx


def request_settings() -> tuple[str | None, dict[str, str]]:
    url = os.getenv("CUSTOMER_MEMORY_URL")
    token = os.getenv("CUSTOMER_MEMORY_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return url, headers


async def lookup_customer(phone_number: str | None) -> dict[str, object] | None:
    url, headers = request_settings()
    if not url or not phone_number:
        return None

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            response = await client.post(
                f"{url.rstrip('/')}/lookup",
                json={"phone_number": phone_number},
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None

    if not payload.get("found"):
        return None
    return payload


async def record_note(
    note: str,
    name: str = "",
    contact: str = "",
) -> dict[str, object]:
    url, headers = request_settings()
    if not url:
        return {
            "status": "SKIPPED",
            "message": "Continue without reporting this result to the caller.",
        }

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            response = await client.post(
                f"{url.rstrip('/')}/note",
                json={"note": note, "name": name, "contact": contact},
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return {
                "status": "SERVICE_UNAVAILABLE",
                "message": "Continue without reporting this result to the caller.",
            }

    return {"status": "SAVED"}


async def remember_customer(
    phone_number: str | None,
    name: str,
    request_summary: str,
    address: str = "",
    property_type: str = "residential",
    business_name: str = "",
    service_code: str = "",
    equipment_details: str = "",
    operational_impact: str = "",
    access_notes: str = "",
) -> dict[str, object]:
    url, headers = request_settings()
    if not url or not phone_number:
        return {
            "status": "SKIPPED",
            "message": "Continue without reporting this result to the caller.",
        }

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            response = await client.post(
                f"{url.rstrip('/')}/remember",
                json={
                    "phone_number": phone_number,
                    "name": name,
                    "previous_request": request_summary,
                    "address": address,
                    "property_type": property_type,
                    "business_name": business_name,
                    "service_code": service_code,
                    "equipment_details": equipment_details,
                    "operational_impact": operational_impact,
                    "access_notes": access_notes,
                },
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return {
                "status": "SERVICE_UNAVAILABLE",
                "message": "Continue without reporting this result to the caller.",
            }

    return {"status": "SAVED"}
