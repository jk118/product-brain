"""Runs one event stream through all three teams and records everything for the judge and the viewer."""
from __future__ import annotations

import asyncio
import json
import random
import sqlite3
import time
from pathlib import Path

from . import judge
from .agents import ROLES, Agent
from .brain import ProductBrain
from .curator import Curator
from .events import World, generate
from .llm import LLM, Settings
from .memory import NaiveMemory, NoMemory

TEAMS = ("no_memory", "naive", "brain")

RESULT_SCHEMA = """
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, day INT, minute INT, type TEXT, author TEXT, text TEXT,
    claims TEXT, trap TEXT, feature_id TEXT);
CREATE TABLE IF NOT EXISTS truth(day INT, fid TEXT, state TEXT, PRIMARY KEY(day, fid));
CREATE TABLE IF NOT EXISTS answers(team TEXT, day INT, qid TEXT, agent TEXT, question TEXT, answer TEXT,
    truth TEXT, correct INT, stale INT, abstain INT, tokens INT);
CREATE TABLE IF NOT EXISTS metrics(team TEXT, day INT, data TEXT, PRIMARY KEY(team, day));
"""


def _save_world(db: sqlite3.Connection, world: World):
    db.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)",
                   [(e.id, e.day, e.minute, e.type, e.author, e.text, json.dumps(e.claims), e.trap, e.feature_id)
                    for e in world.events])
    db.executemany("INSERT INTO truth VALUES (?,?,?)",
                   [(d, fid, json.dumps(s)) for d, snap in enumerate(world.truth) for fid, s in snap.items()])


def _match_truth(world: World, day: int, card: dict) -> str | None:
    names = {n.lower() for n in [card["name"], *card["former"]]}
    for f in world.features:
        if names & {n.lower() for n in f.names}:
            return f.fid
    return None


