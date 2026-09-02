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

from customer_memory_service import lookup_customer, remember_customer
from location_service import check_service_location as resolve_service_location
from weather_service import get_current_weather

load_dotenv()

MAINTENANCE_FOLLOWUP_DAYS = 60


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
        returning_caller_instructions = ""
        if previous_customer:
            name = previous_customer.get("name")
            previous_request = previous_customer.get("previous_request")
            address_on_file = previous_customer.get("address")
            record_age, ask_maintenance = describe_record_age(
                previous_customer.get("updated_at")
            )
            returning_caller_instructions = f"""
This phone number matches a previous customer record. Use it naturally in conversation. Never recite the stored record back to the caller, and never read more than one stored detail in a single response.
Ask if you are speaking with {name}.
Only after the caller confirms their identity, mention that we have a request on file from {record_age} and ask if this call is about that same request.
For your reference only, the request on file is: {previous_request}. Do not read it out unless the caller asks what the request was or cannot remember it.
If this call is about the request on file, ask if the caller wants to add an update. Fold any update into the request summary you save at the end of the call.
If this call is about the request on file, you already have the caller's name; do not ask for it again.
""".strip()
            if ask_maintenance:
                returning_caller_instructions += """
Because the request on file is not recent, also ask whether this call is a scheduled maintenance visit for the same equipment."""
            if address_on_file:
                returning_caller_instructions += f"""
There is a service address on file: {address_on_file}.
When you need the service address, ask if the service is at the same address as last time instead of asking the caller to say it. Do not read the address on file aloud unless the caller asks or seems unsure.
If the caller confirms it is the same address, call check_service_location with the address on file.
If the caller says it is a different address, collect the service address as usual."""

        super().__init__(
            instructions=f"""
You are the front-office agent for Summit Air an HVAC company.
{returning_caller_instructions}
Ask what heating or cooling problem the caller has.
Ask if the property is residential or commercial.
Collect the caller's name, callback number, service address, and availability.
Ask for these details one at a time. Never ask for more than one detail in a single response.
Wait for the caller's answer before asking for the next detail.
If the caller volunteers details before being asked, accept them, do not ask for them again, and move on to the next missing detail.
Repeat the caller's name normally to confirm it.
If the name is unclear, has more than one common spelling, or the caller corrects it, ask the caller to spell the name.
Read the letters back and ask if the spelling is correct.
Do not ask every caller to spell a name that is already clear and confirmed.
When the caller gives a complete service address, call check_service_location.
Follow the status returned by check_service_location.
If the status is FIX, ask for the missing or suspicious address information.
If the status is CONFIRM, read the standardized address and ask if it is correct.
If the status is CONFIRM_ADD_SUBPREMISES, ask for an apartment or suite number.
If the status is ACCEPT, read the standardized address and ask if it is correct.
Whenever you read an address aloud, introduce the ZIP code with the words "and the zip code is" before saying it, for example: "123 Oak Street, San Antonio, Texas, and the zip code is 78205".
For all current and future tool calls, never mention tools, APIs, internal systems, or technical problems to the caller.
If a tool fails, do not report the failure to the caller.
Retry the location check one time if a retry can help.
If the location check fails again, keep the address exactly as the caller gave it and continue.
Do not claim that an address is serviceable when the location check does not return a service-area result.
Do not tell the caller the service-area result until they confirm the standardized address.
After the caller confirms a validated address, call check_current_weather with the exact coordinates returned by check_service_location.
Do not estimate coordinates.
Do not describe the weather unless the caller asks.
Do not set service priority from weather data.
If the caller reports an emergency guide tell them to contact authorities like 911. Do not give repair instructions.
Before the call ends, repeat the problem, property type, name, callback number,
address, and availability. Ask the caller to confirm that all details are correct.
After the caller confirms the final details, call remember_customer_record with the confirmed name, the confirmed service address, and a short summary of the current request. Do not include the address in the request summary.
After remember_customer_record finishes, call end_call. Do not say a separate goodbye before calling end_call.
If the caller wants to hang up before you have collected and confirmed all the required details, say: "I haven't received all the necessary information yet. Do you still want to hang up?"
Only call end_call early like this after the caller explicitly says yes to that question.
If the caller says no, continue collecting the remaining details.
Do not promise an appointment. Say that staff will review the request and follow up.
Keep each response short and conversational.
""".strip(),
            tools=[
                EndCallTool(
                    extra_description=(
                        "If the required details have not all been collected and confirmed, "
                        "do not call this tool until you have warned the caller that you have "
                        "not received all the necessary information and they have explicitly "
                        "confirmed they still want to hang up."
                    ),
                    delete_room=True,
                    end_instructions="Thank the caller, say that staff will follow up, and say goodbye.",
                    ignore_on_enter=True,
                )
            ],
        )

    @function_tool(
        description="Check a service address against the San Antonio service locations."
    )
    async def check_service_location(
        self, context: RunContext, address: str
    ) -> dict[str, object]:
        return await resolve_service_location(address)

    @function_tool(
        description="Get current weather for validated latitude and longitude coordinates."
    )
    async def check_current_weather(
        self, context: RunContext, latitude: float, longitude: float
    ) -> dict[str, object]:
        return await get_current_weather(latitude, longitude)

    @function_tool(
        description="Save the confirmed caller name, confirmed service address, and current service request."
    )
    async def remember_customer_record(
        self, context: RunContext, name: str, request_summary: str, address: str
    ) -> dict[str, object]:
        result = await remember_customer(
            self.phone_number, name, request_summary, address
        )
        return result

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
    await session.start(
        room=ctx.room,
        agent=HVACFrontDeskAgent(
            phone_number=phone_number,
            previous_customer=previous_customer,
        ),
    )
    await session.generate_reply(
        instructions="Introduce yourself as a Summit Air representative. Use the returning-caller instructions when available. Otherwise, ask how you can help."
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
