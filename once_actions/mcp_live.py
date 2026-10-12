"""MCP bridge to one immutable revision in the running local workbench."""

import asyncio
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .runner import local_origin
from .skills import SkillError, tool_schema, validate


def create_server(origin, skill_id, revision):
    if local_origin(origin) != origin:
        raise SkillError("Use the bare loopback workbench origin")

    def get(path):
        with urlopen(origin + path, timeout=10) as response:
            return json.load(response)

    token = get("/api/bootstrap")["token"]
    saved = next((item for item in get("/api/library") if item["id"] == skill_id), None)
    if saved is None or saved["revision"] != revision:
        raise SkillError("Choose the current reviewed skill revision when connecting")
    validate(saved["skill"])
    schema = tool_schema(saved["skill"])

    def call(arguments):
        if not isinstance(arguments, dict) or set(arguments) != {"run_id", "inputs"}:
            return {"status": "invalid", "reason": "Provide a UUID run_id and the named inputs object"}
        try:
            payload = {
                "id": arguments["run_id"],
                "skill_id": skill_id,
                "revision": revision,
                "parameters": arguments["inputs"],
            }
            request = Request(
                origin + "/api/runs",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "X-Once-Token": token},
            )
            with urlopen(request, timeout=10) as response:
                job = json.load(response)
            deadline = time.monotonic() + 145
            while job["status"] == "running" and time.monotonic() < deadline:
                time.sleep(0.2)
                job = get("/api/job?id=" + job["id"])
            return job
        except HTTPError as exc:
            status = exc.code
            exc.close()
            if status >= 500:
                return {
                    "status": "unknown",
                    "reason": "Workbench storage or server error. Inspect run history and application state. Reuse the same run ID and inputs; do not create another write blindly.",
                }
            return {
                "status": "rejected",
                "reason": f"Workbench rejected this request ({status}). Review inputs and active runs.",
            }
        except (URLError, TimeoutError, OSError):
            return {
                "status": "unknown",
                "reason": "Connection interrupted. Inspect run history. Reuse the same run ID and inputs to check without another execution.",
            }

    async def list_tools(context, params):
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=schema["name"],
                    description="Execute one reviewed browser workflow revision. May write data. "
                    "Use a new UUID for an intentional new run; reuse the exact same UUID and inputs after a connection failure. "
                    "A verified result means expected text appeared, not a guaranteed durable remote transaction.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "run_id": {
                                "type": "string",
                                "description": "Canonical UUID identifying this intentional run",
                            },
                            "inputs": schema["parameters"],
                        },
                        "required": ["run_id", "inputs"],
                        "additionalProperties": False,
                    },
                    annotations=types.ToolAnnotations(
                        readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False
                    ),
                )
            ]
        )

    async def call_tool(context, params):
        result = (
            await asyncio.to_thread(call, params.arguments)
            if params.name == schema["name"]
            else {"status": "invalid", "reason": "Unknown tool"}
        )
        return types.CallToolResult(
            content=[types.TextContent(text=json.dumps(result))],
            structuredContent=result,
            isError=result["status"] != "verified",
        )

    return Server("once-actions-library", version="0.2.0", on_list_tools=list_tools, on_call_tool=call_tool)


async def serve(origin, skill_id, revision):
    server = create_server(origin, skill_id, revision)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
