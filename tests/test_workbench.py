import json
import sqlite3
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from playwright.sync_api import expect, sync_playwright

from once_actions.recorder import Recorder
from once_actions.runner import execute
from once_actions.skills import compile_workflow
from once_actions.workbench import Workbench


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.server = Workbench(self.directory.name, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def request(self, path, data=None, token=True):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Once-Token"] = self.server.token
        req = Request(
            self.server.origin + path,
            data=None if data is None else json.dumps(data).encode(),
            headers=headers,
        )
        with urlopen(req) as response:
            return json.load(response)

    def taught(self):
        examples = {"customer": "River FC", "request": "Example request", "priority": "urgent"}

        def drive(page):
            page.get_by_label("Customer", exact=True).fill(examples["customer"])
            page.get_by_label("Request", exact=True).fill(examples["request"])
            page.get_by_label("Priority", exact=True).select_option("urgent")
            page.get_by_role("button", name="Save request", exact=True).click()
            expect(page.get_by_role("status")).to_have_text("Request saved")

        recorder = Recorder()
        recorder.start(
            "create_request",
            self.server.origin + "/app",
            examples,
            {"kind": "text", "value": "Request saved"},
            headless=True,
            drive=drive,
        )
        recorder.thread.join(timeout=15)
        self.assertEqual(recorder.snapshot()["status"], "review", recorder.snapshot())
        self.assertEqual(len(recorder.result["steps"]), 4)
        self.assertNotIn("River FC", json.dumps(recorder.result))
        return recorder.result

    def test_general_recording_replay_and_outcome(self):
        skill = self.taught()
        result = execute(skill, {"customer": "New customer", "request": "New task", "priority": "normal"})
        self.assertEqual(result["status"], "verified", result)
        self.assertEqual(self.server.records[-1]["customer"], "New customer")

    def test_durable_run_deduplicates_request_and_ui_import_export(self):
        skill = self.taught()
        saved = self.request("/api/skills/import", skill)
        payload = {
            "id": str(uuid.uuid4()),
            "skill_id": saved["id"],
            "revision": 1,
            "parameters": {"customer": "Only once", "request": "One request", "priority": "normal"},
        }
        before = len(self.server.records)
        self.request("/api/runs", payload)
        self.request("/api/runs", payload)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            job = self.request("/api/job?id=" + payload["id"])
            if job["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(job["status"], "verified", job)
        self.request("/api/runs", payload)
        self.assertEqual(len(self.server.records), before + 1)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.server.origin)
            page.get_by_role("button", name="create_request", exact=False).click()
            expect(page.locator("#skill-name")).to_have_text("create_request")
            expect(page.locator("#history")).to_contain_text("verified")
            with page.expect_download() as download:
                page.get_by_role("button", name="Export skill", exact=True).click()
            self.assertEqual(download.value.suggested_filename, "create_request.skill.json")
            page.set_viewport_size({"width": 390, "height": 844})
            self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
            self.assertEqual(errors, [])
            browser.close()

    def test_control_token_required_and_url_scope_fixed(self):
        with self.assertRaises(HTTPError) as result:
            self.request("/api/record/finish", {}, token=False)
        self.assertEqual(result.exception.code, 403)
        result.exception.close()
        skill = compile_workflow(
            "bad",
            ["value"],
            [{"action": "click", "target": {"role": "button", "name": "Run"}}],
            self.server.origin + "/",
            {"kind": "text", "value": "done"},
        )
        with self.assertRaises(HTTPError) as result:
            self.request("/api/skills/import", skill)
        self.assertEqual(result.exception.code, 400)
        result.exception.close()

    def test_unverified_is_not_success(self):
        skill = compile_workflow(
            "no_save",
            ["customer"],
            [{"action": "fill", "target": {"role": "textbox", "name": "Customer"}, "parameter": "customer"}],
            self.server.origin + "/app",
            {"kind": "text", "value": "Request saved"},
        )
        result = execute(skill, {"customer": "No saved result"})
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(self.server.records, [])

    def test_complete_interface_teach_run_correct_and_restart(self):
        recorder = self.server.recorder
        original_start = recorder.start
        demonstrated = threading.Event()

        def prepare(page):
            # This must be discarded when the user arms recording.
            page.get_by_label("Customer", exact=True).fill("Private setup value")
            deadline = time.monotonic() + 20
            while not recorder.armed.is_set() and time.monotonic() < deadline:
                page.wait_for_timeout(50)
            self.assertTrue(recorder.armed.is_set())

        def drive(page):
            page.get_by_label("Customer", exact=True).fill("River FC")
            page.get_by_label("Request", exact=True).fill("Update the match announcement")
            page.get_by_label("Priority", exact=True).select_option("urgent")
            page.get_by_role("button", name="Save request", exact=True).click()
            expect(page.get_by_role("status")).to_have_text("Request saved")
            demonstrated.set()
            deadline = time.monotonic() + 20
            while not recorder.stop.is_set() and time.monotonic() < deadline:
                page.wait_for_timeout(50)
            self.assertTrue(recorder.stop.is_set(), "UI did not finish recording")

        def start(*args, **kwargs):
            return original_start(*args, **kwargs, headless=True, prepare=prepare, drive=drive)

        with patch.object(recorder, "start", start), sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.server.origin)
            page.get_by_role("button", name="Teach my first workflow").click()
            page.get_by_role("button", name="Use the practice app").click()
            page.locator("#remember").check()
            page.get_by_role("button", name="Open recording browser").click()
            page.get_by_role("button", name="Start capturing").click(timeout=15000)
            self.assertTrue(demonstrated.wait(10))
            page.get_by_role("button", name="Finish recording").click()
            page.get_by_role("button", name="Save reviewed workflow").click(timeout=15000)
            expect(page.locator("#session-status")).to_contain_text("saved privately")
            saved = self.server.store.list_skills()[0]
            self.assertEqual(len(saved["skill"]["steps"]), 4)
            self.assertNotIn("Private setup value", json.dumps(saved))
            for name, value in {
                "customer": "Second customer",
                "request": "Second task",
                "priority": "normal",
            }.items():
                page.locator(f'#inputs input[data-parameter="{name}"]').fill(value)
            page.get_by_role("button", name="Run workflow", exact=True).click()
            expect(page.locator("#run-status")).to_contain_text("verified", timeout=20000)
            self.assertEqual(len(self.server.records), 2)
            self.assertEqual(self.server.records[-1]["customer"], "Second customer")
            page.get_by_text("Correct one target", exact=True).click()
            page.locator("#target-name").fill("Renamed customer")
            page.get_by_role("button", name="Save reviewed correction").click()
            expect(page.locator("#revision")).to_have_text("Revision 2")
            page.reload()
            page.get_by_role("button", name="create_client_request", exact=False).click()
            expect(page.locator("#teach")).to_be_hidden()
            expect(page.locator("#revision")).to_have_text("Revision 2")
            expect(page.locator("#history")).to_contain_text("verified")
            page.get_by_role("button", name="Forget saved browser state").click()
            expect(page.locator("#session-status")).to_contain_text("without saved cookies")
            self.assertEqual(self.server.store.get(saved["id"], 1)["skill"], saved["skill"])
            self.assertEqual(errors, [])
            browser.close()

    def test_journal_write_failure_stops_new_runs_and_exposes_uncertainty(self):
        skill = self.taught()
        saved = self.server.store.save(skill)
        run_id = str(uuid.uuid4())
        parameters = {"customer": "One write", "request": "Task", "priority": "normal"}
        with patch.object(self.server.store, "finish", side_effect=sqlite3.OperationalError("disk full")):
            self.server.start_run(run_id, saved["id"], 1, parameters)
            deadline = time.monotonic() + 15
            while not self.server.storage_failed and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(self.server.storage_failed)
            self.assertEqual(self.request("/api/job?id=" + run_id)["status"], "storage_failed")
            with self.assertRaises(HTTPError) as result:
                self.request(
                    "/api/runs",
                    {
                        "id": str(uuid.uuid4()),
                        "skill_id": saved["id"],
                        "revision": 1,
                        "parameters": parameters,
                    },
                )
            self.assertEqual(result.exception.code, 409)
            result.exception.close()
        self.assertEqual(len(self.server.records), 2)  # One teaching write, one execution.
