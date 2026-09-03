import asyncio
import json
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    @classmethod
    def json(cls, payload, status=200):
        return cls(payload, status)


workers = types.ModuleType("workers")
workers.Response = FakeResponse
sys.modules.setdefault("workers", workers)

import dashboard  # noqa: E402
import scheduling  # noqa: E402
import service_requests  # noqa: E402


class FakeKV:
    def __init__(self):
        self.values = {}

    async def put(self, key, value):
        self.values[key] = value

    async def get(self, key):
        return self.values.get(key)

    async def list(self, options):
        prefix = options["prefix"]
        return {
            "keys": [
                {"name": key} for key in self.values if key.startswith(prefix)
            ]
        }


class FakeEnv:
    def __init__(self, emergency_assessment=None):
        self.CALLERS = FakeKV()
        self.AI = FakeAI(emergency_assessment)


class FakeAI:
    def __init__(self, assessment=None):
        self.assessment = assessment or {
            "is_emergency": False,
            "reason_code": "ROUTINE_OR_NON_EMERGENCY",
            "reason": "No emergency indicators were provided.",
            "confidence": 0.95,
        }

    async def run(self, model, request):
        return {"response": self.assessment}


class StaffReviewRequestTests(unittest.TestCase):
    def test_supported_commercial_service_is_confirmed_immediately(self):
        env = FakeEnv()
        env.CALLERS.values["techs:index"] = json.dumps(
            [
                {
                    "tech_id": "tech-commercial",
                    "name": "Commercial Tech",
                    "location": "Stone Oak",
                    "on_call": False,
                    "commercial_skills": ["rtu_packaged"],
                }
            ]
        )
        response = asyncio.run(
            scheduling.handle_book(
                env,
                {
                    "tech_id": "tech-commercial",
                    "start": "2026-09-04T09:00:00-05:00",
                    "end": "2026-09-04T11:00:00-05:00",
                    "customer_name": "Alex Rivera",
                    "customer_phone": "+12105550123",
                    "address": "101 Main St",
                    "summary": "Rooftop unit is not cooling",
                    "property_type": "commercial",
                    "service_code": "rtu_packaged_service",
                    "classification_confidence": 0.95,
                    "business_name": "Rivera Foods",
                    "site_contact_name": "Alex Rivera",
                    "site_contact_phone": "+12105550123",
                    "issue_description": "Rooftop unit is not cooling",
                    "is_emergency": False,
                    "after_hours": False,
                },
            )
        )

        self.assertEqual(response.status, 200)
        self.assertTrue(response.payload["booked"])
        self.assertEqual(response.payload["status"], "CONFIRMED")
        self.assertEqual(
            response.payload["staff_confirmation_status"], "NOT_REQUIRED"
        )

    def test_residential_request_is_persisted(self):
        env = FakeEnv()
        response = asyncio.run(
            service_requests.handle_service_request(
                env,
                {
                    "customer_name": "Alex Rivera",
                    "customer_phone": "+12105550123",
                    "address": "101 Main St",
                    "issue_description": "No cooling",
                    "property_type": "residential",
                    "is_emergency": True,
                    "review_reason": "NO_ON_CALL_TECHNICIAN",
                },
            )
        )

        self.assertEqual(response.status, 200)
        self.assertTrue(response.payload["saved"])
        self.assertEqual(response.payload["status"], "STAFF_REVIEW")
        self.assertEqual(len(env.CALLERS.values), 1)
        key, stored = next(iter(env.CALLERS.values.items()))
        self.assertTrue(key.startswith("service-request:sr-"))
        self.assertEqual(json.loads(stored)["property_type"], "residential")

    def test_no_residential_technician_returns_staff_review(self):
        original = scheduling.load_technicians

        async def no_technicians(env):
            return []

        scheduling.load_technicians = no_technicians
        try:
            response = asyncio.run(
                scheduling.handle_availability(
                    FakeEnv(),
                    {
                        "location": "Stone Oak",
                        "property_type": "residential",
                        "issue_type": "maintenance",
                        "issue_description": "Annual tune-up",
                    },
                )
            )
        finally:
            scheduling.load_technicians = original

        self.assertEqual(response.payload["status"], "STAFF_REVIEW")
        self.assertEqual(response.payload["review_reason"], "NO_TECHNICIANS")

    def test_after_hours_emergency_without_capacity_needs_review(self):
        original_load = scheduling.load_technicians
        original_slots = scheduling.open_slots_for_tech
        original_datetime = scheduling.datetime

        async def one_unavailable_technician(env):
            return [
                {
                    "tech_id": "tech-1",
                    "name": "Tech",
                    "location": "Stone Oak",
                    "on_call": False,
                    "commercial_skills": [],
                }
            ]

        class Evening(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 9, 2, 19, 0, tzinfo=tz)

        scheduling.load_technicians = one_unavailable_technician
        scheduling.open_slots_for_tech = lambda *args, **kwargs: []
        scheduling.datetime = Evening
        try:
            response = asyncio.run(
                scheduling.handle_availability(
                    FakeEnv(
                        {
                            "is_emergency": True,
                            "reason_code": "ACTIVE_HVAC_WATER_LEAK",
                            "reason": "Active water is leaking from the unit.",
                            "confidence": 0.98,
                        }
                    ),
                    {
                        "location": "Stone Oak",
                        "property_type": "residential",
                        "issue_type": "other",
                        "issue_description": "Water is leaking from the unit",
                        "escalation_context": "Water is spreading across the floor",
                    },
                )
            )
        finally:
            scheduling.load_technicians = original_load
            scheduling.open_slots_for_tech = original_slots
            scheduling.datetime = original_datetime

        self.assertEqual(response.payload["status"], "STAFF_REVIEW")
        self.assertEqual(
            response.payload["review_reason"], "NO_ON_CALL_TECHNICIAN"
        )

    def test_unassigned_emergency_appears_in_dispatch_queue(self):
        env = FakeEnv()
        env.CALLERS.values["service-request:sr-example"] = json.dumps(
            {
                "request_id": "sr-example",
                "customer_name": "Alex Rivera",
                "is_emergency": True,
                "status": "STAFF_REVIEW",
                "created_at": "2026-09-03T00:00:00+00:00",
            }
        )

        response = asyncio.run(dashboard.handle_emergency_queue(env))

        self.assertEqual(response.payload["counts"]["active"], 1)
        self.assertEqual(response.payload["counts"]["pending"], 1)
        self.assertEqual(response.payload["emergencies"][0]["request_id"], "sr-example")

    def test_after_hours_booking_requires_emergency_assessment(self):
        response = asyncio.run(
            scheduling.handle_book(
                FakeEnv(),
                {
                    "tech_id": "tech-1",
                    "start": "2026-09-03T19:00:00-05:00",
                    "end": "2026-09-03T21:00:00-05:00",
                    "customer_name": "Alex Rivera",
                    "customer_phone": "+12105550123",
                    "address": "101 Main St",
                    "summary": "Noisy unit",
                    "property_type": "residential",
                    "is_emergency": False,
                    "after_hours": True,
                },
            )
        )

        self.assertEqual(response.status, 400)
        self.assertEqual(response.payload["error"], "AFTER_HOURS_REQUIRES_EMERGENCY")

    def test_request_body_cannot_override_emergency_grader(self):
        original_load = scheduling.load_technicians
        original_slots = scheduling.open_slots_for_tech
        original_datetime = scheduling.datetime

        async def one_on_call_technician(env):
            return [
                {
                    "tech_id": "tech-1",
                    "name": "Tech",
                    "location": "Stone Oak",
                    "on_call": True,
                    "commercial_skills": [],
                }
            ]

        class Evening(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 9, 2, 19, 0, tzinfo=tz)

        scheduling.load_technicians = one_on_call_technician
        scheduling.open_slots_for_tech = lambda *args, **kwargs: []
        scheduling.datetime = Evening
        try:
            response = asyncio.run(
                scheduling.handle_availability(
                    FakeEnv(),
                    {
                        "location": "Stone Oak",
                        "property_type": "residential",
                        "issue_type": "maintenance",
                        "issue_description": "Annual tune-up",
                        "is_emergency": True,
                    },
                )
            )
        finally:
            scheduling.load_technicians = original_load
            scheduling.open_slots_for_tech = original_slots
            scheduling.datetime = original_datetime

        self.assertFalse(response.payload["is_emergency"])
        self.assertEqual(response.payload["review_reason"], "NO_SLOTS")


if __name__ == "__main__":
    unittest.main()
