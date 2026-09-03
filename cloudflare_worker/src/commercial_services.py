"""Commercial service catalog and issue classification."""

import json

from prompts import CLASSIFICATION_SYSTEM_PROMPT

CLASSIFICATION_MODEL = "@cf/meta/llama-3.1-8b-instruct-fast"
MINIMUM_CLASSIFICATION_CONFIDENCE = 0.70

COMMERCIAL_SERVICE_CATALOG = {
    "vrv_vrf_service": {
        "label": "VRV or VRF service",
        "description": "Diagnosis or repair of a VRV or VRF system.",
        "required_skill": "vrv_vrf",
        "duration_hours": 3,
        "bookable": True,
    },
    "commercial_commissioning": {
        "label": "Commercial commissioning",
        "description": "Startup, testing, balancing, or commissioning work.",
        "required_skill": "commissioning",
        "duration_hours": 4,
        "bookable": True,
    },
    "rtu_packaged_service": {
        "label": "Rooftop or packaged-unit service",
        "description": "Diagnosis or repair of a rooftop or packaged unit.",
        "required_skill": "rtu_packaged",
        "duration_hours": 2,
        "bookable": True,
    },
    "commercial_split_service": {
        "label": "Commercial split-system service",
        "description": "Diagnosis or repair of a commercial split system or heat pump.",
        "required_skill": "commercial_split",
        "duration_hours": 2,
        "bookable": True,
    },
    "controls_bms_service": {
        "label": "Controls or BMS service",
        "description": "Work on controls, sensors, zoning, or a building management system.",
        "required_skill": "controls_bms",
        "duration_hours": 2,
        "bookable": True,
    },
    "chiller_service": {
        "label": "Chiller service",
        "description": "Diagnosis, repair, or service of a commercial chiller.",
        "required_skill": "chiller",
        "duration_hours": 4,
        "bookable": True,
    },
    "boiler_hydronic_service": {
        "label": "Boiler or hydronic service",
        "description": "Diagnosis or repair of a boiler or hydronic system.",
        "required_skill": "boiler_hydronic",
        "duration_hours": 3,
        "bookable": True,
    },
    "ventilation_iaq_service": {
        "label": "Ventilation or indoor-air-quality service",
        "description": "Work on ventilation, make-up air, exhaust, or indoor air quality.",
        "required_skill": "ventilation_iaq",
        "duration_hours": 3,
        "bookable": True,
    },
    "commercial_maintenance": {
        "label": "Commercial maintenance",
        "description": "Preventive or scheduled maintenance for commercial HVAC equipment.",
        "required_skill": "commercial_maintenance",
        "duration_hours": 3,
        "bookable": True,
    },
    "other_or_unclear": {
        "label": "Other or unclear commercial work",
        "description": "Work that does not clearly match a supported service.",
        "required_skill": None,
        "duration_hours": None,
        "bookable": False,
    },
}


def commercial_service(service_code: object) -> dict | None:
    """Return the commercial service for a valid code."""
    return COMMERCIAL_SERVICE_CATALOG.get(str(service_code or "").strip())


def _catalog_prompt() -> str:
    lines = []
    for code, service in COMMERCIAL_SERVICE_CATALOG.items():
        lines.append(f"- {code}: {service['description']}")
    return "\n".join(lines)


def _native_dict(value: object) -> dict:
    """Convert a Worker binding result to a Python dictionary."""
    if isinstance(value, dict):
        return value
    to_py = getattr(value, "to_py", None)
    if callable(to_py):
        converted = to_py()
        if isinstance(converted, dict):
            return converted
    return {}


def _classification_from_result(result: object) -> dict:
    payload = _native_dict(result)
    classification = payload.get("response", payload)
    if isinstance(classification, str):
        try:
            classification = json.loads(classification)
        except ValueError:
            return {}
    return classification if isinstance(classification, dict) else {}


async def classify_issue(env, issue_description: str) -> dict:
    """Classify one issue excerpt against the commercial service catalog."""
    excerpt = issue_description.strip()[:3000]
    if not excerpt:
        return {
            "status": "STAFF_REVIEW",
            "service_code": "other_or_unclear",
            "confidence": 0.0,
            "reason": "ISSUE_DESCRIPTION_REQUIRED",
        }

    service_codes = list(COMMERCIAL_SERVICE_CATALOG)
    schema = {
        "type": "object",
        "properties": {
            "service_code": {"type": "string", "enum": service_codes},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
        },
        "required": ["service_code", "confidence", "reason"],
        "additionalProperties": False,
    }
    try:
        result = await env.AI.run(
            CLASSIFICATION_MODEL,
            {
                "messages": [
                    {
                        "role": "system",
                        "content": CLASSIFICATION_SYSTEM_PROMPT.format(
                            catalog=_catalog_prompt()
                        ),
                    },
                    {"role": "user", "content": excerpt},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": schema,
                },
            },
        )
        classification = _classification_from_result(result)
    except Exception:
        classification = {}

    service_code = str(classification.get("service_code", "")).strip()
    try:
        confidence = float(classification.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    reason = str(classification.get("reason", "")).strip()
    service = commercial_service(service_code)
    if (
        not service
        or not service.get("bookable")
        or confidence < MINIMUM_CLASSIFICATION_CONFIDENCE
    ):
        return {
            "status": "STAFF_REVIEW",
            "service_code": "other_or_unclear",
            "confidence": max(0.0, min(confidence, 1.0)),
            "reason": reason or "CLASSIFICATION_UNAVAILABLE",
        }

    return {
        "status": "CLASSIFIED",
        "service_code": service_code,
        "service_label": service["label"],
        "required_skill": service["required_skill"],
        "duration_hours": service["duration_hours"],
        "confidence": max(0.0, min(confidence, 1.0)),
        "reason": reason,
    }
