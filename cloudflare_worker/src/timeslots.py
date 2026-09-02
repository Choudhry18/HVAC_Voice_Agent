"""Business-hours configuration and appointment-slot math."""

from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    BUSINESS_TIMEZONE = ZoneInfo("America/Chicago")
except Exception:
    BUSINESS_TIMEZONE = timezone(timedelta(hours=-5), "CDT")

BUSINESS_OPEN_HOUR = 8
BUSINESS_CLOSE_HOUR = 17
SLOT_START_HOURS = (8, 10, 13, 15)
SLOT_HOURS = 2
SEARCH_HORIZON_DAYS = 7

SERVICE_LOCATIONS = ("Downtown San Antonio", "Stone Oak", "Alamo Ranch")


def ordinal(day: int) -> str:
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def spoken_hour(hour: int, include_meridiem: bool = True) -> str:
    meridiem = "AM" if hour < 12 else "PM"
    twelve_hour = hour % 12 or 12
    return f"{twelve_hour} {meridiem}" if include_meridiem else str(twelve_hour)


def spoken_slot(start: datetime, end: datetime) -> str:
    day_phrase = f"{start.strftime('%A %B')} {ordinal(start.day)}"
    same_meridiem = (start.hour < 12) == (end.hour < 12)
    if same_meridiem:
        hours = f"{spoken_hour(start.hour, include_meridiem=False)} to {spoken_hour(end.hour)}"
    else:
        hours = f"{spoken_hour(start.hour)} to {spoken_hour(end.hour)}"
    return f"{day_phrase}, {hours}"


def parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BUSINESS_TIMEZONE)
    return parsed


def overlaps(start: datetime, end: datetime, jobs: list[dict]) -> bool:
    for job in jobs:
        job_start = parse_time(str(job.get("start", "")))
        job_end = parse_time(str(job.get("end", "")))
        if job_start and job_end and start < job_end and job_start < end:
            return True
    return False


def open_slots_for_tech(tech: dict, jobs: list[dict], now: datetime) -> list[dict]:
    slots = []
    for day_offset in range(SEARCH_HORIZON_DAYS + 1):
        slot_date = (now + timedelta(days=day_offset)).date()
        for start_hour in SLOT_START_HOURS:
            start = datetime(
                slot_date.year, slot_date.month, slot_date.day,
                start_hour, tzinfo=BUSINESS_TIMEZONE,
            )
            end = start + timedelta(hours=SLOT_HOURS)
            if start <= now:
                continue
            if overlaps(start, end, jobs):
                continue
            slots.append(
                {
                    "slot_id": f"{tech['tech_id']}|{start.isoformat()}",
                    "tech_id": tech["tech_id"],
                    "tech_name": tech["name"],
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "date": slot_date.isoformat(),
                    "spoken": spoken_slot(start, end),
                }
            )
    return slots
