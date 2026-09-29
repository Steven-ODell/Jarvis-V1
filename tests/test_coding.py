from pathlib import Path

import pytest

from jarvis import coding, fastpath

P = [(n, Path("/p") / n) for n in [
    "CHIP-8", "ParserV2", "ParserV3", "mdparser1", "Term_File_Search", "day_one", "day_two",
    "gitdeck", "osintdeck", "Term-Crypto-Deck", "sweaty-daw", "sweaty-search", "Kore-Storm-Leads",
    "Korestorming", "minecraft-cpp-tutorial", "jarvis", "tatr"]]
ALIASES = {"coindeck": "Term-Crypto-Deck"}


@pytest.mark.parametrize("said,want", [
    ("gitdeck", "gitdeck"), ("get deck", "gitdeck"), ("chip eight", "CHIP-8"),
    ("term file search", "Term_File_Search"), ("sweaty door", "sweaty-daw"),
    ("core storm leads", "Kore-Storm-Leads"), ("coin deck", "Term-Crypto-Deck"),
    ("minecraft", "minecraft-cpp-tutorial"), ("parser v three", "ParserV3"), ("tatter", "tatr"),
])
def test_misheard_names_resolve(said, want):
    kind, got = coding.resolve(said, P, ALIASES)
    assert (kind, got[0][0]) == ("one", want)


@pytest.mark.parametrize("said,want", [
    ("parser", {"ParserV2", "ParserV3"}), ("sweaty", {"sweaty-daw", "sweaty-search"}),
    ("kore storm", {"Kore-Storm-Leads", "Korestorming"}),
])
def test_ambiguous_names_ask(said, want):
    kind, got = coding.resolve(said, P, ALIASES)
    assert kind == "some" and {n for n, _ in got} == want


@pytest.mark.parametrize("said", ["my resume", "what's the weather", "volume up"])
def test_non_projects_dont_match(said):
    assert coding.resolve(said, P)[0] == "none"


def test_answers_to_either_or():
    c = [("ParserV2", 1), ("ParserV3", 2), ("mdparser1", 3)]
    assert coding.pick("the second one", c)[0] == "ParserV3"
    assert coding.pick("three", c)[0] == "ParserV3"
    assert coding.pick("v two", c)[0] == "ParserV2"
    assert coding.pick("md parser", c)[0] == "mdparser1"
    assert coding.pick("yes", c) is None
    assert coding.pick("yeah", c[:1])[0] == "ParserV2"
    assert coding.either(c[:2]) == "Did you mean Parser V 2 or Parser V 3?"


@pytest.mark.parametrize("said,name", [
    ("Hey Jarvis, let's code.", None), ("I want to code", None), ("Let's do some coding.", None),
    ("let's code on gitdeck", "gitdeck"), ("I want to work on some code", None),
])
def test_triggers(said, name):
    m = coding.TRIGGER.fullmatch(fastpath.normalize(said))
    assert m and m.group("name") == name


def test_projects_layout(tmp_path, monkeypatch):
    for d in ["CPP/ParserV3", "Side/jarvis", "Korestorming/.git", "Korestorming/src", "Empty"]:
        (tmp_path / d).mkdir(parents=True)
    monkeypatch.setattr(coding, "PROJECTS", tmp_path)
    assert [n for n, _ in coding.projects()] == ["ParserV3", "Empty", "Korestorming", "jarvis"]


@pytest.mark.parametrize("said,rest,tool", [
    ("let's code on gitdeck with claude", "code on gitdeck", "claude"),
    ("I want to code in neovim", "code", "neovim"),
    ("let's code on jarvis in nvim", "code on jarvis", "nvim"),
])
def test_tool_override(said, rest, tool):
    m = coding.TOOL.fullmatch(fastpath.normalize(said))
    assert (m.group("rest"), m.group("tool")) == (rest, tool)


def test_useful_files_prefers_recent_work(tmp_path):
    import subprocess
    run = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    run("init", "-q")
    for f in ["old.py", "main.cpp", "README.md", "package-lock.json", "node_modules/x.js"]:
        (tmp_path / f).parent.mkdir(exist_ok=True)
        (tmp_path / f).write_text("x")
    run("add", "-A")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one")
    (tmp_path / "main.cpp").write_text("changed")
    (tmp_path / "new.py").write_text("new")
    files = coding.useful_files(tmp_path, 8)
    assert files[:2] == ["main.cpp", "new.py"]
    assert "README.md" == files[-1]
    assert "package-lock.json" not in files and "node_modules/x.js" not in files


@pytest.mark.parametrize("said", ["It's code on git deck.", "Lets code on gitdeck", "its coding time"])
def test_misheard_lets(said):
    t = coding.LEAD.sub("", fastpath.normalize(said))
    assert coding.TRIGGER.fullmatch(t)


def test_lead_leaves_other_sentences_alone():
    assert coding.LEAD.sub("", "it's raining") == "it's raining"
