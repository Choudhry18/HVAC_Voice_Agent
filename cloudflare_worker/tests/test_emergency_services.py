import asyncio
import json
import sys
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from emergency_services import grade_emergency  # noqa: E402


class FakeAI:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def run(self, model, request):
        self.calls.append((model, request))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return {"response": response}


class FakeEnv:
    def __init__(self, responses):
        self.AI = FakeAI(responses)


class EmergencyServicesTests(unittest.TestCase):
    def test_grader_receives_weather_service_and_escalation_context(self):
        env = FakeEnv(
            [
                {
                    "is_emergency": True,
                    "reason_code": "SEVERE_HEAT_COOLING_FAILURE",
                    "reason": "No cooling during dangerous heat.",
                    "confidence": 0.97,
                }
            ]
        )
        result = asyncio.run(
            grade_emergency(
                env,
                property_type="residential",
                issue_type="cooling_failure",
                issue_description="The air conditioner stopped cooling",
                equipment_details="Central air conditioner",
                escalation_context="An elderly resident is inside",
                weather={
                    "status": "OK",
                    "temperature_fahrenheit": 104,
                    "condition": "Sunny",
                },
            )
        )

        self.assertTrue(result["is_emergency"])
        payload = json.loads(env.AI.calls[0][1]["messages"][1]["content"])
        self.assertEqual(payload["weather"]["temperature_fahrenheit"], 104)
        self.assertEqual(payload["issue_type"], "cooling_failure")
        self.assertEqual(
            payload["emergency_context"], "An elderly resident is inside"
        )

    def test_routine_maintenance_is_not_emergency_from_vulnerability_alone(self):
        env = FakeEnv(
            [
                {
                    "is_emergency": True,
                    "reason_code": "VULNERABLE_OCCUPANT_TEMPERATURE_FAILURE",
                    "reason": "An infant is present.",
                    "confidence": 0.8,
                }
            ]
        )
        result = asyncio.run(
            grade_emergency(
                env,
                property_type="residential",
                issue_type="maintenance",
                issue_description="Annual maintenance visit",
                equipment_details="",
                escalation_context="There is an infant in the home",
                weather={"status": "OK", "temperature_fahrenheit": 85},
            )
        )

        self.assertFalse(result["is_emergency"])
        self.assertEqual(result["reason_code"], "ROUTINE_OR_NON_EMERGENCY")

    def test_model_call_retries_once_before_using_successful_result(self):
        env = FakeEnv(
            [
                RuntimeError("temporary failure"),
                {
                    "is_emergency": False,
                    "reason_code": "INSUFFICIENT_EVIDENCE",
                    "reason": "No urgent risk was reported.",
                    "confidence": 0.9,
                },
            ]
        )
        result = asyncio.run(
            grade_emergency(
                env,
                property_type="residential",
                issue_type="other",
                issue_description="The unit is noisy",
                equipment_details="",
                escalation_context="",
                weather={"status": "UNAVAILABLE"},
            )
        )

        self.assertFalse(result["is_emergency"])
        self.assertEqual(len(env.AI.calls), 2)


if __name__ == "__main__":
    unittest.main()
