"""Synthetic product history: an event stream plus the hidden truth table.

Agents only ever see Event.render(). Two hidden fields ride along:
  - Event.claims: what the text *asserts* (a rumor's claim is still recorded as
    "live"). Used by the oracle extractor in place of an LLM; never ground truth.
  - Event.truth: the real state change. Only the judge reads the replayed truth.
"""
from __future__ import annotations

import copy
import random
from collections import defaultdict
from dataclasses import dataclass, field

PLATFORMS = ("ios", "android", "web")
PLATFORM_LABEL = {"ios": "iOS", "android": "Android", "web": "Web"}
STATUSES = ("planned", "beta", "live", "pulled")
TRAPS = ("rollback", "rename_split", "platform_split", "rumor", "data_vs_assumption", "duplicates")

# Which event types each agent role sees. Team chat is visible to everyone.
VISIBLE_TO = {
    "support": {"support_ticket", "chat", "announcement"},
    "writer": {"release_log", "code_change", "announcement", "chat"},
    "analyst": {"usage_stats", "roadmap", "chat"},
}

FEATURE_POOL = [
    "Smart Folders", "Dark Mode", "Offline Sync", "Team Spaces", "Quick Search",
    "Voice Notes", "Calendar View", "Shared Templates", "Bulk Edit", "Reminders",
    "Smart Tags", "Focus Mode", "Web Clipper", "Handwriting", "Version History",
]
RENAME_POOL = ["Collections", "Stacks", "Boards", "Shelves", "Hubs"]
PRODUCTS = ["Notely", "Tasklane", "Pinwheel", "Driftnote", "Quillbox"]
ENGINEERS = ["Priya (eng)", "Marco (eng)", "Jun (eng)", "Tomas (eng)"]
PMS = ["Dana (PM)", "Ravi (PM)"]
MARKETING = ["Ava (marketing)", "Noor (marketing)"]
TEAM = ENGINEERS + PMS + MARKETING + ["Lee (design)", "Sam (support lead)"]
RELEASE_BOT = "release-bot"
METRICS_BOT = "metrics-bot"

DUP_TEMPLATES = [
    "App crashes when I export a big {n} document.",
    "{n}: exporting anything over ~50 pages freezes and then closes the app.",
    "Every time I try exporting from {n} the app quits on me.",
    "Export from {n} = instant crash on large docs. Please fix!",
    "{n} keeps crashing during export of long files.",
]
CHAT_NOISE = [
    "standup moved to 10:30 today", "anyone else seeing the CI flake on the sync tests?",
    "lunch order goes in at noon", "reminder: retro on Friday",
    "design review for onboarding v2 at 3pm", "who owns the staging certs?",
    "PSA: new laptop images are ready", "on-call handoff notes are in the doc",
]
TICKET_NOISE = [
    "How do I reset my password?", "Can I change the email on my account?",
    "The app feels slow on my old iPad.", "Do you offer a student discount?",
    "How do I invite a teammate?", "Sync seems stuck on one of my devices.",
    "Can I get an invoice for last month?", "Is there a keyboard shortcut list?",
]
CODE_NOISE = [
    "refactor sync engine retry logic", "bump dependencies", "add tracing to search indexer",
    "clean up dead onboarding experiment code", "speed up cold start on Android",
    "fix flaky login test",
]


@dataclass
class Event:
    id: int
    day: int
    minute: int
    type: str
    author: str
    text: str
    claims: list = field(default_factory=list)
    truth: list = field(default_factory=list)
    trap: str | None = None
    feature_id: str | None = None

    @property
    def clock(self) -> str:
        return f"{self.minute // 60:02d}:{self.minute % 60:02d}"

    def render(self) -> str:
        return f"#{self.id} [day {self.day} {self.clock}] ({self.type}) {self.author}: {self.text}"

    def public(self) -> dict:
        return {"id": self.id, "day": self.day, "time": self.clock, "type": self.type,
                "author": self.author, "text": self.text}


@dataclass
class Feature:
    fid: str
    name: str
    trap: str
    rename_to: str | None = None
    adoption: tuple = ("ramp", 0.2)  # (shape, level) used to generate usage stats

    @property
    def names(self) -> list[str]:
        return [self.name] + ([self.rename_to] if self.rename_to else [])


