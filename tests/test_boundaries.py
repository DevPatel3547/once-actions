import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from once_actions.runner import execute
from once_actions.server import Studio
from once_actions.skills import SkillError, compile_skill


class BoundaryTests(unittest.TestCase):
    def test_cross_origin_request_is_blocked_before_later_actions(self):
        hits = []

        class Page(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                hits.append(self.path)
                content = (
                    f'<script src="http://127.0.0.1:{other.server_port}/external"></script>'
                    "<button onclick=\"fetch('/write')\">Save</button>"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

        with (
            ThreadingHTTPServer(("127.0.0.1", 0), Page) as app,
            ThreadingHTTPServer(("127.0.0.1", 0), Page) as other,
        ):
            workers = [threading.Thread(target=s.serve_forever, daemon=True) for s in (app, other)]
            for worker in workers:
                worker.start()
            try:
                skill = compile_skill(
                    "blocked_task",
                    ["unused"],
                    [
                        {"action": "click", "target": {"role": "button", "name": "Save"}},
                    ],
                )
                result = execute(skill, {"unused": "input"}, f"http://127.0.0.1:{app.server_port}/")
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["steps"], [])
                self.assertNotIn("/external", hits)
                self.assertNotIn("/write", hits)
            finally:
                app.shutdown()
                other.shutdown()
                for worker in workers:
                    worker.join()

    def test_invalid_parameters_rejected_before_navigation(self):
        skill = compile_skill(
            "fill",
            ["name"],
            [
                {"action": "fill", "target": {"role": "textbox", "name": "Name"}, "parameter": "name"},
            ],
        )
        for value in ({}, {"name": ""}, {"name": 12}, {"name": "x", "url": "other"}):
            with self.subTest(value=value), self.assertRaises(SkillError):
                execute(skill, value, "http://127.0.0.1:1/")

    def test_non_object_requests_are_bad_requests(self):
        with Studio() as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for path in ("compile", "import", "run", "requests"):
                    request = Request(
                        server.origin + "/api/" + path,
                        data=json.dumps([]).encode(),
                        headers={"Content-Type": "application/json"},
                    )
                    with self.subTest(path=path), self.assertRaises(HTTPError) as result:
                        urlopen(request)
                    self.assertEqual(result.exception.code, 400)
                    result.exception.close()
            finally:
                server.shutdown()
                thread.join()
