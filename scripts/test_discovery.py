import sys
import os
import asyncio
from pathlib import Path

# Add apex_brain to sys.path
# We assume this script is in scripts/ directory, so we need to go up one level and then into apex_brain
# Actually, the user instruction says "Add apex_brain to sys.path".
# Since the project root is `c:/Users/stayd/Documents/GitHub/APEX` and `apex_brain` is a subdirectory,
# we should add the project root to sys.path so we can import `apex_brain.brain` etc.
# However, the structure is `apex_brain/brain/...`, so if we want to import `brain.config`,
# we likely need to add `apex_brain` directory itself to sys.path.

# Let's adjust sys.path to point to the `apex_brain` directory
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
apex_brain_dir = project_root / "apex_brain"

sys.path.append(str(apex_brain_dir))

# Import brain.config to load env
import brain.config

# Import the discover tool
from tools.generic import discover

async def main():
    print("Testing 'discover' tool...")
    
    # Test 1: Discover lights
    print("\n--- Discovering Lights ---")
    try:
        # calling discover with what="entities" and filter="light"
        result = await discover("entities", filter="light")
        print(result)
    except Exception as e:
        print(f"Error discovering lights: {e}")

    # Test 2: Discover info (System Info)
    print("\n--- Discovering System Info ---")
    try:
        result = await discover("info")
        print(result)
    except Exception as e:
        print(f"Error discovering info: {e}")

if __name__ == "__main__":
    asyncio.run(main())
