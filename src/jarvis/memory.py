"""Conversation memory that survives restarts.

Every exchange (what Sao said, what Jarvis answered, when, and which path
handled it) is appended to memory/log.jsonl and kept forever; plain text is
tiny. When a Claude session starts, only a bounded block goes into its system
prompt: a rolling summary of older talk plus the last few exchanges. Older
history stays on disk, and the prompt tells Claude where to grep it.

The summary is rebuilt in the background by a small `claude -p` call once
enough exchanges have scrolled out of the recent window, so it never sits
between Sao and a reply.
"""

import datetime as dt
import json
import os
import subprocess
import threading

from .config import ROOT

MEM_DIR = ROOT / "memory"
LOG = MEM_DIR / "log.jsonl"
SUMMARY = MEM_DIR / "summary.md"
STATE = MEM_DIR / "state.json"

# Fast-path turns ("volume up") are logged but kept out of the prompt, or a
# run of them would push real conversation out of the window.
PROMPT_VIAS = ("claude", "local")

SUMMARY_PROMPT = """\
You maintain the long-term memory of Jarvis, a voice assistant for Sao on
his Linux laptop. Below is the current summary of older conversations,
followed by exchanges that are about to drop out of Jarvis's short-term
window. Write the new summary: at most 200 words, plain sentences, no
headings or lists. Keep facts about Sao, his preferences, his projects,
requests still open, and decisions made. Drop small talk and one-off
commands that are done. Output only the summary.

Current summary:
{summary}

Exchanges to fold in (oldest first):
{exchanges}
"""


def _clip(text, n):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _tail_lines(path, want):
    """The last `want` lines of a file, reading backwards so a years-long
    log costs the same as a new one."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            block, data = 16384, b""
            while end > 0 and data.count(b"\n") <= want:
                step = min(block, end)
                end -= step
                f.seek(end)
                data = f.read(step) + data
                block *= 2
    except FileNotFoundError:
        return []
    return [ln for ln in data.decode("utf-8", "replace").splitlines() if ln.strip()][-want:]


def _parse(lines):
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


class Memory:
    def __init__(self, cfg, log, summarize=None):
        self.cfg = cfg
        self.log = log
        self.lock = threading.Lock()
        self.summarizing = False
        # Swappable for tests; the default shells out to claude.
        self.summarize = summarize or self._summarize_with_claude

    # --------------------------------------------------------------- write

    def record(self, heard, reply, via):
        heard, reply = (heard or "").strip(), (reply or "").strip()
        if not heard and not reply:
            return
        row = {"ts": dt.datetime.now().isoformat(timespec="seconds"),
               "heard": heard, "reply": reply, "via": via}
        with self.lock:
            MEM_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            state = self._state()
            if via in PROMPT_VIAS:
                state["pending"] = state.get("pending", 0) + 1
            self._save_state(state)
        self._maybe_summarize()

    def _state(self):
        try:
            return json.loads(STATE.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_state(self, state):
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        tmp.replace(STATE)

    # ---------------------------------------------------------------- read

    def recent(self, n=None):
        """The last n conversational exchanges, oldest first."""
        n = n or int(self.cfg.get("memory.recent"))
        # Fast-path rows are skipped, so read extra to still find n.
        rows = [r for r in _parse(_tail_lines(LOG, n * 6)) if r.get("via") in PROMPT_VIAS]
        return rows[-n:]

    def summary(self):
        try:
            return SUMMARY.read_text().strip()
        except FileNotFoundError:
            return ""

    def context(self):
        """The block appended to the system prompt. Empty on a fresh install."""
        summary, rows = self.summary(), self.recent()
        if not summary and not rows:
            return ""
        parts = ["\nMemory of earlier conversations with Sao (previous sessions; "
                 "use it when relevant, don't recite it):"]
        if summary:
            parts.append("Summary of older conversations: " + summary)
        if rows:
            parts.append("Most recent exchanges, oldest first:")
            for r in rows:
                parts.append(f"[{r['ts'][:16].replace('T', ' ')}] Sao: {_clip(r['heard'], 400)}\n"
                             f"  You: {_clip(r['reply'], 600)}")
        parts.append(f"Every past exchange is in {LOG} (one JSON object per line: ts, heard, "
                     "reply, via). If he asks about something older than this, grep it.")
        return "\n".join(parts) + "\n"

    # ------------------------------------------------------------ summary

    def _maybe_summarize(self):
        """Fold exchanges into the summary once `summarize_every` of them
        have scrolled past the recent window."""
        recent = int(self.cfg.get("memory.recent"))
        every = int(self.cfg.get("memory.summarize_every"))
        with self.lock:
            if self.summarizing or self._state().get("pending", 0) < recent + every:
                return
            self.summarizing = True
        threading.Thread(target=self._summarize_now, daemon=True, name="memory-summary").start()

    def _summarize_now(self):
        try:
            recent = int(self.cfg.get("memory.recent"))
            with self.lock:
                pending = self._state().get("pending", 0)
            fold = pending - recent
            if fold <= 0:
                return
            rows = self.recent(pending)[:fold]
            text = "\n".join(f"[{r['ts'][:16]}] Sao: {_clip(r['heard'], 400)} | Jarvis: {_clip(r['reply'], 500)}"
                             for r in rows)
            new = self.summarize(SUMMARY_PROMPT.format(summary=self.summary() or "(none yet)", exchanges=text))
            if not new:
                return
            with self.lock:
                tmp = SUMMARY.with_suffix(".tmp")
                tmp.write_text(new.strip() + "\n")
                tmp.replace(SUMMARY)
                state = self._state()
                # Exchanges recorded while we ran stay pending.
                state["pending"] = max(0, state.get("pending", 0) - fold)
                self._save_state(state)
            self.log(f"memory: folded {fold} exchanges into the summary")
        except Exception as e:
            self.log(f"memory: summary failed: {e!r}")
        finally:
            self.summarizing = False

    def _summarize_with_claude(self, prompt):
        from .brain import find_claude
        # A bare summarizer: its own system prompt, no tools, and a cwd
        # outside $HOME. Run from the project, it read CLAUDE.md files and
        # folded their contents into the summary as if Sao had said them.
        r = subprocess.run(
            [find_claude(), "-p", "--model", self.cfg.get("memory.summary_model"),
             "--no-session-persistence", "--output-format", "text", "--tools", "",
             "--system-prompt", "You summarize conversation logs. Use only the text you are given."],
            input=prompt, capture_output=True, text=True, timeout=180, cwd="/tmp",
            env={**os.environ, "CLAUDE_CODE_ENTRYPOINT": "jarvis-memory"},
        )
        if r.returncode != 0:
            raise RuntimeError(f"claude exited {r.returncode}: {r.stderr[-300:]}")
        return r.stdout.strip()