@dataclass
class World:
    seed: int
    days: int
    product: str
    features: list[Feature]
    events: list[Event]
    truth: list[dict]  # truth[day][fid] -> feature state at the end of that day

    def __post_init__(self):
        self._by_day = defaultdict(list)
        self.first_mention: dict[str, int] = {}
        for e in self.events:
            self._by_day[e.day].append(e)
            if e.feature_id and e.feature_id not in self.first_mention:
                self.first_mention[e.feature_id] = e.day

    def events_on(self, day: int) -> list[Event]:
        return self._by_day[day]

    def feature(self, fid: str) -> Feature:
        return next(f for f in self.features if f.fid == fid)


# --- claim constructors (what an event asserts) ---------------------------------

def c_status(feature, status, platforms=None):
    return {"kind": "status", "feature": feature, "status": status,
            "platforms": list(platforms) if platforms else None}


def c_rename(old, new):
    return {"kind": "rename", "old": old, "new": new}


def c_issue(feature, symptom):
    return {"kind": "issue", "feature": feature, "symptom": symptom}


def c_fixed(feature, symptom):
    return {"kind": "issue_fixed", "feature": feature, "symptom": symptom}


def c_metric(feature, value):
    return {"kind": "metric", "feature": feature, "metric": "adoption", "value": value}


def c_target(feature, value):
    return {"kind": "target", "feature": feature, "metric": "adoption", "value": value}


def c_opinion(feature, direction):
    return {"kind": "metric_opinion", "feature": feature, "direction": direction}


# --- generator -------------------------------------------------------------------

