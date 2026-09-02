import asyncio
import re
from collections.abc import AsyncIterable
from datetime import datetime, timezone

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    ModelSettings,
    RunContext,
    TurnHandlingOptions,
    function_tool,
    inference,
)
from livekit.agents.beta.tools import EndCallTool

from customer_memory_service import lookup_customer, record_note, remember_customer
from location_service import check_service_location as resolve_service_location
from notification_service import send_email_confirmation
from prompts import (
    ADDRESS_ON_FILE_INSTRUCTIONS,
    BASE_INSTRUCTIONS,
    BOOK_APPOINTMENT_DESCRIPTION,
    CHECK_SERVICE_LOCATION_DESCRIPTION,
    END_CALL_EXTRA_DESCRIPTION,
    END_CALL_GOODBYE_INSTRUCTIONS,
    FIND_APPOINTMENT_SLOTS_DESCRIPTION,
    GREETING_INSTRUCTIONS,
    LOOKUP_BOOKING_DESCRIPTION,
    MAINTENANCE_FOLLOWUP_INSTRUCTIONS,
    RECORD_CONCERN_NOTE_DESCRIPTION,
    RETURNING_CALLER_INSTRUCTIONS,
    SEND_BOOKING_CONFIRMATION_DESCRIPTION,
    UPDATE_BOOKING_DESCRIPTION,
)
from scheduling_service import (
    book_appointment as request_appointment_booking,
    find_available_slots,
    is_severe_weather,
    lookup_booking as request_booking_lookup,
    severe_temperature_kind,
    update_booking as request_booking_update,
)
from weather_service import get_current_weather

load_dotenv()

MAINTENANCE_FOLLOWUP_DAYS = 60
# Console runs have no SIP participant, so fall back to a test number there.
CONSOLE_TEST_PHONE = "+12105550199"


def describe_record_age(updated_at: object) -> tuple[str, bool]:
    """Return a spoken-friendly age for a stored record and whether it is old
    enough to ask about scheduled maintenance."""
    try:
        updated = datetime.fromisoformat(str(updated_at))
    except (TypeError, ValueError):
        return "a previous call", False
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    days = max(0, (datetime.now(timezone.utc) - updated).days)
    if days == 0:
        phrase = "earlier today"
    elif days == 1:
        phrase = "yesterday"
    elif days < 7:
        phrase = f"{days} days ago"
    elif days < 60:
        weeks = round(days / 7)
        phrase = "about a week ago" if weeks == 1 else f"about {weeks} weeks ago"
    elif days < 365:
        months = round(days / 30)
        phrase = "about a month ago" if months == 1 else f"about {months} months ago"
    else:
        phrase = "over a year ago"
    return phrase, days >= MAINTENANCE_FOLLOWUP_DAYS


