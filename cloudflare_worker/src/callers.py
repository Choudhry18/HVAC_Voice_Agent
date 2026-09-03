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
    phone_number = normalize_phone_number(str(body.get("phone_number") or ""))
    if not phone_number:
        return Response.json({"error": "PHONE_NUMBER_REQUIRED"}, status=400)
    stored_record = await env.CALLERS.get(f"caller:{phone_number}")
    if not stored_record:
        return Response.json({"found": False, "phone_number": phone_number})
    return Response.json({"found": True, **json.loads(stored_record)})


async def handle_remember(env, body: dict):
    phone_number = normalize_phone_number(str(body.get("phone_number") or ""))
    if not phone_number:
        return Response.json({"error": "PHONE_NUMBER_REQUIRED"}, status=400)
    name = str(body.get("name") or "").strip()
    previous_request = str(body.get("previous_request") or "").strip()
    address = str(body.get("address") or "").strip()
    if not name or not previous_request:
        return Response.json({"error": "NAME_AND_REQUEST_REQUIRED"}, status=400)

    record = {
        "phone_number": phone_number,
        "name": name,
        "previous_request": previous_request,
        "address": address,
        "property_type": str(
            body.get("property_type", "residential")
        ).strip().lower(),
        "business_name": str(body.get("business_name") or "").strip(),
        "service_code": str(body.get("service_code") or "").strip(),
        "equipment_details": str(body.get("equipment_details") or "").strip(),
        "operational_impact": str(body.get("operational_impact") or "").strip(),
        "access_notes": str(body.get("access_notes") or "").strip(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await env.CALLERS.put(f"caller:{phone_number}", json.dumps(record))
    return Response.json({"saved": True, **record})
