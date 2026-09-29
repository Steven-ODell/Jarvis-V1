"""The two brains: Claude Code (primary) and an Ollama model (fallback).

Claude Code runs as one long-lived `claude -p` process speaking stream-json,
so follow-up questions skip the ~1.5 s CLI boot and keep the conversation. It
starts the moment you press the hotkey (booting while you talk) and exits
after a few idle minutes so it isn't resident between conversations.
"""

import json
import os
import queue
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import actions
from .config import ROOT, STATE_DIR
from .prompt import SYSTEM

# brain.model is an alias (the settings picker and "use sonnet" work in
# aliases). Claude Code 2.1.283's "sonnet" still means Sonnet 5, so pin the
# ID until its alias catches up. It prints an unrecognized_model warning to
# stderr for this ID; the model works fine.
MODEL_IDS = {"sonnet": "claude-sonnet-5-5"}


class BrainError(Exception):
    pass


def find_claude():
    # ~/.local/bin/claude is a mise shim that runs `mise use -g` on every
    # call (~300 ms). Go straight to the installed binary when it exists.
    direct = Path.home() / ".local/share/mise/installs/claude/latest/claude"
    if direct.exists():
        return str(direct)
    return shutil.which("claude") or "claude"


def find_node():
    installs = sorted((Path.home() / ".local/share/mise/installs/node").glob("*/bin/node"))
    if installs:
        return str(installs[-1])
    return shutil.which("node")


_online = {"t": 0.0, "ok": True}


def online():
    """Can we reach Anthropic at all? Cached so it costs nothing per turn."""
    now = time.monotonic()
    ttl = 15 if _online["ok"] else 4
    if now - _online["t"] < ttl:
        return _online["ok"]
    try:
        socket.create_connection(("api.anthropic.com", 443), timeout=1.0).close()
        ok = True
    except OSError:
        ok = False
    _online.update(t=now, ok=ok)
    return ok


def browser_mcp_config():
    node = find_node()
    cli = ROOT / "browser/node_modules/@playwright/mcp/cli.js"
    if not node or not cli.exists():
        return None
    profile = STATE_DIR / "browser-profile"
    profile.mkdir(parents=True, exist_ok=True)
    return json.dumps({"mcpServers": {"browser": {
        "command": node,
        "args": [str(cli), "--browser", "chromium", "--executable-path", "/usr/bin/chromium",
                 "--user-data-dir", str(profile)],
    }}})


