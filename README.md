# Product Brain

**Product knowledge goes stale the moment it's written down.** Product Brain is a shared memory that a
team of agents keeps current, lean and contradiction-free. We measure it by how often each team
confidently gives an answer that *used to be* true.

Track: Shared Brain.

## What it does

A fake product's history streams in over a simulated three weeks: release logs, announcements, team
chat, support tickets, usage stats, roadmap updates and code changes. Three teams of agents (Support,
Release Notes Writer, Analyst) process the same stream. Only their memory differs:

| Team | Memory |
|---|---|
| **No memory** | each agent sees only its last 30 visible events |
| **Naive memory** | every agent appends every claim it extracts to a shared log |
| **Product Brain** | agents *propose* claims; a curator merges, resolves conflicts, links renames, dedups, prunes |

At checkpoints a judge asks questions whose answers come from a hidden truth table, and grades the
release notes the writer produces.

### Planted traps

| Trap | What happens |
|---|---|
| Rollback | a feature launches, then is pulled two days later. Later, chat still says customers love it |
| Rename | feature A becomes B mid-run. Customers keep using the old name |
| Platform split | live on iOS (and Web), still beta on Android |
| Rumor vs reality | chat says "shipped!" while the release log says beta |
| Data vs assumption | roadmap expects ~40% adoption, usage shows ~7%, and chat says "crushing it" |
| Duplicate reports | five differently worded tickets describe one bug, plus one unrelated bug. The main bug is later fixed |

Feature names, timing and trap assignment are randomized per seed.

### The curator's rules ([curator.py](product_brain/curator.py))

- **Source authority:** release_log > usage_stats > announcement > code_change > roadmap > support_ticket > chat.
  A weaker claim that contradicts a stronger one is rejected and logged as a conflict, and the entry is marked disputed.
- **Freshness:** an equal-or-stronger newer claim overrides, and the old value moves to history. Any claim with
  authority ≥ 0.5 can override an entry that hasn't been re-verified for 6 days.
- **Renames:** the old name becomes an alias. If both names already had entries, the entries are merged.
- **Duplicates:** bug reports are clustered by token overlap, with an LLM fallback in live mode. Fixes close the cluster.
- **Size budget:** history and fixed issues are trimmed to keep the brain under ~1.8k tokens.

## Metrics

- **Stale answer rate** (headline): wrong answers that were true earlier in the timeline, given with confidence ≥ 0.6.
- **Accuracy** on checkpoint questions (status, Android availability, open-bug count, adoption vs target).
- **Contradiction rate:** Support and Analyst on the same team answer the same question differently.
- **Release-notes F1** against what's actually live per platform, plus a count of stale items.
- **Memory size over time** and **tokens per task**.

## Run it

Python 3.11+, standard library only.

```bash
# Free pipeline test: no LLM calls
python -m product_brain run --seed 7
open viewer/index.html            # timeline viewer; reads viewer/data.js written by the run

# Real experiment on Crusoe Managed Inference
cp .env.example .env              # add CRUSOE_API_KEY, confirm base URL + model IDs
python -m product_brain run --seed 7 --mode live                  # LLM agents, perfect extraction
python -m product_brain run --seed 7 --mode live --extract llm    # LLM agents extract claims too

python -m product_brain events --seed 7 --traps   # inspect the generated stream
python -m unittest discover -s tests
```

Outputs go to `runs/seed<N>-<mode>-<extract>/`: `run.json`, plus `product_brain.db` (SQLite with events,
truth, the naive notes, all brain tables, the curator log, every graded answer and the metrics).

### Viewer

Every run is published to `viewer/runs/` automatically. `python -m product_brain viewer` republishes all
runs and opens the page (no server or build step needed). Pick a run from the dropdown, or open
**All runs** to compare stale rate and accuracy across every run. Links like
`viewer/index.html#run=seed7-live-oracle&day=12` jump straight to a run and day, which helps in a demo.
Use the arrow keys to step through days and the space bar to play or pause.

### Modes, honestly

- **mock** replaces the LLM with a deterministic reader. For the unstructured memories it uses the most
  recent claim that mentions the feature name. For the brain it reads the curated entry. That makes it a
  pipeline test and a picture of what curation *should* buy, **not evidence**. The brain scores ~100% there by construction.
- **live** sends identical prompts to every team. Only the memory context differs, so live runs are the experiment.
- **`--extract oracle`** uses the generator's annotation of what each event *claims* (a rumor is
  recorded as claiming "live"), standing in for a perfect extractor. This isolates the memory effect.
  **`--extract llm`** has the agents extract claims themselves. Extraction runs once per agent per day
  and is shared by the naive and brain teams, so both get identical input.

### Cost

One live run at the default 21 days makes ~360–420 calls and uses roughly 0.5–0.7M tokens. The naive
team's growing context dominates. Check your per-token price; a few runs across seeds should fit comfortably in $50.

## Safeguards

- Agents never see the truth table, trap labels, or claim annotations. Only `Event.render()` reaches a prompt.
- Questions are generated at checkpoint time from the truth snapshot, and sometimes use a feature's former name.
- Seeds randomize feature names, timing and trap placement. Run several seeds and report the spread.
- All data is synthetic.

## Layout

```
product_brain/
  events.py    generator, traps, truth table
  memory.py    no-memory and naive baselines, shared helpers
  brain.py     Product Brain storage (SQLite) and rendering
  curator.py   the curation rules
  agents.py    Support / Writer / Analyst prompts, extraction, answering
  judge.py     checkpoint questions and grading
  runner.py    runs the three teams, writes results
  llm.py       stdlib OpenAI-compatible client (Crusoe)
viewer/index.html   timeline viewer (no build step)
```
