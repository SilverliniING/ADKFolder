"""
Agent Setup and Execution

Initializes the ADK agent with MCP tools and provides async execution wrapper.
"""

import logging
import os

from google import adk
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types

from tools import (
    read_gcs_document,
    list_gcs_documents,
    parse_financial_document,
    write_firestore_record,
    match_documents,
    query_firestore_matches,
    generate_reconciliation_report,
    format_report_as_text,
)

logger = logging.getLogger("invoice_matching_agent")


def create_agent() -> Agent:
    """
    Create and configure the ADK agent with invoice matching tools.

    The agent is initialized with:
    - Gemini 2.5 Flash model (or specified via MODEL env var)
    - System instruction for invoice-to-payment matching
    - 7 MCP tools registered via FunctionTool

    Returns:
        Configured Agent instance
    """
    agent = Agent(
        name="invoice_matching_agent",
        model=os.environ.get("MODEL", "gemini-2.5-flash"),
        instruction="""You are an invoice matching and reconciliation assistant with access to specialized financial tools.

Your capabilities:
- List documents in GCS buckets using list_gcs_documents to discover all files
- Read invoices and bank statements from Google Cloud Storage using read_gcs_document
- Parse financial documents (invoices, payments) using parse_financial_document
- Store parsed records in Firestore using write_firestore_record
- Cross-reference invoices to payments using match_documents (handles errors gracefully)
- Query matched/unmatched records using query_firestore_matches
- Generate reconciliation reports using generate_reconciliation_report
- Format reports as readable text using format_report_as_text

When the user requests invoice matching:
1. Read invoices from the invoices GCS bucket using read_gcs_document
2. Parse each invoice using parse_financial_document (extract vendor, amount, date, reference number)
3. Write each parsed invoice to Firestore invoices collection using write_firestore_record
4. Read bank statements from the payments GCS bucket using read_gcs_document
5. Parse each payment using parse_financial_document (extract vendor, amount, date, transaction ID)
6. Write each parsed payment to Firestore bankstatements collection using write_firestore_record
7. Use match_documents to cross-reference invoices with payments (by vendor name + amount, within ±7 days)
   - This will return: matched_pairs, unmatched_invoices, unmatched_payments, error_invoices, error_payments
   - Files with errors (malformed data) are gracefully skipped and reported as error_invoices or error_payments
8. Use generate_reconciliation_report with the error_invoices and error_payments from match_documents result
9. Use format_report_as_text to format the report as a readable table

Always be thorough in matching. Vendor names should be matched fuzzily (e.g., "Acme Inc" matches "ACME Corporation").
Amounts must match exactly. Dates should be within 7 days of each other.
Provide a clear reconciliation report with: matched pairs table, list of unmatched invoices, list of unmatched payments, and any error records (files that couldn't be processed due to data issues).

Error Handling Notes:
- If match_documents returns error_invoices or error_payments, pass them to generate_reconciliation_report
- Error records are displayed in their own section with detailed error messages
- This allows the matching process to continue even when some files have issues""",
        tools=[
            FunctionTool(read_gcs_document),
            FunctionTool(list_gcs_documents),
            FunctionTool(parse_financial_document),
            FunctionTool(write_firestore_record),
            FunctionTool(match_documents),
            FunctionTool(query_firestore_matches),
            FunctionTool(generate_reconciliation_report),
            FunctionTool(format_report_as_text),
        ]
    )
    return agent


def create_runner(agent: Agent):
    """
    Create an ADK Runner for the agent.

    Args:
        agent: The agent to create a runner for

    Returns:
        Tuple of (Runner, SessionService)
    """
    session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        app_name="invoice_matching_pipeline",
        session_service=session_service
    )
    return runner, session_service


# Initialize agent and runner at module level
root_agent = create_agent()
agent_runner, session_service = create_runner(root_agent)

# Tool metadata for API endpoints
MCP_TOOLS_META = [
    {"name": "read_gcs_document", "description": "Read invoice PDFs or bank statements from GCS bucket."},
    {"name": "list_gcs_documents", "description": "List all documents in a GCS bucket, optionally filtered by prefix."},
    {"name": "parse_financial_document", "description": "Extract vendor, amount, date from financial documents."},
    {"name": "write_firestore_record", "description": "Write parsed invoice or payment record to Firestore."},
    {"name": "match_documents", "description": "Cross-reference invoices to payments by vendor and amount."},
    {"name": "query_firestore_matches", "description": "Query invoices or payments, optionally filtered by match status."},
    {"name": "generate_reconciliation_report", "description": "Generate matched pairs and unmatched records report."},
    {"name": "format_report_as_text", "description": "Format reconciliation report as human-readable table."},
]


async def execute_agent_with_tools(user_input: str) -> str:
    """
    Execute the ADK agent with invoice matching tools.

    The agent processes the user input and can call any of the registered tools.
    The runner handles all tool calls automatically based on agent decisions.

    Args:
        user_input: The user's request/prompt

    Returns:
        The agent's response text, or error message if execution fails
    """
    try:
        # Create a session for this request
        session = session_service.create_session(
            app_name="invoice_matching_pipeline",
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
