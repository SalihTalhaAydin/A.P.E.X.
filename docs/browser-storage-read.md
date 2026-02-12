# Reading browser storage (e.g. HA access token) from Cursor

The **Cursor in-IDE browser** (the tab you open inside Cursor) cannot be inspected by the AI: there is no API to run JavaScript or read `localStorage` / `sessionStorage` in that tab. Storage can only be read from a **browser instance controlled by an MCP** (e.g. Playwright MCP or the custom browser-storage MCP).

## Option 1: Use the Playwright MCP

If you have the **Playwright MCP** enabled (e.g. in `~/.cursor/mcp.json`), use its browser:

1. **Open the Playwright browser** to your HA URL (e.g. `http://homeassistant.local:8123` or `http://192.168.68.113:8123`). You can ask the agent to run `browser_navigate` to that URL.
2. **Log in** to Home Assistant in that browser (once per session; the Playwright browser is usually ephemeral).
3. Ask the agent to **"read localStorage from the current page"** (or "read sessionStorage"). The agent should call `browser_evaluate` with the script below.

### JavaScript snippet for `browser_evaluate`

Use this in the Playwright MCP’s `browser_evaluate` to return all storage for the current origin:

```javascript
() => {
  const local = {};
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    local[k] = localStorage.getItem(k);
  }
  const session = {};
  for (let i = 0; i < sessionStorage.length; i++) {
    const k = sessionStorage.key(i);
    session[k] = sessionStorage.getItem(k);
  }
  return { localStorage: local, sessionStorage: session };
}
```

The result is a JSON-serializable object with `localStorage` and `sessionStorage` keys. Access tokens (e.g. for HA) may appear under keys like `auth_tokens` or similar, depending on the app.

**Limitation**: After restarting Cursor or the MCP, the Playwright browser starts fresh; you may need to log in again.

## Option 2: Custom browser-storage MCP (automatic HA login)

This repo includes an optional **mcp-browser-storage** server that exposes `browser_get_storage`, `browser_navigate`, and **browser_login_ha**. It loads `.env` from the workspace root. If **HA_URL**, **HA_USERNAME**, and **HA_PASSWORD** are set in `.env`, the agent can call **browser_login_ha** to log in automatically, then **browser_get_storage** to read storage—no manual login. See the [mcp-browser-storage README](../mcp-browser-storage/README.md) for setup.

## Security

Storage may contain access or refresh tokens. Prefer **long-lived tokens in `.env`** (see `.env.example`) for scripts and API use. Use storage read only when you need to inspect what the browser has (e.g. debugging or one-off export). Do not commit tokens or storage dumps.
