"""Local installation checks and consistent private library backups."""

import os
import sqlite3
from pathlib import Path

from playwright.sync_api import Error as BrowserError
from playwright.sync_api import sync_playwright

from .skills import SkillError


def doctor():
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            version = browser.version
            browser.close()
        return {"status": "ok", "chromium": version, "platforms": "macOS and Linux"}
    except BrowserError:
        return {
            "status": "error",
            "reason": "Chromium could not launch. Run: python -m playwright install chromium. On Linux install browser system dependencies too.",
        }


def backup(directory, destination):
    source = Path(directory).expanduser().resolve() / "library.sqlite3"
    destination = Path(destination).expanduser().resolve()
    if not source.is_file():
        raise SkillError("No library exists at that data directory")
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        src = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        try:
            dst = sqlite3.connect(destination)
            try:
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise SkillError("Backup failed its integrity check")
            finally:
                dst.close()
        finally:
            src.close()
    except (OSError, sqlite3.Error, SkillError):
        destination.unlink(missing_ok=True)
        raise
    return {"status": "ok", "path": str(destination)}
