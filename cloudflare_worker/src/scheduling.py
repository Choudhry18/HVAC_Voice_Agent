"""Technician availability search and appointment booking."""

import json
import uuid
from datetime import datetime, timedelta, timezone

from workers import Response

from callers import normalize_phone_number
from commercial_services import (
    MINIMUM_CLASSIFICATION_CONFIDENCE,
    classify_issue,
    commercial_service,
)
from emergency_services import grade_emergency
from observability import log_event
from timeslots import (
    BUSINESS_CLOSE_HOUR,
    BUSINESS_OPEN_HOUR,
    BUSINESS_TIMEZONE,
    SERVICE_LOCATIONS,
    SLOT_HOURS,
    open_slots_for_tech,
    overlaps,
    parse_time,
    spoken_slot,
)


def normalize_booking_id(raw: object) -> str:
    cleaned = "".join(ch for ch in str(raw).lower() if ch.isalnum())
    if cleaned.startswith("bk"):
        cleaned = cleaned[2:]
    return f"bk-{cleaned}" if cleaned else ""


async def load_technicians(env) -> list[dict]:
    stored = await env.CALLERS.get("techs:index")
    return json.loads(stored) if stored else []


async def load_jobs(env, tech_id: str) -> list[dict]:
    stored = await env.CALLERS.get(f"jobs:{tech_id}")
    return json.loads(stored) if stored else []


def technician_has_skill(technician: dict, required_skill: object) -> bool:
    """Return true when the technician has the required commercial skill."""
    return str(required_skill or "") in technician.get("commercial_skills", [])


def _commercial_booking_service(service_code: object) -> tuple[dict | None, str | None]:
    service = commercial_service(service_code)
    if not service:
        return None, "UNKNOWN_COMMERCIAL_SERVICE"
    if not service.get("bookable"):
        return None, "COMMERCIAL_SERVICE_REQUIRES_REVIEW"
    return service, None


