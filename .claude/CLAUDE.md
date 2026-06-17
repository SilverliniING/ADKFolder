# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ADKFolder** is a containerized FastAPI service that implements Google's **Agent-to-Agent (A2A) protocol** with JSON-RPC 2.0 format. It exposes an AI agent powered by Google's Agent Development Kit (ADK) and Gemini 2.5 Flash LLM to process academic data and extract structured information.

The service is designed to run on Google Cloud Run and integrates with Google Cloud services (Firestore for data storage, Cloud Storage for document parsing).

## Architecture

### Core Components

1. **FastAPI Server** (`agent.py`)
   - HTTP server listening on port 8080 (Cloud Run standard)
   - Implements A2A JSON-RPC 2.0 protocol for agent communication
   - Three main endpoints handle different agent tasks

2. **Agent Core**
   - Uses Google ADK's `adk.Agent` class with Gemini 2.5 Flash model
   - Runs on Vertex AI (via `GOOGLE_GENAI_USE_VERTEXAI=TRUE`)
   - Uses in-memory session management for request tracking
   - Agent runner processes messages asynchronously and streams responses back

3. **A2A Protocol Layer**
   - All inbound requests follow A2A JSON-RPC 2.0 format with `jsonrpc`, `id`, `method`, and `params` fields
   - All outbound responses wrap agent output in A2A `SendMessageSuccessResponse` schema
   - Response includes unique `messageId`, role as `"agent"` (not `"model"`), and typed `parts` array with discriminated union (type field mandatory)
   - Supports both standard A2A format and legacy nested formats via `extract_user_message()`

### Request/Response Flow

```
A2A JSON-RPC Request → extract_task_id() + extract_user_message()
                    ↓
            execute_agent_logic()
                    ↓
        agent_runner.run_async() (streams events)
                    ↓
        Collect response_text from event.content.parts
                    ↓
        build_a2a_response() (wraps in A2A format)
                    ↓
        A2A JSON-RPC Response
```

### Key Classes & Functions

- `build_a2a_response(text, request_id)` — Constructs A2A-compliant `SendMessageSuccessResponse` with unique messageId and typed parts
- `extract_task_id(payload)` — Extracts JSON-RPC request id to echo back in response
- `extract_user_message(payload)` — Parses user text from A2A format, with fallback for legacy nested schemas
- `execute_agent_logic(user_input)` — Runs the agent via ADK runner and collects streamed response

## Development Setup

### Prerequisites

- Python 3.11+ (Docker uses 3.11-slim)
- Google Cloud account with Vertex AI API enabled
- gcloud CLI configured
- Docker (for containerized testing and deployment)

### Local Development

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment variables** (copy from `.env` or set directly):
   ```bash
   export GOOGLE_GENAI_USE_VERTEXAI=TRUE
   export GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
   export GOOGLE_CLOUD_LOCATION="asia-south1"  # or your preferred region
   export MODEL="gemini-2.5-flash"
   ```

3. **Authenticate with GCP:**
   ```bash
   gcloud auth application-default login
   ```

## Common Commands

### Running Locally

**Start development server:**
```bash
python agent.py
```
Server runs on `http://localhost:8080`

**Test endpoints (after server starts):**
```bash
bash test.sh
```
Or manually:
```bash
curl -X POST http://localhost:8080/parse_gcs_document \
     -H "Content-Type: application/json" \
     -d '{"message": "Context: MIT professor Dr. Jones published a breakthrough paper on Room-Temperature Superconductors."}'
```

### Docker & Cloud Deployment

**Build Docker image locally:**
```bash
source ./shellConfig.sh
docker build -t ${IMAGE_PATH} .
```

**Run Docker image locally with GCP credentials:**
```bash
bash localDockerTesting.sh
```
This mounts your local GCP credentials into the container and exposes port 8080.

**Deploy to Cloud Run:**
```bash
bash deploy.sh
```
- Builds image with `docker buildx` for Linux/amd64
- Pushes to Artifact Registry in asia-south1
- Deploys to Cloud Run with unauthenticated access on port 3000

**Initial Cloud Run setup** (one-time):
```bash
bash cloudRunSetUp.sh
```
Creates Artifact Registry repository and configures Docker auth.

## Key Files & Responsibilities

| File | Purpose |
|------|---------|
| `agent.py` | Main FastAPI application; request/response handling; A2A protocol compliance |
| `requirements.txt` | Python dependencies (google-adk, fastapi, uvicorn, python-dotenv) |
| `Dockerfile` | Container image definition for Cloud Run deployment |
| `.env` | Environment variables (GCP project, model, region) |
| `shellConfig.sh` | Shared GCP config variables for shell scripts |
| `test.sh` | Manual curl tests for endpoints |
| `localDockerTesting.sh` | Docker build & run with local GCP credentials |
| `deploy.sh` | Full deployment pipeline (build, push, deploy to Cloud Run) |
| `cloudRunSetUp.sh` | One-time Artifact Registry setup |

## Important Patterns & Constraints

### A2A Protocol Compliance

- Every response **must** include `jsonrpc: "2.0"` and echo the inbound `id`
- Agent responses go in `result.parts[0].text`; the `role` **must be** `"agent"`, not `"model"`
- Every part in the response parts array **must** have a `type` discriminator field (e.g., `"text"`)
- The function `build_a2a_response()` handles all of this; use it for all responses

### Schema Flexibility

The `extract_user_message()` function handles both:
- **Standard A2A format:** `params.message.parts[0].text`
- **Legacy nested format:** `message.content.parts[0].text` or `message.parts[0].text`

This allows backward compatibility while transitioning to strict A2A compliance.

### Async Agent Execution

- `execute_agent_logic()` uses `async for` to stream events from `agent_runner.run_async()`
- Only events with `content.parts[].text` are collected
- Session is created per request (not reused); user_id is hardcoded to `"cloud_run_environment"`

### Environment Variables

- `MODEL` defaults to `"gemini-2.5-flash"` if not set
- `GOOGLE_GENAI_USE_VERTEXAI=TRUE` is required; without it, the agent won't use Vertex AI
- `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` are required for Vertex AI
- `PORT` defaults to `8080` but is overridden by Cloud Run

### Cloud Run Constraints

- Uses port 8080 in local dev; deploy script changes it to 3000 (check `deploy.sh` line 16)
- `--allow-unauthenticated` flag exposes the service publicly
- Health checks should return 200 on root `/` endpoint (currently returns A2A response)

## Current Development Branch

**Branch:** `feature.v1.A2AFormat`

This branch implements strict A2A protocol compliance with JSON-RPC 2.0. The agent card has been updated and the FastAPI wrapper with LLM integration is working. Future commits should ensure all responses follow the A2A `SendMessageSuccessResponse` schema exactly.

## Debugging Tips

- **Enable request logging:** Already logging in agent.py with `logger.info(f"Inbound payload: {payload}")` — check logs to debug schema mismatches
- **Test schema locally:** Use `test.sh` to verify endpoints before deploying
- **Check Vertex AI quota:** Large agent runs may hit quota limits; verify in GCP console
- **Docker credential issues:** If deploy.sh fails on docker push, re-run `gcloud auth configure-docker`
