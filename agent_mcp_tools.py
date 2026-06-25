"""
A2A-Compliant Agent with MCP Tool Usage

This agent implements MCP (Model Context Protocol) tools for:
- Reading and parsing documents from Google Cloud Storage
- Extracting structured data from documents
- Writing results to Firestore
- Processing academic metadata

Tools are registered directly with the ADK Agent using FunctionTool.
"""

import io
import os
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
from dotenv import load_dotenv

from google import adk
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types
from google.cloud import storage, firestore

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("academic_agent_mcp")

# GCS & Firestore clients
gcs_client = storage.Client()
db_client = firestore.Client()

# ============================================================================
# TOOL IMPLEMENTATIONS (plain functions — ADK wraps these via FunctionTool)
# ============================================================================


def read_gcs_document(bucket_name: str, blob_path: str) -> dict:
    """
    Read and parse a document from Google Cloud Storage bucket.
    Returns the document content and basic metadata.

    Args:
        bucket_name: The GCS bucket name (e.g. 'my-academic-documents')
        blob_path: The path to the document in the bucket (e.g. 'papers/2024/quantum.pdf')
    """
    try:
        bucket = gcs_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)

        if not blob.exists():
            return {"error": f"Document not found: {blob_path}", "status": 404}

        blob.reload()
        metadata = {
            "name": blob.name,
            "size": blob.size,
            "content_type": blob.content_type,
            "created": blob.time_created.isoformat() if blob.time_created else None,
            "updated": blob.updated.isoformat() if blob.updated else None
        }

        if blob_path.endswith('.pdf'):
            try:
                import PyPDF2
                content_bytes = blob.download_as_bytes()
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(content_bytes))
                text_content = ""
                for page in pdf_reader.pages:
                    text_content += page.extract_text() or ""
                return {"success": True, "content": text_content, "metadata": metadata, "format": "pdf"}
            except ImportError:
                return {"error": "PyPDF2 not installed. Cannot parse PDF.", "status": 400}

        elif blob_path.endswith('.json'):
            content = blob.download_as_string().decode('utf-8')
            return {"success": True, "content": json.loads(content), "metadata": metadata, "format": "json"}

        else:
            content = blob.download_as_string().decode('utf-8')
            return {"success": True, "content": content, "metadata": metadata, "format": "text"}

    except Exception as e:
        logger.error(f"Error reading GCS document: {e}")
        return {"error": str(e), "status": 500}


def extract_academic_metadata(document_content: str, extraction_format: str = "full") -> dict:
    """
    Extract structured academic metadata from document content.
    Returns JSON with fields: title, authors, institution, date, topics, summary.

    Args:
        document_content: The document text content to parse
        extraction_format: What to extract — 'full' (all metadata), 'summary' (title/authors only), 'references' (citations only)
    """
    try:
        metadata = {
            "title": None,
            "authors": [],
            "institution": None,
            "date": None,
            "topics": [],
            "summary": None
        }

        lines = document_content.split('\n')

        for line in lines[:50]:
            line_lower = line.lower()

            if not metadata["title"] and ("title:" in line_lower or "paper:" in line_lower):
                metadata["title"] = line.split(":", 1)[1].strip() if ":" in line else line

            if "author" in line_lower and ":" in line:
                authors_text = line.split(":", 1)[1].strip()
                metadata["authors"] = [a.strip() for a in authors_text.split(",")]

            if not metadata["institution"] and ("affiliation" in line_lower or "institution" in line_lower):
                metadata["institution"] = line.split(":", 1)[1].strip() if ":" in line else line

            if not metadata["date"] and ("date:" in line_lower or "published:" in line_lower):
                metadata["date"] = line.split(":", 1)[1].strip() if ":" in line else line

        for line in lines:
            if line.strip() and len(line.strip()) > 100:
                metadata["summary"] = line.strip()[:500]
                break

        if extraction_format == "summary":
            return {"success": True, "data": {"title": metadata["title"], "authors": metadata["authors"], "format": extraction_format}}

        elif extraction_format == "references":
            references = [line for line in lines if line.strip() and any(
                kw in line.lower() for kw in ["[1]", "[2]", "doi:", "arxiv:", "reference"]
            )]
            return {"success": True, "data": {"references": references[:10], "format": extraction_format}}

        return {"success": True, "data": metadata, "format": extraction_format}

    except Exception as e:
        logger.error(f"Error extracting metadata: {e}")
        return {"error": str(e), "status": 500}


