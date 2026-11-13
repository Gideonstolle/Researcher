"""Offline CLI checks for the optional Web of Science API workflow."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import quote, quote_plus

from researcher.__main__ import main, safe_error
from researcher.citations import parse_ris
from researcher.provenance import json_bytes, verify


def json_documents(text):
    """Doctor emits a configuration report followed by a run result."""
    decoder, documents = json.JSONDecoder(), []
    remaining = text.lstrip()
    while remaining:
        value, end = decoder.raw_decode(remaining)
        documents.append(value)
        remaining = remaining[end:].lstrip()
    return documents


def fixture_record():
    return {
        "id": "webofscience:WOS:SYNTHETIC001",
        "source": "webofscience", "accession": "WOS:SYNTHETIC001",
        "type": "article", "title": "Synthetic CLI citation",
        "authors": [{"family": "Fixture", "given": "Ada"}], "year": "2020",
    }


class WebOfScienceCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_cli(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    @contextlib.contextmanager
    def adapter(self, effect):
        module = types.ModuleType("researcher.webofscience")
        module.search = Mock(side_effect=effect)
        with patch.dict(sys.modules, {"researcher.webofscience": module}):
            yield module.search

    def assert_secret_absent(self, secret, run_path, *messages):
        forms = {secret, quote(secret, safe=""), quote_plus(secret)}
        bodies = list(messages) + [p.read_text(encoding="utf-8")
                                  for p in run_path.rglob("*") if p.is_file()]
        for body in bodies:
            for form in forms:
                self.assertNotIn(form, body)

    def test_online_doctor_dispatches_one_record_and_three_request_budget(self):
        key = "synthetic-wos-key+one/value"

        def search(run, query, **options):
            run.metadata.update(total_count=7, returned_count=1, retrieval_complete=False)
            return [fixture_record()]

        with patch.dict(os.environ, {"WOS_API_KEY": key}), self.adapter(search) as mocked:
            code, stdout, stderr = self.run_cli([
                "doctor", "--database", "webofscience", "--online", "--out", str(self.root / "runs"),
            ])
        self.assertEqual(code, 0, stderr)
        config, result = json_documents(stdout)
        self.assertEqual(config["online_database"], "webofscience")
        self.assertIs(config["wos_api_key_configured"], True)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["records"], 1)
        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.args[1], "TI=(psychology) AND PY=2020")
        self.assertEqual(mocked.call_args.kwargs, {
            "max_records": 1, "allow_partial": True, "api_key": key,
            "collection": "WOS", "edition": None, "max_requests": 3,
        })
        run_path = Path(result["run_directory"])
        manifest = json.loads((run_path / "manifest.json").read_bytes())
        self.assertEqual(manifest["database"], "webofscience")
        self.assertEqual(manifest["purpose"], "connectivity_smoke_test_not_a_review")
        self.assertEqual(len(parse_ris((run_path / "citations.ris").read_bytes(), "webofscience")), 1)
        self.assertIn("Synthetic CLI citation", (run_path / "citations.bib").read_text())
        self.assertGreaterEqual(verify(run_path), 6)
        self.assert_secret_absent(key, run_path, stdout, stderr)

    def test_search_preserves_utf8_crlf_query_and_forwards_explicit_options(self):
        raw_query = ' TS=("émotion" OR "sleep  quality")\r\nAND PY=2020 \r\n'.encode("utf-8")
        query = self.root / "query.txt"
        query.write_bytes(raw_query)
        key = "synthetic-wos-key-two"

        def search(run, actual_query, **options):
            run.metadata.update(total_count=1, returned_count=1, retrieval_complete=True)
            return [fixture_record()]

        with patch.dict(os.environ, {"WOS_API_KEY": key}), self.adapter(search) as mocked:
            code, stdout, stderr = self.run_cli([
                "webofscience", "--query-file", str(query), "--max-records", "20", "--allow-partial",
                "--collection", "WOS", "--edition", "WOS+SSCI", "--max-requests", "4",
                "--out", str(self.root / "runs"),
            ])
        self.assertEqual(code, 0, stderr)
        result = json.loads(stdout)
        run_path = Path(result["run_directory"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual((run_path / "query.txt").read_bytes(), raw_query)
        self.assertEqual(mocked.call_args.args[1], raw_query.decode("utf-8"))
        self.assertEqual(mocked.call_args.kwargs, {
            "max_records": 20, "allow_partial": True, "api_key": key,
            "collection": "WOS", "edition": "WOS+SSCI", "max_requests": 4,
        })
        manifest = json.loads((run_path / "manifest.json").read_bytes())
        events = [json.loads(line) for line in (run_path / "events.jsonl").read_text().splitlines()]
        self.assertEqual(manifest["query"], raw_query.decode("utf-8"))
        self.assertEqual(next(e["query"] for e in events if e["event"] == "query_recorded"), raw_query.decode("utf-8"))
        self.assertEqual(json.loads((run_path / "records.json").read_bytes()), [fixture_record()])
        code, verify_stdout, verify_stderr = self.run_cli(["verify", str(run_path)])
        self.assertEqual(code, 0, verify_stderr)
        self.assertIn("Verified", verify_stdout)
        self.assert_secret_absent(key, run_path, stdout, stderr)

    def test_adapter_error_redacts_key_in_stdout_and_saved_failure(self):
        query = self.root / "query.txt"
        query.write_bytes(b"TI=(synthetic)\r\n")
        key = "synthetic secret+/&value"
        message = "key forms: " + " | ".join((key, quote(key, safe=""), quote_plus(key)))
        with patch.dict(os.environ, {"WOS_API_KEY": key}), self.adapter(RuntimeError(message)):
            self.assertEqual(safe_error(RuntimeError(message)), "key forms: [REDACTED] | [REDACTED] | [REDACTED]")
            code, stdout, stderr = self.run_cli([
                "webofscience", "--query-file", str(query), "--out", str(self.root / "runs"),
            ])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        result = json.loads(stderr)
        run_path = Path(result["run_directory"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("[REDACTED]", result["error"])
        self.assertEqual((run_path / "query.txt").read_bytes(), query.read_bytes())
        self.assertFalse((run_path / "citations.ris").exists())
        verify(run_path)
        self.assert_secret_absent(key, run_path, stdout, stderr)

    def test_offline_doctor_never_calls_the_api(self):
        with patch.dict(os.environ, {}, clear=True), self.adapter(AssertionError("Unexpected search")) as mocked:
            code, stdout, stderr = self.run_cli([
                "doctor", "--database", "webofscience", "--out", str(self.root / "runs"),
            ])
        self.assertEqual(code, 0, stderr)
        config = json.loads(stdout)
        self.assertEqual(config["online_test"], "not_run")
        self.assertIs(config["wos_api_key_configured"], False)
        mocked.assert_not_called()
        self.assertFalse((self.root / "runs").exists())

    def test_authorized_import_remains_separate_from_online_search(self):
        for database in ("psycinfo", "webofscience"):
            with self.subTest(database=database):
                query = self.root / (database + ".txt")
                query.write_text("TI=(synthetic)", encoding="utf-8")
                exported = self.root / (database + ".ris")
                exported.write_bytes(b"TY  - JOUR\nTI  - Synthetic imported citation\nER  -\n")
                metadata = self.root / (database + ".json")
                metadata.write_bytes(json_bytes({
                    "database": database,
                    "platform": "Ovid" if database == "psycinfo" else "Web of Science",
                    "searched_at": None, "filters": None, "total_results": 1,
                    "exported_range": [1, 1], "collection": None, "timespan": None,
                }))
                with patch.dict(os.environ, {}, clear=True), self.adapter(AssertionError("Unexpected API call")) as mocked:
                    code, stdout, stderr = self.run_cli([
                        "import", "--database", database, "--file", str(exported),
                        "--query-file", str(query), "--metadata", str(metadata),
                        "--out", str(self.root / "runs"),
                    ])
                self.assertEqual(code, 0, stderr)
                mocked.assert_not_called()
                result = json.loads(stdout)
                self.assertEqual(result["status"], "imported")
                run_path = Path(result["run_directory"])
                manifest = json.loads((run_path / "manifest.json").read_bytes())
                self.assertEqual(manifest["database"], database)
                self.assertIs(manifest["search_executed_by_program"], False)
                self.assertEqual((run_path / "raw/export.ris").read_bytes(), exported.read_bytes())
                verify(run_path)

    def test_missing_key_fails_before_any_network_request(self):
        # This deliberately exercises the real adapter's credential guard.
        import researcher.webofscience  # noqa: F401

        with patch.dict(os.environ, {}, clear=True), patch("urllib.request.urlopen") as urlopen, patch(
            "urllib.request.OpenerDirector.open"
        ) as opener:
            code, stdout, stderr = self.run_cli([
                "doctor", "--database", "webofscience", "--online", "--out", str(self.root / "runs"),
            ])
        self.assertEqual(code, 1)
        self.assertIs(json.loads(stdout)["wos_api_key_configured"], False)
        result = json.loads(stderr)
        self.assertEqual(result["status"], "failed")
        self.assertIn("WOS_API_KEY", result["error"])
        urlopen.assert_not_called()
        opener.assert_not_called()
        verify(Path(result["run_directory"]))


if __name__ == "__main__":
    unittest.main()
