"""Deterministic native Ollama protocol fixture for worker integration CI only.

Not a model, inference service, runtime fallback or model-quality measurement.
Real local-model runs do not start this fixture. Real Docker checks still judge
its proposed patch independently.
"""
from __future__ import annotations

import contextlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "oryveta-ci:fixture"
DIGEST = "c" * 64
PATH = "src/sample/simple.py"


@contextlib.contextmanager
def serve():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, data, status=200):
            payload = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path == "/api/tags":
                self.respond({"models": [{"name": MODEL, "digest": DIGEST,
                                           "size": 101 * 1024 * 1024}]})
            else:
                self.respond({}, 404)

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 262144:
                self.respond({}, 413)
                return
            body = json.loads(self.rfile.read(size))
            if self.path == "/api/show":
                self.respond({"capabilities": ["completion", "tools"]})
                return
            if self.path != "/api/chat":
                self.respond({}, 404)
                return
            previous = body["messages"][-1]
            tool = previous.get("tool_name")
            name, arguments = "read_file", {"path": PATH}
            if tool == "read_file":
                observed = json.loads(previous["content"])
                name, arguments = "replace_text", {
                    "path": PATH, "expected_sha256": observed["sha256"],
                    "old": "return number + 1", "new": "return number + 2",
                }
            elif tool == "replace_text":
                name, arguments = "run_checks", {}
            message = {"role": "assistant", "content": ""}
            if tool == "run_checks":
                message["content"] = "Candidate ready for independent verification."
            else:
                message["tool_calls"] = [{"type": "function", "function": {
                    "name": name, "arguments": arguments}}]
            self.respond({"model": MODEL, "done": True, "done_reason": "stop",
                          "message": message, "prompt_eval_count": 1, "eval_count": 1})

    server = ThreadingHTTPServer(("127.0.0.1", 11434), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield MODEL, DIGEST
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
