"""Fast-path routing. Actions aren't executed; only what gets matched."""

import pytest

from jarvis import fastpath


def m(text):
    return fastpath.match(text, "google")


@pytest.mark.parametrize("text,reply", [
    ("Open GitHub.", "Opening GitHub."),
    ("open gethub", "Opening GitHub."),
    ("Jarvis, open YouTube please", "Opening YouTube."),
    ("Can you pull up Hacker News?", "Opening Hacker News."),
    ("Go to reddit dot com slash r slash unixporn", "Opening reddit.com."),
    ("open docs.python.org", "Opening docs.python.org."),
    ("Search YouTube for Hyprland rice", "Searching YouTube."),
    ("search for best filament dryer", "Searching."),
    ("Look up PETG settings on Printables", "Searching Printables."),
    ("What time is it?", None),
    ("Set a timer for five minutes", "Timer set for 5 minutes."),
    ("Remind me in 10 minutes to check the print", "I'll remind you in 10 minutes."),
    ("Use opus", "Switching to Opus."),
    ("turn on the wake word", "Wake word on."),
    ("New conversation", "Starting fresh."),
])
def test_matches(text, reply):
    got = m(text)
    assert got is not None, text
    if reply is not None:
        assert got.reply == reply


@pytest.mark.parametrize("text", [
    "open GitHub and find my newest repo",
    "what's on my calendar tomorrow",
    "search my email for the invoice",
    "summarize this page",
    "why is my wifi slow",
    "open the file I was working on yesterday",
])
def test_falls_through_to_claude(text):
    assert m(text) is None, text


@pytest.mark.parametrize("text,control", [
    ("never mind", "cancel"),
    ("Stop.", "cancel"),
    ("start over", "reset"),
    ("open settings", "settings"),
])
def test_controls(text, control):
    assert m(text).control == control


def test_workspace_words():
    assert m("go to workspace three") is not None
    assert m("workspace 4") is not None


@pytest.mark.parametrize("text", [
    "Initiate workstation.",
    "Jarvis, initiate work station",
    "start my workstation",
    "work mode",
    "set up my work desk",
])
def test_workstation(text):
    got = m(text)
    assert got is not None and got.reply == "Setting up your workstation.", text


def test_volume():
    assert m("set volume to 40 percent") is not None
    assert m("turn it up") is not None
    assert m("mute") is not None


def test_type_keeps_case():
    got = m("Type Hello World.")
    assert got is not None and got.run is not None


def test_apps_resolve():
    assert m("open terminal").reply.startswith("Opening")
    assert m("launch files") is not None
    assert m("open lazygit") is not None
