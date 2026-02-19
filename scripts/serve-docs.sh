#!/usr/bin/env bash
# Serve Apex Brain docs locally and open in browser.
# Uses Zensical (Material team's successor to MkDocs); falls back to mkdocs if needed.
# Install: pip install -r requirements-docs.txt  (or: pip install zensical)

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
URL="http://127.0.0.1:8000/"
PORT=8000

# Prefer Zensical (reads mkdocs.yml); fall back to mkdocs
if command -v zensical &>/dev/null; then
  SERVER=zensical
elif [[ -x "$HOME/Library/Python/3.9/bin/zensical" ]]; then
  SERVER="$HOME/Library/Python/3.9/bin/zensical"
elif command -v mkdocs &>/dev/null; then
  SERVER=mkdocs
elif [[ -x "$HOME/Library/Python/3.9/bin/mkdocs" ]]; then
  SERVER="$HOME/Library/Python/3.9/bin/mkdocs"
else
  echo "No docs server found. Install Zensical: pip install -r requirements-docs.txt"
  exit 1
fi

cd "$REPO_ROOT"

# Kill any process already using the port (e.g. leftover mkdocs)
OLD_PID=$(lsof -ti :$PORT 2>/dev/null)
if [[ -n "$OLD_PID" ]]; then
  echo "Stopping process on port $PORT (PID $OLD_PID)..."
  kill $OLD_PID 2>/dev/null || true
  sleep 1
fi

# Start server in background
echo "Starting docs server ($SERVER)..."
$SERVER serve &
SERVER_PID=$!
trap "kill $SERVER_PID 2>/dev/null" EXIT

# Wait for server to be ready
echo -n "Waiting for server"
for i in {1..30}; do
  if curl -s -o /dev/null -w "" "http://127.0.0.1:$PORT/" 2>/dev/null; then
    echo " ready."
    break
  fi
  sleep 0.5
  echo -n "."
  if [[ $i -eq 30 ]]; then
    echo " timeout."
    exit 1
  fi
done

# Open browser
if [[ "$(uname)" == "Darwin" ]]; then
  open "$URL"
elif command -v xdg-open &>/dev/null; then
  xdg-open "$URL"
else
  echo "Docs at: $URL"
fi

echo "Docs served at $URL (Ctrl+C to stop)"
wait $SERVER_PID
