"""Acceptance on unmodified third-party app UIs, with app state checked separately."""

import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect

from once_actions.recorder import Recorder
from once_actions.runner import execute

try:
    from sqlite_web import sqlite_web
    from werkzeug.serving import make_server
except ImportError:
    sqlite_web = None


class QuietFiles(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class ExternalAppTests(unittest.TestCase):
    def teach(self, name, url, example, drive, remember=False):
        recorder = Recorder()
        recorder.start(
            name,
            url,
            example,
            {"kind": "parameter", "value": next(iter(example))},
            headless=True,
            drive=drive,
            remember=remember,
        )
        recorder.thread.join(timeout=20)
        self.assertEqual(recorder.snapshot()["status"], "review", recorder.snapshot())
        self.recorded_state = recorder.browser_state
        return recorder.result

    def test_unmodified_todomvc_enter_submission(self):
        folder = Path(__file__).parent / "vendor" / "todomvc"
        manifest = json.loads((folder / "provenance.json").read_text())
        for name, entry in manifest["files"].items():
            self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), entry["sha256"])
        with ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietFiles, directory=str(folder))) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:

                def drive(page):
                    page.get_by_placeholder("What needs to be done?", exact=True).fill("Demonstrated task")
                    page.get_by_placeholder("What needs to be done?", exact=True).press("Enter")
                    expect(page.get_by_text("Demonstrated task", exact=True)).to_be_visible()

                skill = self.teach(
                    "add_todo",
                    f"http://127.0.0.1:{server.server_port}/",
                    {"task": "Demonstrated task"},
                    drive,
                    remember=True,
                )
                self.assertEqual([s["action"] for s in skill["steps"]], ["fill", "press"])
                states = []
                result = execute(
                    skill,
                    {"task": "Different task"},
                    storage_state=self.recorded_state,
                    save_state=states.append,
                )
                self.assertEqual(result["status"], "verified", result)
                # This upstream ES6 build deliberately stores todos only in JS memory.
                # Its result establishes UI execution, not durable application storage.
                self.assertEqual(states[-1]["origins"], [])
            finally:
                server.shutdown()
                thread.join()

    @unittest.skipIf(sqlite_web is None, "Install the integration extra")
    def test_sqlite_web_writes_exact_row_through_its_native_form(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "external.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE notes (body TEXT NOT NULL)")
            sqlite_web.datasets.clear()
            sqlite_web.initialize_app([str(path)])
            sqlite_web.app.config["SECRET_KEY"] = "local-acceptance-test-only"
            server = make_server("127.0.0.1", 0, sqlite_web.app, threaded=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:

                def drive(page):
                    page.get_by_label("body", exact=True).fill("Demonstrated note")
                    page.get_by_role("button", name="Insert", exact=True).click()
                    expect(page.get_by_text("Demonstrated note", exact=True)).to_be_visible()

                skill = self.teach(
                    "insert_note",
                    f"http://127.0.0.1:{server.server_port}/notes/insert/",
                    {"note": "Demonstrated note"},
                    drive,
                )
                result = execute(skill, {"note": "A different persisted note"})
                self.assertEqual(result["status"], "verified", result)
                with sqlite3.connect(path) as db:
                    rows = db.execute("SELECT body FROM notes ORDER BY rowid").fetchall()
                self.assertEqual(rows, [("Demonstrated note",), ("A different persisted note",)])
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                for dataset in sqlite_web.datasets.values():
                    dataset._database.close()
                sqlite_web.datasets.clear()
