"""Offline fallback against a fake Ollama server: tool call, then answer."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from jarvis.brain import LocalBrain


class FakeOllama(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *a):
        pass

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._json({"models": [{"name": "qwen3.5:9b"}]})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOllama.calls.append(req)
        if not any(m["role"] == "tool" for m in req["messages"]):
            self._json({"message": {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "run_command", "arguments": {"command": "echo hello-from-tool"}}}]}})
        else:
            tool_out = [m for m in req["messages"] if m["role"] == "tool"][-1]["content"]
            self._json({"message": {"role": "assistant", "content": f"The tool said {tool_out}."}})


class Cfg:
    def __init__(self, url):
        self.d = {"local.endpoints": ["http://127.0.0.1:1", url], "local.model": "qwen3.5:9b", "local.keep_alive": "2m"}

    def get(self, k):
        return self.d[k]


def test_fallback_runs_tool_and_answers():
    srv = HTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    brain = LocalBrain(Cfg(f"http://127.0.0.1:{srv.server_port}"), log=lambda m: None)
    spoken, tools = [], []
    reply = brain.ask("say hello", spoken.append, lambda n, i: tools.append(n), lambda: False)
    srv.shutdown()
    assert reply == "The tool said hello-from-tool."
    assert "run_command" in tools
    assert FakeOllama.calls[0]["think"] is False
    assert FakeOllama.calls[0]["keep_alive"] == "2m"


def test_unsafe_commands_refused():
    brain = LocalBrain(Cfg("http://x"), log=lambda m: None)
    assert brain._tool("run_command", {"command": "rm -rf ~"}).startswith("refused")
    assert brain._tool("run_command", {"command": "ls; rm -rf ~"}).startswith("refused")
    assert brain._tool("run_command", {"command": "date"}) != ""
