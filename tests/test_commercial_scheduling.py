"""Tests for commercial classification and skill-based scheduling."""

import json
import sys
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path


class TestResponse:
    """Provide the small Response interface that worker handlers use."""

    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    @classmethod
    def json(cls, payload, status=200):
        return cls(payload, status)


workers_module = types.ModuleType("workers")
workers_module.Response = TestResponse
workers_module.WorkerEntrypoint = object
sys.modules["workers"] = workers_module

WORKER_SOURCE = Path(__file__).parents[1] / "cloudflare_worker" / "src"
sys.path.insert(0, str(WORKER_SOURCE))

from commercial_services import classify_issue, handle_commercial_request  # noqa: E402
from scheduling import (  # noqa: E402
    handle_availability,
    handle_book,
    handle_booking_update,
)
from seed import SEED_TECHNICIANS  # noqa: E402


class MemoryKV:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def put(self, key, value):
        self.values[key] = value


class CatalogAI:
    def __init__(self):
        self.requests = []

    async def run(self, model, request):
        self.requests.append((model, request))
        issue = request["messages"][-1]["content"].lower()
        if "vrv" in issue or "vrf" in issue:
            service_code = "vrv_vrf_service"
        elif "commission" in issue or "startup" in issue:
            service_code = "commercial_commissioning"
        elif "rooftop" in issue or "rtu" in issue:
            service_code = "rtu_packaged_service"
        elif "controls" in issue or "bms" in issue:
            service_code = "controls_bms_service"
        elif "maintenance" in issue:
            service_code = "commercial_maintenance"
        else:
            service_code = "other_or_unclear"
        confidence = 0.95 if service_code != "other_or_unclear" else 0.3
        return {
            "response": {
                "service_code": service_code,
                "confidence": confidence,
                "reason": "Test classification",
            }
        }


class Environment:
    def __init__(self):
        self.CALLERS = MemoryKV()
        self.AI = CatalogAI()


def commercial_booking_body(slot, technician_id):
    return {
        "tech_id": technician_id,
        "start": slot["start"],
        "end": slot["end"],
        "customer_name": "Alex Morgan",
        "customer_phone": "+1 210-555-0200",
        "address": "100 Commerce Street, San Antonio, TX 78205",
        "summary": "Commercial VRV system does not cool the east wing.",
        "is_emergency": False,
        "after_hours": False,
        "property_type": "commercial",
        "service_code": "vrv_vrf_service",
        "classification_confidence": 0.95,
        "business_name": "Example Offices",
        "site_contact_name": "Alex Morgan",
        "site_contact_phone": "+1 210-555-0200",
        "issue_description": "The VRV system does not cool the east wing.",
        "equipment_details": "Roof-mounted VRV system",
        "operational_impact": "The east wing is closed.",
        "access_notes": "Check in at the loading entrance.",
    }


class CommercialSchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = Environment()
        await self.env.CALLERS.put(
            "techs:index", json.dumps(list(SEED_TECHNICIANS))
        )

    async def test_classifier_maps_demo_issue_categories(self):
        examples = {
            "The Daikin VRV system shows an error.": "vrv_vrf_service",
            "We need startup and commissioning for new equipment.": (
                "commercial_commissioning"
            ),
            "The rooftop RTU does not cool.": "rtu_packaged_service",
            "The BMS controls cannot open a damper.": "controls_bms_service",
            "We need quarterly preventive maintenance.": "commercial_maintenance",
        }
        for issue, expected_code in examples.items():
            with self.subTest(issue=issue):
                result = await classify_issue(self.env, issue)
                self.assertEqual("CLASSIFIED", result["status"])
                self.assertEqual(expected_code, result["service_code"])

        review = await classify_issue(self.env, "Something seems unusual.")
        self.assertEqual("STAFF_REVIEW", review["status"])
        self.assertEqual("other_or_unclear", review["service_code"])

    async def test_unclear_issue_can_be_saved_for_staff_review(self):
        response = await handle_commercial_request(
            self.env,
            {
                "business_name": "Example Offices",
                "site_contact_name": "Alex Morgan",
                "site_contact_phone": "+1 210-555-0200",
                "address": "100 Commerce Street, San Antonio, TX 78205",
                "issue_description": "The equipment makes an unusual sound.",
                "service_code": "other_or_unclear",
                "classification_confidence": 0.3,
                "equipment_details": "Equipment type is not known.",
                "operational_impact": "One office area is warm.",
            },
        )
        self.assertEqual(200, response.status)
        self.assertEqual("STAFF_REVIEW", response.payload["status"])
        stored = await self.env.CALLERS.get(
            f"commercial-request:{response.payload['request_id']}"
        )
        self.assertEqual("Example Offices", json.loads(stored)["business_name"])

    async def test_availability_uses_skill_and_service_duration(self):
        response = await handle_availability(
            self.env,
            {
                "location": "Stone Oak",
                "property_type": "commercial",
                "service_code": "vrv_vrf_service",
                "is_emergency": False,
                "severe_weather": False,
            },
        )
        self.assertEqual(200, response.status)
        self.assertTrue(response.payload["slots"])
        self.assertEqual("vrv_vrf", response.payload["required_skill"])
        self.assertEqual(3, response.payload["duration_hours"])
        self.assertEqual(
            {"tech-stoneoak-1"},
            {slot["tech_id"] for slot in response.payload["slots"]},
        )
        for slot in response.payload["slots"]:
            start = datetime.fromisoformat(slot["start"])
            end = datetime.fromisoformat(slot["end"])
            self.assertEqual(3 * 60 * 60, int((end - start).total_seconds()))
            self.assertLessEqual(end.hour, 17)

    async def test_commercial_booking_rejects_skill_mismatch(self):
        availability = await handle_availability(
            self.env,
            {
                "location": "Stone Oak",
                "property_type": "commercial",
                "service_code": "vrv_vrf_service",
            },
        )
        slot = availability.payload["slots"][0]
        response = await handle_book(
            self.env,
            commercial_booking_body(slot, "tech-stoneoak-2"),
        )
        self.assertEqual(400, response.status)
        self.assertEqual("TECHNICIAN_SKILL_MISMATCH", response.payload["error"])

    async def test_commercial_booking_requires_commercial_fields(self):
        availability = await handle_availability(
            self.env,
            {
                "location": "Stone Oak",
                "property_type": "commercial",
                "service_code": "vrv_vrf_service",
            },
        )
        slot = availability.payload["slots"][0]
        body = commercial_booking_body(slot, "tech-stoneoak-1")
        body["business_name"] = ""
        response = await handle_book(self.env, body)
        self.assertEqual(400, response.status)
        self.assertEqual("MISSING_COMMERCIAL_FIELDS", response.payload["error"])

    async def test_long_service_needs_one_continuous_open_window(self):
        request = {
            "location": "Downtown San Antonio",
            "property_type": "commercial",
            "service_code": "commercial_commissioning",
        }
        first_response = await handle_availability(self.env, request)
        blocked_slot = first_response.payload["slots"][0]
        blocked_start = datetime.fromisoformat(blocked_slot["start"])
        conflict_start = blocked_start + timedelta(hours=1)
        conflict_end = conflict_start + timedelta(hours=1)
        await self.env.CALLERS.put(
            "jobs:tech-downtown-2",
            json.dumps(
                [
                    {
                        "job_id": "existing-job",
                        "start": conflict_start.isoformat(),
                        "end": conflict_end.isoformat(),
                    }
                ]
            ),
        )

        second_response = await handle_availability(self.env, request)
        offered_starts = {
            slot["start"] for slot in second_response.payload["slots"]
        }
        self.assertNotIn(blocked_slot["start"], offered_starts)
        self.assertTrue(
            all(slot["duration_hours"] == 4 for slot in second_response.payload["slots"])
        )

    async def test_commercial_booking_is_pending_until_staff_confirms(self):
        availability = await handle_availability(
            self.env,
            {
                "location": "Stone Oak",
                "property_type": "commercial",
                "service_code": "vrv_vrf_service",
            },
        )
        slot = availability.payload["slots"][0]
        response = await handle_book(
            self.env,
            commercial_booking_body(slot, "tech-stoneoak-1"),
        )
        self.assertEqual(200, response.status)
        self.assertEqual("PENDING_CONFIRMATION", response.payload["status"])
        self.assertEqual("PENDING", response.payload["staff_confirmation_status"])
        self.assertEqual("vrv_vrf", response.payload["required_skill"])

        confirmed = await handle_booking_update(
            self.env,
            {"booking_id": response.payload["booking_id"], "action": "confirm"},
        )
        self.assertEqual("CONFIRMED", confirmed.payload["status"])
        self.assertEqual("CONFIRMED", confirmed.payload["staff_confirmation_status"])

    async def test_rejected_commercial_booking_releases_the_slot(self):
        availability = await handle_availability(
            self.env,
            {
                "location": "Stone Oak",
                "property_type": "commercial",
                "service_code": "vrv_vrf_service",
            },
        )
        slot = availability.payload["slots"][0]
        booking = await handle_book(
            self.env,
            commercial_booking_body(slot, "tech-stoneoak-1"),
        )
        rejected = await handle_booking_update(
            self.env,
            {"booking_id": booking.payload["booking_id"], "action": "reject"},
        )
        self.assertEqual("REJECTED", rejected.payload["status"])

        later_availability = await handle_availability(
            self.env,
            {
                "location": "Stone Oak",
                "property_type": "commercial",
                "service_code": "vrv_vrf_service",
            },
        )
        self.assertIn(
            slot["start"],
            {item["start"] for item in later_availability.payload["slots"]},
        )

    async def test_residential_booking_keeps_existing_requirements(self):
        availability = await handle_availability(
            self.env,
            {
                "location": "Downtown San Antonio",
                "is_emergency": False,
                "severe_weather": False,
            },
        )
        slot = availability.payload["slots"][0]
        response = await handle_book(
            self.env,
            {
                "tech_id": slot["tech_id"],
                "start": slot["start"],
                "end": slot["end"],
                "customer_name": "Sam Lee",
                "customer_phone": "+1 210-555-0300",
                "address": "200 Oak Street, San Antonio, TX 78205",
                "summary": "Residential air conditioner does not cool.",
                "is_emergency": False,
                "after_hours": False,
            },
        )
        self.assertEqual(200, response.status)
        self.assertEqual("residential", response.payload["property_type"])
        self.assertEqual("CONFIRMED", response.payload["status"])
        self.assertEqual("NOT_REQUIRED", response.payload["staff_confirmation_status"])


if __name__ == "__main__":
    unittest.main()
