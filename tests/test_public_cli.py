"""Public-source routing must not silently substitute a database or drop filters."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from researcher.__main__ import main
from researcher.provenance import verify


class PublicCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.query = self.root / "query.txt"
        self.query.write_bytes(b'"pretend play" AND development\r\n')

    def call(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    def test_public_pubmed_alias_preserves_query_reason_and_sort(self):
        def result(run, query, **options):
            self.assertEqual(query.encode(), self.query.read_bytes())
            self.assertEqual(options["sort"], "relevance")
            self.assertEqual(options["max_records"], 20)
            self.assertTrue(options["allow_partial"])
            run.metadata.update(total_count=100, returned_count=0, retrieval_complete=False)
            return []
        with patch("researcher.pubmed.search", side_effect=result) as search:
            code, out, err = self.call([
                "search", "--engine", "pubmed", "--query-file", str(self.query),
                "--sort", "relevance", "--max-records", "20", "--allow-partial",
                "--reason", "Check alternate terminology", "--parent-run", "prior-run",
                "--out", str(self.root / "runs")])
        self.assertEqual(code, 0, err)
        search.assert_called_once()
        folder = Path(json.loads(out)["run_directory"])
        manifest = json.loads((folder / "manifest.json").read_text())
        self.assertEqual(manifest["database"], "pubmed")
        self.assertEqual(manifest["search_reason"], "Check alternate terminology")
        self.assertEqual(manifest["parent_run_id"], "prior-run")
        self.assertEqual(manifest["status"], "partial")
        verify(folder)

    def test_scholar_alias_only_plans_without_network_or_pubmed_substitution(self):
        with patch("urllib.request.urlopen") as network, patch("researcher.pubmed.search") as pubmed:
            code, out, err = self.call([
                "search", "--engine", "google-scholar", "--query-file", str(self.query),
                "--year-from", "2020", "--year-to", "2026", "--out", str(self.root / "runs")])
        self.assertEqual(code, 0, err)
        network.assert_not_called()
        pubmed.assert_not_called()
        result = json.loads(out)
        folder = Path(result["run_directory"])
        self.assertEqual(result["status"], "planned")
        self.assertIn("scholar.google.com", result["search_url"])
        self.assertEqual((folder / "query.txt").read_bytes(), self.query.read_bytes())
        manifest = json.loads((folder / "manifest.json").read_text())
        self.assertFalse(manifest["search_executed_by_program"])
        verify(folder)

    def test_source_specific_options_are_not_silently_ignored(self):
        for engine, option in [("pubmed", ["--year-from", "2020"]),
                               ("pubmed", ["--sort", "date"]),
                               ("google-scholar", ["--allow-partial"]),
                               ("google-scholar", ["--max-records", "100"]),
                               ("google-scholar", ["--sort", "pub_date"])]:
            with self.subTest(engine=engine, option=option):
                code, out, err = self.call(["search", "--engine", engine,
                    "--query-file", str(self.query), *option, "--out", str(self.root / "runs")])
                self.assertEqual(code, 2)
                self.assertTrue(err)
                self.assertEqual(out, "")
        self.assertFalse((self.root / "runs").exists())

    def test_scholar_observation_to_review_preserves_search_and_blank_analysis(self):
        code, out, err = self.call(["scholar-plan", "--query-file", str(self.query),
            "--out", str(self.root / "runs")])
        self.assertEqual(code, 0, err)
        planned = Path(json.loads(out)["run_directory"])
        observation = json.loads((planned / "observation-template.json").read_text())
        observation.update(searched_at="2026-11-13T10:00:00+01:00", status="partial",
            pages_checked=[1], stop_reason="Synthetic test cap; not a real search",
            steps=[{"at": "2026-11-13T10:00:00+01:00", "action": "inspect",
                    "details": "Synthetic test fixture only"}],
            results=[{"rank": 1, "page": 1, "title": "Synthetic paper fixture",
                      "url": "https://example.invalid/paper"}])
        observed_file = self.root / "observed.json"
        observed_file.write_text(json.dumps(observation))
        code, out, err = self.call(["scholar-record", "--query-file", str(self.query),
            "--observation", str(observed_file), "--out", str(self.root / "runs")])
        self.assertEqual(code, 0, err)
        observed = Path(json.loads(out)["run_directory"])
        verify(observed)
        destination = self.root / "review"
        code, out, err = self.call(["review", "--runs", str(planned), str(observed),
            "--question", "Synthetic question", "--out", str(destination)])
        self.assertEqual(code, 0, err)
        report = json.loads(out)
        self.assertEqual(report["source_runs"], 2)
        self.assertEqual(report["retrieved_records"], 1)
        self.assertEqual(report["gap_analysis_status"], "scaffold_only")
        self.assertTrue((destination / "evidence.csv").is_file())
        self.assertIn("planned", (destination / "search-log.md").read_text())


if __name__ == "__main__":
    unittest.main()
