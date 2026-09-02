import os

import httpx

RESEND_EMAILS_URL = "https://api.resend.com/emails"

FAILED_MESSAGE = (
    "Do not mention the technical failure to the caller. "
    "Repeat the appointment details aloud instead and continue."
)


def format_confirmation(booking: dict[str, object]) -> tuple[str, str, str]:
    """Return (subject, text body, html body) for a booking confirmation."""
    surcharge_line = (
        "Note: this is an after-hours emergency visit, so the cost may be "
        "higher than a regular appointment."
        if booking.get("after_hours_surcharge")
        else ""
    )
    details = [
        ("Booking ID", booking.get("booking_id")),
        ("Time", booking.get("spoken_time")),
        ("Address", booking.get("address")),
        ("Service", booking.get("summary")),
    ]

    text_lines = ["Your Summit Air appointment is confirmed.", ""]
    text_lines.extend(f"{label}: {value}" for label, value in details)
    if surcharge_line:
        text_lines.extend(["", surcharge_line])
    text_lines.extend(
        ["", "Call +1 (484) 398-5113 and give your booking ID to make changes."]
    )

    detail_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0;color:#666'>{label}</td>"
        f"<td style='padding:4px 0'><strong>{value}</strong></td></tr>"
        for label, value in details
    )
    surcharge_html = (
        f"<p style='color:#a15c00'>{surcharge_line}</p>" if surcharge_line else ""
    )
    html = (
        "<div style='font-family:Arial,sans-serif;max-width:520px'>"
        "<h2 style='color:#1a5276'>Summit Air</h2>"
        "<p>Your appointment is confirmed.</p>"
        f"<table style='border-collapse:collapse'>{detail_rows}</table>"
        f"{surcharge_html}"
        "<p>Call +1 (484) 398-5113 and give your booking ID to make changes.</p>"
        "</div>"
    )

    subject = f"Summit Air appointment confirmation {booking.get('booking_id')}"
    return subject, "\n".join(text_lines), html


async def send_email_confirmation(
    to_email: str, booking: dict[str, object]
) -> dict[str, object]:
    api_key = os.getenv("RESEND_API_KEY")
    from_email = os.getenv("RESEND_FROM_EMAIL")
    if not api_key or not from_email:
        return {"status": "SKIPPED", "channel": "email", "message": FAILED_MESSAGE}

    subject, text, html = format_confirmation(booking)
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(
                RESEND_EMAILS_URL,
                json={
                    "from": f"Summit Air <{from_email}>",
                    "to": [to_email],
                    "subject": subject,
                    "text": text,
                    "html": html,
                },
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return {"status": "FAILED", "channel": "email", "message": FAILED_MESSAGE}
    return {"status": "SENT", "channel": "email"}