class ClaudeSession:
    def __init__(self, cfg, log):
        self.cfg = cfg
        self.log = log
        self.proc = None
        self.events = queue.Queue()
        self.lock = threading.Lock()
        self.last_used = time.monotonic()
        self.model = None
        self.fast = False
        self.busy = False
        self.turns = 0
        threading.Thread(target=self._reaper, daemon=True, name="claude-reaper").start()

    # ------------------------------------------------------------ lifecycle

    def ensure(self):
        """Start the process if it isn't running. Returns immediately."""
        with self.lock:
            self.last_used = time.monotonic()
            model = self.cfg.get("brain.model")
            fast = bool(self.cfg.get("brain.fast"))
            if self.proc and self.proc.poll() is None and (model, fast) == (self.model, self.fast):
                return
            if self.proc and self.proc.poll() is None:
                self._kill_locked()
            self.model, self.fast = model, fast
            self.turns = 0
            args = [
                find_claude(), "-p",
                "--input-format", "stream-json", "--output-format", "stream-json",
                "--verbose", "--include-partial-messages",
                "--model", MODEL_IDS.get(model, model),
                "--effort", self.cfg.get("brain.effort"),
                "--permission-mode", "auto", "--permission-prompts", "none",
                "--no-session-persistence",
                "--append-system-prompt", SYSTEM,
            ]
            if fast:
                args += ["--settings", json.dumps({"fastMode": True})]
            mcp = browser_mcp_config()
            if mcp:
                args += ["--mcp-config", mcp]
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            errlog = open(STATE_DIR / "claude-stderr.log", "ab")
            self.proc = subprocess.Popen(
                args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errlog,
                cwd=str(Path.home()), text=True, bufsize=1,
                # Tool search defers MCP tools behind an extra ToolSearch
                # round-trip (~1.5 s). Voice latency matters more than the
                # tokens, so load the browser/Gmail tools up front.
                env={**os.environ, "CLAUDE_CODE_ENTRYPOINT": "jarvis", "ENABLE_TOOL_SEARCH": "false"},
            )
            self.events = queue.Queue()
            threading.Thread(target=self._reader, args=(self.proc, self.events),
                             daemon=True, name="claude-reader").start()
            self.log(f"claude started ({model}{' fast' if fast else ''}, pid {self.proc.pid})")

    def _reader(self, proc, q):
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                q.put(json.loads(line))
            except json.JSONDecodeError:
                continue
        q.put({"type": "_exit", "code": proc.wait()})

    def _kill_locked(self):
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            try:
                p.stdin.close()
            except OSError:
                pass
            p.terminate()
            try:
                p.wait(3)
            except subprocess.TimeoutExpired:
                p.kill()

    def stop(self):
        with self.lock:
            self._kill_locked()

    def reset(self):
        """Forget the conversation. The next ensure() starts a fresh one."""
        self.stop()
        self.log("claude session reset")

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def _reaper(self):
        while True:
            time.sleep(5)
            idle = time.monotonic() - self.last_used
            limit = float(self.cfg.get("brain.idle_exit_min")) * 60
            if self.turns == 0:
                # Booted on the hotkey but the fast path handled the request,
                # so there's no conversation worth keeping it around for.
                limit = min(limit, 45)
            if self.running() and not self.busy and not self.cfg.get("brain.keep_warm") and idle > limit:
                self.log(f"claude idle {idle / 60:.0f} min, exiting")
                self.stop()

    # ---------------------------------------------------------------- turns

    def _send(self, obj):
        try:
            self.proc.stdin.write(json.dumps(obj) + "\n")
            self.proc.stdin.flush()
        except (OSError, AttributeError) as e:
            raise BrainError(f"claude stdin closed: {e}")

    def interrupt(self):
        if self.running() and self.busy:
            try:
                self._send({"type": "control_request", "request_id": f"int-{time.time()}",
                            "request": {"subtype": "interrupt"}})
            except BrainError:
                pass

    def ask(self, text, on_text, on_tool, cancelled):
        """Run one turn. Streams text through on_text; returns the full reply."""
        self.ensure()
        self.busy = True
        self.turns += 1
        try:
            self._send({"type": "user", "message": {"role": "user", "content": text}})
            reply, blocks, sent_interrupt = [], 0, False
            t0 = time.monotonic()
            got_any = False
            while True:
                if cancelled() and not sent_interrupt:
                    self.interrupt()
                    sent_interrupt = True
                try:
                    ev = self.events.get(timeout=0.1)
                except queue.Empty:
                    # Boot + first token is ~2 s; 40 s of nothing means it's
                    # wedged (or stuck on auth) and the fallback should run.
                    if not got_any and time.monotonic() - t0 > 40:
                        self.stop()
                        raise BrainError("claude produced nothing for 40 s")
                    if sent_interrupt and time.monotonic() - t0 > 60:
                        self.stop()
                        return "".join(reply)
                    continue
                t = ev.get("type")
                if t == "_exit":
                    raise BrainError(f"claude exited with code {ev.get('code')}")
                if t in ("stream_event", "assistant", "result"):
                    got_any = True
                if ev.get("parent_tool_use_id"):
                    continue  # a subagent's chatter, not Jarvis talking
                if t == "stream_event":
                    e = ev.get("event", {})
                    et = e.get("type")
                    if et == "content_block_start":
                        cb = e.get("content_block", {})
                        if cb.get("type") == "text":
                            if blocks:
                                on_text("\n")  # new paragraph after a tool call
                                reply.append(" ")
                            blocks += 1
                        elif cb.get("type") == "tool_use":
                            on_tool(cb.get("name", ""), None)
                    elif et == "content_block_delta":
                        d = e.get("delta", {})
                        if d.get("type") == "text_delta" and not sent_interrupt:
                            reply.append(d["text"])
                            on_text(d["text"])
                elif t == "assistant":
                    for b in ev.get("message", {}).get("content", []):
                        if b.get("type") == "tool_use":
                            on_tool(b.get("name", ""), b.get("input"))
                elif t == "result":
                    self.last_used = time.monotonic()
                    if ev.get("is_error") and not sent_interrupt:
                        msg = ev.get("result") or ev.get("subtype")
                        raise BrainError(f"claude error: {msg}")
                    return "".join(reply) or (ev.get("result") or "")
        finally:
            self.busy = False
            self.last_used = time.monotonic()