class HVACFrontDeskAgent(Agent):
    def __init__(
        self,
        phone_number: str | None = None,
        previous_customer: dict[str, object] | None = None,
    ) -> None:
        self.phone_number = phone_number
        self._weather_task: asyncio.Task | None = None
        self._verified_location: dict[str, object] | None = None
        self._booking: dict[str, object] | None = None
        returning_caller_instructions = ""
        if previous_customer:
            name = previous_customer.get("name")
            previous_request = previous_customer.get("previous_request")
            address_on_file = previous_customer.get("address")
            record_age, ask_maintenance = describe_record_age(
                previous_customer.get("updated_at")
            )
            returning_caller_instructions = RETURNING_CALLER_INSTRUCTIONS.format(
                name=name,
                record_age=record_age,
                previous_request=previous_request,
            )
            if ask_maintenance:
                returning_caller_instructions += "\n" + MAINTENANCE_FOLLOWUP_INSTRUCTIONS
            if address_on_file:
                returning_caller_instructions += "\n" + ADDRESS_ON_FILE_INSTRUCTIONS.format(
                    address_on_file=address_on_file
                )

        super().__init__(
            instructions=BASE_INSTRUCTIONS.format(
                returning_caller_instructions=returning_caller_instructions
            ).strip(),
            tools=[
                EndCallTool(
                    extra_description=END_CALL_EXTRA_DESCRIPTION,
                    delete_room=True,
                    end_instructions=END_CALL_GOODBYE_INSTRUCTIONS,
                    ignore_on_enter=True,
                )
            ],
        )

    @function_tool(description=CHECK_SERVICE_LOCATION_DESCRIPTION)
    async def check_service_location(
        self, context: RunContext, address: str
    ) -> dict[str, object]:
        result = await resolve_service_location(address)
        # Pin the validated address so scheduling and booking use it directly;
        # a lookup for a new address replaces any earlier verification.
        self._verified_location = (
            result if result.get("serviceability") == "SERVICEABLE" else None
        )
        latitude = result.get("latitude")
        longitude = result.get("longitude")
        if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
            # Fetch weather in the background; find_appointment_slots awaits it.
            self._weather_task = asyncio.create_task(
                get_current_weather(float(latitude), float(longitude))
            )
        return result

    async def _current_weather(self) -> dict[str, object] | None:
        if self._weather_task is None:
            return None
        try:
            return await self._weather_task
        except Exception:
            return None

    @function_tool(description=FIND_APPOINTMENT_SLOTS_DESCRIPTION)
    async def find_appointment_slots(
        self,
        context: RunContext,
        is_emergency: bool,
        issue_type: str,
        preferred_date: str | None = None,
        time_preference: str | None = None,
    ) -> dict[str, object]:
        location = None
        if self._verified_location:
            location = self._verified_location.get("nearest_location")
        elif self._booking:
            location = self._booking.get("location")
        if not location:
            return {
                "status": "ADDRESS_NOT_VERIFIED",
                "message": (
                    "Verify the service address with check_service_location "
                    "before offering appointment times."
                ),
            }
        weather = await self._current_weather()
        severe_weather = is_severe_weather(weather)
        # An outage that matches the measured severe temperature is an
        # emergency even if triage missed it: the LLM knows what broke, the
        # weather data knows how extreme it is outside.
        temperature_kind = severe_temperature_kind(weather)
        escalated = not is_emergency and (
            (temperature_kind == "heat" and issue_type == "cooling_failure")
            or (temperature_kind == "cold" and issue_type == "heating_failure")
        )
        is_emergency = is_emergency or escalated
        result = await find_available_slots(
            location=location,
            is_emergency=is_emergency,
            severe_weather=severe_weather,
            preferred_date=preferred_date,
            time_preference=time_preference,
        )
        if result.get("status") == "OK":
            # Give the LLM a short weather summary only when severe weather is
            # actually escalating this emergency (same gate as the scheduler),
            # so it can acknowledge the conditions while offering slots.
            if is_emergency and severe_weather and weather:
                result["severe_weather_context"] = {
                    "temperature_fahrenheit": weather.get("temperature_fahrenheit"),
                    "feels_like_fahrenheit": weather.get("feels_like_fahrenheit"),
                    "condition": weather.get("condition"),
                }
            if escalated:
                result["message"] = (
                    "Current temperatures at the service address make this "
                    "outage an emergency. Treat the request as an emergency "
                    "for the rest of the call, including booking, and offer "
                    "the earliest option first."
                )
        # Keep technician names out of the conversation; the caller only needs times.
        slots = result.get("slots")
        if isinstance(slots, list):
            for slot in slots:
                if isinstance(slot, dict):
                    slot.pop("tech_name", None)
        dispatch = result.get("after_hours_dispatch")
        if isinstance(dispatch, dict):
            dispatch.pop("tech_name", None)
        return result

    @function_tool(description=BOOK_APPOINTMENT_DESCRIPTION)
    async def book_appointment(
        self,
        context: RunContext,
        tech_id: str,
        start: str,
        end: str,
        customer_name: str,
        summary: str,
        is_emergency: bool,
        after_hours: bool,
    ) -> dict[str, object]:
        # The service address comes from the pinned validation result, not the
        # LLM, so a booking can never carry a misheard or unverified address.
        if not self._verified_location:
            return {
                "status": "ADDRESS_NOT_VERIFIED",
                "message": (
                    "Verify the service address with check_service_location "
                    "before booking."
                ),
            }
        address = str(
            self._verified_location.get("standardized_address")
            or self._verified_location.get("original_address")
            or ""
        )
        result = await request_appointment_booking(
            tech_id=tech_id,
            start=start,
            end=end,
            customer_name=customer_name,
            customer_phone=self.phone_number or CONSOLE_TEST_PHONE,
            address=address,
            summary=summary,
            is_emergency=is_emergency,
            after_hours=after_hours,
        )
        if result.get("booked"):
            self._booking = result
            result = {
                **{key: value for key, value in result.items() if key != "tech_name"},
                "message": (
                    "Read back the appointment day and arrival time window. "
                    "Near the end of the call, offer an email confirmation."
                ),
            }
        return result

    @function_tool(description=RECORD_CONCERN_NOTE_DESCRIPTION)
    async def record_concern_note(
        self,
        context: RunContext,
        note: str,
        name: str = "",
        contact: str = "",
    ) -> dict[str, object]:
        return await record_note(note=note, name=name, contact=contact)

    @function_tool(description=LOOKUP_BOOKING_DESCRIPTION)
    async def lookup_booking(
        self, context: RunContext, booking_id: str
    ) -> dict[str, object]:
        result = await request_booking_lookup(booking_id)
        if result.get("found"):
            self._booking = dict(result)
            result = {
                **{key: value for key, value in result.items() if key != "tech_name"},
                "message": (
                    "Confirm the appointment day and time with the caller. "
                    "Ask what they would like to change."
                ),
            }
        return result

    @function_tool(description=UPDATE_BOOKING_DESCRIPTION)
    async def update_booking(
        self,
        context: RunContext,
        booking_id: str,
        action: str,
        tech_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, object]:
        result = await request_booking_update(
            booking_id=booking_id,
            action=action,
            tech_id=tech_id,
            start=start,
            end=end,
        )
        if result.get("updated"):
            self._booking = dict(result)
            if result.get("status") == "CANCELLED":
                message = "Confirm the appointment is cancelled."
            else:
                message = (
                    "Read back the new appointment day and arrival time window. "
                    "Offer an email confirmation of the change."
                )
            result = {
                **{key: value for key, value in result.items() if key != "tech_name"},
                "message": message,
            }
        return result

    @function_tool(description=SEND_BOOKING_CONFIRMATION_DESCRIPTION)
    async def send_booking_confirmation(
        self, context: RunContext, email: str
    ) -> dict[str, object]:
        if not self._booking:
            return {
                "status": "NO_BOOKING",
                "message": "Book an appointment before sending a confirmation.",
            }
        if not email or "@" not in email:
            return {
                "status": "EMAIL_REQUIRED",
                "message": (
                    "Ask the caller to spell their email address, read it back, "
                    "and confirm it before retrying."
                ),
            }
        result = await send_email_confirmation(email, self._booking)
        if result.get("status") == "SENT":
            result = {
                **result,
                "message": "Tell the caller the confirmation email is on its way.",
            }
        return result

    async def save_customer_memory(self) -> None:
        """Persist the caller record from the booking at call end, so the LLM
        never has to remember to do it."""
        booking = self._booking
        if not booking or not booking.get("customer_name"):
            return
        summary = str(booking.get("summary", "")).strip()
        if booking.get("status") == "CANCELLED":
            request_summary = f"{summary} (appointment cancelled)".strip()
        else:
            spoken_time = str(booking.get("spoken_time", "")).strip()
            request_summary = (
                f"{summary} Booked for {spoken_time}." if spoken_time else summary
            )
        if not request_summary:
            return
        await remember_customer(
            self.phone_number,
            str(booking.get("customer_name", "")),
            request_summary,
            str(booking.get("address", "")),
        )

    def tts_node(self, text: AsyncIterable[str], model_settings: ModelSettings):
        # Rewrite "HVAC" so the TTS says it as one word instead of spelling the letters.
        async def adjusted() -> AsyncIterable[str]:
            async for chunk in text:
                yield re.sub(r"\bHVAC\b", "H-vac", chunk, flags=re.IGNORECASE)

        return super().tts_node(adjusted(), model_settings)


server = AgentServer()


@server.rtc_session(agent_name="hvac-front-desk")
async def hvac_front_desk(ctx: agents.JobContext) -> None:
    participant = await ctx.wait_for_participant()
    phone_number = participant.attributes.get("sip.phoneNumber")
    previous_customer = await lookup_customer(phone_number)
    session = AgentSession(
        stt=inference.STT(model="deepgram/nova-3", language="en"),
        llm=inference.LLM(model="google/gemma-4-31b-it"),
        tts=inference.TTS(model="inworld/inworld-tts-2", voice="Ashley"),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
        ),
    )
    agent = HVACFrontDeskAgent(
        phone_number=phone_number,
        previous_customer=previous_customer,
    )
    ctx.add_shutdown_callback(agent.save_customer_memory)
    await session.start(room=ctx.room, agent=agent)
    await session.generate_reply(instructions=GREETING_INSTRUCTIONS)


if __name__ == "__main__":
    agents.cli.run_app(server)
