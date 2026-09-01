from dotenv import load_dotenv
from livekit import agents
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
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
            returning_caller_instructions = f"""
This phone number has a previous customer record.
Ask if you are speaking with {name}.
Only after the caller confirms their identity, mention the previous request: {previous_request}.
Ask if this call is about that request or a new request.
""".strip()

        super().__init__(
            instructions=f"""
You are the front-office agent for Summit Air an HVAC company.
{returning_caller_instructions}
Ask what heating or cooling problem the caller has.
Ask if the property is residential or commercial.
Collect the caller's name, callback number, service address, and availability.
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
After the caller confirms the final details, call remember_customer_record with the confirmed name and a short summary of the current request.
After remember_customer_record finishes, call end_call. Do not say a separate goodbye before calling end_call.
Do not promise an appointment. Say that staff will review the request and follow up.
Keep each response short and conversational.
""".strip()
        )
        self._end_call_tool = EndCallTool(
            delete_room=True,
            end_instructions="Thank the caller, say that staff will follow up, and say goodbye.",
            ignore_on_enter=True,
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
        description="Save the confirmed caller name and current service request."
    )
    async def remember_customer_record(
        self, context: RunContext, name: str, request_summary: str
    ) -> dict[str, object]:
        result = await remember_customer(self.phone_number, name, request_summary)
        await self.update_tools([*self.tools, self._end_call_tool])
        return result


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
