import os
import logging
from fastapi import FastAPI, Request
from dotenv import load_dotenv

# Core Google ADK and GenAI module imports
from google import adk
from google.adk.sessions import InMemorySessionService
from google.genai import types

# 1. Initialization and Environment Setup
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("academic_agent_server")

app = FastAPI(
    title="Gemini Enterprise Academic Agent",
    description="Containerized Cloud Run server for multi-agent parsing tasks"
)

# 2. Define the Declarative Agent Schema
root_agent = adk.Agent(
    name="analysis_agent",
    model=os.environ.get("MODEL", "gemini-2.5-flash"),
    instruction="""You are an academic data processing assistant. 
    Analyze the text context provided and extract: university, professor, topic, summary."""
)

# 3. Instantiate Runtime State Components
# ADK 2.0 requires a session service injected directly into the runner constructor
session_service = InMemorySessionService()

agent_runner = adk.Runner(
    agent=root_agent, 
    app_name="academic_pipeline", 
    session_service=session_service
)

# 4. Web Server Inbound Webhook Processing Loop
@app.post("/")
async def handle_cloud_event(request: Request):
    try:
        payload = await request.json()
        logger.info(f"Incoming event payload processed successfully.")
        
        # Pull text payload from incoming execution parameter context
        user_input = payload.get("message", "Baseline trigger verification check.")
        
        # Format string values into strict structured Google GenAI Type contents
        content = types.Content(role="user", parts=[types.Part(text=user_input)])
        
        # Establish a localized session state tracker
        session = await session_service.create_session(
            app_name="academic_pipeline", 
            user_id="cloud_run_environment"
        )
        
        response_text = ""
        
        # ADK 2.0 streams execution states. We catch text chunks via the async iterator loop
        async for event in agent_runner.run_async(
            user_id="cloud_run_environment",
            session_id=session.id,
            new_message=content
        ):
            # Parse chunks checking safe structural extraction boundaries
            if hasattr(event, 'content') and event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, 'text') and part.text:
                        response_text += part.text
                        
        logger.info("Agent pipeline task execution finished without faults.")
        return {
            "status": "success",
            "agent_response": response_text
        }
        
    except Exception as e:
        logger.error(f"Internal Runtime Exception Caught: {str(e)}")
        return {
            "status": "error", 
            "detail": str(e)
        }

# 5. Application Execution Entry point
if __name__ == "__main__":
    import uvicorn
    # Cloud Run dynamically assigns a PORT environment variable at runtime
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting server infrastructure profile on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)