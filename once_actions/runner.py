"""Execute a reviewed, data-only workflow in one application origin."""

import sqlite3
import threading
import time

from playwright.sync_api import Error as BrowserError
from playwright.sync_api import expect, sync_playwright

from .scope import application_origin, restrict_context
from .skills import SkillError, validate


def local_origin(url):
    # Backward-compatible v1 boundary.
    origin = application_origin(url)
    if not origin.startswith("http://"):
        raise SkillError("Legacy skills require an explicit loopback HTTP URL")
    return origin


def validate_parameters(skill, parameters):
    if not isinstance(parameters, dict) or set(parameters) != set(skill["parameters"]):
        raise SkillError("Provide exactly the declared parameters")
    if any(not isinstance(v, str) or not 1 <= len(v) <= 2000 for v in parameters.values()):
        raise SkillError("Parameter values must be nonempty strings up to 2000 characters")


def resolve(page, target):
    scope = page
    if target.get("group"):
        scope = page.get_by_role("group", name=target["group"], exact=True).filter(visible=True)
        if scope.count() != 1:
            return None
    if "placeholder" in target:
        return scope.get_by_placeholder(target["placeholder"], exact=True).filter(visible=True)
    return scope.get_by_role(target["role"], name=target["name"], exact=True).filter(visible=True)


def execute(
    skill,
    parameters,
    url=None,
    *,
    headless=True,
    cancel=None,
    on_step=None,
    storage_state=None,
    save_state=None,
):
    validate(skill)
    v2 = skill["schema"] == "once-actions/v2"
    if v2:
        if url is not None and url != skill["start_url"]:
            raise SkillError("A saved workflow runs only at its reviewed start URL")
        url = skill["start_url"]
    origin = application_origin(url) if v2 else local_origin(url)
    validate_parameters(skill, parameters)
    started = time.monotonic()
    cancel = cancel or threading.Event()
    events, blocked = [], []
    status, reason = "executed", "Actions executed; application success is not verified."
    effects = False
    browser = None
    context = None
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context(
                service_workers="block", accept_downloads=False, storage_state=storage_state
            )
            restrict_context(context, origin, blocked)
            page = context.new_page()
            page.set_default_timeout(5000)
            page.goto(url, wait_until="networkidle", timeout=20000)
            outcome = None
            if v2:
                check = skill["success"]
                text = parameters[check["value"]] if check["kind"] == "parameter" else check["value"]
                outcome = page.get_by_text(text, exact=True).filter(visible=True)
                if outcome.count():
                    status, reason = (
                        "precondition_failed",
                        "The outcome is already visible. No actions were executed.",
                    )
            if status == "executed":
                for index, step in enumerate(skill["steps"]):
                    if blocked:
                        break
                    if cancel.is_set():
                        status, reason = (
                            "cancelled",
                            "Stopped before the next action. Check any earlier effects.",
                        )
                        break
                    if time.monotonic() - started > 120:
                        status, reason = (
                            "interrupted",
                            "The two-minute execution limit was reached. Check application state.",
                        )
                        break
                    target = step["target"]
                    candidates = resolve(page, target)
                    count = candidates.count() if candidates is not None else 0
                    if count != 1:
                        events.append({"step": index, "target": target, "matches": count, "executed": False})
                        status, reason = (
                            "needs_teaching",
                            f"Expected one visible target; found {count}. No guessing.",
                        )
                        break
                    # Even a fill can trigger autosave. Never imply rollback.
                    effects = True
                    action = step["action"]
                    if action == "fill":
                        candidates.fill(parameters[step["parameter"]])
                    elif action == "select":
                        candidates.select_option(parameters[step["parameter"]])
                    elif action == "press":
                        candidates.press(step["key"])
                    elif action in ("check", "uncheck"):
                        candidates.set_checked(action == "check")
                    else:
                        candidates.click()
                    page.wait_for_load_state("networkidle", timeout=10000)
                    events.append({"step": index, "target": target, "action": action, "executed": True})
                    if on_step:
                        on_step(list(events))
                if status == "executed" and v2 and not blocked:
                    try:
                        expect(outcome).to_have_count(1, timeout=5000)
                        expect(outcome).to_be_visible(timeout=5000)
                        status, reason = "verified", "The expected text became visible after execution."
                    except (AssertionError, BrowserError):
                        status, reason = (
                            "unverified",
                            "Actions ran, but the expected outcome was not observed. Check before retrying.",
                        )
        except BrowserError:
            status, reason = (
                "needs_teaching",
                "The browser or a demonstrated action could not complete. Check browser installation and the page.",
            )
        finally:
            if blocked:
                status, reason = "blocked", "The workflow attempted to leave its approved origin."
            if browser:
                if save_state and context:
                    try:
                        save_state(context.storage_state())
                    except (BrowserError, OSError, sqlite3.Error):
                        status, reason = (
                            "interrupted",
                            "Browser state could not be saved. Check application state before retrying.",
                        )
                browser.close()
    return {
        "status": status,
        "reason": reason,
        "steps": events,
        "duration_seconds": round(time.monotonic() - started, 3),
        "model_calls": 0,
        "skill_hash": skill["hash"],
        "effects_possible": effects,
    }
