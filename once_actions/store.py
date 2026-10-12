"""Private local SQLite journal with immutable revisions and atomic run claims."""

import fcntl
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .skills import SkillError, validate


class Conflict(SkillError):
    pass


class Store:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lease = (self.directory / "owner.lock").open("a+")
        os.chmod(self.directory / "owner.lock", 0o600)
        try:
            fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lease.close()
            raise Conflict("This library is already open in another Once Actions process") from None
        try:
            self._initialize()
        except Exception:
            self.close()
            raise

    def _initialize(self):
        self.path = self.directory / "library.sqlite3"
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        with self.connect() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
                raise SkillError(
                    "This library uses a newer database format. Use its matching Once Actions release"
                )
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS skills (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions (
                    skill_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
                    created REAL NOT NULL, PRIMARY KEY(skill_id, revision),
                    FOREIGN KEY(skill_id) REFERENCES skills(id));
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, skill_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    digest TEXT NOT NULL, status TEXT NOT NULL, result TEXT,
                    created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS browser_states (
                    skill_id TEXT PRIMARY KEY, body TEXT NOT NULL,
                    FOREIGN KEY(skill_id) REFERENCES skills(id));
            """)
            db.execute("INSERT OR IGNORE INTO settings VALUES ('digest_key', ?)", (secrets.token_hex(32),))
            self.key = bytes.fromhex(
                db.execute("SELECT value FROM settings WHERE key='digest_key'").fetchone()[0]
            )
            # A previous owner may have died during a write. Never replay it.
            db.execute(
                "UPDATE runs SET status='interrupted', updated=? WHERE status='running'", (time.time(),)
            )
            db.execute("PRAGMA user_version=1")
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def close(self):
        if not self.lease.closed:
            fcntl.flock(self.lease, fcntl.LOCK_UN)
            self.lease.close()

    def browser_state(self, skill_id):
        with self.connect() as db:
            row = db.execute("SELECT body FROM browser_states WHERE skill_id=?", (skill_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_browser_state(self, skill_id, state):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO browser_states VALUES (?,?)", (skill_id, json.dumps(state)))

    def forget_browser_state(self, skill_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM runs WHERE status='running' LIMIT 1").fetchone():
                raise Conflict("Wait for the active run before clearing browser state")
            db.execute("DELETE FROM browser_states WHERE skill_id=?", (skill_id,))

    def save(self, skill, skill_id=None, expected_revision=None, *, browser_state=None):
        validate(skill)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if skill_id is None:
                skill_id, revision = uuid.uuid4().hex, 1
                db.execute("INSERT INTO skills VALUES (?,?,?)", (skill_id, skill["name"], time.time()))
            else:
                row = db.execute(
                    "SELECT MAX(revision) FROM revisions WHERE skill_id=?", (skill_id,)
                ).fetchone()
                if row[0] is None:
                    raise SkillError("Skill not found")
                if expected_revision != row[0]:
                    raise Conflict("The skill changed. Reload and review the latest revision")
                previous = json.loads(
                    db.execute(
                        "SELECT body FROM revisions WHERE skill_id=? AND revision=?", (skill_id, row[0])
                    ).fetchone()[0]
                )
                if previous["name"] != skill["name"]:
                    raise SkillError("A revision must keep the skill name")
                revision = row[0] + 1
            db.execute(
                "INSERT INTO revisions VALUES (?,?,?,?)", (skill_id, revision, json.dumps(skill), time.time())
            )
            if browser_state is not None:
                db.execute(
                    "INSERT OR REPLACE INTO browser_states VALUES (?,?)",
                    (skill_id, json.dumps(browser_state)),
                )
        return self.get(skill_id, revision)

    def get(self, skill_id, revision=None):
        with self.connect() as db:
            if revision is None:
                row = db.execute(
                    "SELECT * FROM revisions WHERE skill_id=? ORDER BY revision DESC LIMIT 1", (skill_id,)
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT * FROM revisions WHERE skill_id=? AND revision=?", (skill_id, revision)
                ).fetchone()
        if row is None:
            raise SkillError("Skill not found")
        return {"id": skill_id, "revision": row["revision"], "skill": json.loads(row["body"])}

    def list_skills(self):
        with self.connect() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM skills ORDER BY created DESC")]
        return [self.get(skill_id) for skill_id in ids]

    def claim(self, run_id, saved, parameters):
        try:
            if str(uuid.UUID(run_id)) != run_id:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise SkillError("Run ID must be a canonical UUID") from None
        body = json.dumps(
            [saved["id"], saved["revision"], saved["skill"]["hash"], parameters], sort_keys=True
        ).encode()
        digest = hmac.new(self.key, body, hashlib.sha256).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT digest FROM runs WHERE id=?", (run_id,)).fetchone()
            if existing:
                if not hmac.compare_digest(existing[0], digest):
                    raise Conflict("That run ID already belongs to different inputs or a different revision")
                return False
            if db.execute("SELECT 1 FROM runs WHERE status='running' LIMIT 1").fetchone():
                raise Conflict("Another run is active. Wait for it to finish")
            now = time.time()
            db.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)",
                (run_id, saved["id"], saved["revision"], digest, "running", None, now, now),
            )
        return True

    def finish(self, run_id, result):
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET status=?, result=?, updated=? WHERE id=? AND status='running'",
                (result["status"], json.dumps(result), time.time(), run_id),
            )

    def run(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise SkillError("Run not found")
        return {
            "id": row["id"],
            "skill_id": row["skill_id"],
            "revision": row["revision"],
            "status": row["status"],
            "result": json.loads(row["result"]) if row["result"] else None,
            "created": row["created"],
            "updated": row["updated"],
        }

    def list_runs(self):
        with self.connect() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM runs ORDER BY created DESC LIMIT 100")]
        return [self.run(run_id) for run_id in ids]
