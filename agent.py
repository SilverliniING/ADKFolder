import os
from fastapi import FastAPI
from google.adk import Agent
from google.adk.tools import google_search

app = FastAPI()

# 1. Instantiate your ADK Agent 
research_agent = Agent(
    name="analysis_agent",
    model=os.environ.get("MODEL", "gemini-1.5-flash"),
    instruction="You analyze research material and format specific insights.",
    tools=[google_search]
)

# 2. Expose an endpoint that matches the A2A platform expectations
@app.post("/parse_gcs_document")
async def run_agent_task(payload: dict):
    # Your agent runtime logic executes here
    response = research_agent.run(payload.get("message"))
    return {"status": "success", "output": response}

if __name__ == "__main__":
    import uvicorn
    # Cloud Run dynamically assigns a PORT environment variable at runtime
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)