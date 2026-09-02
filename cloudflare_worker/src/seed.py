"""Mock technician roster and schedule seeding."""

import json
import random
import uuid
from datetime import datetime, timedelta, timezone

from workers import Response

from timeslots import (
    BUSINESS_TIMEZONE,
    SEARCH_HORIZON_DAYS,
    SLOT_HOURS,
    SLOT_START_HOURS,
)

SEED_TECHNICIANS = (
    {"tech_id": "tech-downtown-1", "name": "Marcus Rivera", "location": "Downtown San Antonio", "on_call": False},
    {"tech_id": "tech-downtown-2", "name": "Priya Shah", "location": "Downtown San Antonio", "on_call": True},
    {"tech_id": "tech-stoneoak-1", "name": "Dana Whitfield", "location": "Stone Oak", "on_call": True},
    {"tech_id": "tech-stoneoak-2", "name": "Tom Ellis", "location": "Stone Oak", "on_call": False},
    {"tech_id": "tech-alamoranch-1", "name": "Luis Ortega", "location": "Alamo Ranch", "on_call": False},
    {"tech_id": "tech-alamoranch-2", "name": "Keisha Brown", "location": "Alamo Ranch", "on_call": True},
)

SEED_JOB_SUMMARIES = (
    "AC compressor replacement",
    "Furnace inspection",
    "Refrigerant recharge",
    "Thermostat installation",
    "Duct cleaning",
    "Seasonal maintenance visit",
    "Blower motor repair",
)


async def handle_seed(env):
    now = datetime.now(BUSINESS_TIMEZONE)
    total_jobs = 0
    for tech in SEED_TECHNICIANS:
        generator = random.Random(f"{tech['tech_id']}:{now.date().isoformat()}")
        candidates = [
            (day_offset, start_hour)
            for day_offset in range(SEARCH_HORIZON_DAYS + 1)
            for start_hour in SLOT_START_HOURS
        ]
        job_count = generator.randint(4, 6)
        jobs = []
        for day_offset, start_hour in sorted(generator.sample(candidates, job_count)):
            start = datetime(
                now.year, now.month, now.day,
                start_hour, tzinfo=BUSINESS_TIMEZONE,
            ) + timedelta(days=day_offset)
            end = start + timedelta(hours=SLOT_HOURS)
            if end <= now:
                continue
            jobs.append(
                {
                    "job_id": f"job-{uuid.uuid4().hex[:8]}",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "summary": generator.choice(SEED_JOB_SUMMARIES),
                    "customer_phone": "",
                    "is_emergency": False,
                    "after_hours": False,
                    "booked_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        total_jobs += len(jobs)
        await env.CALLERS.put(f"jobs:{tech['tech_id']}", json.dumps(jobs))

    await env.CALLERS.put("techs:index", json.dumps(list(SEED_TECHNICIANS)))
    return Response.json(
        {
            "seeded": True,
            "technicians": len(SEED_TECHNICIANS),
            "jobs": total_jobs,
        }
    )
