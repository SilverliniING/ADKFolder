"""
Agent Setup and Execution

Initializes the ADK agent with MCP tools and provides async execution wrapper.
"""

import logging
import os
from typing import Optional

from google import adk
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types

from tools import (
    read_gcs_document,
    extract_academic_metadata,
    write_to_firestore,
    list_gcs_documents,
    query_firestore,
)

logger = logging.getLogger("academic_agent_mcp")


def create_agent() -> Agent:
    """
    Create and configure the ADK agent with MCP tools.

    The agent is initialized with:
    - Gemini 2.5 Flash model (or specified via MODEL env var)
    - System instruction for academic document processing
    - 5 MCP tools registered via FunctionTool

    Returns:
        Configured Agent instance
    """
    agent = Agent(
        name="academic_agent",
        model=os.environ.get("MODEL", "gemini-2.5-flash"),
        instruction="""You are an academic document processing assistant with access to specialized tools.

Your capabilities:
- Read and parse documents from Google Cloud Storage using read_gcs_document
- Extract structured metadata from academic papers using extract_academic_metadata
- Store results in Firestore using write_to_firestore (only when explicitly requested)
- List available documents using list_gcs_documents
- Query stored data using query_firestore

When the user requests document analysis:
1. Use read_gcs_document to fetch the document content
2. Use extract_academic_metadata to parse structured information
3. Only use write_to_firestore if the user explicitly asks to save or store results
4. Provide a clear summary of findings

Always use your tools to fulfill requests. Never say you cannot access documents — use list_gcs_documents.
Always be precise and cite specific information from documents.
Focus on analyzing and summarizing documents; only write to storage when requested.""",
        tools=[
            FunctionTool(read_gcs_document),
            FunctionTool(extract_academic_metadata),
            FunctionTool(write_to_firestore),
            FunctionTool(list_gcs_documents),
            FunctionTool(query_firestore),
        ]
    )
    return agent


def create_runner(agent: Agent) -> Runner:
    """
    Create an ADK Runner for the agent.

    Args:
        agent: The agent to create a runner for

    Returns:
        Configured Runner instance
    """
    session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        app_name="academic_pipeline",
        session_service=session_service
    )
    return runner, session_service


# Initialize agent and runner at module level
root_agent = create_agent()
agent_runner, session_service = create_runner(root_agent)

# Tool metadata for API endpoints
MCP_TOOLS_META = [
    {"name": "read_gcs_document", "description": "Read and parse a document from GCS bucket."},
    {"name": "extract_academic_metadata", "description": "Extract structured metadata from document content."},
    {"name": "write_to_firestore", "description": "Write extracted metadata to Firestore."},
    {"name": "list_gcs_documents", "description": "List all documents in a GCS bucket."},
    {"name": "query_firestore", "description": "Query documents from Firestore collection."},
]


async def execute_agent_with_tools(user_input: str) -> str:
    """
    Execute the ADK agent with MCP tools.

    The agent processes the user input and can call any of the registered tools.
    The runner handles all tool calls automatically based on agent decisions.

    Args:
        user_input: The user's request/prompt

    Returns:
        The agent's response text, or error message if execution fails
    """
    try:
        # Create session for this request
        session = session_service.create_session(
            app_name="academic_pipeline",
            user_id="cloud_run_environment"
        )

        # Prepare user message
        user_content = types.Content(
            role="user",
            parts=[types.Part(text=user_input)]
        )

        response_text = ""

        # Stream responses from agent
        async for event in agent_runner.run_async(
            user_id="cloud_run_environment",
            session_id=session.id,
            new_message=user_content
        ):
            # Collect text content from events
            if hasattr(event, 'content') and event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, 'text') and part.text:
                        response_text += part.text

        return response_text or "Agent processed request without generating text output"

    except Exception as e:
        logger.error(f"Error in agent execution: {str(e)}")
        return f"Error: {str(e)}"
