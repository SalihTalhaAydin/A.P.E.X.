#!/bin/sh
# Copy app code into ha_addon/ so the HA App build has everything it needs.
# Run this before pushing if you changed brain/, memory/, tools/, or requirements.txt.
set -e
cd "$(dirname "$0")"
rm -rf ha_addon/brain ha_addon/memory ha_addon/tools
cp -r brain memory tools requirements.txt ha_addon/
echo "Synced brain/, memory/, tools/, requirements.txt into ha_addon/"
