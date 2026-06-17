import os
import uuid
import logging
from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv

from google import adk
from google.adk.sessions import InMemorySessionService
from google.genai import types

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("academic_agent_server")

app = FastAPI(
    title="Gemini Enterprise Academic Agent",
    description="Containerized Cloud Run server matching the analysis_agent Agent Card schema."
)

root_agent = adk.Agent(
    name="analysis_agent",
    model=os.environ.get("MODEL", "gemini-2.5-flash"),
    instruction="""You are an academic data processing assistant. 
    Analyze the text context provided and extract: university, professor, topic, summary."""
)

session_service = InMemorySessionService()

agent_runner = adk.Runner(
    agent=root_agent,
    app_name="academic_pipeline",
    session_service=session_service
)


def build_a2a_response(text: str, request_id: str = None) -> dict:
    """
    Builds a fully A2A-compliant JSON-RPC 2.0 SendMessageSuccessResponse.

    The outer envelope:
        jsonrpc, id, result          <- JSON-RPC 2.0 required fields

    result must be a Message object:
        messageId                    <- unique ID for this message
        role                         <- must be "agent" (not "model")
        parts                        <- list of typed Part objects
            type                     <- discriminator, must be "text"
            text                     <- actual content
    """
    return {
        "jsonrpc": "2.0",                       # JSON-RPC version — required on every response
        "id": request_id or str(uuid.uuid4()),  # echo the inbound request id
        "result": {
            "messageId": str(uuid.uuid4()),     # unique ID for this specific message
            "role": "agent",                    # A2A uses "agent", NOT "model"
            "parts": [
                {
                    "type": "text",             # discriminated union — type field is mandatory
                    "text": text
                }
            ]
        }
    }


def extract_task_id(payload: dict) -> str | None:
    """Pull the JSON-RPC request id to echo it back."""
    return payload.get("id") or payload.get("taskId") or None


async def execute_agent_logic(user_input: str) -> str:
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


def extract_user_message(payload: dict) -> str:
    """
    Handles both legacy nested format AND the standard A2A JSON-RPC 2.0 format.

    Standard A2A inbound shape:
    {
        "jsonrpc": "2.0",
        "id": "...",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{ "type": "text", "text": "..." }]
            }
        }
    }
    """
    # Standard A2A JSON-RPC 2.0 path: params.message.parts[0].text
    params = payload.get("params", {})
    if params:
        message = params.get("message", {})
        parts = message.get("parts", [])
        if parts and isinstance(parts[0], dict):
            return parts[0].get("text", "")

    # Legacy fallback path
    message_content = payload.get("message", "")
    if isinstance(message_content, dict):
        # Nested content schema
        if "content" in message_content and "parts" in message_content["content"]:
            parts = message_content["content"]["parts"]
            if parts and isinstance(parts[0], dict) and "text" in parts[0]:
                return parts[0]["text"]
        # Flat parts schema
        elif "parts" in message_content:
            parts = message_content["parts"]
            if parts and isinstance(parts[0], dict) and "text" in parts[0]:
                return parts[0]["text"]

    return str(message_content) if message_content else "Process baseline verification payload."


# --- ENDPOINTS ---

@app.post("/")
async def handle_root_or_general_chat(request: Request):
    try:
        payload = await request.json()
        logger.info("Executing general root route fallback handler.")
        logger.info(f"Inbound payload: {payload}")   # log full payload to debug future schema drifts

        task_id = extract_task_id(payload)
        user_input = extract_user_message(payload)
        agent_response = await execute_agent_logic(user_input)

        return build_a2a_response(agent_response, task_id)

    except Exception as e:
        logger.error(f"Error in root fallback handler: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/parse_gcs_document")
async def parse_gcs_document(request: Request):
    try:
        payload = await request.json()
        logger.info("Executing skill: parse_gcs_document")
        logger.info(f"Inbound payload: {payload}")

        task_id = extract_task_id(payload)
        user_input = extract_user_message(payload)
        agent_response = await execute_agent_logic(user_input)

        return build_a2a_response(agent_response, task_id)

    except Exception as e:
        logger.error(f"Error in parse_gcs_document: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/write_to_firestore")
async def write_to_firestore(request: Request):
    try:
        payload = await request.json()
        logger.info("Executing skill: write_to_firestore")
        logger.info(f"Inbound payload: {payload}")

        task_id = extract_task_id(payload)
        metadata_input = extract_user_message(payload)
        db_instruction = f"Log and format the following metadata for database commitment: {metadata_input}"
        agent_response = await execute_agent_logic(db_instruction)

        return build_a2a_response(agent_response, task_id)

    except Exception as e:
        logger.error(f"Error in write_to_firestore: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting A2A schema-aligned server on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)