def write_to_firestore(collection: str, data: dict, document_id: str = "") -> dict:
    """
    Write extracted metadata and analysis results to Firestore database collection.

    Args:
        collection: Firestore collection name (e.g. 'academic_papers')
        data: The data object to store (any JSON-serializable structure)
        document_id: Document ID — leave empty for auto-generated
    """
    try:
        if not document_id:
            document_id = str(uuid.uuid4())

        data["_created_at"] = firestore.SERVER_TIMESTAMP
        data["_document_id"] = document_id

        db_client.collection(collection).document(document_id).set(data)

        logger.info(f"Written to Firestore: {collection}/{document_id}")
        return {"success": True, "document_id": document_id, "collection": collection}

    except Exception as e:
        logger.error(f"Error writing to Firestore: {e}")
        return {"error": str(e), "status": 500}


def list_gcs_documents(bucket_name: str, prefix: str = "") -> dict:
    """
    List all documents in a GCS bucket, optionally filtered by prefix.

    Args:
        bucket_name: The GCS bucket name
        prefix: Optional prefix to filter results (e.g. 'papers/2024/')
    """
    try:
        bucket = gcs_client.bucket(bucket_name)
        blobs = bucket.list_blobs(prefix=prefix if prefix else None)

        documents = [
            {
                "name": blob.name,
                "size": blob.size,
                "content_type": blob.content_type,
                "updated": blob.updated.isoformat() if blob.updated else None
            }
            for blob in blobs
        ]

        return {"success": True, "bucket": bucket_name, "prefix": prefix, "documents": documents, "count": len(documents)}

    except Exception as e:
        logger.error(f"Error listing GCS documents: {e}")
        return {"error": str(e), "status": 500}


def query_firestore(collection: str, filter_field: str = "", filter_value: str = "", limit: int = 10) -> dict:
    """
    Query documents from Firestore collection with optional filtering.

    Args:
        collection: Collection name to query
        filter_field: Field name to filter on (optional)
        filter_value: Value to match (optional)
        limit: Max documents to return (default 10)
    """
    try:
        query = db_client.collection(collection)

        if filter_field and filter_value:
            query = query.where(filter_field, "==", filter_value)

        docs = query.limit(limit).stream()

        results = [{"id": doc.id, "data": doc.to_dict()} for doc in docs]

        return {"success": True, "collection": collection, "documents": results, "count": len(results)}

    except Exception as e:
        logger.error(f"Error querying Firestore: {e}")
        return {"error": str(e), "status": 500}


# ============================================================================
# AGENT SETUP — tools registered via FunctionTool
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting A2A Agent with MCP Tools")
    yield
    logger.info("Shutting down A2A Agent")


app = FastAPI(
    title="A2A Academic Agent with MCP Tools",
    description="Processes academic documents using MCP tool definitions",
    lifespan=lifespan
)

root_agent = Agent(
    name="academic_agent",
    model=os.environ.get("MODEL", "gemini-2.5-flash"),
    instruction="""You are an academic document processing assistant with access to specialized tools.

Your capabilities:
- Read and parse documents from Google Cloud Storage using read_gcs_document
- Extract structured metadata from academic papers using extract_academic_metadata
- Store results in Firestore using write_to_firestore
- List available documents using list_gcs_documents
- Query stored data using query_firestore

When the user requests document analysis:
1. Use read_gcs_document to fetch the document content
2. Use extract_academic_metadata to parse structured information
3. Use write_to_firestore to save results
4. Provide a clear summary of findings

Always use your tools to fulfill requests. Never say you cannot list documents — use list_gcs_documents.
Always be precise and cite specific information from documents.""",
    tools=[
        FunctionTool(read_gcs_document),
        FunctionTool(extract_academic_metadata),
        FunctionTool(write_to_firestore),
        FunctionTool(list_gcs_documents),
        FunctionTool(query_firestore),
    ]
)

session_service = InMemorySessionService()

agent_runner = Runner(
    agent=root_agent,
    app_name="academic_pipeline",
    session_service=session_service
)

