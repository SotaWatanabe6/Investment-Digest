"""
MCP server exposing the pipeline's data-source and action tools to the
agents. Runs as a local stdio process launched by the orchestrator for the
duration of a single pipeline run (not a persistent hosted server — there's
no need for one, since only the GitHub Actions job ever calls it).

Tool scope (PRD Section 4.4, AI Product Decisions Stage 5):
  - get_filings, get_news, get_macro: read-only, no blast radius beyond
    an external API call.
  - send_email: the one write/action tool, hard-capped at 1 call/day
    in tools/email_tool.py itself — access control, not a prompt instruction.

Ingested content (news/filing text returned by these tools) is external and
untrusted. Agents receiving tool results are instructed via system prompt
(see prompts/) to treat that content strictly as data to analyze, never as
instructions to follow — basic prompt-injection mitigation appropriate to
this product's low blast radius (PRD Section 4, Stage 4 of AI Product
Decisions).
"""
from __future__ import annotations

import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from config import Config
from db import connect
from tools import edgar
from tools.email_tool import send_email
from tools.finnhub_adapter import FinnhubProvider

server = Server("watchlist-tool")
_config = Config.from_env()
_news_provider = FinnhubProvider(_config.finnhub_api_key)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_filings",
            description="Fetch SEC EDGAR filings (Form 4 buys/sells, 8-Ks) for a symbol since a date.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "since_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "until_date": {"type": "string", "description": "YYYY-MM-DD, optional upper bound"},
                },
                "required": ["symbol", "since_date"],
            },
        ),
        Tool(
            name="get_news",
            description="Fetch attributed news articles for a symbol since a date. Excludes social sentiment sources.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "since_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "max_articles": {"type": "integer", "default": 10},
                    "until_date": {"type": "string", "description": "YYYY-MM-DD, optional upper bound"},
                },
                "required": ["symbol", "since_date"],
            },
        ),
        Tool(
            name="get_macro",
            description="Fetch global/US/sector macro context relevant to a symbol.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "sector": {"type": "string"},
                    "since_date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": ["symbol", "since_date"],
            },
        ),
        Tool(
            name="send_email",
            description=(
                "Send the composed daily digest email. Hard-capped at 1 call/day, "
                "enforced in code — a second call in the same day always fails."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "html_body": {"type": "string"},
                },
                "required": ["subject", "html_body"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "get_filings":
        filings = edgar.get_filings(
            arguments["symbol"], arguments["since_date"], until_date=arguments.get("until_date")
        )
        result = [f.__dict__ for f in filings]
    elif name == "get_news":
        articles = _news_provider.get_news(
            arguments["symbol"],
            arguments["since_date"],
            arguments.get("max_articles", 10),
            until_date=arguments.get("until_date"),
        )
        result = [a.__dict__ for a in articles]
    elif name == "get_macro":
        snapshots = _news_provider.get_macro(
            arguments["symbol"], arguments.get("sector"), arguments["since_date"]
        )
        result = [s.__dict__ for s in snapshots]
    elif name == "send_email":
        conn = connect(_config)
        send_email(
            conn,
            _config.resend_api_key,
            _config.digest_to_email,
            _config.digest_from_email,
            arguments["subject"],
            arguments["html_body"],
        )
        result = {"sent": True}
    else:
        raise ValueError(f"Unknown tool: {name}")

    return [TextContent(type="text", text=json.dumps(result))]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
