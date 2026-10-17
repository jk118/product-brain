"""The Curator: the only writer to the Product Brain.

Agents propose claims. The curator:
  - drops the same claim proposed by several agents (team chat is seen by all)
  - resolves conflicts by source authority (release log beats chat rumor)
  - overrides older entries when an equal or stronger source contradicts them
  - links renamed features to their former names, merging entries if needed
  - deduplicates bug reports into known issues with counts
  - prunes history and fixed issues to stay within a size budget
Every action is logged so the viewer can show what changed and why.
"""
from __future__ import annotations

import json
import re

from .events import PLATFORMS
from .llm import LLM, parse_json
from .memory import TRUST

STOP = {"the", "and", "app", "when", "then", "every", "time", "try", "anything", "over", "please", "fix", "fixed",
        "keeps", "during", "from", "with", "this", "that", "big", "for", "any", "about", "into", "just", "on", "me"}


def issue_tokens(text: str, exclude: str = "") -> set[str]:
    skip = {w[:5] for w in re.findall(r"[a-z]+", exclude.lower())}
    return {w[:5] for w in re.findall(r"[a-z]+", text.lower())
            if len(w) > 2 and w not in STOP and w[:5] not in skip}


def overlap(a: set, b: set) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


class Curator:
    def __init__(self, llm: LLM | None = None, budget_tokens: int = 1800, stale_after_days: int = 6,
                 match_threshold: float = 0.2):
        self.llm, self.budget = llm, budget_tokens
        self.stale_after, self.match_threshold = stale_after_days, match_threshold

    async def apply(self, brain, day: int, proposals: list[dict]) -> list[dict]:
        log = []
        seen = set()
        for p in sorted(proposals, key=lambda p: (p["day"], p["event_id"])):
            key = (p["event_id"], p["kind"], p.get("feature"), p.get("status"), p.get("old"))
            if key in seen:
                continue
            seen.add(key)
            handler = getattr(self, f"_{p['kind']}", None)
            if handler:
                before = len(log)
                await handler(brain, day, p, log)
                for entry in log[before:]:  # lets the viewer show what happened to each proposal
                    entry["event_id"] = p["event_id"]
        self._budget(brain, day, log)
        return log

    # --- handlers --------------------------------------------------------------

    async def _status(self, brain, day, p, log):
        fid, created = brain.ensure(p["feature"], p["day"])
        name = brain.name_of(fid)
        src, trust, status = p["source_type"], TRUST.get(p["source_type"], 0.3), p["status"]
        if created:
            log.append(brain.log(day, "create", name, f"new entry from {src} #{p['event_id']}"))
        changed, rejected = [], []
        for plat in p.get("platforms") or PLATFORMS:
            row = brain.platforms(fid).get(plat)
            if row is None or row["status"] == status:
                if row is None or trust >= row["trust"]:
                    brain.set_platform(fid, plat, status, src, trust, p["day"], p["event_id"])
                continue
            stale = p["day"] - row["day"] >= self.stale_after and trust >= 0.5
            if trust >= row["trust"] or stale:
                brain.add_history(fid, p["day"], f"{plat}: {row['status']} -> {status} ({src} #{p['event_id']})")
                brain.set_platform(fid, plat, status, src, trust, p["day"], p["event_id"])
                changed.append((plat, row["status"]))
            else:
                brain.dispute(fid, plat, f"{src} #{p['event_id']} on day {p['day']} claimed '{status}'; rejected, "
                                         f"weaker than {row['source']} (day {row['day']})", day)
                rejected.append((plat, row))
        if changed:
            regress = any(old == "live" and status != "live" for _, old in changed)
            plats = ", ".join(pl for pl, _ in changed)
            log.append(brain.log(day, "rollback" if regress else "update", name,
                                 f"{plats} -> {status} per {src} #{p['event_id']}"))
        if rejected:
            plats = ", ".join(pl for pl, _ in rejected)
            kept = rejected[0][1]
            log.append(brain.log(day, "conflict", name,
                                 f"{src} #{p['event_id']} says {status} on {plats}; kept {kept['status']} "
                                 f"from {kept['source']} (stronger source)"))
        brain.touch(fid, p["day"])

    async def _rename(self, brain, day, p, log):
        old, new, src = p["old"], p["new"], p["source_type"]
        if TRUST.get(src, 0.3) < 0.5:
            log.append(brain.log(day, "conflict", old, f"rename to {new} from {src} ignored (unofficial source)"))
            return
        old_id, new_id = brain.resolve(old), brain.resolve(new)
        if old_id is not None and old_id == new_id:
            return  # already linked
        if old_id is None and new_id is None:
            old_id, _ = brain.ensure(old, p["day"])
        if old_id is not None and new_id is not None:
            brain.merge(into=old_id, other=new_id)
            log.append(brain.log(day, "merge", new, f"merged separate '{new}' entry into '{old}'"))
        target = old_id if old_id is not None else new_id
        brain.rename(target, new)
        if brain.resolve(old) is None:
            brain.db.execute("INSERT INTO brain_aliases VALUES (?,?)", (old, target))
        brain.add_history(target, p["day"], f"renamed {old} -> {new}")
        brain.touch(target, p["day"])
        log.append(brain.log(day, "rename", new, f"'{old}' is now '{new}'; old name kept as alias"))

    async def _issue(self, brain, day, p, log):
        fid, _ = brain.ensure(p["feature"], p["day"])
        tokens = issue_tokens(p["symptom"], exclude=" ".join([brain.name_of(fid), *brain.former_names(fid)]))
        match = await self._match_issue(brain, fid, p["symptom"], tokens)
        name = brain.name_of(fid)
        if match:
            n = brain.bump_issue(match["id"], tokens, p["day"], p["event_id"])
            log.append(brain.log(day, "dedup", name, f"report #{p['event_id']} merged into I{match['id']} ({n} reports)"))
        elif fixed := await self._match_issue(brain, fid, p["symptom"], tokens, status="fixed"):
            brain.bump_issue(fixed["id"], tokens, p["day"], p["event_id"], reopen=True)
            log.append(brain.log(day, "reopen", name, f"I{fixed['id']} was fixed but is reported again (#{p['event_id']}): regression"))
        else:
            iid = brain.add_issue(fid, p["symptom"], tokens, p["day"], p["event_id"])
            log.append(brain.log(day, "new_issue", name, f"I{iid}: {p['symptom']}"))

    async def _issue_fixed(self, brain, day, p, log):
        if TRUST.get(p["source_type"], 0.3) < 0.5:
            return
        fid = brain.resolve(p["feature"])
        if fid is None:
            return
        tokens = issue_tokens(p["symptom"], exclude=" ".join([brain.name_of(fid), *brain.former_names(fid)]))
        match = await self._match_issue(brain, fid, p["symptom"], tokens)
        if match:
            brain.fix_issue(match["id"], p["day"])
            log.append(brain.log(day, "fix", brain.name_of(fid), f"I{match['id']} fixed per {p['source_type']} #{p['event_id']}"))

    async def _metric(self, brain, day, p, log):
        fid, _ = brain.ensure(p["feature"], p["day"])
        cur = brain.metric(fid, "actual")
        if cur is None or p["day"] >= cur["day"]:
            brain.set_metric(fid, "actual", float(p["value"]), p["day"], p["source_type"], p["event_id"])
        opinion = brain.metric(fid, "opinion")
        if opinion:
            brain.delete_metric(fid, "opinion")
            log.append(brain.log(day, "stale", brain.name_of(fid), "dropped unverified opinion; usage data now available"))
        brain.touch(fid, p["day"])

    async def _target(self, brain, day, p, log):
        fid, _ = brain.ensure(p["feature"], p["day"])
        if brain.metric(fid, "target") is None:
            log.append(brain.log(day, "update", brain.name_of(fid), f"adoption target {float(p['value']):.0%} ({p['source_type']})"))
        brain.set_metric(fid, "target", float(p["value"]), p["day"], p["source_type"], p["event_id"])

    async def _metric_opinion(self, brain, day, p, log):
        fid, _ = brain.ensure(p["feature"], p["day"])
        actual, target = brain.metric(fid, "actual"), brain.metric(fid, "target")
        if actual:
            measured = "above" if target and actual["value"] >= target["value"] else "below" if target else "?"
            if measured != p["direction"]:
                log.append(brain.log(day, "conflict", brain.name_of(fid),
                                     f"{p['source_type']} #{p['event_id']} says {p['direction']} expectations; "
                                     f"usage data says {actual['value']:.0%} ({measured} target)"))
            return
        brain.set_metric(fid, "opinion", 1.0 if p["direction"] == "above" else 0.0, p["day"], p["source_type"], p["event_id"])

    # --- helpers ---------------------------------------------------------------

    async def _match_issue(self, brain, fid, symptom, tokens, status="open"):
        candidates = brain.issues(fid, status)
        if not candidates:
            return None
        scored = sorted(((overlap(tokens, set(json.loads(c["tokens"]))), c) for c in candidates),
                        key=lambda x: -x[0])
        if scored[0][0] >= self.match_threshold:
            return scored[0][1]
        if self.llm and not self.llm.mock:
            listing = "\n".join(f"I{c['id']}: {c['summary']}" for c in candidates)
            text, _ = await self.llm.chat(
                "You deduplicate bug reports. Reply with JSON only.",
                f"Existing open issues:\n{listing}\n\nNew report: \"{symptom}\"\n\n"
                'Is the new report the same underlying bug as one of the existing issues? '
                'Respond {"match": "I<id>"} or {"match": null}.', max_tokens=400)
            m = str((parse_json(text) or {}).get("match") or "")
            ids = {f"I{c['id']}": c for c in candidates}
            return ids.get(m.strip())
        return None

    def _budget(self, brain, day, log):
        brain.prune(day, keep_history=4, fixed_grace=4)
        if brain.size_tokens() > self.budget:
            n = brain.prune(day, keep_history=1, fixed_grace=0)
            log.append(brain.log(day, "prune", "-", f"removed {n} old rows to stay under {self.budget} tokens"))
