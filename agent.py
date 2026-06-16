import os
from dotenv import load_dotenv
from google import adk

# Load local variables from .env if present
load_dotenv()

# We set the default fallback model to gemini-2.5-flash
root_agent = adk.Agent(
    name="analysis_agent",
    model=os.environ.get("MODEL", "gemini-2.5-flash"),
    instruction="""You are an academic data processing assistant. 
    Analyze the text context provided and extract: university, professor, topic, summary."""
)