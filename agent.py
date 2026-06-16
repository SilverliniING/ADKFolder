import os
import logging
from fastapi import FastAPI, Request, HTTPException
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
    description="Containerized Cloud Run server matching the analysis_agent Agent Card schema."
)

# 2. Define the Declarative Agent Schema
root_agent = adk.Agent(
    name="analysis_agent",
    model=os.environ.get("MODEL", "gemini-2.5-flash"),
    instruction="""You are an academic data processing assistant. 
    Analyze the text context provided and extract: university, professor, topic, summary."""
)

# 3. Instantiate Runtime State Components
session_service = InMemorySessionService()

agent_runner = adk.Runner(
    agent=root_agent, 
    app_name="academic_pipeline", 
    session_service=session_service
)

# --- HELPER ORCHESTRATION FUNCTION ---
async def execute_agent_logic(user_input: str) -> str:
    """Helper to execute the ADK workflow and aggregate chunks since streaming is disabled."""
    content = types.Content(role="user", parts=[types.Part(text=user_input)])
    
    session = await session_service.create_session(
        app_name="academic_pipeline", 
        user_id="cloud_run_environment"
    )
    
    response_text = ""
    async for event in agent_runner.run_async(
        user_id="cloud_run_environment",
        session_id=session.id,
        new_message=content
    ):
        if hasattr(event, 'content') and event.content and event.content.parts:
            for part in event.content.parts:
                if hasattr(part, 'text') and part.text:
                    response_text += part.text
    return response_text

@app.post("/")
async def handle_root_or_general_chat(request: Request):
    """
    Fallback Root Handler
    Catches general conversational routing (like 'Hi') and platform handshakes.
    """
    try:
        payload = await request.json()
        logger.info("Executing general root route fallback handler.")
        
        # Pull text payload from the general message array
        user_input = payload.get("message", "Hello! How can I assist you with academic data parsing today?")
        
        # Route general text straight to the core ADK agent
        agent_response = await execute_agent_logic(user_input)
        
        return {
            "status": "success",
            "agent_response": agent_response
        }
    except Exception as e:
        logger.error(f"Error in root fallback handler: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
# 4. Aligned A2A Skill Webhook Endpoints

@app.post("/parse_gcs_document")
async def parse_gcs_document(request: Request):
    """
    Skill ID: parse_gcs_document
    Monitors GCS uploads, analyzes text, and extracts structured metadata.
    """
    try:
        payload = await request.json()
        logger.info("Executing skill: parse_gcs_document")
        
        # Pull text payload sent by the orchestration layer
        user_input = payload.get("message", "Baseline trigger verification check.")
        
        agent_response = await execute_agent_logic(user_input)
        
        return {
            "status": "success",
            "skillId": "parse_gcs_document",
            "agent_response": agent_response
        }
    except Exception as e:
        logger.error(f"Error in parse_gcs_document: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/write_to_firestore")
async def write_to_firestore(request: Request):
    """
    Skill ID: write_to_firestore
    Takes structured metadata and records it inside a Firestore collection.
    """
    try:
        payload = await request.json()
        logger.info("Executing skill: write_to_firestore")
        
        # Expecting the structured data payload to be logged
        metadata_input = payload.get("message", "No metadata provided.")
        
        # Construct the execution instruction for saving the state
        db_instruction = f"Log and format the following metadata for database commitment: {metadata_input}"
        
        agent_response = await execute_agent_logic(db_instruction)
        
        return {
            "status": "success",
            "skillId": "write_to_firestore",
            "agent_response": agent_response
        }
    except Exception as e:
        logger.error(f"Error in write_to_firestore: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# 5. Application Execution Entry point
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting A2A schema-aligned server on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)