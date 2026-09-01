from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentServer, AgentSession, TurnHandlingOptions, inference

load_dotenv()


class HVACFrontDeskAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""
You are the front-office agent for Summit Air an HVAC company.
Ask what heating or cooling problem the caller has.
Ask if the property is residential or commercial.
Collect the caller's name, callback number, service address, and availability.
If the caller reports an emergency guide tell them to contact authorities like 911. Do not give repair instructions.
Before the call ends, repeat the problem, property type, name, callback number,
address, and availability. Ask the caller to confirm that all details are correct.
Do not promise an appointment. Say that staff will review the request and follow up.
Keep each response short and conversational.
""".strip()
        )


server = AgentServer()


@server.rtc_session(agent_name="hvac-front-desk")
async def hvac_front_desk(ctx: agents.JobContext) -> None:
    session = AgentSession(
        stt=inference.STT(model="deepgram/nova-3", language="en"),
        llm=inference.LLM(model="google/gemma-4-31b-it"),
        tts=inference.TTS(model="inworld/inworld-tts-2", voice="Ashley"),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
        ),
    )
    await session.start(room=ctx.room, agent=HVACFrontDeskAgent())
    await session.generate_reply(
        instructions="Say that you are the representive from Summit Air and ask how you can help them"
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
