"""The working agents: Support, Release Notes Writer, Analyst.

Each agent (1) extracts claims from the events its role can see and proposes
them to memory, and (2) answers checkpoint questions from whatever memory its
team has. All three teams use identical prompts; only the memory differs.
"""
from __future__ import annotations

import re

from .events import PLATFORMS, STATUSES, VISIBLE_TO, Event
from .llm import LLM, parse_json

ROLES = {
    "support": "Support Agent. You answer customer questions about what the product can do today.",
    "writer": "Release Notes Writer. You write accurate release notes about what has actually shipped.",
    "analyst": "Analyst. You answer questions about feature adoption and performance.",
}

EXTRACT_FORMAT = """Report every factual claim the events make about product features. Report what each event
*claims*, even if you doubt it. Kinds:
  {"kind": "status", "feature": str, "status": "planned"|"beta"|"live"|"pulled", "platforms": ["ios","android","web"] or null if unspecified}
  {"kind": "rename", "old": str, "new": str}
  {"kind": "issue", "feature": str, "symptom": "<the bug as reported>"}
  {"kind": "issue_fixed", "feature": str, "symptom": "<what was fixed>"}
  {"kind": "metric", "feature": str, "metric": "adoption", "value": <fraction 0-1>}
  {"kind": "target", "feature": str, "metric": "adoption", "value": <fraction 0-1>}
  {"kind": "metric_opinion", "feature": str, "direction": "above"|"below"}
Every claim must include "event_id" (the number after #). "live" means generally available; "pulled" means
rolled back or disabled. Ignore events with no feature claims.
Respond with JSON only: {"claims": [...]}"""

ANSWER_RULES = """Answer using only the memory/context below. Information may be outdated, renamed, rumored or
contradictory. Prefer the most recent information from the most authoritative source
(release logs > usage data > announcements > code changes > roadmap > support tickets > chat).
If the context does not contain the answer, answer "unknown". Respond with JSON only."""

FORMATS = {
    "status": '{"answer": "live" | "beta" | "not_available" | "unknown", "confidence": 0.0-1.0, "reason": "<one sentence>"}\n'
              "live = generally available on at least one platform; beta = only available as a beta; "
              "not_available = planned, pulled/rolled back, or never released.",
    "platform": '{"answer": "yes" | "no" | "unknown", "confidence": 0.0-1.0, "reason": "<one sentence>"}\n'
                '"yes" only if generally available (not beta) on that platform.',
    "issues": '{"answer": <integer> | "unknown", "confidence": 0.0-1.0, "reason": "<one sentence>"}\n'
              "Count duplicate reports of the same bug once. Exclude bugs that have been fixed.",
    "target": '{"answer": "above" | "below" | "unknown", "confidence": 0.0-1.0, "reason": "<one sentence>"}\n'
              "Compare the latest measured adoption with the adoption target.",
    "rename": '{"answer": "<the feature\'s current name>" | "unknown", "confidence": 0.0-1.0, "reason": "<one sentence>"}\n'
              "If the feature was renamed, give its new name. If it was not renamed, give the name it has now.",
    "rolled_back": '{"answer": "yes" | "no" | "unknown", "confidence": 0.0-1.0, "reason": "<one sentence>"}\n'
                   '"yes" if it was ever rolled back, pulled or disabled on any platform, even if it is back now.',
    "adoption": '{"answer": <latest measured weekly adoption as a fraction, e.g. 0.12> | "unknown", '
                '"confidence": 0.0-1.0, "reason": "<one sentence>"}\n'
                "Use the most recent usage measurement, not targets or opinions.",
    "release_notes": '{"features": [{"name": "<feature>", "platforms": ["ios", "android", "web"]}], "confidence": 0.0-1.0}\n'
                     "Include only features that are generally available right now, and only the platforms where "
                     "they are generally available.",
}


def _clean_claim(c: dict, events: dict[int, Event]) -> dict | None:
    try:
        ev = events[int(str(c.get("event_id", "")).lstrip("#"))]
    except (ValueError, KeyError):
        return None
    kind = c.get("kind")
    out = {"kind": kind, "event_id": ev.id, "day": ev.day, "source_type": ev.type}
    if kind == "rename":
        if not (isinstance(c.get("old"), str) and isinstance(c.get("new"), str)):
            return None
        return out | {"old": c["old"], "new": c["new"]}
    if not isinstance(c.get("feature"), str) or not c["feature"].strip():
        return None
    out["feature"] = c["feature"].strip()
    if kind == "status":
        plats = c.get("platforms")
        plats = [p.lower() for p in plats if isinstance(p, str) and p.lower() in PLATFORMS] if isinstance(plats, list) else None
        if c.get("status") not in STATUSES:
            return None
        return out | {"status": c["status"], "platforms": plats or None}
    if kind in ("issue", "issue_fixed"):
        return out | {"symptom": str(c.get("symptom") or ev.text)}
    if kind in ("metric", "target"):
        try:
            v = float(str(c.get("value")).rstrip("%"))
        except ValueError:
            return None
        return out | {"metric": "adoption", "value": v / 100 if v > 1 else v}
    if kind == "metric_opinion" and c.get("direction") in ("above", "below"):
        return out | {"direction": c["direction"]}
    return None


