import json
import time

import pytest

from jarvis import memory


class Cfg:
    def __init__(self, **kw):
        self.v = {"memory.recent": 3, "memory.summarize_every": 2, "memory.summary_model": "haiku", **kw}

    def get(self, k):
        return self.v[k]


@pytest.fixture
def mem_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEM_DIR", tmp_path)
    monkeypatch.setattr(memory, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(memory, "SUMMARY", tmp_path / "summary.md")
    monkeypatch.setattr(memory, "STATE", tmp_path / "state.json")
    return tmp_path


def wait_idle(m):
    for _ in range(100):
        if not m.summarizing:
            return
        time.sleep(0.01)


def test_empty_memory_adds_nothing(mem_dir):
    assert memory.Memory(Cfg(), print).context() == ""


def test_recent_window_skips_fast_path(mem_dir):
    m = memory.Memory(Cfg(), print, summarize=lambda p: None)
    for i in range(5):
        m.record(f"question {i}", f"answer {i}", "claude")
        m.record("volume up", "Volume up.", "fast")
    rows = m.recent()
    assert [r["heard"] for r in rows] == ["question 2", "question 3", "question 4"]
    ctx = m.context()
    assert "question 4" in ctx and "question 1" not in ctx and "volume up" not in ctx
    # Everything, fast path included, stays on disk.
    assert len((mem_dir / "log.jsonl").read_text().splitlines()) == 10


def test_summary_folds_what_scrolled_out(mem_dir):
    prompts = []

    def fake(prompt):
        prompts.append(prompt)
        return "Sao likes purple."

    m = memory.Memory(Cfg(), print, summarize=fake)
    for i in range(4):  # recent 3 + every 2 = 5 needed; not yet
        m.record(f"q{i}", f"a{i}", "claude")
    wait_idle(m)
    assert prompts == []
    m.record("q4", "a4", "claude")
    wait_idle(m)
    assert len(prompts) == 1
    assert "q0" in prompts[0] and "q1" in prompts[0] and "q2" not in prompts[0]
    assert json.loads((mem_dir / "state.json").read_text())["pending"] == 3
    ctx = m.context()
    assert "Sao likes purple." in ctx and "q4" in ctx


def test_tail_reads_long_logs(mem_dir):
    with open(mem_dir / "log.jsonl", "w") as f:
        for i in range(20000):
            f.write(json.dumps({"ts": "2026-09-28T10:00:00", "heard": f"q{i}", "reply": "x" * 50,
                                "via": "claude"}) + "\n")
    rows = memory.Memory(Cfg(), print).recent()
    assert [r["heard"] for r in rows] == ["q19997", "q19998", "q19999"]
