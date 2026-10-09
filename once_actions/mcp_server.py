"""Expose one reviewed skill and fixed application URL over MCP stdio."""

import asyncio
import copy
import json
import threading

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .runner import execute, local_origin
from .skills import SkillError, tool_schema, validate


def create_server(skill, url):
    skill = copy.deepcopy(validate(skill))
    local_origin(url)
    schema = tool_schema(skill)
    # Lock belongs to the worker, so cancellation cannot admit a second browser
    # while the first is still finishing. A tool error is never automatically retried.
    lock = threading.Lock()

    def run(arguments):
        if not lock.acquire(blocking=False):
            return {"status": "busy", "reason": "An execution is already in progress. Do not retry blindly."}
        try:
            return execute(skill, arguments, url)
        except SkillError:
            return {"status": "invalid", "reason": "Supply exactly the declared string parameters."}
        finally:
            lock.release()

    async def list_tools(context, params):
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=skill["name"],
                    inputSchema=schema["parameters"],
                    description="Run a user-demonstrated workflow on a fixed local application. "
                    "May write data. Do not retry after partial execution without checking application state.",
                    annotations=types.ToolAnnotations(
                        readOnlyHint=False,
                        destructiveHint=True,
                        idempotentHint=False,
                        openWorldHint=False,
                    ),
                )
            ]
        )

    async def call_tool(context, params):
        if params.name != skill["name"]:
            result = {"status": "invalid", "reason": "Unknown tool."}
        else:
            result = await asyncio.to_thread(run, params.arguments)
        return types.CallToolResult(
            content=[types.TextContent(text=json.dumps(result))],
            structuredContent=result,
            isError=result["status"] != "executed",
        )

    return Server("once-actions", version="0.1.0", on_list_tools=list_tools, on_call_tool=call_tool)


async def serve(skill, url):
    server = create_server(skill, url)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
