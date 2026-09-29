"""Voice coding mode: "let's code" -> "Which project?" -> a terminal there.

Projects are the folders under ~/Projects. A top-level folder that is a git
repo (or has no subfolders) is a project itself; the others (CPP, Side, JS,
...) are groups whose subfolders are the projects. Spoken names are matched
loosely, since whisper hears "get deck" for gitdeck and "chip eight" for
CHIP-8.
"""

import os
import re
import shlex
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

from . import actions
from .config import STATE_DIR

PROJECTS = Path.home() / "Projects"

# Matched against fastpath.normalize() output, which has already peeled
# "hey jarvis", "let's" and "I want to" off the front.
TRIGGER = re.compile(
    r"(?:code|coding|start coding|do some coding|get coding|write (?:some )?code|"
    r"(?:it'?s )?coding time|open (?:a |my )?project|work on (?:a |some |my )?(?:code|project))"
    r"(?: (?:on|in|with|for) (?P<name>.+))?"
)
# Whisper often hears "let's code" as "it's code" or "lets code".
LEAD = re.compile(r"^(?:it'?s|lets|let us|let's)\s+(?=cod|work|open|hack|do|get|write|start)")

# "... with Claude" / "... in Neovim" at the end overrides code.open once.
TOOL = re.compile(r"(?P<rest>.*?)\s*\b(?:with|in|using|and open|open) (?P<tool>claude(?: code)?|neo ?vim|n ?vim|vim)$")

# "let's work on gitdeck": only claimed when the name is clearly a project,
# so "work on my resume" still goes to Claude.
WORK_ON = re.compile(r"(?:work on|hack on|open the project|code) (?P<name>.+)")
CANCEL = re.compile(r"(?:never ?mind|cancel|forget it|stop|nothing|no|nope)(?: thanks?| thank you)?")
YES = re.compile(r"(?:yes|yeah|yep|yup|sure|correct|right|that one|that's (?:it|right|the one))")
ORDINALS = {"first": 0, "second": 1, "third": 2, "last": -1}
COUNTS = {"one": 0, "1": 0, "two": 1, "2": 1, "three": 2, "3": 2}

NUMBERS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
           "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10"}
NOISE = {"the", "my", "a", "project", "projects", "folder", "repo", "directory", "please", "on", "in"}

SURE = 0.74     # best score needed to open without asking
MAYBE = 0.55    # below this it's not a project name at all
TIE = 0.07      # scores this close to the best are "ambiguous"


def named_request(text):
    """The project name in "let's code on X" (tool suffix removed), else None."""
    from .fastpath import normalize
    t = LEAD.sub("", normalize(text))
    m = TOOL.fullmatch(t)
    if m:
        t = m.group("rest")
    m = TRIGGER.fullmatch(t)
    return m.group("name") if m else None


def projects():
    """[(display name, path)] for everything under ~/Projects."""
    out = []
    if not PROJECTS.is_dir():
        return out
    for top in sorted(PROJECTS.iterdir()):
        if not top.is_dir() or top.name.startswith("."):
            continue
        kids = [k for k in sorted(top.iterdir()) if k.is_dir() and not k.name.startswith(".")]
        if (top / ".git").exists() or not kids:
            out.append((top.name, top))
        else:
            out += [(k.name, k) for k in kids]
    return out


def spoken(name):
    """How a folder name sounds: Term_File_Search -> "term file search",
    ParserV3 -> "parser v 3", CHIP-8 -> "chip 8"."""
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    s = re.sub(r"([A-Za-z])(\d)", r"\1 \2", s)
    s = re.sub(r"(\d)([A-Za-z])", r"\1 \2", s)
    return re.sub(r"[-_.]+", " ", s).strip()


def key(text):
    words = re.sub(r"[^a-z0-9 ]+", " ", spoken(text).lower()).split()
    words = [NUMBERS.get(w, w) for w in words]
    kept = [w for w in words if w not in NOISE]
    return " ".join(kept or words)


def _sound(s):
    """A crude phonetic squash: "core" ~ "kore", "sweaty daw" ~ "sweatydaw"."""
    s = s.replace(" ", "").replace("ph", "f").replace("ck", "k").replace("c", "k").replace("z", "s")
    return re.sub(r"(.)\1+", r"\1", s)


def score(query, name):
    a, b = key(query), key(name)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ca, cb = a.replace(" ", ""), b.replace(" ", "")
    if ca == cb:
        return 0.98
    r = max(SequenceMatcher(None, ca, cb).ratio(), SequenceMatcher(None, _sound(ca), _sound(cb)).ratio())
    # Saying part of a long name ("minecraft" for minecraft-cpp-tutorial)
    # counts, as long as it's more than one short word ("deck" is not).
    if len(ca) >= 5 and set(a.split()) <= set(b.split()):
        r = max(r, 0.78 + 0.2 * len(ca) / len(cb))
    return r


def rank(query, candidates, aliases=None):
    """Best-first [(score, name, path)], one entry per project."""
    names = {}
    for name, path in candidates:
        names.setdefault(path, []).append(name)
    for alias, target in (aliases or {}).items():
        for name, path in candidates:
            if name.lower() == target.lower():
                names[path].append(alias)
    scored = []
    for name, path in candidates:
        best = max(score(query, n) for n in names[path])
        scored.append((best, name, path))
    return sorted(scored, key=lambda s: -s[0])


