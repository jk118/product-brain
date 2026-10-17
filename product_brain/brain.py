"""The Product Brain: structured, curated shared memory stored in SQLite.

Agents never write here directly. They hand proposals to the Curator, which
calls the mutation methods below.
"""
from __future__ import annotations

import json
import sqlite3

from .events import PLATFORM_LABEL, PLATFORMS
from .llm import estimate_tokens
from .memory import UNKNOWN

SCHEMA = """
CREATE TABLE IF NOT EXISTS brain_features(id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_day INT, last_verified INT);
CREATE TABLE IF NOT EXISTS brain_aliases(alias TEXT PRIMARY KEY COLLATE NOCASE, feature_id INT NOT NULL);
CREATE TABLE IF NOT EXISTS brain_platforms(feature_id INT, platform TEXT, status TEXT, source TEXT, trust REAL,
    day INT, event_id INT, disputed TEXT, disputed_day INT, PRIMARY KEY(feature_id, platform));
CREATE TABLE IF NOT EXISTS brain_metrics(feature_id INT, kind TEXT, value REAL, day INT, source TEXT, event_id INT,
    PRIMARY KEY(feature_id, kind));
CREATE TABLE IF NOT EXISTS brain_issues(id INTEGER PRIMARY KEY, feature_id INT, summary TEXT, tokens TEXT,
    reports INT, status TEXT, first_day INT, last_day INT, event_ids TEXT);
CREATE TABLE IF NOT EXISTS brain_history(id INTEGER PRIMARY KEY, feature_id INT, day INT, text TEXT);
CREATE TABLE IF NOT EXISTS brain_log(id INTEGER PRIMARY KEY, day INT, action TEXT, feature TEXT, detail TEXT);
"""


def _landmark(text: str) -> bool:
    return "-> pulled" in text or text.startswith("renamed")


def _overall(plats: dict) -> str:
    """One-line verdict so readers don't have to infer availability from per-platform rows."""
    live = [PLATFORM_LABEL[p] for p in PLATFORMS if p in plats and plats[p]["status"] == "live"]
    beta = [PLATFORM_LABEL[p] for p in PLATFORMS if p in plats and plats[p]["status"] == "beta"]
    if live:
        return f"overall: LIVE (generally available on {', '.join(live)})" + (f"; beta on {', '.join(beta)}" if beta else "")
    if beta:
        return f"overall: BETA only (on {', '.join(beta)})"
    pulled = any(r["status"] == "pulled" for r in plats.values())
    return "overall: NOT AVAILABLE (" + ("pulled / rolled back" if pulled else "planned, not released") + ")"


