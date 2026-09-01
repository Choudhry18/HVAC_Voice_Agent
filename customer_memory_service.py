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


async def remember_customer(
    phone_number: str | None, name: str, request_summary: str
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
