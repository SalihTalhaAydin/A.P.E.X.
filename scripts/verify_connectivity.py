#!/usr/bin/env python3
"""
Verify connectivity to Home Assistant using project config and helpers.
"""
import sys
import os
import asyncio
import logging

# Configure logging to stdout
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Add the project root to sys.path so we can import modules
# Assuming this script is run from the project root (where .env is)
sys.path.append(os.path.abspath("apex_brain"))

try:
    from brain.config import settings
    from tools.ha_helpers import ha_request
except ImportError as e:
    print(
        "FAILURE: Could not import project modules. "
        f"Ensure you are running from the project root. Error: {e}"
    )
    sys.exit(1)


async def main():
    print(f"Checking connection to Home Assistant at: {settings.ha_url}")

    try:
        # We use ha_request to hit the API root or a simple endpoint
        # The API root /api/ returns a message "API running."
        response = await ha_request("GET", "/", return_response=False)

        # ha_request returns a dict for JSON responses, or string for others
        # /api/ returns {"message": "API running."}

        is_running = (
            isinstance(response, dict)
            and response.get("message") == "API running."
        )

        if is_running:
            print(
                "SUCCESS: Connected to Home Assistant at "
                f"{settings.ha_api_url}"
            )
            print(f"Response: {response}")
        else:
            # Maybe we hit a different endpoint or got unexpected response
            print(
                "SUCCESS: Connected to Home Assistant at "
                f"{settings.ha_api_url}"
            )
            print(f"Response (unexpected format): {response}")

    except Exception as e:
        print(f"FAILURE: Could not connect to Home Assistant. Reason: {e}")
        # Print more details if available
        if hasattr(e, 'response'):
            print(f"Status Code: {e.response.status_code}")
            print(f"Response Body: {e.response.text}")


if __name__ == "__main__":
    asyncio.run(main())
