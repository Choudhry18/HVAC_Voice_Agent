"""Caller memory: lookup and remember customer records by phone number."""

import json
from datetime import datetime, timezone

from workers import Response


def normalize_phone_number(phone_number: str) -> str:
    digits = "".join(character for character in phone_number if character.isdigit())
    if len(digits) == 10:
        digits = f"1{digits}"
    return f"+{digits}" if digits else ""


async def handle_lookup(env, body: dict):
    phone_number = normalize_phone_number(str(body.get("phone_number", "")))
    if not phone_number:
        return Response.json({"error": "PHONE_NUMBER_REQUIRED"}, status=400)
    stored_record = await env.CALLERS.get(f"caller:{phone_number}")
    if not stored_record:
        return Response.json({"found": False, "phone_number": phone_number})
    return Response.json({"found": True, **json.loads(stored_record)})


async def handle_remember(env, body: dict):
    phone_number = normalize_phone_number(str(body.get("phone_number", "")))
    if not phone_number:
        return Response.json({"error": "PHONE_NUMBER_REQUIRED"}, status=400)
    name = str(body.get("name", "")).strip()
    previous_request = str(body.get("previous_request", "")).strip()
    address = str(body.get("address", "")).strip()
    if not name or not previous_request:
        return Response.json({"error": "NAME_AND_REQUEST_REQUIRED"}, status=400)

    record = {
        "phone_number": phone_number,
        "name": name,
        "previous_request": previous_request,
        "address": address,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await env.CALLERS.put(f"caller:{phone_number}", json.dumps(record))
    return Response.json({"saved": True, **record})
