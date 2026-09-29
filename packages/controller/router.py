"""
Phase 3 step 1: the router.

On every navigate, re-run the Phase 2 capability check (BUILD_STEPS.md:
"a single task may cross both WebMCP-enabled and legacy pages" -- so the
engine selected for the LAST page is never assumed to still be correct).
Whichever engine this selects governs which actions are available until
the next navigate call.
"""
from __future__ import annotations

from playwright.async_api import Page

from engine_webmcp.capability_check import check_webmcp_capability

from .schema import ActionSchema, EngineName

# Engine 2's fixed action menu -- always available as the universal
# fallback, and the only menu available when a page has no WebMCP registry.
PLAYWRIGHT_ACTIONS: list[ActionSchema] = [
    ActionSchema(
        name="click",
        description="Click the first element matching a CSS selector.",
        input_schema={
            "type": "object",
            "properties": {"selector": {"type": "string"}},
            "required": ["selector"],
        },
        engine="playwright",
    ),
    ActionSchema(
        name="type",
        description="Type text into the first element matching a CSS selector.",
        input_schema={
            "type": "object",
            "properties": {"selector": {"type": "string"}, "text": {"type": "string"}},
            "required": ["selector", "text"],
        },
        engine="playwright",
    ),
    ActionSchema(
        name="extract_text",
        description="Extract visible text, optionally scoped to a CSS selector.",
        input_schema={
            "type": "object",
            "properties": {"selector": {"type": "string"}},
            "required": [],
        },
        engine="playwright",
    ),
    ActionSchema(
        name="screenshot",
        description="Take a PNG screenshot of the current page.",
        input_schema={"type": "object", "properties": {}, "required": []},
        engine="playwright",
    ),
]


async def select_engine(page: Page) -> tuple[EngineName, list[ActionSchema]]:
    """
    Runs the Phase 2 capability check against whatever page is currently
    loaded in `page` and returns which engine governs it, plus the action
    menu the agent should see for this specific page.
    """
    cap = await check_webmcp_capability(page)
    if cap["supported"]:
        webmcp_actions = [
            ActionSchema(
                name=tool["name"],
                description=tool.get("description", ""),
                input_schema=tool.get("inputSchema"),
                engine="webmcp",
            )
            for tool in cap["tools"]
        ]
        return "webmcp", webmcp_actions
    return "playwright", PLAYWRIGHT_ACTIONS