# ---------------------------------------------------------------- local ---

LOCAL_SYSTEM = """\
You are Jarvis, a voice assistant on an Arch Linux (Hyprland) laptop. You are
the offline fallback, so keep it simple. Replies are spoken aloud: one or two
short sentences, no markdown. Use the tools to act; don't describe commands.
"""

LOCAL_TOOLS = [
    {"type": "function", "function": {
        "name": "open_url", "description": "Open a web page in the default browser.",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "launch_app", "description": "Open or focus a desktop application by name.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "run_command",
        "description": "Run a read-only shell command and get its output (date, ls, df, hyprctl, uptime...).",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
]

# The local model is small and runs with no permission system, so it gets
# an allowlist of harmless commands rather than a denylist of scary ones.
SAFE_CMD = re.compile(
    r"^\s*(date|cal|uptime|whoami|hostname|ls|df|du|free|cat|head|tail|wc|grep|find|"
    r"hyprctl|ps|pgrep|uname|sensors|acpi|nmcli|ip|ping -c \d+|echo|wpctl status|"
    r"brightnessctl|which|pacman -Q\w*|omarchy)\b"
)


class LocalBrain:
    def __init__(self, cfg, log):
        self.cfg = cfg
        self.log = log
        self.history = []

    def _post(self, base, path, body, timeout):
        req = urllib.request.Request(base.rstrip("/") + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def _pick(self):
        want = self.cfg.get("local.model")
        for base in self.cfg.get("local.endpoints"):
            try:
                with urllib.request.urlopen(base.rstrip("/") + "/api/tags", timeout=1.2) as r:
                    names = [m["name"] for m in json.loads(r.read()).get("models", [])]
            except (OSError, ValueError, urllib.error.URLError):
                continue
            if not names:
                continue
            model = want if want in names else next((n for n in names if n.startswith(want)), names[0])
            return base, model
        return None, None

    def _tool(self, name, args):
        if name == "open_url":
            actions.open_url(args.get("url", ""))
            return "opened"
        if name == "launch_app":
            got = actions.launch_app(args.get("name", ""))
            return f"opened {got}" if got else "no app by that name"
        if name == "run_command":
            cmd = args.get("command", "")
            if not SAFE_CMD.match(cmd) or re.search(r"[;&|`$><]", cmd):
                return "refused: only simple read-only commands are allowed offline"
            code, out = actions.run(cmd, timeout=8)
            return out[:3000] or f"exit {code}"
        return "unknown tool"

    def ask(self, text, on_text, on_tool, cancelled):
        base, model = self._pick()
        if not base:
            raise BrainError("no local model server reachable")
        self.log(f"local brain: {model} @ {base}")
        on_tool("local:" + model, None)
        msgs = [{"role": "system", "content": LOCAL_SYSTEM}] + self.history[-8:] + \
               [{"role": "user", "content": text}]
        for _ in range(5):
            if cancelled():
                return ""
            r = self._post(base, "/api/chat", {
                "model": model, "messages": msgs, "tools": LOCAL_TOOLS, "stream": False,
                "think": False, "keep_alive": self.cfg.get("local.keep_alive"),
            }, timeout=90)
            msg = r.get("message", {})
            msgs.append(msg)
            calls = msg.get("tool_calls") or []
            if not calls:
                reply = (msg.get("content") or "").strip()
                on_text(reply)
                self.history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
                return reply
            for c in calls:
                fn = c.get("function", {})
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                on_tool(fn.get("name", ""), args)
                msgs.append({"role": "tool", "content": self._tool(fn.get("name"), args)})
        on_text("I got stuck doing that.")
        return "I got stuck doing that."
