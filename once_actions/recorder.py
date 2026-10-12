"""One explicitly started recording session, owned by one browser thread."""

import copy
import threading
import time
from pathlib import Path

from playwright.sync_api import Error as BrowserError
from playwright.sync_api import sync_playwright

from .scope import application_origin, restrict_context
from .skills import SkillError, compile_workflow, validate_target


class Recorder:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.armed = threading.Event()
        self.thread = None
        self.state = {"status": "idle", "steps": [], "error": None}
        self.result = None
        self.browser_state = None

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def start(
        self, name, url, examples, success, *, headless=False, drive=None, prepare=None, remember=False
    ):
        if (
            not isinstance(examples, dict)
            or not examples
            or any(not isinstance(v, str) or not 1 <= len(v) <= 2000 for v in examples.values())
        ):
            raise SkillError("Provide named, nonempty example strings")
        if len(set(examples.values())) != len(examples):
            raise SkillError("Example values must be distinct so their names are unambiguous")
        compile_workflow(
            name,
            list(examples),
            [{"action": "click", "target": {"role": "button", "name": "Validate"}}],
            url,
            success,
        )
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise SkillError("Finish the active recording first")
            self.state = {"status": "opening", "steps": [], "error": None}
            self.result = None
            self.browser_state = None
            self.stop.clear()
            self.armed.clear()
            self.thread = threading.Thread(
                target=self._record,
                args=(name, url, copy.deepcopy(examples), success, headless, drive, prepare, remember),
                daemon=True,
            )
            self.thread.start()
        return self.snapshot()

    def arm(self):
        if self.snapshot()["status"] != "preparing":
            raise SkillError("Wait until the recording browser is ready")
        self.armed.set()
        return self.snapshot()

    def finish(self):
        self.stop.set()
        return self.snapshot()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join()

    def _record(self, name, url, examples, success, headless, drive, prepare, remember):
        steps, blocked = [], []
        origin = application_origin(url)
        browser = None
        failed = None
        capturing = False
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=headless)
                context = browser.new_context(service_workers="block", accept_downloads=False)
                restrict_context(context, origin, blocked)
                page = context.new_page()

                def receive(source, detail):
                    nonlocal failed
                    if not capturing:
                        return
                    if source["page"] != page or source["frame"] != page.main_frame:
                        failed = "Frames and popups are not supported in this release"
                        return
                    try:
                        if not isinstance(detail, dict) or len(steps) >= 100:
                            raise SkillError("Recording limit reached")
                        action = detail["action"]
                        validate_target(detail["target"], action)
                        step = {"action": action, "target": detail["target"]}
                        if action in ("fill", "select"):
                            matches = [k for k, v in examples.items() if v == detail.get("value")]
                            if len(matches) != 1:
                                raise SkillError(
                                    "An entered value did not match one named example. Discard this recording and try again."
                                )
                            step["parameter"] = matches[0]
                        if action == "press":
                            step["key"] = detail["key"]
                        # Validate each captured action before displaying or storing it.
                        compile_workflow(name, list(examples), [step], url, success)
                        steps.append(step)
                        with self.lock:
                            self.state["steps"] = copy.deepcopy(steps)
                    except (SkillError, KeyError, TypeError):
                        failed = "A control or value could not be recorded. Use supported controls and exact example values."

                context.expose_binding("__onceRecord", receive)
                context.add_init_script(path=str(Path(__file__).parent / "assets" / "recorder.js"))
                page.goto(url, wait_until="networkidle", timeout=20000)
                with self.lock:
                    self.state["status"] = "preparing"
                deadline = time.monotonic() + 900
                if prepare:
                    prepare(page)  # Acceptance hook; never supplied by HTTP callers.
                if drive:
                    self.armed.set()
                while (
                    not self.armed.is_set()
                    and not self.stop.is_set()
                    and not page.is_closed()
                    and time.monotonic() < deadline
                ):
                    page.wait_for_timeout(100)
                if not self.armed.is_set() or page.is_closed():
                    raise SkillError("Recording ended before capture started")
                if application_origin(page.url) != origin:
                    raise SkillError("Start capture inside the selected application origin")
                url = page.url
                page.evaluate("window.__onceFlush?.()")
                page.wait_for_timeout(100)
                capturing = True
                with self.lock:
                    self.state["status"] = "recording"
                    self.state["start_url"] = url
                if drive:
                    drive(page)  # Browser acceptance hook, never exposed over HTTP.
                    self.stop.set()
                while not self.stop.is_set() and not page.is_closed() and time.monotonic() < deadline:
                    page.wait_for_timeout(100)
                if page.is_closed() or time.monotonic() >= deadline:
                    failed = "The browser closed or the 15-minute recording limit elapsed. Record again."
                else:
                    page.evaluate("window.__onceFlush?.()")
                    page.wait_for_timeout(150)
                if blocked:
                    failed = "The page requested another origin. This version supports self-contained applications only."
                if failed:
                    raise SkillError(failed)
                compiled = compile_workflow(name, list(examples), steps, url, success)
                with self.lock:
                    self.result = compiled
                    self.browser_state = context.storage_state() if remember else None
                    self.state["status"] = "review"
                    self.state["hash"] = compiled["hash"]
                    self.state["remembers_browser"] = remember
            except (BrowserError, SkillError) as exc:
                with self.lock:
                    self.state["status"] = "error"
                    self.state["error"] = (
                        str(exc)
                        if isinstance(exc, SkillError)
                        else "The browser could not record this page. Check Chromium installation and the application URL."
                    )
            finally:
                if browser:
                    browser.close()
                examples.clear()
