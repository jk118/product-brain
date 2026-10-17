"""Baseline memories (no memory, naive append-only) and helpers shared with the Product Brain.

Every memory exposes the same interface so the agents treat them identically:
    async ingest(day, proposals) -> curator log entries
    context(role, day) -> str          text the LLM agent reads before answering
    mock_answer(q, role, day) -> dict  stand-in for the LLM in mock mode
    size_tokens() -> int
"""
from __future__ import annotations

import json
import sqlite3

from .events import PLATFORM_LABEL, PLATFORMS, VISIBLE_TO, World
from .llm import estimate_tokens

# How much the curator trusts each source when claims conflict.
TRUST = {
    "release_log": 1.0, "usage_stats": 0.9, "announcement": 0.85, "code_change": 0.5,
    "roadmap": 0.45, "support_ticket": 0.35, "chat": 0.25,
}
STATUS_TO_ANSWER = {"live": "live", "beta": "beta", "planned": "not_available", "pulled": "not_available"}
UNKNOWN = {"answer": "unknown", "confidence": 0.0, "reason": "not in memory"}


def claim_summary(c: dict) -> str:
    k = c["kind"]
    if k == "status":
        plats = ", ".join(PLATFORM_LABEL[p] for p in c["platforms"]) if c.get("platforms") else "all platforms"
        return f"{c['feature']} is {c['status']} on {plats}"
    if k == "rename":
        return f"{c['old']} was renamed to {c['new']}"
    if k == "issue":
        return f"bug report for {c['feature']}: \"{c['symptom']}\""
    if k == "issue_fixed":
        return f"fix shipped for {c['feature']}: \"{c['symptom']}\""
    if k == "metric":
        return f"{c['feature']} adoption is {c['value']:.0%}"
    if k == "target":
        return f"{c['feature']} adoption target is {c['value']:.0%}"
    if k == "metric_opinion":
        return f"someone says {c['feature']} is performing {c['direction']} expectations"
    return json.dumps(c)


def latest_claim_answer(claims: list[dict], q: dict) -> dict:
    """Mock reader for unstructured memories: the most recent claim that mentions the name wins.

    It does no source weighting, alias resolution or deduplication. That is what
    the curator adds, so the mock isolates the effect of curation. Real LLM runs
    are the actual experiment.
    """
    name = q.get("name", "").lower()

    def about(c):
        return (c.get("feature") or "").lower() == name

    t = q["type"]
    if t == "status":
        for c in reversed(claims):
            if c["kind"] == "status" and about(c):
                return {"answer": STATUS_TO_ANSWER[c["status"]], "confidence": 0.8, "reason": claim_summary(c)}
    elif t == "platform":
        for c in reversed(claims):
            if c["kind"] == "status" and about(c) and (not c.get("platforms") or q["platform"] in c["platforms"]):
                return {"answer": "yes" if c["status"] == "live" else "no", "confidence": 0.8,
                        "reason": claim_summary(c)}
    elif t == "issues":
        reports = sum(1 for c in claims if c["kind"] == "issue" and about(c))
        fixes = sum(1 for c in claims if c["kind"] == "issue_fixed" and about(c))
        if reports:
            return {"answer": max(0, reports - fixes), "confidence": 0.7, "reason": f"{reports} reports, {fixes} fixes"}
    elif t == "target":
        actual = next((c for c in reversed(claims) if c["kind"] in ("metric", "metric_opinion") and about(c)), None)
        target = next((c for c in reversed(claims) if c["kind"] == "target" and about(c)), None)
        if actual and actual["kind"] == "metric_opinion":
            return {"answer": actual["direction"], "confidence": 0.7, "reason": claim_summary(actual)}
        if actual and target:
            return {"answer": "above" if actual["value"] >= target["value"] else "below", "confidence": 0.8,
                    "reason": f"{claim_summary(actual)}; {claim_summary(target)}"}
    elif t == "rename":
        for c in reversed(claims):
            if c["kind"] == "rename" and c["old"].lower() == name:
                return {"answer": c["new"], "confidence": 0.8, "reason": claim_summary(c)}
    elif t == "rolled_back":
        statuses = [c for c in claims if c["kind"] == "status" and about(c)]
        if statuses:
            pulled = any(c["status"] == "pulled" for c in statuses)
            return {"answer": "yes" if pulled else "no", "confidence": 0.7, "reason": f"{len(statuses)} status notes"}
    elif t == "adoption":
        for c in reversed(claims):
            if c["kind"] == "metric" and about(c):
                return {"answer": c["value"], "confidence": 0.8, "reason": claim_summary(c)}
    elif t == "release_notes":
        state = {}
        for c in claims:
            if c["kind"] == "status":
                for p in c.get("platforms") or PLATFORMS:
                    state[(c["feature"], p)] = c["status"]
        feats = {}
        for (feat, p), s in state.items():
            if s == "live":
                feats.setdefault(feat, []).append(p)
        return {"features": [{"name": n, "platforms": ps} for n, ps in feats.items()], "confidence": 0.8}
    return dict(UNKNOWN)


