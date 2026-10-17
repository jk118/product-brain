"""Publish every run under runs/ to the viewer.

The viewer is opened straight from disk (file://), where fetch() is blocked, so
each run is written as a script that registers itself on window.RUNS, plus an
index script listing all runs for the picker.
"""
from __future__ import annotations

import json
from pathlib import Path

VIEWER = Path(__file__).resolve().parent.parent / "viewer"


def _label(meta: dict) -> str:
    if meta["mode"] == "mock":
        model = "mock"
    else:
        model = (meta.get("agent_model") or "?").split("/")[-1]
    return f"seed {meta['seed']} · {meta['days']}d · {model} · {meta['extract']} extraction"


def export_runs(runs_root: str | Path = "runs", viewer_dir: Path = VIEWER) -> list[dict]:
    out_dir = viewer_dir / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for path in sorted(Path(runs_root).glob("*/run.json")):
        run = json.loads(path.read_text())
        rid = path.parent.name
        (out_dir / f"{rid}.js").write_text(
            "window.RUNS = window.RUNS || {};\n"
            f"window.RUNS[{json.dumps(rid)}] = {json.dumps(run, default=str)};\n")
        meta = run["meta"]
        index.append({"id": rid, "label": _label(meta), "mode": meta["mode"], "seed": meta["seed"],
                      "days": meta["days"], "extract": meta["extract"], "product": meta["product"],
                      "agent_model": meta.get("agent_model"), "updated": path.stat().st_mtime,
                      "summary": run["summary"]})
    index.sort(key=lambda r: r["updated"], reverse=True)
    (out_dir / "index.js").write_text("window.RUN_INDEX = " + json.dumps(index, indent=1) + ";\n")
    return index