async def handle_availability(env, body: dict):
    location = str(body.get("location") or "").strip()
    if location not in SERVICE_LOCATIONS:
        return Response.json({"error": "UNKNOWN_LOCATION"}, status=400)
    property_type = str(body.get("property_type") or "residential").strip().lower()
    issue_type = str(body.get("issue_type") or "other").strip().lower()
    service_code = str(body.get("service_code") or "").strip()
    issue_description = str(body.get("issue_description") or "").strip()
    equipment_details = str(body.get("equipment_details") or "").strip()
    escalation_context = str(body.get("escalation_context") or "").strip()
    weather = body.get("weather")
    if not isinstance(weather, dict):
        weather = {"status": "UNAVAILABLE"}
    try:
        classification_confidence = float(
            body.get("classification_confidence", 0.0)
        )
    except (TypeError, ValueError):
        classification_confidence = 0.0
    preferred_date = str(body.get("preferred_date", "") or "").strip()
    time_preference = str(body.get("time_preference", "") or "").strip().lower()

    if property_type not in {"residential", "commercial"}:
        return Response.json({"error": "INVALID_PROPERTY_TYPE"}, status=400)

    log_event(
        "availability_request",
        location=location,
        property_type=property_type,
        issue_type=issue_type,
        service_code=service_code or None,
        preferred_date=preferred_date or None,
        time_preference=time_preference or None,
        has_escalation_context=bool(escalation_context),
        weather_status=weather.get("status"),
    )

    emergency_assessment = await grade_emergency(
        env,
        property_type=property_type,
        issue_type=issue_type,
        issue_description=issue_description,
        equipment_details=equipment_details,
        escalation_context=escalation_context,
        weather=weather,
    )
    is_emergency = emergency_assessment["is_emergency"]
    log_event(
        "emergency_assessment",
        is_emergency=is_emergency,
        reason_code=emergency_assessment.get("reason_code"),
        confidence=emergency_assessment.get("confidence"),
    )
    temperature = weather.get("temperature_fahrenheit")
    thunderstorm = weather.get("thunderstorm_probability")
    severe_weather = (
        isinstance(temperature, (int, float))
        and (temperature >= 100 or temperature <= 32)
    ) or (
        isinstance(thunderstorm, (int, float)) and thunderstorm >= 50
    )

    def assessed(payload: dict) -> dict:
        return {
            **payload,
            "is_emergency": is_emergency,
            "emergency_assessment": emergency_assessment,
        }

    service = None
    required_skill = None
    duration_hours = SLOT_HOURS
    classification = None
    if property_type == "commercial":
        if not service_code:
            classification = await classify_issue(env, issue_description)
            log_event(
                "commercial_classification",
                status=classification.get("status"),
                service_code=classification.get("service_code"),
                confidence=classification.get("confidence"),
            )
            if classification.get("status") != "CLASSIFIED":
                log_event(
                    "no_slots_offered",
                    stage="commercial_classification",
                    review_reason=str(
                        classification.get("reason", "CLASSIFICATION_UNCLEAR")
                    ).upper(),
                )
                return Response.json(
                    assessed({
                        **classification,
                        "property_type": "commercial",
                        "review_reason": str(
                            classification.get("reason", "CLASSIFICATION_UNCLEAR")
                        ).upper(),
                        "message": (
                            "Collect the remaining details, save a service "
                            "request for staff review, and do not "
                            "offer appointment times."
                        ),
                    })
                )
            service_code = str(classification.get("service_code", "")).strip()
            classification_confidence = float(
                classification.get("confidence", 0.0)
            )
        service, error = _commercial_booking_service(service_code)
        if error:
            log_event(
                "no_slots_offered",
                stage="commercial_service_lookup",
                review_reason=error,
                service_code=service_code,
            )
            return Response.json(
                assessed({
                    "status": "STAFF_REVIEW",
                    "property_type": "commercial",
                    "service_code": service_code,
                    "classification_confidence": classification_confidence,
                    "review_reason": error,
                    "message": (
                        "This service cannot be scheduled automatically. Collect "
                        "the remaining details, save a service request, and tell "
                        "the caller that staff will follow up."
                    ),
                })
            )
        required_skill = service["required_skill"]
        duration_hours = int(service["duration_hours"])

    technicians = [
        tech for tech in await load_technicians(env)
        if tech.get("location") == location
    ]
    if required_skill:
        technicians = [
            tech for tech in technicians
            if technician_has_skill(tech, required_skill)
        ]
    if not technicians:
        review_reason = (
            "NO_QUALIFIED_TECHNICIAN" if required_skill else "NO_TECHNICIANS"
        )
        log_event(
            "no_slots_offered",
            stage="technician_filter",
            review_reason=review_reason,
            location=location,
            required_skill=required_skill,
        )
        response = {
            "status": "STAFF_REVIEW",
            "property_type": property_type,
            "service_code": service_code,
            "classification_confidence": classification_confidence,
            "review_reason": review_reason,
            "message": (
                "No suitable technician is available. Collect the remaining "
                "details, save a service request, and tell the caller that "
                "staff will follow up."
            ),
        }
        if classification:
            response["classification_reason"] = classification.get("reason", "")
        return Response.json(assessed(response))

    now = datetime.now(BUSINESS_TIMEZONE)
    within_business_hours = BUSINESS_OPEN_HOUR <= now.hour < BUSINESS_CLOSE_HOUR

    slots = []
    for tech in technicians:
        jobs = await load_jobs(env, tech["tech_id"])
        slots.extend(open_slots_for_tech(tech, jobs, now, duration_hours))
    slots.sort(key=lambda slot: slot["start"])

    filtered = slots
    note = None
    if preferred_date:
        filtered = [slot for slot in filtered if slot["date"] == preferred_date]
    if time_preference == "morning":
        filtered = [
            slot for slot in filtered
            if parse_time(slot["start"]).hour < 12
        ]
    elif time_preference == "afternoon":
        filtered = [
            slot for slot in filtered
            if parse_time(slot["start"]).hour >= 12
        ]
    if not filtered:
        filtered = slots
        note = "NO_SLOTS_MATCHING_PREFERENCE"

    log_event(
        "slot_search",
        technicians=len(technicians),
        open_slots=len(slots),
        after_preference_filter=len(filtered),
        note=note,
        within_business_hours=within_business_hours,
        duration_hours=duration_hours,
    )

    recommendation = None
    if is_emergency and severe_weather:
        filtered = filtered[:3]
        recommendation = "OFFER_EARLIEST_SLOT_FIRST"
    else:
        filtered = filtered[:6]

    after_hours_dispatch = None
    if not within_business_hours:
        if not is_emergency:
            after_hours_dispatch = {"available": False, "reason": "NOT_EMERGENCY"}
        else:
            on_call = next(
                (tech for tech in technicians if tech.get("on_call")), None
            )
            if not on_call:
                after_hours_dispatch = {
                    "available": False,
                    "reason": "NO_ON_CALL_TECH",
                }
            else:
                eta_start = now + timedelta(hours=1)
                eta_end = eta_start + timedelta(hours=duration_hours)
                after_hours_dispatch = {
                    "available": True,
                    "tech_id": on_call["tech_id"],
                    "tech_name": on_call["name"],
                    "eta_window": {
                        "start": eta_start.isoformat(),
                        "end": eta_end.isoformat(),
                    },
                    "surcharge_applies": True,
                    "surcharge_note": "MUST_WARN_CALLER_HIGHER_COST",
                }

    if not filtered and not (
        isinstance(after_hours_dispatch, dict)
        and after_hours_dispatch.get("available")
    ):
        review_reason = (
            "NO_ON_CALL_TECHNICIAN"
            if is_emergency
            and isinstance(after_hours_dispatch, dict)
            and after_hours_dispatch.get("reason") == "NO_ON_CALL_TECH"
            else "NO_SLOTS"
        )
        log_event(
            "no_slots_offered",
            stage="final",
            review_reason=review_reason,
            is_emergency=is_emergency,
            within_business_hours=within_business_hours,
        )
        return Response.json(
            assessed({
                "status": "STAFF_REVIEW",
                "property_type": property_type,
                "service_code": service_code,
                "classification_confidence": classification_confidence,
                "review_reason": review_reason,
                "message": (
                    "No appointment can be offered. Collect the remaining "
                    "details, save a service request, and tell the caller that "
                    "staff will follow up."
                ),
            })
        )

    response = {
        "status": "OK",
        "location": location,
        "property_type": property_type,
        "within_business_hours": within_business_hours,
        "current_time_local": now.isoformat(),
        "slots": filtered,
        "after_hours_dispatch": after_hours_dispatch,
        "is_emergency": is_emergency,
        "emergency_assessment": emergency_assessment,
    }
    if service:
        response.update(
            {
                "service_code": service_code,
                "service_label": service["label"],
                "required_skill": required_skill,
                "duration_hours": duration_hours,
                "appointment_status": "CONFIRMED",
                "classification_confidence": classification_confidence,
            }
        )
        if classification:
            response["classification_reason"] = classification.get("reason", "")
    if recommendation:
        response["recommendation"] = recommendation
    if note:
        response["note"] = note
    log_event(
        "availability_response",
        slots_returned=len(filtered),
        after_hours_dispatch=(
            after_hours_dispatch.get("available")
            if isinstance(after_hours_dispatch, dict)
            else None
        ),
        recommendation=recommendation,
        is_emergency=is_emergency,
    )
    return Response.json(response)