class NoMemory:
    """Agents only see the most recent raw events visible to their role."""
    name = "no_memory"

    def __init__(self, world: World, window: int = 30):
        self.world, self.window = world, window

    async def ingest(self, day, proposals):
        return []

    def _visible(self, role, day):
        evs = [e for e in self.world.events if e.day <= day and e.type in VISIBLE_TO[role]]
        return evs[-self.window:]

    def context(self, role, day):
        return "RECENT EVENTS (no long-term memory):\n" + "\n".join(e.render() for e in self._visible(role, day))

    def mock_answer(self, q, role, day):
        claims = [dict(c, source_type=e.type, day=e.day) for e in self._visible(role, day) for c in e.claims]
        return latest_claim_answer(claims, q)

    def size_tokens(self):
        return 0


class NaiveMemory:
    """Every agent appends every claim it extracts. No dedup, no conflict handling, no pruning."""
    name = "naive"

    def __init__(self, db: sqlite3.Connection, max_context_tokens: int = 12000):
        self.db, self.max_context_tokens = db, max_context_tokens
        db.execute("CREATE TABLE IF NOT EXISTS naive_notes(id INTEGER PRIMARY KEY, day INT, agent TEXT, "
                   "source TEXT, event_id INT, claim TEXT, text TEXT)")

    async def ingest(self, day, proposals):
        self.db.executemany(
            "INSERT INTO naive_notes(day, agent, source, event_id, claim, text) VALUES (?,?,?,?,?,?)",
            [(p["day"], p["agent"], p["source_type"], p["event_id"], json.dumps(p), claim_summary(p))
             for p in sorted(proposals, key=lambda p: p["event_id"])])
        self.db.commit()
        return []

    def _window(self):
        """Most recent notes that fit in the context budget (oldest are truncated, as with a real context limit)."""
        rows = self.db.execute("SELECT * FROM naive_notes ORDER BY id DESC").fetchall()
        kept, used = [], 0
        for r in rows:
            line = f"[day {r['day']}] {r['agent']} noted (from {r['source']} #{r['event_id']}): {r['text']}"
            used += estimate_tokens(line) + 1
            if used > self.max_context_tokens:
                break
            kept.append((line, r))
        return list(reversed(kept)), len(kept) < len(rows)

    def context(self, role, day):
        kept, truncated = self._window()
        head = "SHARED NOTES (append-only):\n" + ("(older notes truncated)\n" if truncated else "")
        return head + "\n".join(line for line, _ in kept)

    def mock_answer(self, q, role, day):
        kept, _ = self._window()
        return latest_claim_answer([json.loads(r["claim"]) for _, r in kept], q)

    def size_tokens(self):
        row = self.db.execute("SELECT COALESCE(SUM(LENGTH(text)) + COUNT(*) * 60, 0) FROM naive_notes").fetchone()
        return row[0] // 4

    def count(self):
        return self.db.execute("SELECT COUNT(*) FROM naive_notes").fetchone()[0]
