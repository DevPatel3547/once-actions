import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

from .runner import execute
from .skills import tool_schema, validate


def main():
    parser = argparse.ArgumentParser(description="Teach a browser task. Run it as a tool.")
    commands = parser.add_subparsers(dest="command", required=True)
    studio = commands.add_parser("studio")
    studio.add_argument("--port", type=int, default=8780)
    studio.add_argument("--data-dir", type=Path, default=Path.home() / ".local/share/once-actions")
    live = commands.add_parser("mcp-live", help="Connect one saved revision to the running workbench")
    live.add_argument("--studio", default="http://127.0.0.1:8780")
    live.add_argument("--skill-id", required=True)
    live.add_argument("--revision", type=int, required=True)
    commands.add_parser("doctor", help="Verify that Chromium can launch")
    backup_command = commands.add_parser("backup", help="Create a private, consistent SQLite backup")
    backup_command.add_argument("--data-dir", type=Path, default=Path.home() / ".local/share/once-actions")
    backup_command.add_argument("--output", type=Path, required=True)
    for name in ("run", "tool", "mcp"):
        command = commands.add_parser(name)
        command.add_argument("skill", type=Path)
        if name in ("run", "mcp"):
            command.add_argument("--url", help="Required for legacy v1 skills; v2 skills fix their own URL")
        if name == "run":
            command.add_argument("--parameters", type=Path, required=True)
            command.add_argument("--show-browser", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "studio":
            from .workbench import Workbench

            with Workbench(args.data_dir, args.port) as server:
                print("Once Actions: " + server.origin, flush=True)
                server.serve_forever()
        elif args.command in ("doctor", "backup"):
            from .maintenance import backup, doctor

            result = doctor() if args.command == "doctor" else backup(args.data_dir, args.output)
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "ok" else 2
        elif args.command == "mcp-live":
            try:
                from .mcp_live import serve
            except ImportError:
                raise ValueError("Install the MCP extra: pip install '.[mcp]'") from None
            asyncio.run(serve(args.studio, args.skill_id, args.revision))
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
                return 0 if result["status"] in ("executed", "verified") else 2
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except sqlite3.Error:
        print(
            "The local library could not be read or written. Check disk space, permissions, and your backup.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
