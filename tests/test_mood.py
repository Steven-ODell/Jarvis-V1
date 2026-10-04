from jarvis.mood import MoodFilter, react, strip


def run(chunks):
    moods = []
    f = MoodFilter(moods.append)
    text = "".join(f.feed(c) for c in chunks) + f.flush()
    return text, moods


def test_tag_whole():
    assert run(["[happy] Good evening, sir."]) == ("Good evening, sir.", ["happy"])


def test_tag_split_across_deltas():
    assert run(["[ha", "ppy", "] Hi.", " [sad]", " Sorry."]) == ("Hi. Sorry.", ["happy", "sad"])


def test_alias_and_unknown_brackets_kept():
    assert run(["[worried] It failed [exit 2]."]) == ("It failed [exit 2].", ["sad"])


def test_long_bracket_not_held():
    t, m = run(["see [this is not a tag at all] ok"])
    assert t == "see [this is not a tag at all] ok" and m == []


def test_strip():
    assert strip("[happy] Done. [sad] But one failed.") == "Done. But one failed."


def test_react():
    assert react("no way, really?") == "surprised"
    assert react("my dog died today") == "sad"
    assert react("thanks Jarvis") == "happy"
    assert react("open firefox") is None
