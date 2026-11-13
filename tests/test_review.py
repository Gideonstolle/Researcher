"""Review assembly tests use synthetic search runs and make no network calls."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from researcher.provenance import Run, json_bytes, verify
from researcher.review import create_review


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "review"

    def source(self, records, status="complete", database="pubmed", **metadata):
        run = Run(self.root / "runs", database)
        query = b'  "play"[Title]\r\nAND child*\r\n'
        run.write_bytes("query.txt", query)
        run.write_bytes("raw/response.txt", b"Synthetic fixture; no real study")
        run.write_bytes("records.json", json_bytes(records))
        run.metadata.update(returned_count=len(records), total_count=len(records), **metadata)
        run.finish(status)
        return run.directory

    def build(self, *sources):
        return create_review(list(sources), self.output, "Does pretend play support development?")

    def records(self):
        return json.loads((self.output / "records.json").read_bytes())

    def test_shared_doi_merges_and_retains_both_discoveries(self):
        first = self.source([{"id": "pubmed:1", "title": "Play", "doi": "10.1234/ABC", "pmid": "1"}])
        second = self.source([{"id": "scholar:2", "title": "Play", "doi": "https://doi.org/10.1234/abc", "discovery": {"rank": 3, "page": 1}}], status="partial", database="google-scholar")
        summary = self.build(first, second)
        self.assertEqual(summary["unique_records"], 1)
        self.assertEqual(summary["duplicate_occurrences"], 1)
        discoveries = self.records()[0]["discovery_occurrences"]
        self.assertEqual(len(discoveries), 2)
        self.assertTrue(any(d["rank"] == 3 and d["page"] == 1 for d in discoveries))
        for source in (first, second):
            snapshot = self.output / "sources" / source.name
            verify(snapshot)
            self.assertEqual((snapshot / "query.txt").read_bytes(), (source / "query.txt").read_bytes())
            self.assertEqual((snapshot / "raw/response.txt").read_bytes(), b"Synthetic fixture; no real study")

    def test_no_title_based_merging_without_strong_identity(self):
        source = self.source([{"id": "a", "title": "Same title"}, {"id": "b", "title": "Same title"}])
        summary = self.build(source)
        self.assertEqual(summary["unique_records"], 2)
        self.assertEqual(len({r["evidence_id"] for r in self.records()}), 2)

    def test_pmid_bridges_to_missing_doi_and_metadata_conflict_is_flagged(self):
        first = self.source([{"id": "a", "title": "Original title", "pmid": "123"}])
        second = self.source([{"id": "b", "title": "Different title", "pmid": "123", "doi": "10.9999/test"}])
        summary = self.build(first, second)
        record = self.records()[0]
        self.assertEqual(summary["unique_records"], 1)
        self.assertEqual(record["doi"], "10.9999/test")
        self.assertTrue(any(c["field"] == "title" for c in record["metadata_conflicts"]))
        self.assertTrue(any("metadata conflicts" in w for w in summary["warnings"]))

    def test_conflicting_identifier_group_stays_separate(self):
        source = self.source([{"id": "a", "pmid": "123", "doi": "10.9999/one"}, {"id": "b", "pmid": "123", "doi": "10.9999/two"}])
        summary = self.build(source)
        self.assertEqual(summary["unique_records"], 2)
        self.assertTrue(any("Conflicting DOI/PMID" in warning for warning in summary["warnings"]))
        self.assertTrue(all(any(c["field"] == "identity" for c in r["metadata_conflicts"]) for r in self.records()))

    def test_evidence_is_blank_and_csv_preserves_quotation(self):
        title = 'A "quoted", multiline\ntitle'
        source = self.source([{"id": "a", "title": title, "abstract": "An abstract is not a verified extraction."}])
        self.build(source)
        with (self.output / "evidence.csv").open(newline="", encoding="utf-8") as handle:
            row = next(csv.DictReader(handle))
        self.assertEqual(row["title"], title)
        for name in ("screening_decision", "exclusion_reason", "evidence_level", "population", "design", "sample_size", "outcomes", "findings", "limitations", "source_locator"):
            self.assertEqual(row[name], "")
        self.assertIn("scaffold, not a finding", (self.output / "gap-analysis.md").read_text())

    def test_bad_checksum_fails_before_output_created(self):
        source = self.source([])
        (source / "query.txt").write_text("Altered")
        with self.assertRaisesRegex(ValueError, "Checksum"):
            self.build(source)
        self.assertFalse(self.output.exists())

    def test_missing_run_and_no_runs_fail_before_output_created(self):
        with self.assertRaises(OSError):
            self.build(self.root / "missing")
        with self.assertRaisesRegex(ValueError, "At least one"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_existing_output_is_never_overwritten(self):
        self.output.mkdir()
        marker = self.output / "keep.txt"
        marker.write_text("Keep")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.build(self.source([]))
        self.assertEqual(marker.read_text(), "Keep")

    def test_rejects_duplicate_run_and_unfinished_status(self):
        source = self.source([])
        with self.assertRaisesRegex(ValueError, "Duplicate source"):
            self.build(source, source)
        unfinished = self.source([], status="running")
        with self.assertRaisesRegex(ValueError, "finished"):
            self.build(unfinished)
        self.assertFalse(self.output.exists())

    def test_planned_blocked_failed_are_logged_not_ingested(self):
        inputs = []
        for status in ("planned", "blocked", "failed"):
            run = Run(self.root / "runs", "google-scholar")
            run.write_bytes("query.txt", b"play")
            # Even a failed adapter's stray records must never be included.
            run.write_bytes("records.json", json_bytes([{"id": "stray", "title": "Unused"}]))
            run.finish(status)
            inputs.append(run.directory)
        summary = self.build(*inputs)
        self.assertEqual(summary["unique_records"], 0)
        self.assertEqual(summary["retrieved_records"], 0)
        self.assertTrue(all(row["total_matched"] is None for row in summary["searches"]))
        self.assertEqual(len(summary["warnings"]), 3)
        self.assertIn("Matched: unknown", (self.output / "search-log.md").read_text())

    def test_unknown_and_approximate_counts_remain_distinct(self):
        run = Run(self.root / "runs", "google-scholar")
        run.write_bytes("query.txt", b"play")
        run.write_bytes("records.json", json_bytes([]))
        run.metadata.update(total_count=None, displayed_count=12000, displayed_count_is_approximate=True,
                            original_search={"searched_at": "2026-11-13T10:00:00+01:00", "displayed_count": 12000,
                                             "filters": {"sort": "date"}})
        run.finish("partial")
        summary = self.build(run.directory)
        self.assertIsNone(summary["searches"][0]["total_matched"])
        self.assertEqual(summary["searches"][0]["displayed_count"], 12000)
        self.assertEqual(summary["searches"][0]["sort"], "date")
        self.assertIn("approximate count: 12000", (self.output / "search-log.md").read_text())

    def test_identity_ids_independent_of_source_input_order(self):
        first = self.source([{"id": "a", "doi": "10.9999/a"}, {"id": "b", "title": "No ID"}])
        second = self.source([{"id": "c", "pmid": "2"}])
        self.build(first, second)
        expected = {r["evidence_id"] for r in self.records()}
        other = self.root / "other"
        create_review([second, first], other, "Question")
        actual = {r["evidence_id"] for r in json.loads((other / "records.json").read_bytes())}
        self.assertEqual(expected, actual)

    def test_revision_reason_and_parent_run_are_preserved(self):
        source = self.source([], search_reason="Broaden outcome synonyms", parent_run_id="previous-run")
        summary = self.build(source)
        row = summary["searches"][0]
        self.assertEqual(row["search_reason"], "Broaden outcome synonyms")
        self.assertEqual(row["parent_run_id"], "previous-run")

    def test_rejects_output_inside_source_run(self):
        source = self.source([])
        self.output = source / "nested"
        with self.assertRaisesRegex(ValueError, "outside"):
            self.build(source)
        self.assertFalse(self.output.exists())

    def test_discovery_differences_are_not_metadata_conflicts(self):
        source = self.source([
            {"id": "a", "doi": "10.9999/test", "discovery": {"rank": 1, "page": 1}},
            {"id": "b", "doi": "10.9999/test", "discovery": {"rank": 2, "page": 1}},
        ])
        self.build(source)
        self.assertEqual(self.records()[0]["metadata_conflicts"], [])


if __name__ == "__main__":
    unittest.main()
