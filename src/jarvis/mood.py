"""Moods for the face.

Two sources, both free in latency:
- Claude puts a tag like [happy] before a sentence. MoodFilter strips tags
  out of the streamed reply before it reaches the voice or the captions,
  and reports each one the moment it arrives, so the face changes on the
  sentence it belongs to.
- react() looks at what Sao said and gives an instant reaction while
  Claude is still thinking ("no way" -> surprised).
"""

import re

MOODS = ("neutral", "happy", "sad", "surprised", "confused")

# Words Claude might reach for that map onto a face we have.
ALIASES = {
    "excited": "happy", "glad": "happy", "amused": "happy", "pleased": "happy", "joy": "happy",
    "sorry": "sad", "concerned": "sad", "worried": "sad", "apologetic": "sad", "disappointed": "sad",
    "shocked": "surprised", "amazed": "surprised", "wow": "surprised",
    "puzzled": "confused", "unsure": "confused", "curious": "confused",
    "calm": "neutral", "serious": "neutral",
}

TAG = re.compile(r"\[\s*([a-zA-Z]{3,14})\s*\]\s*")


def resolve(word):
    w = word.lower()
    if w in MOODS:
        return w
    return ALIASES.get(w)


def strip(text):
    """Remove mood tags from a finished reply (for memory and captions)."""
    return TAG.sub(lambda m: "" if resolve(m.group(1)) else m.group(0), text).strip()


class MoodFilter:
    """Streaming tag stripper. feed() returns the text that is safe to pass
    on and calls on_mood for each tag. A tag split across deltas is held
    back until its closing bracket arrives (or it clearly isn't a tag)."""

    def __init__(self, on_mood):
        self.on_mood = on_mood
        self.held = ""
        self.at_tag_end = False

    def feed(self, delta):
        s = self.held + delta
        self.held = ""
        out = []
        i = 0
        while i < len(s):
            # Drop the space after a tag so "[sad] Sorry" speaks as "Sorry".
            if self.at_tag_end and s[i] in " \t":
                i += 1
                continue
            self.at_tag_end = False
            if s[i] != "[":
                j = s.find("[", i)
                j = len(s) if j < 0 else j
                out.append(s[i:j])
                i = j
                continue
            close = s.find("]", i)
            if close < 0:
                rest = s[i:]
                if len(rest) <= 16 and re.fullmatch(r"\[\s*[a-zA-Z]*\s*", rest):
                    self.held = rest  # might be the start of a tag
                    break
                out.append("[")
                i += 1
                continue
            mood = resolve(s[i + 1:close].strip())
            if mood:
                self.on_mood(mood)
                self.at_tag_end = True
            else:
                out.append(s[i:close + 1])
            i = close + 1
        return "".join(out)

    def flush(self):
        rest, self.held = self.held, ""
        return rest


# Instant reactions to what he said. First match wins, so the order matters
# a little: "that's not funny" should not read as happy.
REACT = [
    ("surprised", r"\b(no way|wow|whoa|holy|what the|are you serious|seriously\?|i'?m (so )?surprised|can'?t believe|unbelievable|guess what)\b"),
    ("sad", r"\b(sad|died|passed away|lost my|bad news|sucks|depress\w*|miserable|awful day|terrible day|i'?m sorry|heartbroken|crying)\b"),
    ("confused", r"\b(huh|i'?m confused|doesn'?t make sense|what do you mean|i don'?t (get|understand))\b"),
    ("happy", r"\b(thank(s| you)|awesome|amazing|love (it|you|that)|haha|lol|great job|nice one|good job|perfect|that'?s great|yay|i'?m (so )?happy|good morning)\b"),
]
REACT = [(m, re.compile(p, re.I)) for m, p in REACT]


def react(text):
    for mood, pat in REACT:
        if pat.search(text or ""):
            return mood
    return None