class ProductBrain:
    name = "brain"

    def __init__(self, db: sqlite3.Connection, curator):
        self.db, self.curator = db, curator
        db.executescript(SCHEMA)

    # --- memory interface ------------------------------------------------------

    async def ingest(self, day, proposals):
        log = await self.curator.apply(self, day, proposals)
        self.db.commit()
        return log

    def context(self, role, day):
        return self.render()

    def size_tokens(self):
        return estimate_tokens(self.render())

    # --- reads -----------------------------------------------------------------

    def resolve(self, name: str) -> int | None:
        row = self.db.execute("SELECT feature_id FROM brain_aliases WHERE alias=?", (name.strip(),)).fetchone()
        return row[0] if row else None

    def features(self):
        return self.db.execute("SELECT * FROM brain_features ORDER BY id").fetchall()

    def name_of(self, fid):
        return self.db.execute("SELECT name FROM brain_features WHERE id=?", (fid,)).fetchone()[0]

    def former_names(self, fid):
        name = self.name_of(fid)
        rows = self.db.execute("SELECT alias FROM brain_aliases WHERE feature_id=?", (fid,)).fetchall()
        return [r[0] for r in rows if r[0].lower() != name.lower()]

    def platforms(self, fid) -> dict:
        rows = self.db.execute("SELECT * FROM brain_platforms WHERE feature_id=?", (fid,)).fetchall()
        return {r["platform"]: r for r in rows}

    def metric(self, fid, kind):
        return self.db.execute("SELECT * FROM brain_metrics WHERE feature_id=? AND kind=?", (fid, kind)).fetchone()

    def issues(self, fid, status=None):
        sql, args = "SELECT * FROM brain_issues WHERE feature_id=?", [fid]
        if status:
            sql += " AND status=?"
            args.append(status)
        return self.db.execute(sql + " ORDER BY id", args).fetchall()

    def history(self, fid):
        return self.db.execute("SELECT * FROM brain_history WHERE feature_id=? ORDER BY id", (fid,)).fetchall()

    # --- writes (curator only) -------------------------------------------------

    def ensure(self, name: str, day: int) -> tuple[int, bool]:
        fid = self.resolve(name)
        if fid is not None:
            return fid, False
        cur = self.db.execute("INSERT INTO brain_features(name, created_day, last_verified) VALUES (?,?,?)",
                              (name.strip(), day, day))
        self.db.execute("INSERT INTO brain_aliases VALUES (?,?)", (name.strip(), cur.lastrowid))
        return cur.lastrowid, True

    def touch(self, fid, day):
        self.db.execute("UPDATE brain_features SET last_verified=MAX(last_verified, ?) WHERE id=?", (day, fid))

    def set_platform(self, fid, platform, status, source, trust, day, event_id):
        self.db.execute("INSERT OR REPLACE INTO brain_platforms VALUES (?,?,?,?,?,?,?,NULL,NULL)",
                        (fid, platform, status, source, trust, day, event_id))

    def dispute(self, fid, platform, text, day):
        self.db.execute("UPDATE brain_platforms SET disputed=?, disputed_day=? WHERE feature_id=? AND platform=?",
                        (text, day, fid, platform))

    def set_metric(self, fid, kind, value, day, source, event_id):
        self.db.execute("INSERT OR REPLACE INTO brain_metrics VALUES (?,?,?,?,?,?)",
                        (fid, kind, value, day, source, event_id))

    def delete_metric(self, fid, kind):
        self.db.execute("DELETE FROM brain_metrics WHERE feature_id=? AND kind=?", (fid, kind))

    def add_issue(self, fid, summary, tokens, day, event_id) -> int:
        cur = self.db.execute("INSERT INTO brain_issues(feature_id, summary, tokens, reports, status, first_day, "
                              "last_day, event_ids) VALUES (?,?,?,1,'open',?,?,?)",
                              (fid, summary, json.dumps(sorted(tokens)), day, day, json.dumps([event_id])))
        return cur.lastrowid

    def bump_issue(self, iid, tokens, day, event_id, reopen=False):
        row = self.db.execute("SELECT * FROM brain_issues WHERE id=?", (iid,)).fetchone()
        merged = sorted(set(json.loads(row["tokens"])) | set(tokens))
        ids = json.loads(row["event_ids"]) + [event_id]
        self.db.execute("UPDATE brain_issues SET reports=reports+1, tokens=?, last_day=?, event_ids=?"
                        + (", status='open'" if reopen else "") + " WHERE id=?",
                        (json.dumps(merged), day, json.dumps(ids), iid))
        return row["reports"] + 1

    def fix_issue(self, iid, day):
        self.db.execute("UPDATE brain_issues SET status='fixed', last_day=? WHERE id=?", (day, iid))

    def add_history(self, fid, day, text):
        self.db.execute("INSERT INTO brain_history(feature_id, day, text) VALUES (?,?,?)", (fid, day, text))

    def rename(self, fid, new):
        self.db.execute("UPDATE brain_features SET name=? WHERE id=?", (new.strip(), fid))
        self.db.execute("INSERT OR REPLACE INTO brain_aliases VALUES (?,?)", (new.strip(), fid))

    def merge(self, into: int, other: int):
        """Fold entry `other` into `into` (used when a rename reveals two entries are one feature)."""
        mine = self.platforms(into)
        for p, row in self.platforms(other).items():
            if p not in mine or (row["trust"], row["day"]) > (mine[p]["trust"], mine[p]["day"]):
                self.set_platform(into, p, row["status"], row["source"], row["trust"], row["day"], row["event_id"])
        for kind in ("actual", "target", "opinion"):
            theirs, ours = self.metric(other, kind), self.metric(into, kind)
            if theirs and (not ours or theirs["day"] > ours["day"]):
                self.set_metric(into, kind, theirs["value"], theirs["day"], theirs["source"], theirs["event_id"])
        for table in ("brain_aliases", "brain_issues", "brain_history"):
            self.db.execute(f"UPDATE {table} SET feature_id=? WHERE feature_id=?", (into, other))
        for table in ("brain_platforms", "brain_metrics"):
            self.db.execute(f"DELETE FROM {table} WHERE feature_id=?", (other,))
        self.db.execute("DELETE FROM brain_features WHERE id=?", (other,))

    def prune(self, day, keep_history: int, fixed_grace: int) -> int:
        """Drop old history, long-fixed issues and resolved disputes. Returns rows removed."""
        removed = 0
        for f in self.features():
            # Rollbacks and renames are landmarks agents get asked about later; never prune them.
            ids = [r["id"] for r in self.history(f["id"]) if not _landmark(r["text"])]
            for hid in ids[:-keep_history] if keep_history else ids:
                self.db.execute("DELETE FROM brain_history WHERE id=?", (hid,))
                removed += 1
        removed += self.db.execute("DELETE FROM brain_issues WHERE status='fixed' AND last_day<?",
                                   (day - fixed_grace,)).rowcount
        removed += self.db.execute("UPDATE brain_platforms SET disputed=NULL, disputed_day=NULL "
                                   "WHERE disputed IS NOT NULL AND disputed_day<?", (day - 5,)).rowcount
        return removed

    def log(self, day, action, feature, detail) -> dict:
        self.db.execute("INSERT INTO brain_log(day, action, feature, detail) VALUES (?,?,?,?)",
                        (day, action, feature, detail))
        return {"day": day, "action": action, "feature": feature, "detail": detail}

    # --- views -----------------------------------------------------------------

    def render(self) -> str:
        lines = ["PRODUCT BRAIN (curated shared memory; conflicts resolved by source authority)"]
        for f in self.features():
            fid = f["id"]
            former = self.former_names(fid)
            lines.append(f"\n## {f['name']}" + (f"  [formerly: {', '.join(former)}]" if former else "")
                         + f"  (last verified day {f['last_verified']})")
            plats = self.platforms(fid)
            lines.append("  " + _overall(plats))
            lines.append("  " + " | ".join(
                f"{PLATFORM_LABEL[p]}: {plats[p]['status']} ({plats[p]['source']} #{plats[p]['event_id']}, day {plats[p]['day']})"
                for p in PLATFORMS if p in plats))
            for p in PLATFORMS:
                if p in plats and plats[p]["disputed"]:
                    lines.append(f"  ! {PLATFORM_LABEL[p]} disputed: {plats[p]['disputed']}")
            actual, target, opinion = (self.metric(fid, k) for k in ("actual", "target", "opinion"))
            if actual or target:
                parts = []
                if actual:
                    parts.append(f"adoption {actual['value']:.0%} ({actual['source']}, day {actual['day']})")
                if target:
                    parts.append(f"target {target['value']:.0%} ({target['source']})")
                if actual and target:
                    parts.append("ABOVE target" if actual["value"] >= target["value"] else "BELOW target")
                lines.append("  " + "; ".join(parts))
            if opinion and not actual:
                lines.append(f"  unverified opinion ({opinion['source']}): performing "
                             f"{'above' if opinion['value'] else 'below'} expectations")
            for i in self.issues(fid):
                lines.append(f"  issue I{i['id']} [{i['status']}]: \"{i['summary']}\" ({i['reports']} reports)")
            hist = self.history(fid)
            if hist:
                lines.append("  history: " + "; ".join(f"day {h['day']} {h['text']}" for h in hist))
        return "\n".join(lines)

    def cards(self) -> list[dict]:
        out = []
        for f in self.features():
            fid = f["id"]
            plats = self.platforms(fid)
            actual, target = self.metric(fid, "actual"), self.metric(fid, "target")
            out.append({
                "id": fid, "name": f["name"], "former": self.former_names(fid), "last_verified": f["last_verified"],
                "platforms": {p: {"status": r["status"], "source": r["source"], "day": r["day"],
                                  "disputed": r["disputed"]} for p, r in plats.items()},
                "issues": [{"id": i["id"], "summary": i["summary"], "reports": i["reports"], "status": i["status"]}
                           for i in self.issues(fid)],
                "adoption": actual["value"] if actual else None,
                "target": target["value"] if target else None,
            })
        return out

    def mock_answer(self, q, role, day):
        """Mock reader for structured memory: look the answer up in the curated entry."""
        t = q["type"]
        if t == "release_notes":
            feats = []
            for f in self.features():
                live = [p for p, r in self.platforms(f["id"]).items() if r["status"] == "live"]
                if live:
                    feats.append({"name": f["name"], "platforms": live})
            return {"features": feats, "confidence": 0.85}
        fid = self.resolve(q["name"])
        if fid is None:
            return dict(UNKNOWN)
        plats = self.platforms(fid)
        if t == "status":
            statuses = {r["status"] for r in plats.values()}
            ans = "live" if "live" in statuses else "beta" if "beta" in statuses else "not_available"
            conf = max((r["trust"] for r in plats.values()), default=0.3)
            return {"answer": ans, "confidence": conf, "reason": f"brain entry {self.name_of(fid)}"}
        if t == "platform":
            r = plats.get(q["platform"])
            if not r:
                return dict(UNKNOWN)
            return {"answer": "yes" if r["status"] == "live" else "no", "confidence": r["trust"],
                    "reason": f"{r['status']} per {r['source']} #{r['event_id']}"}
        if t == "issues":
            return {"answer": len(self.issues(fid, "open")), "confidence": 0.8, "reason": "deduplicated issues"}
        if t == "rename":
            return {"answer": self.name_of(fid), "confidence": 0.9, "reason": "alias resolved"}
        if t == "rolled_back":
            pulled = any(r["status"] == "pulled" for r in plats.values()) or any(
                _landmark(h["text"]) and "-> pulled" in h["text"] for h in self.history(fid))
            return {"answer": "yes" if pulled else "no", "confidence": 0.8, "reason": "status and history"}
        if t == "adoption":
            actual = self.metric(fid, "actual")
            if actual:
                return {"answer": actual["value"], "confidence": 0.9, "reason": f"usage_stats day {actual['day']}"}
            return dict(UNKNOWN)
        if t == "target":
            actual, target, opinion = (self.metric(fid, k) for k in ("actual", "target", "opinion"))
            if actual and target:
                return {"answer": "above" if actual["value"] >= target["value"] else "below", "confidence": 0.9,
                        "reason": f"{actual['value']:.0%} vs {target['value']:.0%}"}
            if opinion:
                return {"answer": "above" if opinion["value"] else "below", "confidence": 0.3, "reason": "opinion"}
        return dict(UNKNOWN)
