"""
A2A Protocol Helpers

Functions for handling A2A JSON-RPC 2.0 protocol compliance:
- Building responses
- Extracting request IDs
- Parsing user messages from various formats
"""

import uuid
from typing import Any, Dict, Optional


def build_a2a_response(text: str, request_id: Optional[str] = None) -> dict:
    """
    Build an A2A-compliant JSON-RPC 2.0 SendMessageSuccessResponse.

    A2A Protocol Requirements:
    - jsonrpc: "2.0" (always)
    - id: echo the request id
    - result.parts: array of typed parts with discriminated union
    - result.parts[].type: discriminator field (required on all parts)
    - result.role: "agent" (never "model")
    - result.messageId: unique per response

    Args:
        text: The response text from the agent
        request_id: The request id to echo back

    Returns:
        A2A-compliant response dict
    """
    return {
        "jsonrpc": "2.0",
        "id": request_id or str(uuid.uuid4()),
        "result": {
            "messageId": str(uuid.uuid4()),
            "role": "agent",
            "parts": [
                {
                    "type": "text",
                    "text": text
                }
            ]
        }
    }


def extract_task_id(payload: dict) -> str:
    """
    Extract the JSON-RPC request id from the inbound payload.
    This id must be echoed back in the response.

    Args:
        payload: The inbound request payload

    Returns:
        The request ID, or a generated UUID if not found
    """
    task_id = payload.get("id") or payload.get("taskId")
    if not task_id:
        task_id = str(uuid.uuid4())
    return task_id


def extract_user_message(payload: dict) -> str:
    """
    Extract the user message from A2A format payload.
    Handles both standard A2A and legacy nested formats for compatibility.

    Standard A2A format:
        payload.params.message.parts[0].text

    Legacy nested formats:
        payload.message.content.parts[0].text
        payload.message.parts[0].text

    Args:
        payload: The inbound request payload

    Returns:
        The extracted user message text, or empty string if not found
    """
    # Try standard A2A format first: params.message.parts[0].text
    params = payload.get("params", {})
    if params:
        parts = params.get("message", {}).get("parts", [])
        if parts and isinstance(parts[0], dict):
            text = parts[0].get("text", "")
            if text:
                return text

    # Try legacy nested format: message.content.parts[0].text
    message_content = payload.get("message", "")
    if isinstance(message_content, dict):
        # Path 1: message.content.parts
        if "content" in message_content and "parts" in message_content["content"]:
            parts = message_content["content"]["parts"]
            if parts and isinstance(parts[0], dict):
                text = parts[0].get("text", "")
                if text:
                    return text

        # Path 2: message.parts (direct)
        elif "parts" in message_content:
            parts = message_content["parts"]
            if parts and isinstance(parts[0], dict):
                text = parts[0].get("text", "")
                if text:
                    return text

    # Fallback: treat raw message string as text
    return str(message_content) if message_content else ""
