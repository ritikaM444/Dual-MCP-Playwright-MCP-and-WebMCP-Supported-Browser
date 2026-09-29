"""
Phase 1 standalone test -- NO LLM involved (BUILD_STEPS.md checkpoint).
Spawns server.py as a child process over stdio and drives it with a real
MCP client, calling tools directly against real sites to confirm
navigate -> extract_text (and click/type on a login form) round-trip
correctly before anything is built on top of Engine 2.

Site choices, and why (see project README "Demo site choices" for the
full rationale): the-internet.herokuapp.com is a QA-automation practice
site (built specifically to be automated against, so it won't move or
add anti-bot defenses) and Hacker News is a plain server-rendered page
with a stable, minimal DOM. Both avoid the bot-detection / CAPTCHA risk
that a live Google or DuckDuckGo search page could add on demo day.
Swap or extend this list once you've run it once and seen what happens.

Run with: python -m engine_playwright.test_client
"""
from __future__ import annotations

import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SITES = [
    {
        "url": "https://the-internet.herokuapp.com/",
        "selector": "h1",
        "note": "landing page -- sanity check for plain navigate + extract_text",
    },
    {
        "url": "https://the-internet.herokuapp.com/tables",
        "selector": "#table1",
        "note": "structured table -- stand-in for a multi-row data extraction task",
    },
    {
        "url": "https://news.ycombinator.com/",
        "selector": ".titleline",
        "note": "real-world news listing -- stable static markup",
    },
]


async def test_login_flow(session: ClientSession) -> None:
    print("\n--- login form: click + type round trip ---")
    await session.call_tool(
        "navigate", arguments={"url": "https://the-internet.herokuapp.com/login"}
    )
    await session.call_tool("type", arguments={"selector": "#username", "text": "tomsmith"})
    await session.call_tool(
        "type", arguments={"selector": "#password", "text": "SuperSecretPassword!"}
    )
    click_result = await session.call_tool(
        "click", arguments={"selector": "button[type='submit']"}
    )
    print("click:", click_result.content)
    extract = await session.call_tool("extract_text", arguments={"selector": "#flash"})
    print("post-login flash message:", extract.content)


async def main() -> None:
    server_params = StdioServerParameters(command="python", args=["-m", "engine_playwright.server"])

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("Tools exposed:", [t.name for t in tools.tools])

            for site in SITES:
                print(f"\n--- {site['url']}  ({site['note']}) ---")
                nav = await session.call_tool("navigate", arguments={"url": site["url"]})
                print("navigate:", nav.content)
                extract = await session.call_tool(
                    "extract_text", arguments={"selector": site["selector"]}
                )
                print("extract_text:", extract.content)

            await test_login_flow(session)

            shot = await session.call_tool("screenshot", arguments={})
            shot_len = len(shot.content[0].data) if shot.content else 0
            print(f"\nscreenshot: got {shot_len} base64 chars")


if __name__ == "__main__":
    asyncio.run(main())
