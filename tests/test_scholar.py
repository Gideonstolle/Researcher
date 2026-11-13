"""Synthetic observations: no calls to Google Scholar are made by these tests."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from researcher.provenance import Run, json_bytes, verify
from researcher.scholar import prepare, record, search_url


class ScholarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.query = '"pretend play" AND children\n'

    def run_object(self):
        run = Run(self.root, "google-scholar")
        run.write_bytes("query.txt", self.query.encode("utf-8"))
        run.metadata["query"] = self.query
        return run

    def observation(self):
        return {
            "query": self.query,
            "search_url": search_url(self.query, 2020, 2026, "date"),
            "searched_at": "2026-11-13T11:30:00+01:00",
            "status": "partial",
            "filters": {"year_from": 2020, "year_to": 2026, "sort": "date", "other": {}},
            "displayed_count": 234,
            "displayed_count_text": "About 234 results",
            "pages_checked": [1, 2],
            "steps": [{"at": "2026-11-13T11:30:00+01:00", "action": "search",
                       "details": "Synthetic test: inspected pages 1 and 2, selected rank 11."}],
            "results": [{"rank": 11, "page": 2, "title": "Synthetic paper, not research evidence",
                         "url": "https://example.org/paper", "authors": ["A. Example"],
                         "year": 2024, "doi": "10.1234/example", "abstract": "Synthetic abstract.",
                         "evidence_level": "abstract"}],
            "stop_reason": "Synthetic test cap of two pages.",
        }

    def test_prepare_is_unexecuted_and_preserves_unicode_and_whitespace(self):
        query = '"café play"\r\nchildren + adults'
        run = self.run_object()
        self.assertEqual(prepare(run, query, 2020, 2026, "date"), [])
        run.finish("planned")
        self.assertEqual(run.metadata["status"], "planned")
        self.assertFalse(run.metadata["search_executed_by_program"])
        self.assertIsNone(run.metadata["retrieval_complete"])
        self.assertEqual(run.metadata["coverage"], "not_searched")
        self.assertEqual(run.metadata["search_url"], run.metadata["planned_url"])
        params = parse_qs(urlsplit(run.metadata["planned_url"]).query)
        self.assertEqual(params["q"], [query])
        self.assertEqual(params["scisbd"], ["1"])
        template = json.loads((run.directory / "observation-template.json").read_text())
        self.assertEqual(template["query"], query)
        self.assertIsNone(template["searched_at"])
        self.assertIsNone(template["status"])
        self.assertGreater(verify(run.directory), 3)

    def test_record_preserves_raw_observation_and_evidence(self):
        run = self.run_object()
        observation = self.observation()
        data = json_bytes(observation)
        evidence = self.root / "page.txt"
        evidence.write_text("Synthetic screenshot transcript", encoding="utf-8")
        records = record(run, self.query, data, [evidence])
        run.write_bytes("records.json", json_bytes(records))
        run.finish(run.metadata["observation_status"])
        self.assertEqual((run.directory / "raw/observation.json").read_bytes(), data)
        self.assertEqual((run.directory / "raw/evidence/1-page.txt").read_text(), evidence.read_text())
        self.assertEqual(records[0]["authors"], [{"literal": "A. Example"}])
        self.assertEqual(records[0]["year"], "2024")
        self.assertEqual(records[0]["discovery"]["rank"], 11)
        self.assertEqual(records[0]["discovery"]["evidence_level"], "abstract")
        self.assertFalse(run.metadata["search_executed_by_program"])
        self.assertIsNone(run.metadata["total_count"])
        self.assertEqual(run.metadata["displayed_count"], 234)
        self.assertTrue(run.metadata["displayed_count_is_approximate"])
        self.assertEqual(run.metadata["status"], "partial")
        self.assertEqual(run.metadata["search_url"], observation["search_url"])
        self.assertGreater(verify(run.directory), 3)

    def test_failure_keeps_original_input(self):
        run = self.run_object()
        data = b'{"broken":'
        with self.assertRaises(ValueError):
            record(run, self.query, data)
        run.finish("failed", "Invalid synthetic observation")
        self.assertEqual((run.directory / "raw/observation.json").read_bytes(), data)
        verify(run.directory)

    def test_observed_query_must_match_all_whitespace(self):
        observation = self.observation()
        observation["query"] = self.query.rstrip()
        with self.assertRaisesRegex(ValueError, "exact query"):
            record(self.run_object(), self.query, json_bytes(observation))

    def test_url_query_and_filters_cannot_disagree(self):
        urls = [
            search_url("different query", 2020, 2026, "date"),
            search_url(self.query, 2021, 2026, "date"),
            search_url(self.query, 2020, 2027, "date"),
            search_url(self.query, 2020, 2026, "relevance"),
            "https://scholar.google.com.example.org/scholar?q=x",
            "http://scholar.google.com/scholar?q=x",
            search_url(self.query, 2020, 2026, "date") + "&q=duplicate",
        ]
        for url in urls:
            with self.subTest(url=url):
                observation = self.observation()
                observation["search_url"] = url
                with self.assertRaises(ValueError):
                    record(self.run_object(), self.query, json_bytes(observation))

    def test_regional_scholar_url_is_allowed(self):
        observation = self.observation()
        observation["search_url"] = observation["search_url"].replace("scholar.google.com", "scholar.google.nl")
        self.assertEqual(len(record(self.run_object(), self.query, json_bytes(observation))), 1)

    def test_additional_url_parameters_are_retained_without_inferred_meaning(self):
        observation = self.observation()
        observation["search_url"] += "&as_vis=1&lr=lang_en"
        observation["filters"]["other"] = {"include_citations": False, "language": "English"}
        run = self.run_object()
        record(run, self.query, json_bytes(observation))
        self.assertEqual(run.metadata["url_parameters"]["as_vis"], ["1"])
        self.assertEqual(run.metadata["url_parameters"]["lr"], ["lang_en"])
        self.assertEqual(run.metadata["filters"]["other"], observation["filters"]["other"])
        observation["filters"]["other"] = []
        with self.assertRaisesRegex(ValueError, "filters.other"):
            record(self.run_object(), self.query, json_bytes(observation))

    def test_blocked_attempt_is_not_zero_result_success(self):
        observation = self.observation()
        observation.update(status="blocked", displayed_count=None, displayed_count_text=None,
                           results=[], pages_checked=[], stop_reason="CAPTCHA prevented access.")
        run = self.run_object()
        self.assertEqual(record(run, self.query, json_bytes(observation)), [])
        run.finish(run.metadata["observation_status"])
        self.assertEqual(run.metadata["status"], "blocked")
        self.assertIsNone(run.metadata["total_count"])
        self.assertIsNone(run.metadata["retrieval_complete"])
        for changes in ({"results": self.observation()["results"]}, {"displayed_count": 0}, {"pages_checked": [1]}):
            invalid = {**observation, **changes}
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                record(self.run_object(), self.query, json_bytes(invalid))

    def test_observed_empty_page_still_not_exhaustive(self):
        observation = self.observation()
        observation.update(results=[], displayed_count=0, displayed_count_text="No results found")
        run = self.run_object()
        self.assertEqual(record(run, self.query, json_bytes(observation)), [])
        self.assertEqual(run.metadata["observation_status"], "partial")
        self.assertIsNone(run.metadata["retrieval_complete"])

    def test_zero_result_count_cannot_contradict_selected_records(self):
        observation = self.observation()
        observation.update(displayed_count=0, displayed_count_text="No results found")
        with self.assertRaisesRegex(ValueError, "zero-result"):
            record(self.run_object(), self.query, json_bytes(observation))

    def test_low_nonzero_estimate_preserved_with_warning(self):
        observation = self.observation()
        second = copy.deepcopy(observation["results"][0])
        second.update(rank=12, title="A second synthetic record", url="https://example.org/paper-2")
        observation["results"].append(second)
        observation.update(displayed_count=1, displayed_count_text="About 1 result")
        run = self.run_object()
        records = record(run, self.query, json_bytes(observation))
        self.assertEqual(len(records), 2)
        self.assertEqual(run.metadata["displayed_count"], 1)
        self.assertTrue(any("estimate is below" in warning for warning in run.metadata["warnings"]))

    def test_invalid_observation_fields_are_rejected(self):
        variants = [
            {"searched_at": "2026-11-13T11:30:00"},
            {"searched_at": "not a timestamp"},
            {"status": "complete"},
            {"displayed_count": True},
            {"displayed_count": -1},
            {"displayed_count_text": None},
            {"pages_checked": [True]},
            {"pages_checked": [1, 1]},
            {"pages_checked": []},
            {"steps": []},
            {"stop_reason": ""},
        ]
        for changes in variants:
            with self.subTest(changes=changes):
                observation = {**self.observation(), **changes}
                with self.assertRaises(ValueError):
                    record(self.run_object(), self.query, json_bytes(observation))

    def test_result_ranks_pages_and_urls_are_validated(self):
        for changes in ({"rank": 0}, {"rank": True}, {"page": 3}, {"url": "javascript:alert(1)"},
                        {"authors": "A. Example"}, {"year": "202"}, {"evidence_level": "snippet"}):
            with self.subTest(changes=changes):
                observation = self.observation()
                observation["results"][0].update(changes)
                with self.assertRaises(ValueError):
                    record(self.run_object(), self.query, json_bytes(observation))
        observation = self.observation()
        observation["results"].append(copy.deepcopy(observation["results"][0]))
        with self.assertRaisesRegex(ValueError, "ranks must be unique"):
            record(self.run_object(), self.query, json_bytes(observation))

    def test_year_constraints_and_sort(self):
        for args in ((2026, 2020, "date"), (True, None, "date"), (None, None, "citation")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                prepare(self.run_object(), self.query, *args)


if __name__ == "__main__":
    unittest.main()
