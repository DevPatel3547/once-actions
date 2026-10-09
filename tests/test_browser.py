"""Actual browser capture, compilation, execution, and server-state assertions.

No language model is involved. The taught trace comes from real browser events.
"""

import json
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from playwright.sync_api import expect, sync_playwright

from once_actions.runner import execute
from once_actions.server import Studio
from once_actions.skills import compile_skill

EXAMPLE = {"customer": "River FC", "request": "Update the match announcement", "priority": "urgent"}


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Studio()
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = cls.server.origin
        cls.skill = cls.teach()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    @classmethod
    def teach(cls, layout="original"):
        captured = []
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.expose_function("__onceCapture", lambda detail: captured.append(detail))
            page.goto(cls.origin + "/app?layout=" + layout)
            page.get_by_label("Account owner" if layout == "renamed" else "Customer", exact=True).fill(
                EXAMPLE["customer"]
            )
            page.get_by_label("Request", exact=True).fill(EXAMPLE["request"])
            page.get_by_label("Priority", exact=True).select_option(EXAMPLE["priority"])
            page.get_by_role("button", name="Save request", exact=True).click()
            expect(page.get_by_role("status")).to_have_text("Request saved")
            browser.close()
        steps = []
        for raw in captured:
            step = {"action": raw["action"], "target": raw["target"]}
            if "value" in raw:
                step["parameter"] = next(k for k, v in EXAMPLE.items() if v == raw["value"])
            steps.append(step)
        if len(steps) != 4:
            raise AssertionError(f"Expected three field changes and one save, got {steps}")
        return compile_skill("create_client_request", list(EXAMPLE), steps)

    def test_changed_values_layout_and_ids_produce_exact_record(self):
        for layout in ("original", "reordered", "columns"):
            with self.subTest(layout=layout):
                values = {
                    "customer": f"New customer {layout}",
                    "request": "<script>untrusted input</script>",
                    "priority": "normal",
                }
                before = len(self.server.records)
                result = execute(self.skill, values, self.origin + "/app?layout=" + layout)
                self.assertEqual(result["status"], "executed", result)
                self.assertEqual(result["model_calls"], 0)
                self.assertEqual(len(self.server.records), before + 1)
                self.assertEqual(self.server.records[-1], values)
                self.assertNotIn(values["request"], json.dumps(result))

    def test_missing_or_ambiguous_target_does_not_submit(self):
        for layout in ("renamed", "ambiguous"):
            with self.subTest(layout=layout):
                before = len(self.server.records)
                result = execute(self.skill, EXAMPLE, self.origin + "/app?layout=" + layout)
                self.assertEqual(result["status"], "needs_teaching")
                self.assertEqual(len(self.server.records), before)
                self.assertFalse(result["steps"][-1]["executed"])
                self.assertEqual(result["steps"][-1]["matches"], 0 if layout == "renamed" else 2)

    def test_new_demonstration_handles_renamed_field(self):
        repaired = self.teach("renamed")
        values = {**EXAMPLE, "customer": "Corrected workflow"}
        result = execute(repaired, values, self.origin + "/app?layout=renamed")
        self.assertEqual(result["status"], "executed", result)
        self.assertEqual(self.server.records[-1], values)
        self.assertNotEqual(repaired["hash"], self.skill["hash"])

    def test_export_does_not_contain_example_field_values(self):
        serialized = json.dumps(self.skill)
        for value in EXAMPLE.values():
            self.assertNotIn(value, serialized)

    def test_full_studio_flow_and_mobile(self):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(self.origin)
            page.get_by_role("button", name="Start teaching", exact=True).click()
            app = page.frame_locator("#app")
            app.get_by_label("Customer", exact=True).fill(EXAMPLE["customer"])
            app.get_by_label("Request", exact=True).fill(EXAMPLE["request"])
            app.get_by_label("Priority", exact=True).select_option("urgent")
            app.get_by_role("button", name="Save request", exact=True).click()
            expect(app.get_by_role("status")).to_have_text("Request saved")
            expect(page.locator("#count")).to_have_text("4 steps")
            page.get_by_role("button", name="Finish & learn", exact=True).click()
            expect(page.locator("#teaching-status")).to_contain_text("Skill compiled")
            page.get_by_label("Customer", exact=True).fill("Second customer")
            page.get_by_label("Request", exact=True).fill("Second request")
            page.get_by_label("Application layout").select_option("reordered")
            page.get_by_role("button", name="Run learned skill →", exact=True).click()
            expect(page.locator("#result")).to_contain_text("4 actions executed", timeout=15000)
            expect(app.locator("#records article").first).to_contain_text("Second customer")
            self.assertEqual(self.server.records[-1]["request"], "Second request")
            with page.expect_download() as download:
                page.get_by_role("button", name="Export skill", exact=True).click()
            exported = json.loads(Path(download.value.path()).read_text())
            self.assertEqual(exported["name"], "create_client_request")
            self.assertNotIn("River FC", json.dumps(exported))
            page.get_by_label("Application layout").select_option("ambiguous")
            before = len(self.server.records)
            page.get_by_role("button", name="Run learned skill →", exact=True).click()
            expect(page.locator("#result")).to_contain_text("found 2", timeout=15000)
            self.assertEqual(len(self.server.records), before)
            page.set_viewport_size({"width": 390, "height": 844})
            self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
            self.assertEqual(errors, [])
            browser.close()

    def test_server_rejects_cross_origin_and_bad_host(self):
        for headers in ({"Origin": "https://untrusted.example"}, {"Host": "untrusted.example"}):
            request = Request(
                self.origin + "/api/requests",
                data=json.dumps(EXAMPLE).encode(),
                headers={"Content-Type": "application/json", **headers},
            )
            with self.assertRaises(HTTPError) as result:
                urlopen(request)
            self.assertEqual(result.exception.code, 403)
            result.exception.close()
