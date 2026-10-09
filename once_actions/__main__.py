import argparse
import asyncio
import json
import sys
from pathlib import Path

from .runner import execute
from .server import Studio
from .skills import tool_schema, validate


def main():
    parser = argparse.ArgumentParser(description="Teach a browser task. Run it as a tool.")
    commands = parser.add_subparsers(dest="command", required=True)
    studio = commands.add_parser("studio")
    studio.add_argument("--port", type=int, default=8780)
    for name in ("run", "tool", "mcp"):
        command = commands.add_parser(name)
        command.add_argument("skill", type=Path)
        if name in ("run", "mcp"):
            command.add_argument("--url", required=True)
        if name == "run":
            command.add_argument("--parameters", type=Path, required=True)
            command.add_argument("--show-browser", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "studio":
            with Studio(args.port) as server:
                print("Once Actions: " + server.origin, flush=True)
                server.serve_forever()
        else:
            if args.skill.stat().st_size > 100000:
                raise ValueError("Skill file exceeds 100 KB")
            skill = validate(json.loads(args.skill.read_text()))
            if args.command == "tool":
                print(json.dumps(tool_schema(skill), indent=2))
            elif args.command == "mcp":
                try:
                    from .mcp_server import serve
                except ImportError:
                    raise ValueError("Install the MCP extra: pip install '.[mcp]'") from None

                asyncio.run(serve(skill, args.url))
            else:
                if args.parameters.stat().st_size > 100000:
                    raise ValueError("Parameter file exceeds 100 KB")
                result = execute(
                    skill, json.loads(args.parameters.read_text()), args.url, headless=not args.show_browser
                )
                print(json.dumps(result, indent=2))
                return 0 if result["status"] == "executed" else 2
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