# Tool metadata for the /tools endpoint
MCP_TOOLS_META = [
    {"name": "read_gcs_document", "description": "Read and parse a document from GCS bucket."},
    {"name": "extract_academic_metadata", "description": "Extract structured metadata from document content."},
    {"name": "write_to_firestore", "description": "Write extracted metadata to Firestore."},
    {"name": "list_gcs_documents", "description": "List all documents in a GCS bucket."},
    {"name": "query_firestore", "description": "Query documents from Firestore collection."},
]

# ============================================================================
# A2A PROTOCOL HELPERS
# ============================================================================


def build_a2a_response(text: str, request_id: str = None) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id or str(uuid.uuid4()),
        "result": {
            "messageId": str(uuid.uuid4()),
            "role": "agent",
            "parts": [{"type": "text", "text": text}]
        }
    }


def extract_task_id(payload: dict) -> str:
    return payload.get("id") or payload.get("taskId") or str(uuid.uuid4())


def extract_user_message(payload: dict) -> str:
    params = payload.get("params", {})
    if params:
        parts = params.get("message", {}).get("parts", [])
        if parts and isinstance(parts[0], dict):
            text = parts[0].get("text", "")
            if text:
                return text

    message_content = payload.get("message", "")
    if isinstance(message_content, dict):
        for path in [
            lambda m: m.get("content", {}).get("parts", []),
            lambda m: m.get("parts", []),
        ]:
            parts = path(message_content)
            if parts and isinstance(parts[0], dict):
                text = parts[0].get("text", "")
                if text:
                    return text

    return str(message_content) if message_content else ""


# ============================================================================
# AGENT EXECUTION
# ============================================================================


async def execute_agent_with_tools(user_input: str) -> str:
    """
    Execute the ADK agent. Tools are registered on the agent itself,
    so the runner handles all tool calls automatically.
    """
    try:
        session = session_service.create_session(
            app_name="academic_pipeline",
            user_id="cloud_run_environment"
        )

        user_content = types.Content(
            role="user",
            parts=[types.Part(text=user_input)]
        )

        response_text = ""

        async for event in agent_runner.run_async(
            user_id="cloud_run_environment",
            session_id=session.id,
            new_message=user_content
        ):
            # Capture final text response only
            if hasattr(event, 'is_final_response') and event.is_final_response():
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if hasattr(part, 'text') and part.text:
                            response_text += part.text

        return response_text or "Agent processed request without generating text output"

    except Exception as e:
        logger.error(f"Error in agent execution: {e}")
        return f"Error: {str(e)}"


# ============================================================================
# FASTAPI ENDPOINTS
# ============================================================================


@app.get("/")
async def health_check():
    return build_a2a_response(
        "Agent with MCP tools is ready. Available tools: " +
        ", ".join(t["name"] for t in MCP_TOOLS_META)
    )


@app.post("/parse_gcs_document")
async def parse_gcs_document(request: Request):
    task_id = None
    try:
        payload = await request.json()
        task_id = extract_task_id(payload)
        user_input = extract_user_message(payload)

        if not user_input:
            return JSONResponse(status_code=400, content=build_a2a_response("Error: No message content", task_id))

        agent_response = await execute_agent_with_tools(user_input)
        return build_a2a_response(agent_response, task_id)

    except Exception as e:
        logger.error(f"Error in parse_gcs_document: {e}")
        return JSONResponse(status_code=500, content=build_a2a_response(f"Error: {str(e)}", task_id or str(uuid.uuid4())))


@app.post("/process_message")
async def process_message(request: Request):
    task_id = None
    try:
        payload = await request.json()
        task_id = extract_task_id(payload)
        user_input = extract_user_message(payload)

        if not user_input:
            return JSONResponse(status_code=400, content=build_a2a_response("Error: No message content", task_id))

        agent_response = await execute_agent_with_tools(user_input)
        return build_a2a_response(agent_response, task_id)

    except Exception as e:
        logger.error(f"Error in process_message: {e}")
        return JSONResponse(status_code=500, content=build_a2a_response(f"Error: {str(e)}", task_id or str(uuid.uuid4())))


@app.get("/tools")
async def list_tools():
    return {"tools": MCP_TOOLS_META, "count": len(MCP_TOOLS_META)}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting A2A Agent with MCP Tools on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)