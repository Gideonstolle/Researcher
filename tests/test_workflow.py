"""Offline checks for the provenance contract, failure records and imports."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote_plus

from researcher.__main__ import main
from researcher.imports import import_export
from researcher.provenance import Run, json_bytes, sha256, verify


RIS = b"TY  - JOUR\nTI  - Synthetic fixture one\nER  -\nTY  - JOUR\nTI  - Synthetic fixture two\nER  -\n"


def metadata(database="psycinfo"):
    return {
        "database": database,
        "platform": "Ovid" if database == "psycinfo" else "Web of Science",
        "searched_at": "2026-01-03T14:25:00+01:00",
        "filters": {},
        "total_results": 2,
        "exported_range": [1, 2],
        "collection": "APA PsycInfo" if database == "psycinfo" else "Core Collection",
        "timespan": "All years",
    }


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_cli(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_cli_preserves_exact_utf8_crlf_query_in_all_logs(self):
        original = ' ("émotion"[Title] OR "sleep  quality"[Title])\r\nAND 2020[Date - Publication] \r\n'.encode("utf-8")
        query_file = self.root / "input.txt"
        query_file.write_bytes(original)
        output = self.root / "runs"
        seen = []

        def fake_search(run, query, **options):
            seen.append(query)
            run.metadata.update(retrieval_complete=True, returned_count=0, total_results=0)
            return []

        with patch("researcher.pubmed.search", side_effect=fake_search):
            code, stdout, stderr = self.run_cli(["pubmed", "--query-file", str(query_file), "--out", str(output)])
        self.assertEqual(code, 0, stderr)
        run_path = Path(json.loads(stdout)["run_directory"])
        self.assertEqual((run_path / "query.txt").read_bytes(), original)
        self.assertEqual(seen, [original.decode("utf-8")])
        manifest = json.loads((run_path / "manifest.json").read_bytes())
        self.assertEqual(manifest["query"], seen[0])
        self.assertEqual(manifest["status"], "complete")
        events = [json.loads(line) for line in (run_path / "events.jsonl").read_text().splitlines()]
        recorded = next(event for event in events if event["event"] == "query_recorded")
        self.assertEqual(recorded["query"], seen[0])
        self.assertTrue(recorded["timestamp"])
        self.assertGreaterEqual(verify(run_path), 6)

    def test_failed_attempt_is_retained_and_credential_error_is_redacted(self):
        query_file = self.root / "query.txt"
        query_file.write_bytes(b"synthetic[Title]\r\n")
        output = self.root / "runs"
        key, email = "secret+key&value", "researcher+test@example.invalid"
        problem = "Request failed with " + quote_plus(key) + " and " + quote_plus(email)
        with patch.dict(os.environ, {"NCBI_API_KEY": key, "NCBI_EMAIL": email}), patch(
            "researcher.pubmed.search", side_effect=RuntimeError(problem)
        ):
            code, stdout, stderr = self.run_cli(["pubmed", "--query-file", str(query_file), "--out", str(output)])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        report = json.loads(stderr)
        run_path = Path(report["run_directory"])
        self.assertEqual(report["status"], "failed")
        self.assertEqual((run_path / "query.txt").read_bytes(), query_file.read_bytes())
        manifest = json.loads((run_path / "manifest.json").read_bytes())
        self.assertEqual(manifest["status"], "failed")
        self.assertTrue(manifest["finished_at"])
        self.assertFalse((run_path / "citations.ris").exists())
        for artifact in (run_path / "manifest.json", run_path / "events.jsonl"):
            body = artifact.read_text()
            for secret in (key, email, quote_plus(key), quote_plus(email)):
                self.assertNotIn(secret, body)
        self.assertIn("[REDACTED]", report["error"])
        verify(run_path)

    def test_bom_rejection_retains_original_bytes_and_unique_runs(self):
        query_file = self.root / "query.txt"
        original = b"\xef\xbb\xbfpsychology"
        query_file.write_bytes(original)
        output = self.root / "runs"
        paths = []
        with patch("researcher.pubmed.search") as search:
            for _ in range(2):
                code, _, stderr = self.run_cli(["pubmed", "--query-file", str(query_file), "--out", str(output)])
                self.assertEqual(code, 1)
                run_path = Path(json.loads(stderr)["run_directory"])
                paths.append(run_path)
                self.assertEqual((run_path / "query.txt").read_bytes(), original)
                verify(run_path)
            search.assert_not_called()
        self.assertNotEqual(paths[0], paths[1])

    def test_import_cli_failure_retains_raw_export_and_metadata(self):
        query = self.root / "query.txt"
        query.write_bytes(b"TI(synthetic)\n")
        data = self.root / "export.ris"
        data.write_bytes(RIS)
        details = self.root / "metadata.json"
        wrong = metadata()
        wrong["exported_range"] = [1, 3]
        details.write_bytes(json_bytes(wrong))
        code, _, stderr = self.run_cli([
            "import", "--database", "psycinfo", "--file", str(data), "--query-file", str(query),
            "--metadata", str(details), "--out", str(self.root / "runs"),
        ])
        self.assertEqual(code, 1)
        run_path = Path(json.loads(stderr)["run_directory"])
        self.assertEqual((run_path / "raw/export.ris").read_bytes(), RIS)
        self.assertEqual((run_path / "raw/search-metadata.json").read_bytes(), details.read_bytes())
        verify(run_path)


class ImportProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def do_import(self, details, data=RIS, database="psycinfo"):
        run = Run(self.root, database)
        records = import_export(run, database, data, json_bytes(details))
        return run, records

    def test_complete_export_is_a_user_claim_not_an_executed_search(self):
        for database in ("psycinfo", "webofscience"):
            with self.subTest(database=database):
                details = metadata(database)
                run, records = self.do_import(details, database=database)
                self.assertEqual(len(records), 2)
                self.assertEqual(run.metadata["coverage"], "user_reported_complete")
                self.assertIs(run.metadata["retrieval_complete"], None)
                self.assertIs(run.metadata["search_executed_by_program"], False)
                self.assertEqual(run.metadata["original_search"], details)
                self.assertNotEqual(run.metadata["started_at"], details["searched_at"])
                self.assertEqual(run.metadata["returned_count"], 2)
                self.assertEqual((run.directory / "raw/export.ris").read_bytes(), RIS)

    def test_partial_and_unknown_metadata_never_claim_completeness(self):
        partial = metadata()
        partial.update(total_results=20, exported_range=[5, 6])
        unknown = metadata()
        unknown.update(searched_at=None, total_results=None, exported_range=None, collection=None, timespan=None)
        for details in (partial, unknown):
            with self.subTest(details=details):
                run, _ = self.do_import(details)
                self.assertEqual(run.metadata["coverage"], "partial_or_unverified")
                self.assertEqual(run.metadata["original_search"], details)

    def test_unknown_filters_remain_unknown(self):
        details = metadata()
        details["filters"] = None
        run, _ = self.do_import(details)
        self.assertIsNone(run.metadata["original_search"]["filters"])

    def test_invalid_metadata_is_rejected(self):
        changes = [
            {"database": "webofscience"}, {"platform": "Guessed provider"},
            {"searched_at": "2026-01-03T14:25:00"}, {"searched_at": 123},
            {"total_results": True}, {"total_results": -1}, {"total_results": "2"},
            {"exported_range": [0, 1]}, {"exported_range": [2, 1]},
            {"exported_range": [1, 3]}, {"exported_range": [2, 3], "total_results": 2},
            {"collection": ["Core"]}, {"timespan": 2020}, {"filters": []},
            {"exported_range": None, "total_results": 1},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                details = metadata()
                details.update(change)
                self.do_import(details)
        for missing in ("searched_at", "filters", "total_results", "exported_range", "collection", "timespan"):
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                details = metadata()
                del details[missing]
                self.do_import(details)


class ChecksumTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def finished_run(self):
        run = Run(self.root / "runs", "pubmed")
        run.write_bytes("raw/sample.json", b'{"count":0}\n')
        run.finish("complete")
        return run

    def test_changes_missing_files_and_untracked_artifacts_are_detected(self):
        run = self.finished_run()
        self.assertEqual(verify(run.directory), 3)
        sample = run.directory / "raw/sample.json"
        original = sample.read_bytes()
        sample.write_bytes(b'{"count":1}\n')
        with self.assertRaisesRegex(ValueError, "missing or changed"):
            verify(run.directory)
        sample.unlink()
        with self.assertRaisesRegex(ValueError, "missing or changed"):
            verify(run.directory)
        sample.write_bytes(original)
        (run.directory / "surprise.txt").write_text("extra")
        with self.assertRaisesRegex(ValueError, "untracked artifact"):
            verify(run.directory)

    def test_writes_cannot_escape_run_directory(self):
        run = Run(self.root / "runs", "pubmed")
        for filename in ("../escape.txt", str(self.root / "absolute.txt")):
            with self.subTest(filename=filename), self.assertRaisesRegex(ValueError, "inside"):
                run.write_bytes(filename, b"do not write")
        outside = self.root / "external"
        outside.mkdir()
        (run.directory / "link").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "inside"):
            run.write_bytes("link/escape.txt", b"do not write")
        self.assertFalse((outside / "escape.txt").exists())

    def test_checksum_inventory_cannot_read_escaped_paths(self):
        run = self.finished_run()
        inventory = run.directory / "checksums.json"
        contents = json.loads(inventory.read_bytes())
        contents["../outside.txt"] = sha256(b"outside")
        inventory.write_bytes(json_bytes(contents))
        with self.assertRaisesRegex(ValueError, "unsafe path"):
            verify(run.directory)

    def test_tracked_symlink_escape_and_incomplete_inventory_fail(self):
        run = self.finished_run()
        outside = self.root / "external.json"
        outside.write_bytes(b'{"count":0}\n')
        sample = run.directory / "raw/sample.json"
        sample.unlink()
        sample.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "unsafe path"):
            verify(run.directory)
        (run.directory / "checksums.json").write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "incomplete checksum inventory"):
            verify(run.directory)


if __name__ == "__main__":
    unittest.main()