async def run(seed: int = 7, days: int = 21, mode: str = "mock", extract: str = "oracle",
              out_root: str = "runs", settings: Settings | None = None, log=print, write_viewer: bool = True) -> dict:
    settings = settings or Settings.from_env()
    if mode == "live" and not settings.api_key:
        raise SystemExit("CRUSOE_API_KEY is not set (copy .env.example to .env)")
    if mode == "mock" and extract == "llm":
        raise SystemExit("--extract llm needs --mode live")

    world = generate(seed, days)
    qrng = random.Random(seed * 7919 + 1)  # judge randomness, independent of the generator
    checkpoints = judge.checkpoint_days(days, qrng)

    out = Path(out_root) / f"seed{seed}-{mode}-{extract}"
    out.mkdir(parents=True, exist_ok=True)
    dbpath = out / "product_brain.db"
    dbpath.unlink(missing_ok=True)
    db = sqlite3.connect(dbpath)
    db.row_factory = sqlite3.Row
    db.executescript(RESULT_SCHEMA)
    _save_world(db, world)

    mock = mode == "mock"
    agent_llm = LLM(settings, settings.agent_model, mock=mock)
    curator_llm = LLM(settings, settings.curator_model, mock=mock)
    teams = {"no_memory": NoMemory(world), "naive": NaiveMemory(db),
             "brain": ProductBrain(db, Curator(curator_llm))}
    agents = {role: Agent(role, world.product, agent_llm) for role in ROLES}

    log(f"{world.product}: {len(world.events)} events over {days} days, checkpoints on days {checkpoints}")
    started = time.time()
    day_records, cp_records, all_answers, finale = [], [], {t: [] for t in TEAMS}, None
    extract_tokens = 0

    for day in range(days):
        evs = world.events_on(day)
        results = await asyncio.gather(*(agents[r].extract(evs, extract) for r in ROLES))
        proposals = [p for ps, _ in results for p in ps]
        extract_tokens += sum(t for _, t in results)
        await teams["naive"].ingest(day, proposals)
        curator_log = await teams["brain"].ingest(day, proposals)
        db.commit()

        rec = {"day": day, "events": [dict(e.public(), trap=e.trap) for e in evs],
               "truth": world.truth[day], "log": curator_log, "proposals": len(proposals),
               "sizes": {t: teams[t].size_tokens() for t in TEAMS}, "naive_notes": teams["naive"].count()}
        cards = teams["brain"].cards()
        for c in cards:
            c["fid"] = _match_truth(world, day, c)
        rec["brain"] = cards

        if day in checkpoints:
            cp, fin = await _checkpoint(world, day, qrng, teams, agents, db, all_answers,
                                        finale=day == checkpoints[-1])
            rec["checkpoint"] = cp
            cp_records.append(cp)
            finale = fin or finale
            log(f"day {day:>2} checkpoint  " + "  ".join(
                f"{t}: acc {cp['teams'][t]['accuracy']:.0%} stale {cp['teams'][t]['stale_rate']:.0%}" for t in TEAMS))
        day_records.append(rec)

    summary = {t: judge.score(all_answers[t]) | {"final_memory_tokens": teams[t].size_tokens()} for t in TEAMS}
    for t in TEAMS:
        db.execute("INSERT INTO metrics VALUES (?,?,?)", (t, -1, json.dumps(summary[t])))
    db.commit()
    db.close()

    result = {
        "meta": {"seed": seed, "days": days, "product": world.product, "mode": mode, "extract": extract,
                 "agent_model": None if mock else settings.agent_model,
                 "curator_model": None if mock else settings.curator_model,
                 "llm_calls": agent_llm.calls + curator_llm.calls,
                 "llm_tokens": agent_llm.prompt_tokens + agent_llm.completion_tokens
                               + curator_llm.prompt_tokens + curator_llm.completion_tokens,
                 "extract_tokens": extract_tokens, "checkpoints": checkpoints,
                 "seconds": round(time.time() - started, 1), "events": len(world.events)},
        "features": [{"fid": f.fid, "trap": f.trap, "names": f.names} for f in world.features],
        "days": day_records, "summary": summary, "finale": finale,
    }
    (out / "run.json").write_text(json.dumps(result, indent=1, default=str))
    log(f"wrote {out / 'run.json'}")
    if write_viewer:
        viewer = Path(__file__).resolve().parent.parent / "viewer" / "data.js"
        viewer.write_text("window.RUN = " + json.dumps(result, default=str) + ";\n")
        log(f"wrote {viewer} (open viewer/index.html)")
    return result


async def _checkpoint(world, day, rng, teams, agents, db, all_answers, finale):
    qs = judge.make_questions(world, day, rng, finale=finale)

    async def ask(team, q, role):
        a = await agents[role].answer(q, teams[team], day)
        g = judge.grade(world, q, a)
        return team, {"qid": q["qid"], "type": q["type"], "agent": role, "question": q["text"],
                      "truth": q["truth"], "finale": q.get("finale", False), **a, **g}

    results = await asyncio.gather(*(ask(t, q, r) for t in TEAMS for q in qs for r in q["agents"]))
    per_team = {t: [] for t in TEAMS}
    for team, r in results:
        per_team[team].append(r)
        all_answers[team].append(r)
    db.executemany("INSERT INTO answers VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   [(t, day, r["qid"], r["agent"], r["question"], json.dumps(r["answer"]), json.dumps(r["truth"]),
                     int(r["correct"]), int(r["stale"]), int(r["abstain"]), r["tokens"]) for t, r in results])
    scores = {t: judge.score(per_team[t]) | {"memory_tokens": teams[t].size_tokens()} for t in TEAMS}
    for t in TEAMS:
        db.execute("INSERT INTO metrics VALUES (?,?,?)", (t, day, json.dumps(scores[t])))

    fin = None
    fq = next((q for q in qs if q.get("finale")), None)
    if fq:
        fin = {"day": day, "question": fq["text"], "truth": fq["truth"],
               "answers": {t: next(r for r in per_team[t] if r["qid"] == fq["qid"] and r["agent"] == "support")
                           for t in TEAMS}}
    return {"day": day, "teams": scores, "answers": per_team}, fin
