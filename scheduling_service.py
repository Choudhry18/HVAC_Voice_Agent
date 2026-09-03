import httpx

from customer_memory_service import request_settings

SERVICE_UNAVAILABLE_RESULT = {
    "status": "SERVICE_UNAVAILABLE",
    "message": (
        "Tell the caller staff will call back to schedule. "
        "Continue without reporting this failure."
    ),
}


async def find_available_slots(
    location: str,
    issue_type: str,
    property_type: str = "residential",
    service_code: str | None = None,
    classification_confidence: float | None = None,
    issue_description: str | None = None,
    equipment_details: str | None = None,
    escalation_context: str | None = None,
    weather: dict[str, object] | None = None,
    preferred_date: str | None = None,
    time_preference: str | None = None,
) -> dict[str, object]:
    url, headers = request_settings()
    if not url:
        return SERVICE_UNAVAILABLE_RESULT

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.post(
                f"{url.rstrip('/')}/availability",
                json={
                    "location": location,
                    "issue_type": issue_type,
                    "property_type": property_type,
                    "service_code": service_code,
                    "classification_confidence": classification_confidence,
                    "issue_description": issue_description,
                    "equipment_details": equipment_details,
                    "escalation_context": escalation_context,
                    "weather": weather,
                    "preferred_date": preferred_date,
                    "time_preference": time_preference,
                },
                headers=headers,
            )
            if response.status_code == 404:
                return {
                    "status": "STAFF_REVIEW",
                    "property_type": property_type,
                    "review_reason": "NO_TECHNICIANS",
                    "message": (
                        "No suitable appointment is available. Collect the "
                        "remaining details, save a service request, and tell "
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
            if response.status_code == 400:
                return {
                    "status": "STAFF_REVIEW",
                    "property_type": property_type,
                    "review_reason": "BOOKING_REJECTED",
                    "message": (
                        "Do not claim the appointment is booked. Save the request for staff "
                        "review and tell the caller that staff will follow up."
                    ),
                }
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            return SERVICE_UNAVAILABLE_RESULT


async def save_service_request(
    customer_name: str,
    customer_phone: str,
    property_type: str,
    is_emergency: bool,
    emergency_reason_code: str,
    emergency_reason: str,
    review_reason: str,
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
                f"{url.rstrip('/')}/service-request",
                json={
                    "customer_name": customer_name,
                    "customer_phone": customer_phone,
                    "property_type": property_type,
                    "is_emergency": is_emergency,
                    "emergency_reason_code": emergency_reason_code,
                    "emergency_reason": emergency_reason,
                    "review_reason": review_reason,
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
