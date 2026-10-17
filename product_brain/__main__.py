"""CLI: python -m product_brain run | events"""
from __future__ import annotations

import argparse
import asyncio

from .events import generate
from .runner import TEAMS, run


def main():
    ap = argparse.ArgumentParser(prog="product_brain")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the three-team experiment")
    r.add_argument("--seed", type=int, default=7)
    r.add_argument("--days", type=int, default=21)
    r.add_argument("--mode", choices=["mock", "live"], default="mock",
                   help="mock: no LLM calls (pipeline test); live: Crusoe-hosted models")
    r.add_argument("--extract", choices=["oracle", "llm"], default="oracle",
                   help="how agents turn events into proposals (oracle = perfect extraction, isolates memory)")
    r.add_argument("--out", default="runs")
    e = sub.add_parser("events", help="print a generated event stream")
    e.add_argument("--seed", type=int, default=7)
    e.add_argument("--days", type=int, default=21)
    e.add_argument("--traps", action="store_true", help="annotate trap events (never shown to agents)")
    args = ap.parse_args()

    if args.cmd == "events":
        w = generate(args.seed, args.days)
        print(f"# {w.product}, seed {w.seed}")
        for f in w.features:
            print(f"#   {f.fid} {f.trap:<20} {' -> '.join(f.names)}")
        for ev in w.events:
            print(ev.render() + (f"   <<{ev.trap}>>" if args.traps and ev.trap else ""))
        return

    res = asyncio.run(run(args.seed, args.days, args.mode, args.extract, args.out))
    print(f"\n{'team':<11}{'accuracy':>9}{'stale':>8}{'contra':>8}{'notesF1':>9}{'tok/task':>10}{'memory':>8}")
    for t in TEAMS:
        s = res["summary"][t]
        print(f"{t:<11}{s['accuracy']:>9.0%}{s['stale_rate']:>8.0%}{s['contradiction_rate']:>8.0%}"
              f"{s['notes_f1']:>9.2f}{s['tokens_per_task']:>10}{s['final_memory_tokens']:>8}")
    if res["finale"]:
        f = res["finale"]
        print(f"\nFinale (day {f['day']}): {f['question']}  truth: {f['truth']}")
        for t in TEAMS:
            print(f"  {t:<10} {f['answers'][t]['answer']}  (conf {f['answers'][t]['confidence']:.2f})")


if __name__ == "__main__":
    main()