class _Gen:
    def __init__(self, rng: random.Random, days: int):
        self.rng, self.days, self.events = rng, days, []
        self.pr = rng.randint(1200, 1900)
        self.ticket = rng.randint(4000, 6000)

    def emit(self, day, type_, author, text, *, claims=(), truth=(), fid=None, trap=None, minute=None):
        if not 0 <= day < self.days:
            return
        if minute is None:
            minute = self.rng.randint(9 * 60, 18 * 60)
        self.events.append(Event(0, day, min(minute, 23 * 60 + 59), type_, author, text,
                                 list(claims), list(truth), trap, fid))

    def pick(self, people):
        return self.rng.choice(people)

    def next_pr(self):
        self.pr += self.rng.randint(1, 9)
        return self.pr

    def customer(self):
        self.ticket += self.rng.randint(1, 40)
        return f"customer (ticket #{self.ticket})"

    def span(self, lo: float, hi: float) -> int:
        return self.rng.randint(int(self.days * lo), int(self.days * hi))

    def release(self, day, f, name, status, platforms, text, *, announce=None, cheer=None, trap=None):
        m = self.rng.randint(10 * 60, 15 * 60)
        claim = c_status(name, status, platforms)
        self.emit(day, "release_log", RELEASE_BOT, text, claims=[claim],
                  truth=[("status", f.fid, {p: status for p in platforms})], fid=f.fid, trap=trap, minute=m)
        if announce:
            self.emit(day, "announcement", self.pick(MARKETING), announce, claims=[claim], fid=f.fid,
                      trap=trap, minute=m + 30)
        if cheer:
            self.emit(day, "chat", self.pick(TEAM), cheer, claims=[claim], fid=f.fid, trap=trap, minute=m + 60)

    def intro(self, f, day, extra="", claims=(), truth=()):
        self.emit(day, "roadmap", self.pick(PMS), f"Roadmap update: {f.name} is planned for this cycle.{extra}",
                  claims=[c_status(f.name, "planned"), *claims], truth=truth, fid=f.fid, minute=9 * 60)

    # One method per trap. Each writes the feature's whole story.

    def steady(self, f):
        self.intro(f, self.rng.randint(0, 1), " Success target: 20% weekly adoption.",
                   claims=[c_target(f.name, 0.2)], truth=[("target", f.fid, 0.2)])
        b = self.rng.randint(2, max(3, self.days // 5))
        self.emit(b - 1, "code_change", self.pick(ENGINEERS),
                  f"Merged PR #{self.next_pr()}: {f.name} core implementation behind a feature flag.", fid=f.fid)
        self.release(b, f, f.name, "beta", PLATFORMS, f"{{ver}}: {f.name} enters beta on iOS, Android and Web.")
        live = b + self.rng.randint(3, 5)
        self.release(live, f, f.name, "live", PLATFORMS,
                     f"{{ver}}: {f.name} is generally available on iOS, Android and Web.",
                     announce=f"Big news: {f.name} is now available to everyone on iOS, Android and Web!",
                     cheer=f"{f.name} GA is out, nice work team 🎉")
        f.adoption = ("ramp", self.rng.uniform(0.28, 0.4))

    def rollback(self, f):
        self.intro(f, self.rng.randint(0, 1))
        b = self.rng.randint(1, 3)
        self.release(b, f, f.name, "beta", PLATFORMS, f"{{ver}}: {f.name} enters beta on all platforms.")
        live = max(self.span(0.25, 0.4), b + 2)
        self.release(live, f, f.name, "live", PLATFORMS,
                     f"{{ver}}: {f.name} is generally available on iOS, Android and Web.",
                     announce=f"{f.name} is live for everyone! Try it today.",
                     cheer=f"{f.name} launched!! 🚀", trap="rollback")
        self.emit(live + 1, "support_ticket", self.customer(), f"Love the new {f.name}! Exactly what I needed.",
                  fid=f.fid, trap="rollback")
        self.release(live + 2, f, f.name, "pulled", PLATFORMS,
                     f"{{ver}}: ROLLBACK. {f.name} has been disabled on all platforms after a data-loss bug. "
                     f"It will return in a future release.",
                     announce=f"We've temporarily pulled {f.name} while we fix an issue. Sorry for the disruption!",
                     trap="rollback")
        self.emit(live + 2, "code_change", self.pick(ENGINEERS),
                  f"Merged PR #{self.next_pr()}: disable {f.name} flag globally (revert).", fid=f.fid,
                  trap="rollback", minute=16 * 60)
        self.emit(live + 4, "chat", self.pick(MARKETING + PMS),
                  f"btw customers keep telling me how much they love {f.name}, great launch!",
                  claims=[c_status(f.name, "live")], fid=f.fid, trap="rollback")
        self.emit(live + 5, "support_ticket", self.customer(), f"Where did {f.name} go? It was there last week.",
                  fid=f.fid, trap="rollback")

    def rename_split(self, f):
        old, new = f.name, f.rename_to
        self.intro(f, self.rng.randint(0, 1))
        b = self.rng.randint(1, 3)
        self.release(b, f, old, "beta", PLATFORMS, f"{{ver}}: {old} enters beta on iOS, Android and Web.")
        ios = max(self.span(0.2, 0.33), b + 2)
        self.release(ios, f, old, "live", ("ios",),
                     f"{{ver}}: {old} is generally available on iOS. Android and Web remain in beta.",
                     announce=f"{old} has arrived on iOS! Android and Web are coming soon.",
                     cheer=f"{old} is live on iOS 🚀", trap="platform_split")
        r = max(self.span(0.42, 0.55), ios + 2)
        m = 11 * 60
        self.emit(r, "release_log", RELEASE_BOT,
                  f"{{ver}}: {old} is renamed to {new} across all platforms. No change in functionality.",
                  claims=[c_rename(old, new)], truth=[("rename", f.fid, new)], fid=f.fid, trap="rename", minute=m)
        self.emit(r, "announcement", self.pick(MARKETING),
                  f"Say hello to {new}! We've renamed {old} to {new} to better reflect how you use it.",
                  claims=[c_rename(old, new)], fid=f.fid, trap="rename", minute=m + 30)
        self.emit(r, "code_change", self.pick(ENGINEERS),
                  f"Merged PR #{self.next_pr()}: rename {old} -> {new} in UI strings and analytics events.",
                  fid=f.fid, trap="rename", minute=m + 90)
        self.emit(r + 1, "support_ticket", self.customer(),
                  f"I updated the app and {old} is gone?? Where did my stuff go?", fid=f.fid, trap="rename")
        self.emit(r + 2, "chat", self.pick(ENGINEERS),
                  f"{new} on Android is basically done, should ship tomorrow!",
                  claims=[c_status(new, "live", ("android",))], fid=f.fid, trap="rumor")
        self.emit(r + 3, "support_ticket", self.customer(), f"Is {old} ever coming to Android?",
                  fid=f.fid, trap="rename")
        if self.rng.random() < 0.5:
            self.release(self.rng.randint(r + 3, self.days - 2), f, new, "live", ("android",),
                         f"{{ver}}: {new} is generally available on Android.",
                         announce=f"{new} is now on Android!", trap="platform_split")

    def platform_split(self, f):
        self.intro(f, self.rng.randint(0, 2))
        b = self.rng.randint(2, 4)
        self.release(b, f, f.name, "beta", PLATFORMS, f"{{ver}}: {f.name} enters beta on iOS, Android and Web.")
        live = max(self.span(0.3, 0.5), b + 2)
        self.release(live, f, f.name, "live", ("ios", "web"),
                     f"{{ver}}: {f.name} is generally available on iOS and Web. Android stays in beta while we "
                     f"fix performance on low-end devices.",
                     announce=f"{f.name} is now available on iOS and the web!", trap="platform_split")
        self.emit(live + 1, "chat", self.pick(TEAM), f"{f.name} is out everywhere 🎉",
                  claims=[c_status(f.name, "live")], fid=f.fid, trap="rumor")
        self.emit(live + 2, "support_ticket", self.customer(), f"Why can't I find {f.name} on my Android phone?",
                  fid=f.fid, trap="platform_split")

    def rumor(self, f):
        self.intro(f, self.rng.randint(0, 2))
        b = self.span(0.15, 0.3)
        self.release(b, f, f.name, "beta", PLATFORMS, f"{{ver}}: {f.name} enters beta on iOS, Android and Web.")
        self.emit(b + 3, "chat", self.pick(ENGINEERS), f"{f.name} shipped!! 🚀 great work everyone",
                  claims=[c_status(f.name, "live")], fid=f.fid, trap="rumor")
        self.emit(b + 5, "chat", self.pick(MARKETING), f"confirming {f.name} is live for all users now",
                  claims=[c_status(f.name, "live")], fid=f.fid, trap="rumor")
        self.emit(b + 6, "code_change", self.pick(ENGINEERS),
                  f"Merged PR #{self.next_pr()}: fix flaky {f.name} beta telemetry.", fid=f.fid)

    def data_vs_assumption(self, f):
        target = self.rng.randint(35, 45) / 100
        self.intro(f, self.rng.randint(0, 1), f" Expected impact: {target:.0%} weekly adoption within a week of launch.",
                   claims=[c_target(f.name, target)], truth=[("target", f.fid, target)])
        b = self.rng.randint(1, 2)
        self.release(b, f, f.name, "beta", PLATFORMS, f"{{ver}}: {f.name} enters beta on iOS, Android and Web.")
        live = max(self.span(0.2, 0.3), b + 2)
        self.release(live, f, f.name, "live", PLATFORMS,
                     f"{{ver}}: {f.name} is generally available on iOS, Android and Web.",
                     announce=f"{f.name} is here for everyone!")
        self.emit(live + 3, "chat", self.pick(PMS + MARKETING),
                  f"{f.name} is crushing it, feels like everyone's using it",
                  claims=[c_opinion(f.name, "above")], fid=f.fid, trap="data_vs_assumption")
        self.emit(live + 5, "roadmap", self.pick(PMS),
                  f"Roadmap check-in: still planning around {f.name} hitting {target:.0%} adoption.",
                  claims=[c_target(f.name, target)], fid=f.fid, trap="data_vs_assumption")
        f.adoption = ("flat", self.rng.uniform(0.05, 0.1))

    def duplicates(self, f):
        self.intro(f, 0)
        self.release(1, f, f.name, "beta", PLATFORMS, f"{{ver}}: {f.name} enters beta on iOS, Android and Web.")
        self.release(2, f, f.name, "live", PLATFORMS,
                     f"{{ver}}: {f.name} is generally available on iOS, Android and Web.",
                     announce=f"{f.name} is now available to everyone!")
        k = self.span(0.3, 0.42)
        templates = DUP_TEMPLATES[:]
        self.rng.shuffle(templates)
        for i, t in enumerate(templates):
            text = t.format(n=f.name)
            self.emit(k + i, "support_ticket", self.customer(), text, claims=[c_issue(f.name, text)],
                      truth=[("issue", f.fid, "export-crash", "open")], fid=f.fid, trap="duplicates")
        text = f"{f.name} shows the wrong timezone on shared items."
        self.emit(k + 2, "support_ticket", self.customer(), text, claims=[c_issue(f.name, text)],
                  truth=[("issue", f.fid, "timezone", "open")], fid=f.fid, trap="duplicates")
        text = f"Fixed a crash when exporting large documents from {f.name}."
        self.emit(min(k + 8, self.days - 2), "release_log", RELEASE_BOT, f"{{ver}}: {text}",
                  claims=[c_fixed(f.name, text)], truth=[("issue", f.fid, "export-crash", "fixed")],
                  fid=f.fid, trap="duplicates")

    def noise(self):
        for d in range(self.days):
            for _ in range(self.rng.randint(1, 3)):
                self.emit(d, "chat", self.pick(TEAM), self.rng.choice(CHAT_NOISE))
            for _ in range(self.rng.randint(1, 2)):
                self.emit(d, "support_ticket", self.customer(), self.rng.choice(TICKET_NOISE))
            for _ in range(self.rng.randint(0, 1)):
                self.emit(d, "code_change", self.pick(ENGINEERS),
                          f"Merged PR #{self.next_pr()}: {self.rng.choice(CODE_NOISE)}.")

    def usage(self, features, truth):
        """Daily usage stats for every feature that was live at the end of the previous day."""
        live_since = {}
        for d in range(1, self.days):
            parts, claims, updates = [], [], []
            for f in features:
                st = truth[d - 1][f.fid]
                if "live" not in st["platforms"].values():
                    live_since.pop(f.fid, None)
                    continue
                n = d - 1 - live_since.setdefault(f.fid, d - 1)
                shape, level = f.adoption
                v = min(level, 0.04 + 0.045 * n) if shape == "ramp" else level
                v = round(max(0.01, v + self.rng.uniform(-0.01, 0.01)), 3)
                parts.append(f"{st['name']} {v:.0%}")
                claims.append(c_metric(st["name"], v))
                updates.append(("adoption", f.fid, v))
            if parts:
                self.emit(d, "usage_stats", METRICS_BOT,
                          f"Weekly-active adoption as of end of day {d - 1}: " + ", ".join(parts) + ".",
                          claims=claims, truth=updates, minute=8 * 60)


def _blank(f: Feature) -> dict:
    return {"name": f.name, "former_names": [], "platforms": {p: "planned" for p in PLATFORMS},
            "adoption": None, "target": None, "issues": {}}


def _apply(state: dict, update: tuple):
    kind, fid, *rest = update
    s = state[fid]
    if kind == "status":
        s["platforms"].update(rest[0])
    elif kind == "rename":
        s["former_names"].append(s["name"])
        s["name"] = rest[0]
    elif kind in ("adoption", "target"):
        s[kind] = rest[0]
    elif kind == "issue":
        s["issues"][rest[0]] = rest[1]


def _replay(features, events, days) -> list[dict]:
    state = {f.fid: _blank(f) for f in features}
    by_day = defaultdict(list)
    for e in events:
        by_day[e.day].append(e)
    snapshots = []
    for d in range(days):
        for e in sorted(by_day[d], key=lambda e: e.minute):
            for u in e.truth:
                _apply(state, u)
        snapshots.append(copy.deepcopy(state))
    return snapshots


def generate(seed: int, days: int = 21) -> World:
    """Build a randomized product history. Names, timing and trap placement all vary with the seed."""
    if days < 14:
        raise ValueError("need at least 14 simulated days for the traps to play out")
    rng = random.Random(seed)
    product = rng.choice(PRODUCTS)
    traps = list(TRAPS) + ["steady"]
    rng.shuffle(traps)
    names = rng.sample(FEATURE_POOL, len(traps))
    features = [Feature(f"f{i + 1}", name, trap, rng.choice(RENAME_POOL) if trap == "rename_split" else None,
                        ("ramp", rng.uniform(0.12, 0.3)))
                for i, (trap, name) in enumerate(zip(traps, names))]

    gen = _Gen(rng, days)
    for f in features:
        getattr(gen, f.trap)(f)
    gen.noise()
    gen.usage(features, _replay(features, gen.events, days))

    events = sorted(gen.events, key=lambda e: (e.day, e.minute))
    major, n = rng.randint(2, 5), 0
    for i, e in enumerate(events, 1):
        e.id = i
        if "{ver}" in e.text:
            n += 1
            e.text = e.text.replace("{ver}", f"v{major}.{n}")
    return World(seed, days, product, features, events, _replay(features, events, days))
