"""Real MCP subprocess/client/browser integration. No inference or API keys."""

import asyncio
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

try:
    from mcp import Client, StdioServerParameters
except ImportError:
    Client = None

from once_actions.server import Studio
from once_actions.skills import compile_skill


@unittest.skipIf(Client is None, "Install the mcp extra")
class MCPTests(unittest.TestCase):
    def test_client_calls_browser_tool_over_stdio(self):
        skill = compile_skill(
            "create_request",
            ["customer", "request", "priority"],
            [
                {
                    "action": "fill",
                    "target": {"role": "textbox", "name": "Customer"},
                    "parameter": "customer",
                },
                {"action": "fill", "target": {"role": "textbox", "name": "Request"}, "parameter": "request"},
                {
                    "action": "select",
                    "target": {"role": "combobox", "name": "Priority"},
                    "parameter": "priority",
                },
                {"action": "click", "target": {"role": "button", "name": "Save request"}},
            ],
        )
        with Studio() as server, tempfile.TemporaryDirectory() as folder:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            path = Path(folder) / "skill.json"
            path.write_text(json.dumps(skill))

            async def scenario():
                spec = StdioServerParameters(
                    command=sys.executable,
                    args=[
                        "-m",
                        "once_actions",
                        "mcp",
                        str(path),
                        "--url",
                        server.origin + "/app?layout=reordered",
                    ],
                )
                async with Client(spec) as client:
                    listed = await client.list_tools()
                    self.assertEqual([tool.name for tool in listed.tools], ["create_request"])
                    self.assertFalse(listed.tools[0].input_schema["additionalProperties"])
                    values = {
                        "customer": "MCP customer",
                        "request": "Called through stdio",
                        "priority": "urgent",
                    }
                    result = await client.call_tool("create_request", values)
                    self.assertFalse(result.is_error, result)
                    self.assertEqual(result.structured_content["status"], "executed")
                    self.assertEqual(server.records, [values])
                    invalid = await client.call_tool(
                        "create_request", {**values, "url": "https://example.com"}
                    )
                    self.assertTrue(invalid.is_error)
                    self.assertEqual(server.records, [values])

            try:
                asyncio.run(scenario())
            finally:
                server.shutdown()
                thread.join()
