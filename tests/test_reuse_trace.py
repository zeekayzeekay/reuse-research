"""Audit epistemic boundaries; no network or real expected candidate names."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import trace_retrieval as trace


class TraceBoundaries(unittest.TestCase):
    def test_missing_discovery_trace_does_not_become_retrieval_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "run").mkdir()
            (root / "run/report.md").write_text("An incomplete report.", encoding="utf-8")
            with patch.object(trace, "ROOT", root):
                row = trace.audit_run({"id": "test", "path": "run"}, [{"repo": "a/app"}])["rows"][0]
            self.assertIsNone(row["final_pool"])
            self.assertEqual(row["first_observed_loss"], "unknown_missing_ledger")

    def test_same_name_different_owner_does_not_earn_visibility(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "run").mkdir()
            (root / "run/report.md").write_text("https://github.com/other/editor is an editor.", encoding="utf-8")
            with patch.object(trace, "ROOT", root):
                row = trace.audit_run({"id": "test", "path": "run"}, [{"repo": "a/editor"}])["rows"][0]
            self.assertFalse(row["report_mention"])

    def test_unresolved_name_in_search_response_stays_separate_from_link(self):
        value = {"logs": [{"queries": ["profile library"], "result": "A wrapper uses the Profiles library."}]}
        logs = trace.query_logs(value)
        self.assertEqual(logs[0]["texts"], ["profile library"])
        self.assertEqual(logs[0]["links"], [])


if __name__ == "__main__":
    unittest.main()
