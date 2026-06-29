"""
FastAPI Application and Endpoints

Defines HTTP endpoints for:
- Health checks
- Document parsing with MCP tools
- General message processing
- Tool listing
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

from agent_setup import execute_agent_with_tools, MCP_TOOLS_META
from helpers import build_a2a_response, extract_task_id, extract_user_message

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("invoice_matching_agent")


# ============================================================================
# FastAPI Application Setup
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    logger.info("Starting Invoice Matching Agent with MCP Tools")
    logger.info(f"Available tools: {', '.join(t['name'] for t in MCP_TOOLS_META)}")
    yield
    logger.info("Shutting down Invoice Matching Agent")


app = FastAPI(
    title="Invoice Matching Agent with MCP Tools",
    description="Matches invoices to bank payments and generates reconciliation reports",
    lifespan=lifespan
)

# Export app for Uvicorn
__all__ = ["app"]


# ============================================================================
# Endpoints
# ============================================================================

@app.get("/")
async def health_check():
    """
    Health check endpoint.

    Returns:
        A2A-compliant response with available tools list
    """
    return build_a2a_response(
        "Invoice Matching Agent is ready. Available tools: " +
        ", ".join(t["name"] for t in MCP_TOOLS_META)
    )


@app.post("/match_invoices")
async def match_invoices(request: Request):
    """
    Match invoices to bank payments and generate reconciliation report.

    The agent will:
    1. Read all invoices from the invoices GCS bucket
    2. Parse each invoice (vendor, amount, date)
    3. Write each invoice to Firestore invoices collection
    4. Read all bank statements from the payments GCS bucket
    5. Parse each payment (vendor, amount, date)
    6. Write each payment to Firestore bankstatements collection
    7. Cross-reference invoices to payments by vendor+amount
    8. Generate reconciliation report with matched pairs and unmatched records

    Expected A2A Request:
    {
        "jsonrpc": "2.0",
        "id": "unique-request-id",
        "method": "match_invoices",
        "params": {
            "message": {
                "parts": [{
                    "type": "text",
                    "text": "Match all invoices with bank payments"
                }]
            }
        }
    }

    Args:
        request: FastAPI Request object

    Returns:
        A2A-compliant JSON-RPC response with reconciliation report
    """
    task_id = None
    try:
        payload = await request.json()
        task_id = extract_task_id(payload)
        user_input = extract_user_message(payload)

        if not user_input:
            return JSONResponse(
                status_code=400,
                content=build_a2a_response("Error: No message content", task_id)
            )

        agent_response = await execute_agent_with_tools(user_input)
        return build_a2a_response(agent_response, task_id)

    except Exception as e:
        logger.error(f"Error in match_invoices: {str(e)}")
        task_id = task_id or "error"
        return JSONResponse(
            status_code=500,
            content=build_a2a_response(f"Error: {str(e)}", task_id)
        )


@app.post("/parse_gcs_document")
async def parse_gcs_document(request: Request):
    """
    Parse a financial document from Google Cloud Storage.

    The agent will:
    1. Use read_gcs_document to fetch the file from GCS
    2. Parse financial data (vendor, amount, date)
    3. Optionally save to Firestore
    4. Return extracted information

    Expected A2A Request:
    {
        "jsonrpc": "2.0",
        "id": "unique-request-id",
        "method": "parse_gcs_document",
        "params": {
            "message": {
                "parts": [{
                    "type": "text",
                    "text": "Parse gs://bucket/path/to/invoice.pdf"
                }]
            }
        }
    }

    Args:
        request: FastAPI Request object

    Returns:
        A2A-compliant JSON-RPC response
    """
    task_id = None
    try:
        payload = await request.json()
        task_id = extract_task_id(payload)
        user_input = extract_user_message(payload)

        if not user_input:
            return JSONResponse(
                status_code=400,
                content=build_a2a_response("Error: No message content", task_id)
            )

        agent_response = await execute_agent_with_tools(user_input)
        return build_a2a_response(agent_response, task_id)

    except Exception as e:
        logger.error(f"Error in parse_gcs_document: {str(e)}")
        task_id = task_id or "error"
        return JSONResponse(
            status_code=500,
            content=build_a2a_response(f"Error: {str(e)}", task_id)
        )


@app.post("/process_message")
async def process_message(request: Request):
    """
    General message processing endpoint with invoice matching tool support.

    The agent can use any available tool based on the user's request:
    - Read invoices and payments from GCS
    - Parse financial documents
    - Write records to Firestore
    - Match invoices to payments
    - Query and report on reconciliation

    Expected A2A Request:
    {
        "jsonrpc": "2.0",
        "id": "unique-request-id",
        "params": {
            "message": {
                "parts": [{
                    "type": "text",
                    "text": "Your request or query here"
                }]
            }
        }
    }

    Args:
        request: FastAPI Request object

    Returns:
        A2A-compliant JSON-RPC response
    """
    task_id = None
    try:
        payload = await request.json()
        task_id = extract_task_id(payload)
        user_input = extract_user_message(payload)

        if not user_input:
            return JSONResponse(
                status_code=400,
                content=build_a2a_response("Error: No message content", task_id)
            )

        agent_response = await execute_agent_with_tools(user_input)
        return build_a2a_response(agent_response, task_id)

    except Exception as e:
        logger.error(f"Error in process_message: {str(e)}")
        task_id = task_id or "error"
        return JSONResponse(
            status_code=500,
            content=build_a2a_response(f"Error: {str(e)}", task_id)
        )


@app.get("/tools")
async def list_tools():
    """
    List all available MCP tools.

    Returns:
        dict with tools array and count
    """
    return {"tools": MCP_TOOLS_META, "count": len(MCP_TOOLS_META)}


# ============================================================================
# Server Startup
# ============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting Invoice Matching Agent on port {port}...")
    logger.info(f"MCP Tools registered: {len(MCP_TOOLS_META)}")
    logger.info(f"Main endpoint: POST /match_invoices")
    uvicorn.run(app, host="0.0.0.0", port=port)