def resolve(query, candidates, aliases=None):
    """("one", [(name, path)]) to open, ("some", [...]) to ask about, or
    ("none", [])."""
    ranked = rank(query, candidates, aliases)
    if not ranked or ranked[0][0] < MAYBE:
        return "none", []
    top = ranked[0][0]
    close = [(n, p) for s, n, p in ranked if s >= top - TIE][:3]
    if len(close) == 1 and top >= SURE:
        return "one", close
    return "some", close


def pick(text, cands):
    """His answer to "X or Y?": a name, "the second one", or a yes when
    there was only one guess."""
    words = re.sub(r"[^a-z0-9' ]+", " ", text.lower()).split()
    for w in words:
        if w in ORDINALS and (ORDINALS[w] < len(cands)):
            return cands[ORDINALS[w]]
    if len(cands) == 1 and YES.fullmatch(" ".join(words)):
        return cands[0]
    # A name first: among ParserV2 / ParserV3, "three" and "v two" name one.
    said = set(key(text).split())
    hits = [c for c in cands if said and said <= set(key(c[0]).split())]
    if len(hits) == 1:
        return hits[0]
    kind, got = resolve(text, cands)
    if kind == "one" or (kind == "some" and len(got) == 1):
        return got[0]
    if len(words) == 1 and words[0] in COUNTS and COUNTS[words[0]] < len(cands):
        return cands[COUNTS[words[0]]]
    return None


def say_name(name):
    return spoken(name)


def either(cands):
    names = [say_name(n) for n, _ in cands]
    if len(names) == 1:
        return f"Did you mean {names[0]}?"
    return "Did you mean " + ", ".join(names[:-1]) + " or " + names[-1] + "?"


SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "build", "dist", "target", "out",
             "__pycache__", ".cache", ".next", "models", "bin", "obj", ".pytest_cache", "vendor"}
CODE_EXT = {".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".qml", ".frag", ".vert", ".glsl", ".c", ".cc",
            ".cpp", ".cxx", ".h", ".hh", ".hpp", ".rs", ".go", ".lua", ".sh", ".java", ".kt", ".cs",
            ".html", ".css", ".scss", ".vue", ".svelte", ".sql", ".zig"}
DOC_EXT = {".md", ".toml", ".json", ".yaml", ".yml", ".txt", ".cmake", ".ini", ".cfg"}
CODE_NAMES = {"Makefile", "CMakeLists.txt", "justfile", "Dockerfile"}
JUNK = re.compile(r"(?:[-.]lock\.(?:json|ya?ml)|\.lock|\.min\.(?:js|css)|\.map|\.qsb)$")


def _wanted(root, rel):
    p = root / rel
    if JUNK.search(rel) or any(part in SKIP_DIRS for part in Path(rel).parts[:-1]):
        return False
    if not (p.suffix in CODE_EXT or p.suffix in DOC_EXT or p.name in CODE_NAMES):
        return False
    try:
        return p.is_file() and p.stat().st_size < 2_000_000
    except OSError:
        return False


def _git(root, *args):
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=2)
        return r.stdout.splitlines() if r.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired):
        return []


def useful_files(root, n=8):
    """The files he's most likely to want open, most relevant first:
    uncommitted changes, then what recent commits touched, then the newest
    source files on disk. Code before docs."""
    root = Path(root)
    seen = []

    def add(rel):
        rel = rel.strip().strip('"')
        if rel and rel not in seen and _wanted(root, rel):
            seen.append(rel)

    if (root / ".git").exists():
        for line in _git(root, "status", "--porcelain", "-uall"):
            if line[:2].strip() != "D":
                add(line[3:].split(" -> ")[-1])
        for line in _git(root, "log", "-n", "20", "--name-only", "--pretty=format:"):
            add(line)
    if len(seen) < n:
        found = []
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for f in files:
                rel = os.path.relpath(os.path.join(dirpath, f), root)
                if _wanted(root, rel):
                    found.append((os.path.getmtime(os.path.join(dirpath, f)), rel))
            if len(found) > 5000:
                break
        for _, rel in sorted(found, reverse=True):
            add(rel)
    code = [r for r in seen if Path(r).suffix not in DOC_EXT]
    docs = [r for r in seen if Path(r).suffix in DOC_EXT]
    return (code + docs)[:n]


def open_project(path, tool="nvim", max_files=8):
    """A ghostty window in the project running nvim (with buffers) or
    Claude Code; quitting either leaves a shell there."""
    if tool == "claude":
        cmd = "claude"
    else:
        files = useful_files(path, max_files)
        cmd = "nvim" + ("".join(" " + shlex.quote(f) for f in ["--", *files]) if files else " .")
    log_to = shlex.quote(str(STATE_DIR / "code-launch.log"))
    actions.spawn(f"uwsm app -- ghostty --working-directory={shlex.quote(str(path))} "
                  f"-e zsh -ic {shlex.quote(cmd + '; exec zsh')} >>{log_to} 2>&1")
