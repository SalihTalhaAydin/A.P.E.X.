"""
Vision tool — Camera snapshot + AI analysis.
Fetches a snapshot from HA's camera proxy,
sends it to the LLM for vision analysis.
"""

import base64
import logging

import litellm
from brain.config import settings

from tools.base import tool
from tools.ha_helpers import get_ha_client, read_state

logger = logging.getLogger(__name__)


@tool(
    description=(
        "Look through a camera and describe what you see. "
        "Optionally answer a specific question about the image. "
        "Use discover(what='entities', filter_str='camera') "
        "to find available cameras first."
    ),
    parameters={
        "type": "object",
        "properties": {
            "camera_entity_id": {
                "type": "string",
                "description": (
                    "Camera entity ID, e.g. 'camera.front_door'"
                ),
            },
            "question": {
                "type": "string",
                "description": (
                    "Optional question about what you see. "
                    "If empty, gives a general description."
                ),
                "default": "",
            },
        },
        "required": ["camera_entity_id"],
    },
)
async def see(camera_entity_id: str, question: str = "") -> str:
    """Fetch camera snapshot and analyze with vision model."""
    # 1. Verify camera exists and is available
    try:
        state = await read_state(camera_entity_id)
        if isinstance(state, dict) and state.get("error"):
            return f"Camera error: {state['error']}"
        if isinstance(state, dict) and state.get("state") == "unavailable":
            name = state.get("attributes", {}).get(
                "friendly_name", camera_entity_id
            )
            return f"{name} is unavailable."
    except Exception as e:
        return f"Error accessing camera: {e}"

    # 2. Fetch snapshot from HA camera proxy
    client = await get_ha_client()
    proxy_url = f"{settings.ha_api_url}/camera_proxy/{camera_entity_id}"
    try:
        response = await client.get(proxy_url, headers=settings.ha_headers)
        if not response.is_success:
            return f"Error fetching snapshot: HTTP {response.status_code}"
        image_bytes = response.content
        content_type = response.headers.get("content-type", "image/jpeg")
    except Exception as e:
        return f"Error fetching camera snapshot: {e}"

    # 3. Base64 encode
    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    # 4. Build vision prompt
    prompt = (
        question
        if question
        else "Describe what you see in this camera image."
    )

    # 5. Call LLM with vision
    try:
        result = await litellm.acompletion(
            model=settings.litellm_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": (
                                    f"data:{content_type};"
                                    f"base64,{b64_image}"
                                ),
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
            max_tokens=500,
            temperature=0.3,
        )
        if result.choices:
            name = state.get("attributes", {}).get(
                "friendly_name", camera_entity_id
            )
            description = result.choices[0].message.content
            return f"[{name}] {description}"
        return "Vision analysis returned no response."
    except Exception as e:
        logger.error("Vision analysis failed: %s", e)
        return f"Vision analysis error: {e}"
