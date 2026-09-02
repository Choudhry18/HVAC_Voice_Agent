# LiveKit HVAC Voice Agent

1. Copy `.env.example` to `.env` and add your LiveKit credentials.
2. Run `uv sync`.
3. Run `uv run python agent.py console` for a local voice test.
4. Run `uv run python agent.py dev` for a LiveKit call test.

## Commercial demo

The worker classifies the issue excerpt against a fixed commercial service
catalog. It then offers tentative times from technicians who have the required
skill and enough continuous availability. Commercial bookings use the
`PENDING_CONFIRMATION` status until staff sends a `confirm` or `reject` booking
update.

The demo catalog includes VRV or VRF service, commissioning, rooftop and
packaged units, commercial split systems, controls and BMS work, chillers,
boilers and hydronics, ventilation and indoor air quality, and preventive
maintenance.
