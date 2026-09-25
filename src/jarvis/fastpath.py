"""Commands handled locally in milliseconds, no model involved.

match() only claims an utterance when the whole sentence fits a pattern and
the target resolves. Anything fuzzier ("open GitHub and find my newest repo")
falls through to Claude, which is slower but understands it.
"""

import datetime as dt
import difflib
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import actions

SITES = {
    "github": "https://github.com",
    "youtube": "https://youtube.com",
    "reddit": "https://reddit.com",
    "hacker news": "https://news.ycombinator.com",
    "gmail": "https://mail.google.com",
    "email": "https://mail.google.com",
    "google": "https://google.com",
    "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com",
    "google docs": "https://docs.google.com",
    "google calendar": "https://calendar.google.com",
    "calendar": "https://calendar.google.com",
    "google maps": "https://maps.google.com",
    "maps": "https://maps.google.com",
    "kagi": "https://kagi.com",
    "chatgpt": "https://chatgpt.com",
    "claude ai": "https://claude.ai",
    "claude dot ai": "https://claude.ai",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "amazon": "https://amazon.com",
    "netflix": "https://netflix.com",
    "wikipedia": "https://wikipedia.org",
    "stack overflow": "https://stackoverflow.com",
    "arch wiki": "https://wiki.archlinux.org",
    "aur": "https://aur.archlinux.org",
    "omarchy manual": "https://learn.omacom.io/2/the-omarchy-manual",
    "omarchy": "https://omarchy.org",
    "hyprland wiki": "https://wiki.hypr.land",
    "twitch": "https://twitch.tv",
    "linkedin": "https://linkedin.com",
    "indeed": "https://indeed.com",
    "weather": "https://weather.com",
    "printables": "https://printables.com",
    "thingiverse": "https://thingiverse.com",
    "makerworld": "https://makerworld.com",
}

SEARCH = {
    "google": "https://www.google.com/search?q={}",
    "kagi": "https://kagi.com/search?q={}",
    "duckduckgo": "https://duckduckgo.com/?q={}",
    "brave": "https://search.brave.com/search?q={}",
    "youtube": "https://www.youtube.com/results?search_query={}",
    "github": "https://github.com/search?q={}&type=repositories",
    "reddit": "https://www.reddit.com/search/?q={}",
    "amazon": "https://www.amazon.com/s?k={}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={}",
    "maps": "https://www.google.com/maps/search/{}",
    "google maps": "https://www.google.com/maps/search/{}",
    "the aur": "https://aur.archlinux.org/packages?K={}",
    "aur": "https://aur.archlinux.org/packages?K={}",
    "arch wiki": "https://wiki.archlinux.org/index.php?search={}",
    "printables": "https://www.printables.com/search/models?q={}",
}

NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "to": 2, "too": 2, "three": 3, "four": 4, "for": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty five": 45,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
    "a": 1, "an": 1,
}


def num(word):
    word = word.strip()
    if word.isdigit():
        return int(word)
    return NUMBERS.get(word)


@dataclass
class Match:
    reply: str = ""                          # spoken ack; "" = silent
    run: Optional[Callable[[], None]] = None
    control: Optional[str] = None            # handled by the daemon: cancel, reset, ...
    arg: object = None
    keeps_media_paused: bool = False         # "pause the music" must not be undone
    tags: list = field(default_factory=list)


FILLER = re.compile(
    r"^(?:(?:hey|ok|okay|yo)\s+)?(?:jarvis[,\s]+)?(?:(?:can|could|would|will)\s+you\s+|please\s+|go\s+ahead\s+and\s+|i\s+want\s+to\s+|let'?s\s+)*",
)


