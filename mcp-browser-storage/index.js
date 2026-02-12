#!/usr/bin/env node
/**
 * MCP server: browser_get_storage, browser_navigate, browser_login_ha.
 * Reads localStorage and sessionStorage from the current page (e.g. HA for access token).
 * Loads .env from workspace root (process.cwd()) so HA_URL, HA_USERNAME, HA_PASSWORD can automate login.
 * Optional: set MCP_BROWSER_USER_DATA_DIR for a persistent profile so login survives restarts.
 */

import { chromium } from "playwright";
import { z } from "zod";
import { config as loadEnv } from "dotenv";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

// Load .env from workspace root (Cursor typically runs with cwd = repo root)
loadEnv({ path: `${process.cwd()}/.env` });

let context = null;
let page = null;

async function ensureBrowser() {
  if (page) return;
  const userDataDir = process.env.MCP_BROWSER_USER_DATA_DIR;
  if (userDataDir) {
    context = await chromium.launchPersistentContext(userDataDir, { headless: true });
  } else {
    const browser = await chromium.launch({ headless: true });
    context = await browser.newContext();
  }
  page = await context.newPage();
}

const GET_STORAGE_SCRIPT = `() => {
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
}`;

async function main() {
  const server = new McpServer(
    {
      name: "mcp-browser-storage",
      version: "1.0.0",
    }
  );

  server.registerTool(
    "browser_get_storage",
    {
      title: "Get browser storage",
      description:
        "Returns localStorage and sessionStorage for the current page. For Home Assistant: call browser_login_ha first (uses HA_URL, HA_USERNAME, HA_PASSWORD from .env) to log in automatically, then call this to read tokens or other storage.",
      inputSchema: z.object({}),
    },
    async () => {
      await ensureBrowser();
      if (!page) throw new Error("No page");
      try {
        const result = await page.evaluate(GET_STORAGE_SCRIPT);
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        };
      } catch (err) {
        const msg = err.message || String(err);
        return {
          content: [
            {
              type: "text",
              text: `Error: ${msg}. Ensure the page is loaded and not an auth redirect that blocks storage access.`,
            },
          ],
          isError: true,
        };
      }
    }
  );

  server.registerTool(
    "browser_navigate",
    {
      title: "Navigate browser",
      description:
        "Navigate the MCP browser to a URL (e.g. your Home Assistant URL). Use this before logging in and calling browser_get_storage.",
      inputSchema: z.object({
        url: z.string().describe("URL to open (e.g. http://homeassistant.local:8123)"),
      }),
    },
    async ({ url }) => {
      await ensureBrowser();
      if (!page) throw new Error("No page");
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
      const current = page.url();
      return {
        content: [
          {
            type: "text",
            text: `Navigated to ${url}. Current URL: ${current}. Log in if needed, then call browser_get_storage.`,
          },
        ],
      };
    }
  );

  server.registerTool(
    "browser_login_ha",
    {
      title: "Log in to Home Assistant",
      description:
        "Uses HA_URL, HA_USERNAME, and HA_PASSWORD from .env to navigate to HA and log in automatically. Call this before browser_get_storage to get authenticated storage. Requires .env in workspace root with those variables set.",
      inputSchema: z.object({}),
    },
    async () => {
      const haUrl = process.env.HA_URL;
      const username = process.env.HA_USERNAME;
      const password = process.env.HA_PASSWORD;
      if (!haUrl?.trim()) {
        return {
          content: [{ type: "text", text: "HA_URL is not set in .env. Add HA_URL (e.g. http://homeassistant.local:8123)." }],
          isError: true,
        };
      }
      if (!username?.trim() || !password) {
        return {
          content: [
            {
              type: "text",
              text: "HA_USERNAME and HA_PASSWORD must be set in .env for automatic login. Add them and try again.",
            },
          ],
          isError: true,
        };
      }
      await ensureBrowser();
      if (!page) throw new Error("No page");
      const baseUrl = haUrl.replace(/\/$/, "");
      try {
        await page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
        let url = page.url();
        if (url.includes("/auth/authorize") && !url.includes("auth_callback")) {
          await page.waitForSelector('input[type="password"], ha-textfield, [name="password"]', { timeout: 8000 }).catch(() => null);
          const userInput = await page.locator('input[type="text"], input[name="username"], ha-textfield[type="text"]').first();
          const passInput = await page.locator('input[type="password"], input[name="password"], ha-textfield[type="password"]').first();
          if ((await userInput.count()) && (await passInput.count())) {
            await userInput.fill(username);
            await passInput.fill(password);
            const submit = page.locator('button[type="submit"], input[type="submit"], ha-button[type="submit"], paper-button').first();
            await submit.click();
            await page.waitForURL((u) => !u.pathname.includes("/auth/authorize") || u.search.includes("auth_callback"), { timeout: 15000 }).catch(() => {});
          }
        }
        const current = page.url();
        const loggedIn = !current.includes("/auth/authorize") || current.includes("auth_callback");
        return {
          content: [
            {
              type: "text",
              text: loggedIn
                ? `Logged in to Home Assistant. Current URL: ${current}. You can call browser_get_storage to read storage.`
                : `Navigated to ${current}. Login form may have failed (wrong selectors or 2FA). Check .env (HA_URL, HA_USERNAME, HA_PASSWORD) and try again or log in manually in the browser.`,
            },
          ],
          ...(loggedIn ? {} : { isError: true }),
        };
      } catch (err) {
        const msg = err.message || String(err);
        return {
          content: [{ type: "text", text: `Error: ${msg}. Check HA_URL in .env and that HA is reachable.` }],
          isError: true,
        };
      }
    }
  );

  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("mcp-browser-storage running (stdio)");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
