"""The Judge: builds checkpoint questions from the hidden truth table and grades answers.

Questions are generated at run time from the truth snapshot (never shown to
agents in advance) and sometimes use a feature's former name.
"""
from __future__ import annotations

import random

from .events import PLATFORMS, World

STALE_CONFIDENCE = 0.6
ADOPTION_TOLERANCE = 0.02  # adoption answers within 2 points count as correct


def checkpoint_days(days: int, rng: random.Random) -> list[int]:
    picks = {min(days - 2, max(3, round(days * f) + rng.randint(-1, 1))) for f in (0.25, 0.45, 0.6, 0.75)}
    return sorted(picks | {days - 1})


def truth_value(qtype: str, state: dict, platform: str | None = None):
    plats = state["platforms"].values()
    if qtype == "status":
        return "live" if "live" in plats else "beta" if "beta" in plats else "not_available"
    if qtype == "platform":
        return "yes" if state["platforms"][platform] == "live" else "no"
    if qtype == "issues":
        return sum(1 for s in state["issues"].values() if s == "open")
    if qtype == "target":
        if state["adoption"] is None or state["target"] is None:
            return None
        return "above" if state["adoption"] >= state["target"] else "below"
    if qtype == "rename":
        return state["name"]
    if qtype == "adoption":
        return state["adoption"]
    raise ValueError(qtype)


def ever_pulled(world: World, fid: str, day: int) -> str:
    return "yes" if any("pulled" in world.truth[d][fid]["platforms"].values() for d in range(day + 1)) else "no"


def live_pairs(world: World, day: int) -> set[tuple[str, str]]:
    return {(fid, p) for fid, s in world.truth[day].items() for p in PLATFORMS if s["platforms"][p] == "live"}


def make_questions(world: World, day: int, rng: random.Random, finale: bool = False) -> list[dict]:
    snap = world.truth[day]
    qs = []

    def add(qtype, f, name, text, platform=None, value=truth_value, **extra):
        truth = value(qtype, snap[f.fid], platform) if value is truth_value else value(day)
        if truth is None:
            return
        earlier = (value(qtype, world.truth[d][f.fid], platform) if value is truth_value else value(d)
                   for d in range(day))
        past = {v for v in earlier if v is not None and not matches(qtype, v, truth)}
        qs.append({"qid": f"d{day}-{qtype}-{f.fid}{'-' + platform if platform else ''}", "day": day, "type": qtype,
                   "fid": f.fid, "name": name, "platform": platform, "text": text, "truth": truth,
                   "past": sorted(past, key=str), "agents": ["support", "analyst"], **extra})

    for f in world.features:
        if world.first_mention.get(f.fid, world.days) > day:
            continue
        s = snap[f.fid]
        name = s["name"]
        if s["former_names"] and rng.random() < 0.4:
            name = rng.choice(s["former_names"])
        add("status", f, name, f"A customer asks: is {name} available yet?")
        if f.trap in ("rename_split", "platform_split") and "planned" not in s["platforms"].values():
            is_finale = finale and f.trap == "rename_split"
            pname = s["name"] if is_finale else name
            add("platform", f, pname, f"A customer asks: is {pname} available on Android?", platform="android",
                finale=is_finale)
        if f.trap == "duplicates" and s["issues"]:
            add("issues", f, name, f"How many distinct open bugs are currently known for {name}?")
        add("target", f, name, f"Is {name} meeting its adoption target?")
        for old in s["former_names"]:
            add("rename", f, old, f"A customer asks: where did {old} go? What is it called now?")
        launched = any("live" in world.truth[d][f.fid]["platforms"].values() for d in range(day + 1))
        if f.trap in ("rollback", "partial_rollback", "steady") and launched:
            add("rolled_back", f, name, f"Has {name} ever been rolled back or pulled, on any platform?",
                value=lambda d, fid=f.fid: ever_pulled(world, fid, d))
        if f.trap in ("steady", "data_vs_assumption"):
            add("adoption", f, name, f"What is {name}'s latest measured weekly adoption?")

    truth = live_pairs(world, day)
    past = set().union(*(live_pairs(world, d) for d in range(day))) - truth if day else set()
    qs.append({"qid": f"d{day}-release_notes", "day": day, "type": "release_notes", "fid": None, "name": "",
               "platform": None, "agents": ["writer"], "truth": sorted(truth), "past": sorted(past),
               "text": "Write the 'available now' section of the release notes: list every generally "
                       "available feature and the platforms it is available on."})
    return qs


def grade(world: World, q: dict, a: dict) -> dict:
    if q["type"] == "release_notes":
        return grade_notes(world, q, a)
    ans, t = a["answer"], q["type"]
    abstain = ans == "unknown"
    correct = not abstain and matches(t, ans, q["truth"])
    stale = (not correct and not abstain and a["confidence"] >= STALE_CONFIDENCE
             and any(matches(t, ans, p) for p in q["past"]))
    return {"correct": correct, "stale": stale, "abstain": abstain}


def matches(qtype: str, answer, value) -> bool:
    if qtype == "adoption":
        return isinstance(answer, (int, float)) and abs(answer - value) <= ADOPTION_TOLERANCE
    if qtype == "rename":
        return str(answer).strip().lower() == str(value).strip().lower()
    return answer == value


def grade_notes(world: World, q: dict, a: dict) -> dict:
    names = {n.lower(): f.fid for f in world.features for n in f.names}
    pred = {(names[f["name"].strip().lower()], p) for f in a["answer"]
            if f["name"].strip().lower() in names for p in f["platforms"]}
    truth, past = set(map(tuple, q["truth"])), set(map(tuple, q["past"]))
    tp = len(pred & truth)
    precision = tp / len(pred) if pred else (1.0 if not truth else 0.0)
    recall = tp / len(truth) if truth else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"correct": f1 == 1.0, "f1": round(f1, 3), "stale_items": len(pred & past),
            "stale": bool(pred & past), "abstain": not a["answer"]}


def score(records: list[dict]) -> dict:
    """Aggregate graded answers for one team (one checkpoint or the whole run)."""
    qa = [r for r in records if r["type"] != "release_notes"]
    notes = [r for r in records if r["type"] == "release_notes"]
    by_q: dict[str, list] = {}
    for r in qa:
        by_q.setdefault(r["qid"], []).append(r["answer"])
    pairs = [v for v in by_q.values() if len(v) > 1]
    n = len(qa) or 1
    return {
        "questions": len(qa),
        "accuracy": round(sum(r["correct"] for r in qa) / n, 3),
        "stale_rate": round(sum(r["stale"] for r in qa) / n, 3),
        "abstain_rate": round(sum(r["abstain"] for r in qa) / n, 3),
        "contradiction_rate": round(sum(len({str(x) for x in v}) > 1 for v in pairs) / (len(pairs) or 1), 3),
        "notes_f1": round(sum(r["f1"] for r in notes) / (len(notes) or 1), 3),
        "notes_stale_items": sum(r["stale_items"] for r in notes),
        "tokens_per_task": round(sum(r["tokens"] for r in records) / (len(records) or 1)),
    }