def normalize(text):
    t = text.lower().strip()
    t = t.replace("’", "'")
    t = re.sub(r"[,!?]+", " ", t)
    t = re.sub(r"\.(?=\s|$)", " ", t)          # sentence dots, not "reddit.com"
    t = re.sub(r"\s+dot\s+(com|org|net|io|dev|ai|co|gov|edu|tv|app)\b", r".\1", t)
    t = re.sub(r"\s+slash\s+", "/", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = FILLER.sub("", t)
    prev = None
    while prev != t:  # "open github now please" has two to peel off
        prev = t
        t = re.sub(r"\s+(?:please|for me|right now|now|real quick|thanks|thank you)$", "", t)
    return t.strip()


def resolve_site(target):
    target = target.strip()
    target = re.sub(r"^(?:the\s+)?(?:website\s+|site\s+)?", "", target)
    target = re.sub(r"\s+(?:website|site|page|homepage)$", "", target)
    # Spoken domains: "reddit.com/r/unixporn", "docs.python.org".
    if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?", target.replace(" ", "")) and "." in target:
        return "https://" + target.replace(" ", "")
    if target in SITES:
        return SITES[target]
    squashed = target.replace(" ", "")
    for name, url in SITES.items():
        if squashed == name.replace(" ", ""):
            return url
    hit = difflib.get_close_matches(target, SITES.keys(), n=1, cutoff=0.8)
    return SITES[hit[0]] if hit else None


def pretty_site(url):
    host = urllib.parse.urlparse(url).netloc.removeprefix("www.")
    names = {v: k for k, v in SITES.items()}
    name = names.get(url)
    if name:
        return {"github": "GitHub", "youtube": "YouTube", "chatgpt": "ChatGPT", "aur": "the AUR",
                "hacker news": "Hacker News", "x": "X"}.get(name, name.title())
    return host


def match(text, search_engine="google"):
    t = normalize(text)
    if not t:
        return None

    # ---- Jarvis itself
    if re.fullmatch(r"(?:never ?mind|cancel|stop|shut up|be quiet|quiet|stop talking|that's all|nothing)", t):
        return Match(control="cancel")
    if re.fullmatch(r"(?:new|fresh|start a new) (?:conversation|chat|session)|start over|reset|forget (?:that|everything)|clear (?:the )?(?:conversation|context)", t):
        return Match(reply="Starting fresh.", control="reset")
    m = re.fullmatch(r"(?:turn |switch )?(on|off|enable|disable) (?:the )?wake ?word|(?:turn |switch )?(?:the )?wake ?word (on|off)", t)
    if m:
        on = (m.group(1) or m.group(2)) in ("on", "enable")
        return Match(reply=f"Wake word {'on' if on else 'off'}.", control="set", arg=("wake.enabled", on))
    m = re.fullmatch(r"(?:use|switch to|change to) (haiku|sonnet|opus)(?: model)?", t)
    if m:
        return Match(reply=f"Switching to {m.group(1).title()}.", control="set", arg=("brain.model", m.group(1)))
    if re.fullmatch(r"(?:open |show )?(?:jarvis |your )?settings", t):
        return Match(control="settings")

    # ---- time and date
    if re.fullmatch(r"what(?:'s| is) the time(?: right now)?|what time is it(?: right now)?|time|got the time", t):
        now = dt.datetime.now()
        return Match(reply=f"It's {now.strftime('%-I:%M %p')}.")
    if re.fullmatch(r"what(?:'s| is) (?:the date|today's date|today)(?: today)?|what day is (?:it|today)(?: today)?|what's today", t):
        now = dt.datetime.now()
        return Match(reply=f"It's {now.strftime('%A, %B %-d')}.")

    # ---- search
    site = query = None
    m = re.fullmatch(r"(?:search|look up|find) (?:on )?(\w+(?: \w+)?) for (.+)", t)
    if m and m.group(1) in SEARCH:
        site, query = m.group(1), m.group(2)
    if site is None:
        m = re.fullmatch(r"(?:search(?: for)?|look up|find|google) (.+) (?:on|in) (\w+(?: \w+)?)", t)
        if m and m.group(2) in SEARCH:
            site, query = m.group(2), m.group(1)
    if site is None:
        # Default engine only for plain "search X" / "google X". "look up
        # what's on my calendar" is a question for Claude, not a web search.
        m = re.fullmatch(r"(?:search(?: for| the web for)?|google) (.+)", t)
        if m and not re.search(r"\b(?:and|then|my|me)\b", m.group(1)):
            site, query = search_engine, m.group(1)
    if site and query:
        url = SEARCH[site].format(urllib.parse.quote_plus(query))
        where = "" if site == search_engine else f" {pretty_site(SITES.get(site, site))}"
        return Match(reply=f"Searching{where}.", run=lambda: actions.open_url(url))

    # ---- workspaces and windows
    m = re.fullmatch(r"(?:go to |switch to |show )?workspace (\w+)", t)
    if m and num(m.group(1)) is not None:
        n = num(m.group(1))
        return Match(run=lambda: actions.hypr("workspace", n))
    m = re.fullmatch(r"(?:move|send) (?:this|it|this window|the window) to workspace (\w+)", t)
    if m and num(m.group(1)) is not None:
        n = num(m.group(1))
        return Match(run=lambda: actions.hypr("movetoworkspace", n))
    if re.fullmatch(r"close (?:this|it|this window|the window|window)", t):
        return Match(run=lambda: actions.hypr("killactive"))
    if re.fullmatch(r"(?:make (?:this|it) )?full ?screen|toggle full ?screen", t):
        return Match(run=lambda: actions.hypr("fullscreen", 0))
    if re.fullmatch(r"(?:toggle |make (?:this|it) )?float(?:ing)?", t):
        return Match(run=lambda: actions.hypr("togglefloating"))

    # ---- volume, brightness, media
    m = re.fullmatch(r"(?:set )?(?:the )?volume (?:to )?(\w+)(?: percent| %)?", t) or \
        re.fullmatch(r"(?:set|put) (?:the )?volume (?:at|to) (\w+)(?: percent| %)?", t)
    if m and num(m.group(1)) is not None:
        n = num(m.group(1))
        return Match(run=lambda: actions.volume(n))
    if re.fullmatch(r"(?:turn (?:it|the volume|the music) up|volume up|louder|raise (?:the )?volume)", t):
        return Match(run=lambda: actions.volume("+10"))
    if re.fullmatch(r"(?:turn (?:it|the volume|the music) down|volume down|quieter|lower (?:the )?volume)", t):
        return Match(run=lambda: actions.volume("-10"))
    if re.fullmatch(r"(?:un)?mute(?: (?:the )?(?:volume|sound|audio|it))?", t):
        return Match(run=lambda: actions.volume("mute-toggle"))
    m = re.fullmatch(r"(?:set )?(?:the )?brightness (?:to )?(\w+)(?: percent| %)?", t)
    if m and num(m.group(1)) is not None:
        n = num(m.group(1))
        return Match(run=lambda: actions.brightness(f"{n}%"))
    if re.fullmatch(r"(?:brightness up|brighter|turn (?:the )?brightness up|increase (?:the )?brightness)", t):
        return Match(run=lambda: actions.brightness("+10%"))
    if re.fullmatch(r"(?:brightness down|dimmer|dim (?:the )?screen|turn (?:the )?brightness down|decrease (?:the )?brightness)", t):
        return Match(run=lambda: actions.brightness("10%-"))
    if re.fullmatch(r"(?:pause|stop) (?:the )?(?:music|song|playback|video|media|audio)|pause", t):
        return Match(run=lambda: actions.media("Pause"), keeps_media_paused=True)
    if re.fullmatch(r"(?:play|resume|unpause)(?: (?:the )?(?:music|song|playback|video|media))?", t):
        return Match(run=lambda: actions.media("Play"), keeps_media_paused=True)
    if re.fullmatch(r"(?:next|skip)(?: (?:song|track|this))?|skip (?:this )?(?:song|track)", t):
        return Match(run=lambda: actions.media("Next"))
    if re.fullmatch(r"(?:previous|last|go back)(?: (?:song|track))?", t):
        return Match(run=lambda: actions.media("Previous"))

    # ---- system
    if re.fullmatch(r"lock(?: (?:the|my))?(?: screen| computer| laptop)?", t):
        return Match(run=lambda: actions.spawn(["omarchy", "system", "lock"]))
    if re.fullmatch(r"(?:take a |grab a )?screenshot|screen ?shot", t):
        return Match(run=lambda: actions.spawn(["omarchy", "capture", "screenshot", "fullscreen", "save"]))

    # ---- reminders and timers
    m = re.fullmatch(r"(?:set a |start a )?timer (?:for )?(\w+(?: \w+)?) minutes?", t) or \
        re.fullmatch(r"(?:set a |start a )?(\w+(?: \w+)?) minute timer", t)
    if m and num(m.group(1)) is not None:
        n = num(m.group(1))
        return Match(reply=f"Timer set for {n} minute{'s' if n != 1 else ''}.",
                     run=lambda: actions.run(["omarchy", "reminder", str(n), "Timer done"]))
    m = re.fullmatch(r"remind me in (\w+(?: \w+)?) minutes? (?:to |about |that )?(.+)", t) or \
        re.fullmatch(r"remind me (?:to |about )?(.+) in (\w+(?: \w+)?) minutes?", t)
    if m:
        a, b = m.group(1), m.group(2)
        n, what = (num(a), b) if num(a) is not None else (num(b), a)
        if n is not None:
            return Match(reply=f"I'll remind you in {n} minute{'s' if n != 1 else ''}.",
                         run=lambda: actions.run(["omarchy", "reminder", str(n), what[:1].upper() + what[1:]]))

    # ---- typing
    m = re.fullmatch(r"type (.+)", t)
    if m:
        # Re-cut from the raw transcript so the typed text keeps its case and
        # punctuation; the normalized copy is lowercase.
        raw = re.sub(r"^.*?\btype\s+", "", text.strip(), count=1, flags=re.I)
        return Match(run=lambda: actions.type_text(raw))

    # ---- open things (last, since it's the loosest pattern)
    m = re.fullmatch(r"(?:open|launch|start|go to|pull up|bring up|show me|take me to|navigate to|visit)(?: up)? (.+)", t)
    if m and " and " not in m.group(1) and " then " not in m.group(1):
        target = re.sub(r"^(?:my |the )", "", m.group(1))
        target = re.sub(r"\s+(?:app|application|program)$", "", target)
        opener = t.split()[0]
        site = resolve_site(target)
        # "open files" is an app, "go to github" is a site; apps win for
        # launch/start, sites win for go to/visit.
        if opener in ("launch", "start"):
            order = ("app", "site")
        else:
            order = ("site", "app") if site and site != SITES.get("claude ai") else ("app", "site")
        for kind in order:
            if kind == "site" and site:
                return Match(reply=f"Opening {pretty_site(site)}.", run=lambda: actions.open_url(site))
            if kind == "app":
                name = _app_name(target)
                if name:
                    return Match(reply=f"Opening {name}.", run=lambda: actions.launch_app(target))
    return None


def _app_name(target):
    """Resolve without launching, so match() stays side-effect free."""
    key = target.lower().strip()
    if key in actions.APP_ALIASES or difflib.get_close_matches(key, actions.APP_ALIASES.keys(), n=1, cutoff=0.85):
        return target.title() if len(target) > 3 else target.upper()
    entry = actions.apps().find(key)
    return entry["name"] if entry else None
