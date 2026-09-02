"""Tests for residential and commercial email wording."""

import unittest

from notification_service import format_confirmation


class NotificationTests(unittest.TestCase):
    def test_pending_commercial_email_is_not_a_confirmation(self):
        subject, text, html = format_confirmation(
            {
                "booking_id": "bk-demo123",
                "status": "PENDING_CONFIRMATION",
                "business_name": "Example Offices",
                "spoken_time": "Friday, 8 AM to 11 AM",
                "address": "100 Commerce Street",
                "summary": "VRV service",
            }
        )
        self.assertIn("request received", subject)
        self.assertIn("pending staff confirmation", text)
        self.assertIn("pending staff confirmation", html)
        self.assertNotIn("appointment is confirmed", text)

    def test_residential_email_remains_confirmed(self):
        subject, text, _ = format_confirmation(
            {
                "booking_id": "bk-demo456",
                "status": "CONFIRMED",
                "spoken_time": "Friday, 8 AM to 10 AM",
                "address": "200 Oak Street",
                "summary": "Cooling repair",
            }
        )
        self.assertIn("appointment confirmation", subject)
        self.assertIn("appointment is confirmed", text)


if __name__ == "__main__":
    unittest.main()