async def handle_book(env, body: dict):
    tech_id = str(body.get("tech_id") or "").strip()
    start_raw = str(body.get("start") or "").strip()
    end_raw = str(body.get("end") or "").strip()
    customer_name = str(body.get("customer_name") or "").strip()
    customer_phone = normalize_phone_number(str(body.get("customer_phone") or ""))
    address = str(body.get("address") or "").strip()
    summary = str(body.get("summary") or "").strip()
    is_emergency = bool(body.get("is_emergency", False))
    after_hours = bool(body.get("after_hours", False))
    property_type = str(body.get("property_type") or "residential").strip().lower()
    service_code = str(body.get("service_code") or "").strip()
    business_name = str(body.get("business_name") or "").strip()
    site_contact_name = str(body.get("site_contact_name") or "").strip()
    site_contact_phone = normalize_phone_number(
        str(body.get("site_contact_phone") or "")
    )
    issue_description = str(body.get("issue_description") or "").strip()
    equipment_details = str(body.get("equipment_details") or "").strip()
    operational_impact = str(body.get("operational_impact") or "").strip()
    access_notes = str(body.get("access_notes") or "").strip()
    try:
        classification_confidence = float(
            body.get("classification_confidence", 0.0)
        )
    except (TypeError, ValueError):
        classification_confidence = 0.0

    if not all([tech_id, start_raw, end_raw, customer_name, customer_phone, address, summary]):
        return Response.json({"error": "MISSING_FIELDS"}, status=400)
    if property_type not in {"residential", "commercial"}:
        return Response.json({"error": "INVALID_PROPERTY_TYPE"}, status=400)
    if after_hours and not is_emergency:
        return Response.json({"error": "AFTER_HOURS_REQUIRES_EMERGENCY"}, status=400)

    service = None
    required_skill = None
    if property_type == "commercial":
        commercial_fields = [
            service_code,
            business_name,
            site_contact_name,
            site_contact_phone,
            issue_description,
        ]
        if not all(commercial_fields):
            return Response.json(
                {"error": "MISSING_COMMERCIAL_FIELDS"}, status=400
            )
        service, error = _commercial_booking_service(service_code)
        if error:
            return Response.json({"error": error}, status=400)
        if classification_confidence < MINIMUM_CLASSIFICATION_CONFIDENCE:
            return Response.json(
                {"error": "LOW_CLASSIFICATION_CONFIDENCE"}, status=400
            )
        required_skill = service["required_skill"]

    start = parse_time(start_raw)
    end = parse_time(end_raw)
    if not start or not end or end <= start:
        return Response.json({"error": "INVALID_TIME_WINDOW"}, status=400)

    technicians = await load_technicians(env)
    tech = next(
        (record for record in technicians if record.get("tech_id") == tech_id),
        None,
    )
    if not tech:
        return Response.json({"error": "UNKNOWN_TECHNICIAN"}, status=404)
    if required_skill and not technician_has_skill(tech, required_skill):
        return Response.json({"error": "TECHNICIAN_SKILL_MISMATCH"}, status=400)

    if service:
        expected_seconds = int(service["duration_hours"]) * 60 * 60
        if int((end - start).total_seconds()) != expected_seconds:
            return Response.json({"error": "INVALID_SERVICE_DURATION"}, status=400)

    jobs = await load_jobs(env, tech_id)
    if overlaps(start, end, jobs):
        log_event("booking_conflict", tech_id=tech_id, start=start.isoformat())
        return Response.json({"error": "SLOT_TAKEN"}, status=409)

    booking_id = f"bk-{uuid.uuid4().hex[:8]}"
    booking_status = "CONFIRMED"
    job = {
        "job_id": booking_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "summary": summary,
        "customer_phone": customer_phone,
        "is_emergency": is_emergency,
        "after_hours": after_hours,
        "property_type": property_type,
        "service_code": service_code,
        "required_skill": required_skill,
        "status": booking_status,
        "booked_at": datetime.now(timezone.utc).isoformat(),
    }
    jobs.append(job)
    await env.CALLERS.put(f"jobs:{tech_id}", json.dumps(jobs))

    booking = {
        "booking_id": booking_id,
        "tech_id": tech_id,
        "tech_name": tech["name"],
        "location": tech["location"],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "spoken_time": spoken_slot(start, end),
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "address": address,
        "summary": summary,
        "is_emergency": is_emergency,
        "after_hours_surcharge": after_hours,
        "property_type": property_type,
        "service_code": service_code,
        "required_skill": required_skill,
        "classification_confidence": (
            classification_confidence if property_type == "commercial" else None
        ),
        "business_name": business_name,
        "site_contact_name": site_contact_name,
        "site_contact_phone": site_contact_phone,
        "issue_description": issue_description,
        "equipment_details": equipment_details,
        "operational_impact": operational_impact,
        "access_notes": access_notes,
        "status": booking_status,
        "staff_confirmation_status": "NOT_REQUIRED",
        "booked_at": job["booked_at"],
    }
    await env.CALLERS.put(f"booking:{booking_id}", json.dumps(booking))
    log_event(
        "booking_created",
        booking_id=booking_id,
        tech_id=tech_id,
        start=start.isoformat(),
        status=booking_status,
        after_hours=after_hours,
    )
    return Response.json({"booked": True, **booking})


