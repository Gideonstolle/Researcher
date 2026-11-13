"""Offline Starter API contract tests. No real subscription or network is used."""

import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import Mock, patch

from researcher.webofscience import WebOfScienceError, _NoRedirect, _record, search


class FakeRun:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.metadata = {}
        self.events = []

    def event(self, event):
        self.events.append(event)

    def write_bytes(self, name, data):
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


class Response:
    status = 200

    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.data


def hit(number=1, **extra):
    return {"uid": f"WOS:{number}", "title": f"Synthetic title {number}",
            "types": ["Article"], **extra}


def page(hits, total=None, number=1, limit=50, **extra):
    return json.dumps({"metadata": {"total": len(hits) if total is None else total,
                                     "page": number, "limit": limit},
                       "hits": hits, **extra}, ensure_ascii=False).encode("utf-8")


def http_error(code, body=b"error", headers=None):
    return urllib.error.HTTPError(
        "https://api.clarivate.com/apis/wos-starter/v1/documents", code,
        "Synthetic HTTP error", headers or {}, io.BytesIO(body),
    )


class WebOfScienceTests(unittest.TestCase):
    def test_corporate_authors_remain_literal_including_commas(self):
        record = _record(hit(names={"corp": [{"displayName": "Research Group, Netherlands"}]}))
        self.assertEqual(record["authors"], [{"literal": "Research Group, Netherlands"}])
        with self.assertRaises(WebOfScienceError):
            _record(hit(names={"corp": "unexpected string"}))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = FakeRun(self.temp.name)
        self.sleeper = patch("researcher.webofscience.time.sleep").start()
        self.addCleanup(patch.stopall)

    def call(self, *responses, query="TI=psychology", **kwargs):
        opener = Mock()
        opener.open.side_effect = [Response(item) if isinstance(item, bytes) else item
                                   for item in responses]
        kwargs.setdefault("api_key", "synthetic-private-key")
        with patch("researcher.webofscience.urllib.request.build_opener", return_value=opener):
            records = search(self.run, query, **kwargs)
        return records, opener

    def test_exact_query_header_and_redacted_provenance(self):
        query = '  TS=("dépression" OR anxiety)\r\nAND PY=2024  '
        records, opener = self.call(page([hit()]), query=query, api_key="private+/key")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        parsed = urllib.parse.urlsplit(request.full_url)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "api.clarivate.com")
        self.assertEqual(parsed.path, "/apis/wos-starter/v1/documents")
        params = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(params["q"], [query])
        self.assertEqual(params["db"], ["WOS"])
        self.assertEqual(params["sortField"], ["LD+A"])
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["x-apikey"], "private+/key")
        self.assertNotIn("private", request.full_url)
        self.assertEqual(self.run.metadata["query"], query)
        self.assertIsNone(self.run.metadata.get("query_translation"))
        logs = json.dumps(self.run.events)
        self.assertNotIn("private+/key", logs)
        self.assertTrue(all("timestamp" in event for event in self.run.events))
        self.assertEqual(records[0]["accession"], "WOS:1")
        self.assertTrue(self.run.metadata["retrieval_complete"])

    def test_missing_key_never_sends_a_request(self):
        for key in (None, "", "   "):
            with self.subTest(key=key), patch("researcher.webofscience.urllib.request.build_opener") as factory:
                with self.assertRaises(WebOfScienceError):
                    search(self.run, "TI=psychology", api_key=key)
                factory.return_value.open.assert_not_called()

    def test_invalid_caps_and_budget_never_send_requests(self):
        for kwargs in ({"max_records": 0}, {"max_records": True}, {"max_records": 1.5},
                       {"max_requests": 0}, {"max_requests": True}, {"max_requests": 1.5}):
            with self.subTest(kwargs=kwargs), patch("researcher.webofscience.urllib.request.build_opener") as factory:
                with self.assertRaises(WebOfScienceError):
                    search(self.run, "TI=x", api_key="test", **kwargs)
                factory.return_value.open.assert_not_called()

    def test_cap_requires_explicit_partial_and_archives_response(self):
        with self.assertRaises(WebOfScienceError):
            self.call(page([hit()], total=100, limit=1), max_records=1)
        self.assertEqual(self.run.metadata["total_count"], 100)
        self.assertFalse(self.run.metadata["retrieval_complete"])
        self.assertTrue(list((self.run.directory / "raw").glob("*.json")))

    def test_partial_pagination_keeps_page_limit_constant_and_trims_after_archiving(self):
        first = [hit(i) for i in range(1, 51)]
        second = [hit(i) for i in range(51, 101)]
        raw_second = page(second, total=100, number=2, limit=50)
        records, opener = self.call(page(first, total=100), raw_second,
                                    max_records=51, allow_partial=True)
        self.assertEqual(len(records), 51)
        self.assertEqual(records[-1]["accession"], "WOS:51")
        params = [urllib.parse.parse_qs(urllib.parse.urlsplit(c.args[0].full_url).query)
                  for c in opener.open.call_args_list]
        self.assertEqual([p["limit"] for p in params], [["50"], ["50"]])
        self.assertEqual([p["page"] for p in params], [["1"], ["2"]])
        self.assertEqual(self.run.metadata["returned_count"], 51)
        self.assertFalse(self.run.metadata["retrieval_complete"])
        self.assertTrue(self.run.metadata["partial"])
        self.assertEqual(len(self.run.metadata["selected_ids"]), 51)
        self.assertIn(raw_second, [p.read_bytes() for p in (self.run.directory / "raw").glob("*.json")])

    def test_complete_multiple_pages_and_zero_results(self):
        records, _ = self.call(page([hit(i) for i in range(50)], total=51),
                                page([hit(50)], total=51, number=2), max_records=51)
        self.assertEqual(len(records), 51)
        self.assertTrue(self.run.metadata["retrieval_complete"])
        records, opener = self.call(page([], total=0))
        self.assertEqual(records, [])
        self.assertTrue(self.run.metadata["retrieval_complete"])
        self.assertEqual(opener.open.call_count, 1)

    def test_duplicate_ids_missing_ids_and_truncated_pages_fail(self):
        bad_pages = [page([hit(), hit()], total=2), page([{"title": "Missing UID"}]),
                     page([hit()], total=2), page([hit(uid=" ")])]
        for response in bad_pages:
            with self.subTest(response=response), self.assertRaises(WebOfScienceError):
                self.call(response)

    def test_cross_page_duplicate_and_changed_total_fail(self):
        first = page([hit(i) for i in range(50)], total=51)
        for second in (page([hit(49)], total=51, number=2),
                       page([hit(50), hit(51)], total=52, number=2),
                       page([], total=51, number=2)):
            with self.subTest(second=second), self.assertRaises(WebOfScienceError):
                self.call(first, second, max_records=60)

    def test_malformed_metadata_and_non_json_fail(self):
        responses = [b"not JSON", b"[]", b'{}', page([], total=True), page([], total="0"),
                     page([], total=-1), page([], number=2), page([], limit=49)]
        for response in responses:
            with self.subTest(response=response), self.assertRaises(WebOfScienceError):
                self.call(response)

    def test_authentication_and_permission_errors_are_not_retried(self):
        for status in (401, 403):
            opener = Mock()
            opener.open.side_effect = http_error(status)
            with self.subTest(status=status), patch("researcher.webofscience.urllib.request.build_opener", return_value=opener):
                with self.assertRaisesRegex(WebOfScienceError, str(status)):
                    search(self.run, "TI=x", api_key="test")
                self.assertEqual(opener.open.call_count, 1)

    def test_transient_error_retries_but_request_budget_counts_attempts(self):
        records, opener = self.call(http_error(429, headers={"Retry-After": "1"}), page([hit()]))
        self.assertEqual(len(records), 1)
        self.assertEqual(opener.open.call_count, 2)
        opener = Mock()
        opener.open.side_effect = http_error(503)
        with patch("researcher.webofscience.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(WebOfScienceError):
                search(self.run, "TI=x", api_key="test", max_requests=1)
            self.assertEqual(opener.open.call_count, 1)

    def test_retry_limit_and_waits_are_bounded(self):
        opener = Mock()
        opener.open.side_effect = [http_error(503) for _ in range(3)]
        with patch("researcher.webofscience.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(WebOfScienceError):
                search(self.run, "TI=x", api_key="test", max_requests=10)
        self.assertEqual(opener.open.call_count, 3)
        self.assertTrue(all(0 <= call.args[0] <= 30 for call in self.sleeper.call_args_list))

    def test_long_retry_after_stops_instead_of_retrying_early(self):
        opener = Mock()
        opener.open.side_effect = http_error(429, headers={"Retry-After": "120"})
        with patch("researcher.webofscience.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(WebOfScienceError):
                search(self.run, "TI=x", api_key="test")
        self.assertEqual(opener.open.call_count, 1)
        self.sleeper.assert_not_called()

    def test_page_request_budget_exhaustion_is_a_failure(self):
        opener = Mock()
        opener.open.side_effect = [Response(page([hit(i) for i in range(50)], total=51))]
        with patch("researcher.webofscience.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(WebOfScienceError):
                search(self.run, "TI=x", api_key="test", max_records=51, max_requests=1)
        self.assertEqual(opener.open.call_count, 1)
        self.assertFalse(self.run.metadata["retrieval_complete"])

    def test_errors_and_raw_bodies_redact_key_and_encoded_forms(self):
        key = "secret+/value"
        body = (key + " " + urllib.parse.quote(key, safe="") + " " + urllib.parse.quote_plus(key)).encode()
        with self.assertRaises(WebOfScienceError) as caught:
            self.call(http_error(403, body), api_key=key)
        all_saved = b" ".join(p.read_bytes() for p in self.run.directory.rglob("*") if p.is_file())
        logs = json.dumps(self.run.events) + str(caught.exception)
        for form in (key, urllib.parse.quote(key, safe=""), urllib.parse.quote_plus(key)):
            self.assertNotIn(form, logs)
            self.assertNotIn(form.encode(), all_saved)
        self.assertIn(b"[REDACTED]", all_saved)

    def test_network_error_preserves_safe_reason_and_hides_credentials(self):
        key = "secret+/value"
        reason = "certificate verification failed " + urllib.parse.quote_plus(key)
        with self.assertRaises(WebOfScienceError) as caught:
            self.call(*[urllib.error.URLError(reason) for _ in range(3)], api_key=key)
        text = str(caught.exception) + json.dumps(self.run.events)
        self.assertIn("certificate", text)
        self.assertNotIn(key, text)
        self.assertNotIn(urllib.parse.quote_plus(key), text)

    def test_redirects_are_not_followed(self):
        request = urllib.request.Request("https://api.clarivate.com/apis/wos-starter/v1/documents",
                                         headers={"X-ApiKey": "test"})
        self.assertIsNone(_NoRedirect().redirect_request(request, None, 302, "Found", {},
                                                        "https://elsewhere.example/"))

    def test_native_metadata_mapping_preserves_names_and_missing_fields(self):
        record = _record(hit(names={"authors": [{"displayName": "García, Ana"},
                                                  {"displayName": "Study Consortium"}]},
                             source={"sourceTitle": "Example Journal", "publishYear": 2024,
                                     "publishMonth": "NOV", "volume": "2", "issue": "3",
                                     "pages": {"range": "1-9"}},
                             identifiers={"doi": "10.0000/synthetic", "pmid": "12345"},
                             keywords={"authorKeywords": ["psychology"]},
                             links={"record": "https://example.test/record"}))
        self.assertEqual(record["source"], "webofscience")
        self.assertEqual(record["id"], "webofscience:WOS:1")
        self.assertEqual(record["authors"], [{"family": "García", "given": "Ana"},
                                             {"literal": "Study Consortium"}])
        self.assertEqual(record["journal"], "Example Journal")
        self.assertEqual(str(record["year"]), "2024")
        self.assertEqual(record["pages"], "1-9")
        self.assertEqual(record["keywords"], ["psychology"])
        self.assertEqual(record["pmid"], "12345")
        self.assertEqual(record["doi"], "10.0000/synthetic")
        self.assertNotIn("abstract", record)
        minimal = _record({"uid": "WOS:minimal"})
        self.assertNotIn("doi", minimal)
        self.assertNotIn("year", minimal)

    def test_chapters_books_and_unknown_types_are_not_journal_articles(self):
        chapter = _record(hit(types=["Book Chapter"], source={"sourceTitle": "Book container"}))
        self.assertEqual(chapter["type"], "CHAP")
        self.assertEqual(chapter["booktitle"], "Book container")
        self.assertNotIn("journal", chapter)
        self.assertEqual(_record(hit(types=["Book"]))["type"], "book")
        self.assertEqual(_record(hit(types=["Poetry"]))["type"], "GEN")


if __name__ == "__main__":
    unittest.main()
