# MCP Browser Storage

Optional MCP server that exposes **browser_get_storage** and **browser_navigate** so the agent can read `localStorage` and `sessionStorage` from a browser (e.g. to inspect a Home Assistant access token).

This is a **separate browser instance** from the Cursor in-IDE tab. You navigate this browser to your HA URL, log in once, then the agent can call `browser_get_storage` to read storage.

## Setup

1. **Install dependencies** (from this directory):
   ```bash
   npm install
   ```
2. **Install Playwright browsers** (first time only):
   ```bash
   npx playwright install chromium
   ```
3. **Add to Cursor MCP config**  
   This project's config at [.cursor/mcp.json](../.cursor/mcp.json) includes `browser_storage` with a relative path (`mcp-browser-storage/index.js`). Cursor runs with the repo as workspace root, so that path works. To use a full path instead (e.g. if the server fails to start), add to your MCP config:
   ```json
   "browser_storage": {
     "command": "node",
     "args": ["/full/path/to/APEX/mcp-browser-storage/index.js"]
   }
   ```

## Tools

- **browser_navigate** – Navigate the MCP browser to a URL (e.g. `http://homeassistant.local:8123`).
- **browser_login_ha** – Automatic Home Assistant login using **HA_URL**, **HA_USERNAME**, and **HA_PASSWORD** from `.env` (loaded from workspace root). Call this first, then **browser_get_storage** to read authenticated storage. Requires the three variables in `.env`.
- **browser_get_storage** – Returns `localStorage` and `sessionStorage` for the current page as JSON. For HA, call **browser_login_ha** first so the session is logged in.

## Persistent profile (optional)

To keep cookies/storage across restarts (so you don’t have to log in every time), set:

```bash
export MCP_BROWSER_USER_DATA_DIR="/path/to/a/directory"
```

Then configure Cursor to pass this env when starting the server, e.g. in `.cursor/mcp.json`:

```json
"browser_storage": {
  "command": "node",
  "args": ["/path/to/APEX/mcp-browser-storage/index.js"],
  "env": {
    "MCP_BROWSER_USER_DATA_DIR": "/path/to/browser-profile-dir"
  }
}
```

Use a directory that exists and is writable; Playwright will use it as the Chromium user data directory.

## See also

- [docs/browser-storage-read.md](../docs/browser-storage-read.md) – Full workflow and JS snippet for using the Playwright MCP directly.