async def handle_booking_lookup(env, body: dict):
    booking_id = normalize_booking_id(body.get("booking_id", ""))
    if not booking_id:
        return Response.json({"error": "BOOKING_ID_REQUIRED"}, status=400)
    stored = await env.CALLERS.get(f"booking:{booking_id}")
    if not stored:
        return Response.json({"error": "BOOKING_NOT_FOUND"}, status=404)
    return Response.json({"found": True, **json.loads(stored)})


async def remove_job(env, tech_id: str, job_id: str) -> None:
    jobs = await load_jobs(env, tech_id)
    remaining = [job for job in jobs if job.get("job_id") != job_id]
    await env.CALLERS.put(f"jobs:{tech_id}", json.dumps(remaining))


async def set_job_status(env, tech_id: str, job_id: str, status: str) -> None:
    """Set the status on one scheduled job."""
    jobs = await load_jobs(env, tech_id)
    for job in jobs:
        if job.get("job_id") == job_id:
            job["status"] = status
    await env.CALLERS.put(f"jobs:{tech_id}", json.dumps(jobs))


async def handle_booking_update(env, body: dict):
    booking_id = normalize_booking_id(body.get("booking_id", ""))
    action = str(body.get("action") or "").strip().lower()
    if not booking_id:
        return Response.json({"error": "BOOKING_ID_REQUIRED"}, status=400)
    stored = await env.CALLERS.get(f"booking:{booking_id}")
    if not stored:
        return Response.json({"error": "BOOKING_NOT_FOUND"}, status=404)
    booking = json.loads(stored)

    if action in {"confirm", "reject"}:
        if booking.get("property_type") != "commercial":
            return Response.json(
                {"error": "COMMERCIAL_BOOKING_REQUIRED"}, status=400
            )
        now_utc = datetime.now(timezone.utc).isoformat()
        if action == "confirm":
            booking["status"] = "CONFIRMED"
            booking["staff_confirmation_status"] = "CONFIRMED"
            await set_job_status(
                env, booking["tech_id"], booking_id, "CONFIRMED"
            )
        else:
            booking["status"] = "REJECTED"
            booking["staff_confirmation_status"] = "REJECTED"
            await remove_job(env, booking["tech_id"], booking_id)
        booking["updated_at"] = now_utc
        await env.CALLERS.put(f"booking:{booking_id}", json.dumps(booking))
        return Response.json({"updated": True, **booking})

    if action == "cancel":
        await remove_job(env, booking["tech_id"], booking_id)
        booking["status"] = "CANCELLED"
        if booking.get("property_type") == "commercial":
            booking["staff_confirmation_status"] = "CANCELLED"
        booking["updated_at"] = datetime.now(timezone.utc).isoformat()
        await env.CALLERS.put(f"booking:{booking_id}", json.dumps(booking))
        return Response.json({"updated": True, **booking})

    if action == "reschedule":
        tech_id = str(body.get("tech_id") or "").strip()
        start = parse_time(str(body.get("start") or "").strip())
        end = parse_time(str(body.get("end") or "").strip())
        if not tech_id or not start or not end or end <= start:
            return Response.json({"error": "MISSING_FIELDS"}, status=400)

        technicians = await load_technicians(env)
        tech = next(
            (record for record in technicians if record.get("tech_id") == tech_id),
            None,
        )
        if not tech:
            return Response.json({"error": "UNKNOWN_TECHNICIAN"}, status=404)

        required_skill = booking.get("required_skill")
        service = None
        if booking.get("property_type") == "commercial":
            service, error = _commercial_booking_service(
                booking.get("service_code")
            )
            if error:
                return Response.json({"error": error}, status=400)
            if not technician_has_skill(tech, required_skill):
                return Response.json(
                    {"error": "TECHNICIAN_SKILL_MISMATCH"}, status=400
                )
            expected_seconds = int(service["duration_hours"]) * 60 * 60
            if int((end - start).total_seconds()) != expected_seconds:
                return Response.json(
                    {"error": "INVALID_SERVICE_DURATION"}, status=400
                )

        jobs = await load_jobs(env, tech_id)
        other_jobs = [job for job in jobs if job.get("job_id") != booking_id]
        if overlaps(start, end, other_jobs):
            return Response.json({"error": "SLOT_TAKEN"}, status=409)

        await remove_job(env, booking["tech_id"], booking_id)
        now_utc = datetime.now(timezone.utc).isoformat()
        job = {
            "job_id": booking_id,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "summary": booking.get("summary", ""),
            "customer_phone": booking.get("customer_phone", ""),
            "is_emergency": booking.get("is_emergency", False),
            "after_hours": False,
            "property_type": booking.get("property_type", "residential"),
            "service_code": booking.get("service_code", ""),
            "required_skill": required_skill,
            "status": "CONFIRMED",
            "booked_at": now_utc,
        }
        new_jobs = await load_jobs(env, tech_id)
        new_jobs.append(job)
        await env.CALLERS.put(f"jobs:{tech_id}", json.dumps(new_jobs))

        booking_status = "CONFIRMED"
        booking.update(
            {
                "tech_id": tech_id,
                "tech_name": tech["name"],
                "location": tech["location"],
                "start": start.isoformat(),
                "end": end.isoformat(),
                "spoken_time": spoken_slot(start, end),
                "after_hours_surcharge": False,
                "status": booking_status,
                "staff_confirmation_status": "NOT_REQUIRED",
                "updated_at": now_utc,
            }
        )
        await env.CALLERS.put(f"booking:{booking_id}", json.dumps(booking))
        return Response.json({"updated": True, **booking})

    return Response.json({"error": "UNKNOWN_ACTION"}, status=400)
