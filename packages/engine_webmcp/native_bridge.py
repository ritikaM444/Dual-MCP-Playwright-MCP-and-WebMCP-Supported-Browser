"""
Phase 2 step 3: the native bridge (Python port).

Given the page, a tool name, and arguments, invokes the page's
registered WebMCP tool and returns its structured JSON result. This is
Engine 1's equivalent of Engine 2's click/type/extract_text -- except
instead of simulating a DOM interaction, it calls straight into the
page's own JS via the modelContext registry, matching the spec's
"native function call" framing.
"""
from __future__ import annotations

from typing import Any, Optional

from playwright.async_api import Page

_CALL_JS = """
async ({ name, args }) => {
  const mc = document.modelContext;
  if (!mc || typeof mc.callTool !== "function") {
    return { ok: false, error: "document.modelContext.callTool is not available on this page" };
  }
  try {
    const result = await mc.callTool(name, args);
    return { ok: true, result };
  } catch (err) {
    return { ok: false, error: err && err.message ? String(err.message) : String(err) };
  }
}
"""


async def call_webmcp_tool(
    page: Page, name: str, args: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    return await page.evaluate(_CALL_JS, {"name": name, "args": args or {}})
