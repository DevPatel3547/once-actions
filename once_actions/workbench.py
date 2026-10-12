"""Local personal workbench. Persistent library, explicit recording and run jobs."""

import json
import secrets
import sqlite3
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .recorder import Recorder
from .runner import execute, validate_parameters
from .scope import application_origin
from .server import ASSETS
from .server import Handler as DemoHandler
from .skills import SkillError, correct_target, validate
from .store import Conflict, Store


class Workbench(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, directory, port=8780):
        self.store = Store(directory)
        self.recorder = Recorder()
        self.token = secrets.token_urlsafe(32)
        self.records, self.lock = [], threading.Lock()
        self.jobs = {}
        self.jobs_lock = threading.Lock()
        self.saved_recording = None
        self.storage_failed = False
        self.failed_runs = {}
        try:
            super().__init__(("127.0.0.1", port), Handler)
        except Exception:
            self.store.close()
            raise

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server_port}"

    def check_url(self, url):
        origin = application_origin(url)
        if origin == self.origin and urlsplit(url).path != "/app":
            raise SkillError("The workbench itself cannot be an automation target")

    def start_run(self, run_id, skill_id, revision, parameters):
        if self.storage_failed:
            raise Conflict("The run journal could not be saved. Check disk space and restart before new runs")
        saved = self.store.get(skill_id, revision)
        if saved["skill"]["schema"] != "once-actions/v2":
            raise SkillError("The workbench requires a v2 workflow with an outcome check")
        self.check_url(saved["skill"]["start_url"])
        validate_parameters(saved["skill"], parameters)
        parameters = dict(parameters)
        if self.store.claim(run_id, saved, parameters):
            cancel = threading.Event()

            def run():
                try:
                    state = self.store.browser_state(skill_id)
                    result = execute(
                        saved["skill"],
                        parameters,
                        cancel=cancel,
                        storage_state=state,
                        save_state=(lambda value: self.store.save_browser_state(skill_id, value))
                        if state is not None
                        else None,
                    )
                except Exception:  # noqa: BLE001 -- worker boundary must journal unexpected failures
                    result = {
                        "status": "interrupted",
                        "reason": "An unexpected execution error occurred. Check application state before another run.",
                        "effects_possible": True,
                    }
                finally:
                    parameters.clear()
                try:
                    self.store.finish(run_id, result)
                except sqlite3.Error:
                    self.storage_failed = True
                    self.failed_runs[run_id] = {
                        "id": run_id,
                        "skill_id": skill_id,
                        "revision": revision,
                        "status": "storage_failed",
                        "result": {
                            "reason": "The run journal could not be saved. Check application state and disk space, then restart. Do not repeat the write blindly.",
                            "effects_possible": True,
                        },
                    }
                finally:
                    with self.jobs_lock:
                        self.jobs.pop(run_id, None)

            thread = threading.Thread(target=run, daemon=True)
            with self.jobs_lock:
                self.jobs[run_id] = (cancel, thread)
            thread.start()
        return self.store.run(run_id)

    def run_status(self, run_id):
        return self.failed_runs.get(run_id) or self.store.run(run_id)

    def server_close(self):
        self.recorder.close()
        with self.jobs_lock:
            jobs = list(self.jobs.values())
        for cancel, _ in jobs:
            cancel.set()
        for _, thread in jobs:
            thread.join()
        super().server_close()
        self.store.close()


