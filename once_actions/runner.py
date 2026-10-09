"""Playwright executor restricted to an explicitly supplied loopback application."""

import ipaddress
import time
from urllib.parse import urlsplit

from playwright.sync_api import Error as BrowserError
from playwright.sync_api import sync_playwright

from .skills import SkillError, validate


def local_origin(url):
    parsed = urlsplit(url)
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError:
        raise SkillError("This prototype only runs against literal loopback HTTP addresses") from None
    if parsed.scheme != "http" or not address.is_loopback or not port or parsed.username or parsed.password:
        raise SkillError("This prototype only runs against literal loopback HTTP addresses with a port")
    if parsed.fragment:
        raise SkillError("URL fragments are not supported")
    return f"{parsed.scheme}://{parsed.netloc}"


def execute(skill, parameters, url, *, headless=True):
    validate(skill)
    origin = local_origin(url)
    if not isinstance(parameters, dict) or set(parameters) != set(skill["parameters"]):
        raise SkillError("Provide exactly the declared parameters")
    if any(not isinstance(v, str) or not 1 <= len(v) <= 2000 for v in parameters.values()):
        raise SkillError("Parameter values must be nonempty strings up to 2000 characters")
    started = time.monotonic()
    events = []
    blocked = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(service_workers="block")

        def route(request):
            parts = urlsplit(request.request.url)
            if f"{parts.scheme}://{parts.netloc}" != origin:
                blocked.append("Cross-origin request blocked")
                request.abort()
            else:
                request.continue_()

        context.route("**/*", route)
        context.route_web_socket("**/*", lambda socket: socket.close())
        page = context.new_page()
        page.set_default_timeout(4000)
        status, reason = (
            "executed",
            "All demonstrated steps executed; external effects need application verification.",
        )
        try:
            page.goto(url, wait_until="networkidle")
            for index, step in enumerate(skill["steps"]):
                if blocked:
                    break
                target = step["target"]
                scope = page
                if target.get("group"):
                    scope = page.get_by_role("group", name=target["group"], exact=True)
                    if scope.count() != 1:
                        status, reason = "needs_teaching", "The demonstrated group is missing or ambiguous."
                        break
                candidates = scope.get_by_role(target["role"], name=target["name"], exact=True).filter(
                    visible=True
                )
                count = candidates.count()
                if count != 1:
                    events.append({"step": index, "target": target, "matches": count, "executed": False})
                    status, reason = (
                        "needs_teaching",
                        f"Expected one visible target; found {count}. No guessing.",
                    )
                    break
                if step["action"] == "fill":
                    candidates.fill(parameters[step["parameter"]])
                elif step["action"] == "select":
                    candidates.select_option(parameters[step["parameter"]])
                else:
                    candidates.click()
                    page.wait_for_load_state("networkidle")
                events.append({"step": index, "target": target, "action": step["action"], "executed": True})
        except BrowserError:
            # Browser errors can contain input values and complete page text; don't expose them.
            status, reason = "needs_teaching", "The page changed or a demonstrated action could not complete."
        finally:
            if blocked:
                status, reason = "blocked", "The workflow attempted to leave its approved origin."
            browser.close()
    return {
        "status": status,
        "reason": reason,
        "steps": events,
        "duration_seconds": round(time.monotonic() - started, 3),
        "model_calls": 0,
        "skill_hash": skill["hash"],
    }
