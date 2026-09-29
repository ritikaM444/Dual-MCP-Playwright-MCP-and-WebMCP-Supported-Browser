"""
Phase 2 step 2: the capability-check script (Python port).

Injected into the current page via Playwright's page.evaluate -- the
string below is *browser-side* JavaScript, not Python; it has to be JS
because it runs inside the page's own JS context, not our Python
process. See polyfill/webmcp-polyfill.js for why getTools()/callTool()
exist even though they're not (yet) part of the official WebMCP spec.

Detection deliberately checks for getTools specifically (our own
addition) rather than just `document.modelContext`, so that a future
real-browser implementation that only has registerTool() and no
discovery surface yet still correctly reports "not usable by an
external agent" rather than a false positive.
"""
from __future__ import annotations

from typing import Any

from playwright.async_api import Page

_CHECK_JS = """
() => {
  const mc = document.modelContext;
  if (!mc || typeof mc.getTools !== "function") {
    return { supported: false, tools: [] };
  }
  try {
    const tools = mc.getTools();
    const list = Array.isArray(tools) ? tools : [];
    return { supported: list.length > 0, tools: list };
  } catch {
    return { supported: false, tools: [] };
  }
}
"""


async def check_webmcp_capability(page: Page) -> dict[str, Any]:
    """Returns {"supported": bool, "tools": [...]} for the page currently loaded in `page`."""
    return await page.evaluate(_CHECK_JS)
