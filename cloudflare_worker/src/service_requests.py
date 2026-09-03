"""Persist unbooked residential and commercial requests for staff review."""

import json
import uuid
from datetime import datetime, timezone

from workers import Response


VALID_PROPERTY_TYPES = {"residential", "commercial"}


async def handle_service_request(env, body: dict):
    property_type = str(body.get("property_type", "")).strip().lower()
    required = {
        "customer_name": str(body.get("customer_name", "")).strip(),
        "customer_phone": str(body.get("customer_phone", "")).strip(),
        "address": str(body.get("address", "")).strip(),
        "issue_description": str(body.get("issue_description", "")).strip(),
        "review_reason": str(body.get("review_reason", "")).strip().upper(),
    }
    if property_type not in VALID_PROPERTY_TYPES:
        return Response.json({"error": "INVALID_PROPERTY_TYPE"}, status=400)
    if not all(required.values()):
        return Response.json({"error": "MISSING_FIELDS"}, status=400)

    commercial_fields = {
        "business_name": str(body.get("business_name", "")).strip(),
        "site_contact_name": str(body.get("site_contact_name", "")).strip(),
        "site_contact_phone": str(body.get("site_contact_phone", "")).strip(),
        "service_code": str(
            body.get("service_code", "other_or_unclear")
        ).strip(),
        "classification_confidence": body.get("classification_confidence", 0.0),
        "equipment_details": str(body.get("equipment_details", "")).strip(),
        "operational_impact": str(body.get("operational_impact", "")).strip(),
        "access_notes": str(body.get("access_notes", "")).strip(),
    }
    if property_type == "commercial" and not all(
        commercial_fields[field]
        for field in ("business_name", "site_contact_name", "site_contact_phone")
    ):
        return Response.json({"error": "MISSING_COMMERCIAL_FIELDS"}, status=400)

    request_id = f"sr-{uuid.uuid4().hex[:8]}"
    record = {
        "request_id": request_id,
        "property_type": property_type,
        **required,
        "is_emergency": bool(body.get("is_emergency", False)),
        "emergency_reason_code": str(
            body.get("emergency_reason_code", "")
        ).strip(),
        "emergency_reason": str(body.get("emergency_reason", "")).strip(),
        **commercial_fields,
        "preferred_time": str(body.get("preferred_time", "")).strip(),
        "status": "STAFF_REVIEW",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await env.CALLERS.put(f"service-request:{request_id}", json.dumps(record))
    return Response.json({"saved": True, **record})
