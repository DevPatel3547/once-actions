"""Loopback-only product prototype and an owned request-entry app."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .runner import execute
from .skills import SkillError, compile_skill, tool_schema, validate

ASSETS = Path(__file__).parent / "assets"


class Studio(ThreadingHTTPServer):
    def __init__(self, port=0):
        self.records = []
        self.skill = None
        self.lock = threading.Lock()
        self.run_lock = threading.Lock()
        super().__init__(("127.0.0.1", port), Handler)

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, data, status=200, content_type="application/json"):
        body = json.dumps(data).encode() if content_type == "application/json" else data
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        if self.headers.get("Host") != urlsplit(self.server.origin).netloc:
            self.send({"error": "Wrong host"}, 403)
            return False
        return True

    def do_GET(self):
        if not self.valid_host():
            return
        path = urlsplit(self.path).path
        assets = {"/": "studio.html", "/app": "app.html", "/capture.js": "capture.js"}
        if path in assets:
            self.send(
                (ASSETS / assets[path]).read_bytes(),
                content_type=(
                    "text/javascript; charset=utf-8" if path.endswith(".js") else "text/html; charset=utf-8"
                ),
            )
        elif path == "/api/requests":
            with self.server.lock:
                self.send(self.server.records)
        elif path == "/api/skill":
            self.send(self.server.skill)
        elif path == "/api/tool":
            self.send(tool_schema(self.server.skill) if self.server.skill else None)
        else:
            self.send({"error": "Not found"}, 404)

    def do_POST(self):
        if not self.valid_host():
            return
        if self.headers.get("Origin") not in (None, self.server.origin):
            self.send({"error": "Wrong origin"}, 403)
            return
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.send({"error": "JSON required"}, 415)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 100_000:
                raise SkillError("Request body must be 1–100000 bytes")
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise SkillError("A JSON object is required")
            path = urlsplit(self.path).path
            if path == "/api/requests":
                if not isinstance(data, dict) or set(data) != {"customer", "request", "priority"}:
                    raise SkillError("Invalid request fields")
                if any(not isinstance(v, str) or not 1 <= len(v) <= 2000 for v in data.values()):
                    raise SkillError("Invalid field value")
                if data["priority"] not in ("normal", "urgent"):
                    raise SkillError("Invalid priority")
                with self.server.lock:
                    self.server.records.append(data)
                self.send({"saved": True}, 201)
            elif path == "/api/compile":
                skill = compile_skill(data["name"], data["parameters"], data["steps"])
                self.server.skill = skill
                self.send(skill)
            elif path == "/api/import":
                self.server.skill = validate(data)
                self.send(self.server.skill)
            elif path == "/api/run":
                layout = data.get("layout", "original")
                if layout not in ("original", "reordered", "columns", "renamed", "ambiguous"):
                    raise SkillError("Unknown application variation")
                if not self.server.skill:
                    raise SkillError("Teach or import a skill first")
                if not self.server.run_lock.acquire(blocking=False):
                    self.send({"error": "A run is already in progress"}, 409)
                    return
                try:
                    result = execute(
                        self.server.skill, data["parameters"], self.server.origin + "/app?layout=" + layout
                    )
                finally:
                    self.server.run_lock.release()
                self.send(result)
            else:
                self.send({"error": "Not found"}, 404)
        except (ValueError, KeyError, TypeError):
            self.send(
                {"error": "Invalid request or skill. Check parameter names and demonstrated targets."}, 400
            )
