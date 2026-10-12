import json
import sqlite3
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from once_actions.skills import SkillError, compile_workflow, correct_target
from once_actions.store import Conflict, Store


def workflow():
    return compile_workflow(
        "create",
        ["name"],
        [
            {"action": "fill", "target": {"role": "textbox", "name": "Name"}, "parameter": "name"},
            {"action": "click", "target": {"role": "button", "name": "Save"}},
        ],
        "http://127.0.0.1:9999/",
        {"kind": "parameter", "value": "name"},
    )


class StoreTests(unittest.TestCase):
    def test_newer_format_rejected_without_leaking_library_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.close()
            with sqlite3.connect(Path(directory) / "library.sqlite3") as db:
                db.execute("PRAGMA user_version=99")
            for _ in range(2):
                with self.assertRaisesRegex(SkillError, "newer database format"):
                    Store(directory)
            with sqlite3.connect(Path(directory) / "library.sqlite3") as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 99)

    def test_private_backup_restores_saved_workflow_and_session(self):
        from once_actions.maintenance import backup

        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "library")
            self.addCleanup(store.close)
            saved = store.save(workflow())
            state = {"cookies": [{"name": "test", "value": "private-demo-cookie"}], "origins": []}
            store.save_browser_state(saved["id"], state)
            destination = Path(directory) / "backup.sqlite3"
            backup(store.directory, destination)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                backup(store.directory, destination)
            restored_dir = Path(directory) / "restored"
            restored_dir.mkdir()
            destination.rename(restored_dir / "library.sqlite3")
            restored = Store(restored_dir)
            self.addCleanup(restored.close)
            self.assertEqual(restored.get(saved["id"]), saved)
            self.assertEqual(restored.browser_state(saved["id"]), state)
            restored.forget_browser_state(saved["id"])
            self.assertIsNone(restored.browser_state(saved["id"]))

    def test_revisions_are_immutable_and_stale_correction_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            self.addCleanup(store.close)
            first = store.save(workflow())
            corrected = correct_target(first["skill"], 0, {"role": "textbox", "name": "Full name"})
            second = store.save(corrected, first["id"], 1)
            self.assertEqual(second["revision"], 2)
            self.assertEqual(store.get(first["id"], 1), first)
            with self.assertRaises(Conflict):
                store.save(corrected, first["id"], 1)
            self.assertEqual(second["skill"]["steps"][1], first["skill"]["steps"][1])

    def test_atomic_claim_and_no_plaintext_values(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            self.addCleanup(store.close)
            saved = store.save(workflow())
            run_id = str(uuid.uuid4())
            with ThreadPoolExecutor(max_workers=8) as pool:
                claims = list(
                    pool.map(lambda _: store.claim(run_id, saved, {"name": "PRIVATE-EXAMPLE-4719"}), range(8))
                )
            self.assertEqual(sum(claims), 1)
            with self.assertRaises(Conflict):
                store.claim(run_id, saved, {"name": "different"})
            self.assertNotIn(b"PRIVATE-EXAMPLE-4719", Path(directory, "library.sqlite3").read_bytes())
            self.assertNotIn("digest", json.dumps(store.list_runs()))

    def test_restart_marks_unfinished_run_and_never_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            saved = store.save(workflow())
            run_id = str(uuid.uuid4())
            self.assertTrue(store.claim(run_id, saved, {"name": "x"}))
            with self.assertRaises(Conflict):
                Store(directory)
            store.close()
            recovered = Store(directory)
            self.addCleanup(recovered.close)
            self.assertEqual(recovered.run(run_id)["status"], "interrupted")
            self.assertFalse(recovered.claim(run_id, saved, {"name": "x"}))
            self.assertEqual(recovered.get(saved["id"]), saved)

    def test_only_one_distinct_active_run(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            self.addCleanup(store.close)
            saved = store.save(workflow())
            first = str(uuid.uuid4())
            store.claim(first, saved, {"name": "x"})
            with self.assertRaises(Conflict):
                store.claim(str(uuid.uuid4()), saved, {"name": "y"})
            store.finish(first, {"status": "verified"})
            self.assertTrue(store.claim(str(uuid.uuid4()), saved, {"name": "y"}))
