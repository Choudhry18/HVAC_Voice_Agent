"""Technician availability search and appointment booking."""

import json
import uuid
from datetime import datetime, timedelta, timezone

from workers import Response

from callers import normalize_phone_number
from timeslots import (
    BUSINESS_CLOSE_HOUR,
    BUSINESS_OPEN_HOUR,
    BUSINESS_TIMEZONE,
    SERVICE_LOCATIONS,
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


async def handle_availability(env, body: dict):
    location = str(body.get("location", "")).strip()
    if location not in SERVICE_LOCATIONS:
        return Response.json({"error": "UNKNOWN_LOCATION"}, status=400)
    is_emergency = bool(body.get("is_emergency", False))
    severe_weather = bool(body.get("severe_weather", False))
    preferred_date = str(body.get("preferred_date", "") or "").strip()
    time_preference = str(body.get("time_preference", "") or "").strip().lower()

    technicians = [
        tech for tech in await load_technicians(env)
        if tech.get("location") == location
    ]
    if not technicians:
        return Response.json({"error": "NO_TECHNICIANS"}, status=404)

    now = datetime.now(BUSINESS_TIMEZONE)
    within_business_hours = BUSINESS_OPEN_HOUR <= now.hour < BUSINESS_CLOSE_HOUR

    slots = []
    for tech in technicians:
        jobs = await load_jobs(env, tech["tech_id"])
        slots.extend(open_slots_for_tech(tech, jobs, now))
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
                eta_end = now + timedelta(hours=3)
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

    response = {
        "status": "OK",
        "location": location,
        "within_business_hours": within_business_hours,
        "current_time_local": now.isoformat(),
        "slots": filtered,
        "after_hours_dispatch": after_hours_dispatch,
    }
    if recommendation:
        response["recommendation"] = recommendation
    if note:
        response["note"] = note
    return Response.json(response)


async def handle_book(env, body: dict):
    tech_id = str(body.get("tech_id", "")).strip()
    start_raw = str(body.get("start", "")).strip()
    end_raw = str(body.get("end", "")).strip()
    customer_name = str(body.get("customer_name", "")).strip()
    customer_phone = normalize_phone_number(str(body.get("customer_phone", "")))
    address = str(body.get("address", "")).strip()
    summary = str(body.get("summary", "")).strip()
    is_emergency = bool(body.get("is_emergency", False))
    after_hours = bool(body.get("after_hours", False))

    if not all([tech_id, start_raw, end_raw, customer_name, customer_phone, address, summary]):
        return Response.json({"error": "MISSING_FIELDS"}, status=400)

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

    jobs = await load_jobs(env, tech_id)
    if overlaps(start, end, jobs):
        return Response.json({"error": "SLOT_TAKEN"}, status=409)

    booking_id = f"bk-{uuid.uuid4().hex[:8]}"
    job = {
        "job_id": booking_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "summary": summary,
        "customer_phone": customer_phone,
        "is_emergency": is_emergency,
        "after_hours": after_hours,
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
        "booked_at": job["booked_at"],
    }
    await env.CALLERS.put(f"booking:{booking_id}", json.dumps(booking))
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


async def handle_booking_update(env, body: dict):
    booking_id = normalize_booking_id(body.get("booking_id", ""))
    action = str(body.get("action", "")).strip().lower()
    if not booking_id:
        return Response.json({"error": "BOOKING_ID_REQUIRED"}, status=400)
    stored = await env.CALLERS.get(f"booking:{booking_id}")
    if not stored:
        return Response.json({"error": "BOOKING_NOT_FOUND"}, status=404)
    booking = json.loads(stored)

    if action == "cancel":
        await remove_job(env, booking["tech_id"], booking_id)
        booking["status"] = "CANCELLED"
        booking["updated_at"] = datetime.now(timezone.utc).isoformat()
        await env.CALLERS.put(f"booking:{booking_id}", json.dumps(booking))
        return Response.json({"updated": True, **booking})

    if action == "reschedule":
        tech_id = str(body.get("tech_id", "")).strip()
        start = parse_time(str(body.get("start", "")).strip())
        end = parse_time(str(body.get("end", "")).strip())
        if not tech_id or not start or not end or end <= start:
            return Response.json({"error": "MISSING_FIELDS"}, status=400)

        technicians = await load_technicians(env)
        tech = next(
            (record for record in technicians if record.get("tech_id") == tech_id),
            None,
        )
        if not tech:
            return Response.json({"error": "UNKNOWN_TECHNICIAN"}, status=404)

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
            "booked_at": now_utc,
        }
        new_jobs = await load_jobs(env, tech_id)
        new_jobs.append(job)
        await env.CALLERS.put(f"jobs:{tech_id}", json.dumps(new_jobs))

        booking.update(
            {
                "tech_id": tech_id,
                "tech_name": tech["name"],
                "location": tech["location"],
                "start": start.isoformat(),
                "end": end.isoformat(),
                "spoken_time": spoken_slot(start, end),
                "after_hours_surcharge": False,
                "status": "CONFIRMED",
                "updated_at": now_utc,
            }
        )
        await env.CALLERS.put(f"booking:{booking_id}", json.dumps(booking))
        return Response.json({"updated": True, **booking})

    return Response.json({"error": "UNKNOWN_ACTION"}, status=400)
