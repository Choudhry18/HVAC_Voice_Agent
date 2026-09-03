"""Emergency grading for appointment requests."""

import json

from commercial_services import CLASSIFICATION_MODEL, _classification_from_result
from observability import log_event
from prompts import EMERGENCY_CLASSIFICATION_SYSTEM_PROMPT


EMERGENCY_REASON_CODES = [
    "IMMEDIATE_SAFETY_HAZARD",
    "ACTIVE_HVAC_WATER_LEAK",
    "SEVERE_HEAT_COOLING_FAILURE",
    "FREEZING_WEATHER_HEATING_FAILURE",
    "VULNERABLE_OCCUPANT_TEMPERATURE_FAILURE",
    "COMMERCIAL_UNSAFE_CONDITION",
    "COMMERCIAL_BUILDING_WIDE_OUTAGE",
    "COMMERCIAL_CRITICAL_AREA_OR_INVENTORY",
    "ROUTINE_OR_NON_EMERGENCY",
    "INSUFFICIENT_EVIDENCE",
]


def _fallback_assessment(
    issue_type: str,
    issue_description: str,
    escalation_context: str,
    weather: dict,
) -> dict:
    """Use narrow, deterministic rules if the model is unavailable."""
    combined = f"{issue_description} {escalation_context}".lower()
    temperature = weather.get("temperature_fahrenheit")
    if any(term in combined for term in ("water leak", "leaking water", "flooding")):
        return {
            "is_emergency": True,
            "reason_code": "ACTIVE_HVAC_WATER_LEAK",
            "reason": "The request reports active water leaking from HVAC equipment.",
            "confidence": 0.8,
        }
    if issue_type == "cooling_failure" and isinstance(temperature, (int, float)) and temperature >= 100:
        return {
            "is_emergency": True,
            "reason_code": "SEVERE_HEAT_COOLING_FAILURE",
            "reason": "Cooling has failed during dangerous heat.",
            "confidence": 0.9,
        }
    if issue_type == "heating_failure" and isinstance(temperature, (int, float)) and temperature <= 32:
        return {
            "is_emergency": True,
            "reason_code": "FREEZING_WEATHER_HEATING_FAILURE",
            "reason": "Heating has failed during freezing weather.",
            "confidence": 0.9,
        }
    return {
        "is_emergency": False,
        "reason_code": "INSUFFICIENT_EVIDENCE",
        "reason": "The available information does not establish an emergency.",
        "confidence": 0.5,
    }


def _weather_payload(weather: object) -> dict:
    if not isinstance(weather, dict):
        return {"status": "UNAVAILABLE"}
    allowed = {
        "status",
        "current_time",
        "time_zone",
        "condition",
        "condition_type",
        "temperature_fahrenheit",
        "feels_like_fahrenheit",
        "heat_index_fahrenheit",
        "wind_chill_fahrenheit",
        "relative_humidity",
        "precipitation_probability",
        "thunderstorm_probability",
    }
    return {key: weather.get(key) for key in allowed if key in weather}


async def grade_emergency(
    env,
    *,
    property_type: str,
    issue_type: str,
    issue_description: str,
    equipment_details: str,
    escalation_context: str,
    weather: object,
) -> dict:
    """Grade a request using the service, weather, and volunteered context."""
    safe_weather = _weather_payload(weather)
    request = {
        "property_type": property_type[:40],
        "issue_type": issue_type[:80],
        "service_requested": issue_description.strip()[:3000],
        "equipment_details": equipment_details.strip()[:2000],
        "emergency_context": escalation_context.strip()[:3000],
        "weather": safe_weather,
    }
    schema = {
        "type": "object",
        "properties": {
            "is_emergency": {"type": "boolean"},
            "reason_code": {"type": "string", "enum": EMERGENCY_REASON_CODES},
            "reason": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["is_emergency", "reason_code", "reason", "confidence"],
        "additionalProperties": False,
    }
    assessment = {}
    for _attempt in range(2):
        try:
            result = await env.AI.run(
                CLASSIFICATION_MODEL,
                {
                    "messages": [
                        {
                            "role": "system",
                            "content": EMERGENCY_CLASSIFICATION_SYSTEM_PROMPT,
                        },
                        {"role": "user", "content": json.dumps(request)},
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": schema,
                    },
                },
            )
            assessment = _classification_from_result(result)
            if all(key in assessment for key in schema["required"]):
                break
        except Exception:
            assessment = {}

    if not assessment:
        log_event("emergency_grading_fallback", reason="MODEL_UNAVAILABLE")
        return _fallback_assessment(
            issue_type, issue_description, escalation_context, safe_weather
        )

    try:
        confidence = max(0.0, min(float(assessment.get("confidence", 0)), 1.0))
    except (TypeError, ValueError):
        confidence = 0.0
    reason_code = str(assessment.get("reason_code", "")).strip()
    if reason_code not in EMERGENCY_REASON_CODES:
        return _fallback_assessment(
            issue_type, issue_description, escalation_context, safe_weather
        )
    is_emergency = assessment.get("is_emergency") is True
    if (
        issue_type == "maintenance"
        and reason_code == "VULNERABLE_OCCUPANT_TEMPERATURE_FAILURE"
    ):
        is_emergency = False
        reason_code = "ROUTINE_OR_NON_EMERGENCY"
        assessment["reason"] = (
            "Routine maintenance is not an emergency without an independent "
            "HVAC hazard or active failure."
        )
    return {
        "is_emergency": is_emergency,
        "reason_code": reason_code,
        "reason": str(assessment.get("reason", "")).strip(),
        "confidence": confidence,
    }
