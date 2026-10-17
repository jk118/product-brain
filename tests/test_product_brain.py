import asyncio
import sqlite3
import tempfile
import unittest

from product_brain import judge
from product_brain.agents import _clean_claim, normalize
from product_brain.brain import ProductBrain
from product_brain.curator import Curator
from product_brain.events import Event, generate
from product_brain.llm import Settings
from product_brain.runner import run


def proposal(kind, event_id, day, source, **fields):
    return {"kind": kind, "event_id": event_id, "day": day, "source_type": source, "agent": "support", **fields}


class GeneratorTest(unittest.TestCase):
    def test_deterministic_per_seed_and_varies_across_seeds(self):
        a, b, c = generate(3), generate(3), generate(4)
        self.assertEqual([e.text for e in a.events], [e.text for e in b.events])
        self.assertNotEqual([e.text for e in a.events], [e.text for e in c.events])

    def test_traps_land_in_truth(self):
        for seed in range(10):
            w = generate(seed)
            by_trap = {f.trap: f for f in w.features}
            final = w.truth[-1]
            history = lambda trap: [day[by_trap[trap].fid] for day in w.truth]

            rollback = history("rollback")
            self.assertTrue(any(set(s["platforms"].values()) == {"pulled"} for s in rollback))
            self.assertEqual(set(rollback[-1]["platforms"].values()), {"live"})  # relaunched

            self.assertEqual(set(final[by_trap["rumor"].fid]["platforms"].values()), {"beta"})
            split = final[by_trap["platform_split"].fid]["platforms"]
            self.assertEqual((split["ios"], split["android"]), ("live", "beta"))
            partial = final[by_trap["partial_rollback"].fid]["platforms"]
            self.assertEqual((partial["ios"], partial["android"]), ("live", "pulled"))

            renamed = final[by_trap["rename_split"].fid]
            self.assertEqual(renamed["name"], by_trap["rename_split"].rename_to)

            data = history("data_vs_assumption")
            self.assertTrue(any(s["adoption"] and s["adoption"] < s["target"] for s in data))
            self.assertGreaterEqual(data[-1]["adoption"], data[-1]["target"])  # target revised down

            issues = [s["issues"].get("export-crash") for s in history("duplicates")]
            self.assertIn("fixed", issues)
            self.assertEqual(issues[-1], "open")  # regression
            self.assertEqual(final[by_trap["duplicates"].fid]["issues"]["timezone"], "open")

    def test_no_feature_regresses_from_live_to_beta(self):
        # A launch must never be followed by an "enters beta" release (only a rollback may undo it).
        for days in (14, 18, 21, 28):
            for seed in range(25):
                w = generate(seed, days)
                for f in w.features:
                    for d in range(1, days):
                        for p, before in w.truth[d - 1][f.fid]["platforms"].items():
                            after = w.truth[d][f.fid]["platforms"][p]
                            self.assertFalse(before == "live" and after == "beta",
                                             f"seed {seed} days {days} {f.name} {p} live->beta on day {d}")


class CuratorTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.brain = ProductBrain(self.db, Curator())
        self.addCleanup(self.db.close)

    def ingest(self, day, *props):
        return asyncio.run(self.brain.ingest(day, list(props)))

    def status(self, name, platform):
        return self.brain.platforms(self.brain.resolve(name))[platform]["status"]

    def test_rumor_loses_to_release_log(self):
        self.ingest(2, proposal("status", 1, 2, "release_log", feature="X", status="beta", platforms=None))
        log = self.ingest(5, proposal("status", 2, 5, "chat", feature="X", status="live", platforms=None))
        self.assertEqual(self.status("X", "ios"), "beta")
        self.assertEqual(log[-1]["action"], "conflict")

    def test_rollback_overrides_launch(self):
        self.ingest(5, proposal("status", 1, 5, "release_log", feature="X", status="live", platforms=None))
        log = self.ingest(7, proposal("status", 2, 7, "release_log", feature="X", status="pulled", platforms=None))
        self.assertEqual(self.status("X", "android"), "pulled")
        self.assertEqual(log[-1]["action"], "rollback")

    def test_rename_links_old_name_and_merges_entries(self):
        self.ingest(3, proposal("status", 1, 3, "release_log", feature="Old", status="live", platforms=["ios"]))
        self.ingest(4, proposal("status", 2, 4, "chat", feature="New", status="beta", platforms=["android"]))
        self.ingest(5, proposal("rename", 3, 5, "release_log", old="Old", new="New"))
        self.assertEqual(self.brain.resolve("Old"), self.brain.resolve("New"))
        self.assertEqual(len(self.brain.features()), 1)
        self.assertEqual(self.status("Old", "ios"), "live")

    def test_duplicate_reports_merge(self):
        reports = ["App crashes when I export a big X document.", "Every time I try exporting from X the app quits on me.",
                   "X: exporting anything over ~50 pages freezes and then closes the app.",
                   "Export from X = instant crash on large docs. Please fix!", "X keeps crashing during export of long files."]
        for i, r in enumerate(reports):
            self.ingest(i, proposal("issue", i + 1, i, "support_ticket", feature="X", symptom=r))
        self.ingest(6, proposal("issue", 9, 6, "support_ticket", feature="X", symptom="X shows the wrong timezone on shared items."))
        issues = self.brain.issues(self.brain.resolve("X"), "open")
        self.assertEqual(sorted(i["reports"] for i in issues), [1, 5])


    def test_regression_reopens_fixed_issue(self):
        crash = "App crashes when I export a big X document."
        self.ingest(1, proposal("issue", 1, 1, "support_ticket", feature="X", symptom=crash))
        self.ingest(2, proposal("issue_fixed", 2, 2, "release_log", feature="X",
                                symptom="Fixed a crash when exporting large documents from X."))
        log = self.ingest(4, proposal("issue", 3, 4, "support_ticket", feature="X",
                                      symptom="X is crashing on export again after the last update."))
        self.assertEqual(log[-1]["action"], "reopen")
        self.assertEqual(len(self.brain.issues(self.brain.resolve("X"), "open")), 1)


class ParsingTest(unittest.TestCase):
    def test_clean_llm_claim(self):
        ev = Event(12, 3, 600, "chat", "a", "X shipped!")
        c = _clean_claim({"kind": "status", "feature": "X", "status": "live", "platforms": ["iOS", "tv"], "event_id": "#12"}, {12: ev})
        self.assertEqual((c["source_type"], c["platforms"]), ("chat", ["ios"]))
        self.assertIsNone(_clean_claim({"kind": "status", "feature": "X", "status": "shipped", "event_id": 12}, {12: ev}))

    def test_normalize_answers(self):
        self.assertEqual(normalize({"type": "status"}, {"answer": "Not available"})["answer"], "not_available")
        self.assertEqual(normalize({"type": "issues"}, {"answer": "2 bugs"})["answer"], 2)
        self.assertEqual(normalize({"type": "platform"}, None)["answer"], "unknown")


class EndToEndTest(unittest.TestCase):
    def test_mock_run(self):
        with tempfile.TemporaryDirectory() as out:
            res = asyncio.run(run(seed=11, out_root=out, settings=Settings("", "", "m", "m"), log=lambda *_: None,
                                  write_viewer=False))
        s = res["summary"]
        self.assertLess(s["brain"]["final_memory_tokens"], s["naive"]["final_memory_tokens"])
        self.assertGreaterEqual(s["brain"]["accuracy"], s["naive"]["accuracy"])
        self.assertIsNotNone(res["finale"])
        self.assertEqual(len(res["days"]), 21)

    def test_stale_grading(self):
        q = {"type": "status", "truth": "not_available", "past": ["beta", "live"]}
        self.assertTrue(judge.grade(None, q, {"answer": "live", "confidence": 0.9})["stale"])
        self.assertFalse(judge.grade(None, q, {"answer": "live", "confidence": 0.3})["stale"])


if __name__ == "__main__":
    unittest.main()