def normalize(q: dict, raw: dict) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    try:
        conf = min(1.0, max(0.0, float(raw.get("confidence", 0.5))))
    except (TypeError, ValueError):
        conf = 0.5
    out = {"confidence": conf, "reason": str(raw.get("reason", ""))[:300]}
    t = q["type"]
    if t == "release_notes":
        feats = []
        for f in raw.get("features") or []:
            if isinstance(f, dict) and isinstance(f.get("name"), str):
                plats = [p.lower() for p in f.get("platforms") or [] if isinstance(p, str) and p.lower() in PLATFORMS]
                feats.append({"name": f["name"], "platforms": plats or list(PLATFORMS)})
        return out | {"answer": feats}
    if t == "rename":
        a = str(raw.get("answer", "unknown")).strip().strip("\"'.")
        if not a or a.lower() == "unknown":
            out["confidence"] = 0.0
            a = "unknown"
        return out | {"answer": a}
    if t == "adoption":
        v = raw.get("answer")
        m = re.search(r"\d+(?:\.\d+)?", str(v)) if v is not None else None
        if not m:
            return out | {"answer": "unknown", "confidence": 0.0}
        x = float(m.group())
        return out | {"answer": round(x / 100 if "%" in str(v) or x > 1 else x, 4)}
    a = str(raw.get("answer", "unknown")).strip().lower().replace(" ", "_")
    if t == "status":
        a = {"available": "live", "ga": "live", "yes": "live", "not_available_yet": "not_available", "no": "not_available",
             "pulled": "not_available", "planned": "not_available", "rolled_back": "not_available"}.get(a, a)
        a = a if a in ("live", "beta", "not_available") else "unknown"
    elif t in ("platform", "rolled_back"):
        a = {"true": "yes", "false": "no"}.get(a, a)
        a = a if a in ("yes", "no") else "unknown"
    elif t == "issues":
        m = re.search(r"\d+", a)
        a = int(m.group()) if m else "unknown"
    elif t == "target":
        a = "above" if a.startswith(("above", "meet", "exceed")) else "below" if a.startswith("below") else "unknown"
    if a == "unknown":
        out["confidence"] = 0.0
    return out | {"answer": a}


class Agent:
    def __init__(self, role: str, product: str, llm: LLM):
        self.role, self.product, self.llm = role, product, llm

    def system(self, day: int) -> str:
        return f"You are the {ROLES[self.role]} You work on the {self.product} product team. Today is day {day}."

    async def extract(self, events: list[Event], mode: str) -> tuple[list[dict], int]:
        """Turn the day's visible events into proposals. mode='oracle' reads the generator's claim
        annotations (a perfect extractor, free); mode='llm' asks the model."""
        events = [e for e in events if e.type in VISIBLE_TO[self.role]]
        if not events:
            return [], 0
        if mode == "oracle":
            return [dict(c, event_id=e.id, day=e.day, source_type=e.type, agent=self.role)
                    for e in events for c in e.claims], 0
        user = "NEW EVENTS:\n" + "\n".join(e.render() for e in events) + "\n\n" + EXTRACT_FORMAT
        text, tokens = await self.llm.chat(self.system(events[0].day), user, max_tokens=2000)
        by_id = {e.id: e for e in events}
        claims = (parse_json(text) or {}).get("claims") or []
        cleaned = [_clean_claim(c, by_id) for c in claims if isinstance(c, dict)]
        return [dict(c, agent=self.role) for c in cleaned if c], tokens

    async def answer(self, q: dict, memory, day: int) -> dict:
        user = (f"{ANSWER_RULES}\n\nMEMORY / CONTEXT:\n{memory.context(self.role, day)}\n\n"
                f"QUESTION: {q['text']}\n\nRespond with JSON in this format:\n{FORMATS[q['type']]}")
        text, tokens = await self.llm.chat(self.system(day), user)
        raw = memory.mock_answer(q, self.role, day) if self.llm.mock else parse_json(text)
        return normalize(q, raw) | {"tokens": tokens}
