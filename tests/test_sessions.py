import json
import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect

from once_actions.recorder import Recorder
from once_actions.runner import execute


class SessionsTests(unittest.TestCase):
    def test_local_storage_survives_contexts_and_is_not_in_skill(self):
        class Quiet(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

        with tempfile.TemporaryDirectory() as folder:
            Path(
                folder, "index.html"
            ).write_text("""<label>Name<input id="name"></label><button id="save">Save</button><div id="records"></div><script>
            function render(){document.getElementById('records').replaceChildren();for(const text of JSON.parse(localStorage.getItem('items')||'[]')){const p=document.createElement('p');p.textContent=text;document.getElementById('records').append(p);}}
            document.getElementById('save').onclick=()=>{const rows=JSON.parse(localStorage.getItem('items')||'[]');rows.push(document.getElementById('name').value);localStorage.setItem('items',JSON.stringify(rows));document.cookie='demo_session=local-test-cookie; SameSite=Strict';render();};render();</script>""")
            with ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=folder)) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:

                    def drive(page):
                        page.get_by_label("Name", exact=True).fill("Example")
                        page.get_by_role("button", name="Save", exact=True).click()
                        expect(page.get_by_text("Example", exact=True)).to_be_visible()

                    recorder = Recorder()
                    recorder.start(
                        "add_name",
                        f"http://127.0.0.1:{server.server_port}/",
                        {"name": "Example"},
                        {"kind": "parameter", "value": "name"},
                        headless=True,
                        drive=drive,
                        remember=True,
                    )
                    recorder.thread.join(timeout=15)
                    self.assertEqual(recorder.snapshot()["status"], "review", recorder.snapshot())
                    self.assertNotIn("local-test-cookie", json.dumps(recorder.result))
                    self.assertNotIn("Example", json.dumps(recorder.result))
                    state = []
                    result = execute(
                        recorder.result,
                        {"name": "Second name"},
                        storage_state=recorder.browser_state,
                        save_state=state.append,
                    )
                    self.assertEqual(result["status"], "verified", result)
                    self.assertIn("Second name", json.dumps(state[-1]))
                    self.assertIn("local-test-cookie", json.dumps(state[-1]))
                    repeated = execute(recorder.result, {"name": "Second name"}, storage_state=state[-1])
                    self.assertEqual(repeated["status"], "precondition_failed")
                    self.assertFalse(repeated["effects_possible"])
                finally:
                    server.shutdown()
                    thread.join()