class Handler(DemoHandler):
    def end_headers(self):
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        if urlsplit(self.path).path != "/app":
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'",
            )
        super().end_headers()

    def do_GET(self):
        if not self.valid_host():
            return
        parsed = urlsplit(self.path)
        try:
            if parsed.path == "/":
                self.send((ASSETS / "workbench.html").read_bytes(), content_type="text/html; charset=utf-8")
            elif parsed.path in ("/workbench.js", "/workbench.css"):
                self.send(
                    (ASSETS / parsed.path[1:]).read_bytes(),
                    content_type="text/javascript; charset=utf-8"
                    if parsed.path.endswith(".js")
                    else "text/css; charset=utf-8",
                )
            elif parsed.path == "/api/bootstrap":
                self.send(
                    {"token": self.server.token, "demo_url": self.server.origin + "/app", "version": "0.2.0"}
                )
            elif parsed.path == "/api/library":
                items = self.server.store.list_skills()
                for item in items:
                    item["remembers_browser"] = self.server.store.browser_state(item["id"]) is not None
                self.send(items)
            elif parsed.path == "/api/history":
                rows = self.server.store.list_runs()
                self.send([{**row, **self.server.failed_runs.get(row["id"], {})} for row in rows])
            elif parsed.path == "/api/recording":
                state = self.server.recorder.snapshot()
                if self.server.saved_recording and state["status"] == "review":
                    state["status"] = "saved"
                self.send(state)
            elif parsed.path == "/api/job":
                self.send(self.server.run_status(parse_qs(parsed.query).get("id", [None])[0]))
            elif parsed.path == "/health":
                self.send(
                    {"status": "storage_failed" if self.server.storage_failed else "ok", "version": "0.2.0"},
                    503 if self.server.storage_failed else 200,
                )
            elif parsed.path in ("/app", "/capture.js", "/api/requests"):
                super().do_GET()
            else:
                self.send({"error": "Not found"}, 404)
        except SkillError as exc:
            self.send({"error": str(exc)}, 404)
        except sqlite3.Error:
            self.send({"error": "The local library is unavailable. Check disk space and restart."}, 503)

    def do_POST(self):
        if not self.valid_host():
            return
        path = urlsplit(self.path).path
        # The owned demo's data endpoint stays separate from all control APIs.
        if path == "/api/requests":
            return super().do_POST()
        if self.headers.get("Origin") not in (None, self.server.origin):
            return self.send({"error": "Wrong origin"}, 403)
        if not secrets.compare_digest(self.headers.get("X-Once-Token", ""), self.server.token):
            return self.send({"error": "Reload the workbench to refresh its control token"}, 403)
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.send({"error": "JSON required"}, 415)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 100_000:
                raise SkillError("Request body must be 1–100000 bytes")
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise SkillError("A JSON object is required")
            if path == "/api/record/start":
                self.server.check_url(data["url"])
                if type(data.get("remember", False)) is not bool:
                    raise SkillError("Browser-state preference must be true or false")
                started = self.server.recorder.start(
                    data["name"],
                    data["url"],
                    data["examples"],
                    data["success"],
                    remember=data.get("remember", False),
                )
                self.server.saved_recording = None
                self.send(started)
            elif path == "/api/record/arm":
                self.send(self.server.recorder.arm())
            elif path == "/api/record/finish":
                self.send(self.server.recorder.finish())
            elif path == "/api/record/save":
                if self.server.recorder.snapshot()["status"] != "review" or not self.server.recorder.result:
                    raise SkillError("Finish and review a valid recording before saving")
                with self.server.recorder.lock:
                    skill = self.server.recorder.result
                    if data.get("hash") != skill["hash"]:
                        raise Conflict("The recording changed. Review it again before saving")
                    if self.server.saved_recording:
                        self.send(self.server.saved_recording)
                    else:
                        saved = self.server.store.save(
                            skill, browser_state=self.server.recorder.browser_state
                        )
                        if self.server.recorder.browser_state is not None:
                            self.server.recorder.browser_state = None
                        self.server.saved_recording = saved
                        self.send(saved, 201)
            elif path == "/api/skills/forget-session":
                if any(row["status"] == "running" for row in self.server.store.list_runs()):
                    raise Conflict("Wait for the active run before clearing browser state")
                self.server.store.forget_browser_state(data["id"])
                self.send({"forgotten": True})
            elif path == "/api/skills/import":
                skill = validate(data)
                if skill["schema"] != "once-actions/v2":
                    raise SkillError("Import a v2 workflow; v1 files still work with the CLI")
                self.server.check_url(skill["start_url"])
                self.send(self.server.store.save(skill), 201)
            elif path == "/api/skills/correct":
                saved = self.server.store.get(data["id"], data["revision"])
                corrected = correct_target(saved["skill"], data["index"], data["target"])
                self.send(self.server.store.save(corrected, data["id"], data["revision"]), 201)
            elif path == "/api/runs":
                self.send(
                    self.server.start_run(data["id"], data["skill_id"], data["revision"], data["parameters"]),
                    202,
                )
            elif path == "/api/runs/cancel":
                with self.server.jobs_lock:
                    job = self.server.jobs.get(data["id"])
                    if job:
                        job[0].set()
                self.send(self.server.store.run(data["id"]))
            else:
                self.send({"error": "Not found"}, 404)
        except Conflict as exc:
            self.send({"error": str(exc)}, 409)
        except SkillError as exc:
            self.send({"error": str(exc)}, 400)
        except (ValueError, KeyError, TypeError):
            self.send({"error": "Invalid request fields"}, 400)
        except sqlite3.Error:
            self.send({"error": "The local library could not be saved. Check disk space and restart."}, 503)
