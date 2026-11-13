"""Offline tests of request provenance, truncation and record integrity."""

import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
import urllib.parse
from unittest.mock import patch

from researcher.pubmed import PubMedError, _Client, _parse_records, search


class FakeRun:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.metadata = {}
        self.events = []

    def event(self, value):
        self.events.append(value)

    def write_bytes(self, relative_name, value):
        path = self.directory / relative_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)


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


def esearch(ids, count=None, **extra):
    return json.dumps({"esearchresult": {"count": str(len(ids) if count is None else count),
                                       "idlist": ids, "querytranslation": "translated query",
                                       **extra}}).encode()


def article(pmid="123", title="Example <i>nested</i> title"):
    return f"""<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article>
    <ArticleTitle>{title}</ArticleTitle>
    <Journal><Title>Test Journal</Title><JournalIssue><Volume>4</Volume><Issue>2</Issue>
    <PubDate><MedlineDate>2020 Winter</MedlineDate></PubDate></JournalIssue></Journal>
    <AuthorList><Author><LastName>García</LastName><ForeName>Ana</ForeName></Author>
    <Author><CollectiveName>Study Group</CollectiveName></Author></AuthorList>
    <Pagination><MedlinePgn>12-18</MedlinePgn></Pagination>
    <Abstract><AbstractText Label="METHODS">Text with <b>markup</b>.</AbstractText>
    <AbstractText Label="RESULTS">Second section.</AbstractText></Abstract>
    </Article><KeywordList><Keyword>psychology</Keyword></KeywordList></MedlineCitation>
    <PubmedData><ArticleIdList><ArticleId IdType="doi">10.1000/example</ArticleId>
    </ArticleIdList></PubmedData></PubmedArticle>"""


def xml(*articles):
    return ("<PubmedArticleSet>" + "".join(articles) + "</PubmedArticleSet>").encode()


class PubMedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = FakeRun(self.temp.name)
        self.sleep_patch = patch("researcher.pubmed.time.sleep")
        self.sleep = self.sleep_patch.start()
        self.addCleanup(self.sleep_patch.stop)

    def call(self, *responses, query="psychology", **kwargs):
        with patch("researcher.pubmed.urllib.request.urlopen", side_effect=[Response(r) for r in responses]) as opener:
            result = search(self.run, query, **kwargs)
        return result, opener

    def test_exact_query_and_credentials_in_request_but_redacted_logs(self):
        query = '  ("dépression"[Title/Abstract] OR stress)\nAND 2020[pdat]  '
        records, opener = self.call(esearch(["123"]), xml(article()), query=query,
                                    email="researcher@example.test", api_key="private-key")
        request = opener.call_args_list[0].args[0]
        sent = urllib.parse.parse_qs(request.data.decode())
        self.assertEqual(sent["term"], [query])
        self.assertEqual(sent["email"], ["researcher@example.test"])
        self.assertEqual(sent["api_key"], ["private-key"])
        self.assertEqual(self.run.metadata["query"], query)
        self.assertEqual(self.run.metadata["query_translation"], "translated query")
        events = json.dumps(self.run.events)
        self.assertNotIn("private-key", events)
        self.assertNotIn("researcher@example.test", events)
        self.assertIn("[REDACTED]", events)
        self.assertTrue(all("timestamp" in event for event in self.run.events))
        self.assertTrue(self.run.metadata["retrieval_complete"])
        self.assertEqual(records[0]["pmid"], "123")
        self.assertEqual((self.run.directory / "raw/esearch.json").read_bytes(), esearch(["123"]))
        self.assertEqual((self.run.directory / "raw/efetch-0001.xml").read_bytes(), xml(article()))

    def test_structured_abstract_collective_author_and_nested_title(self):
        record = _parse_records(xml(article()))[0]
        self.assertEqual(record["title"], "Example nested title")
        self.assertEqual(record["authors"], [{"family": "García", "given": "Ana"}, {"literal": "Study Group"}])
        self.assertEqual(record["abstract"], "METHODS: Text with markup.\nRESULTS: Second section.")
        self.assertEqual(record["year"], "2020")
        self.assertEqual(record["date"], "2020 Winter")
        self.assertEqual(record["doi"], "10.1000/example")

    def test_minimal_book_metadata_does_not_invent_doi_or_authors(self):
        book = """<PubmedBookArticle><BookDocument><PMID>999</PMID><Book>
        <BookTitle>A book</BookTitle><PubDate><Year>2022</Year></PubDate></Book>
        </BookDocument></PubmedBookArticle>"""
        record = _parse_records(xml(book))[0]
        self.assertEqual(record["type"], "book")
        self.assertEqual(record["title"], "A book")
        self.assertEqual(record["authors"], [])
        self.assertEqual(record["date"], "2022")
        self.assertNotIn("doi", record)

    def test_book_chapter_keeps_chapter_and_container_titles(self):
        chapter = """<PubmedBookArticle><BookDocument><PMID>999</PMID>
        <ArticleTitle>A chapter</ArticleTitle><Book><BookTitle>A book</BookTitle>
        <PubDate><Year>2022</Year></PubDate></Book></BookDocument></PubmedBookArticle>"""
        record = _parse_records(xml(chapter))[0]
        self.assertEqual(record["type"], "CHAP")
        self.assertEqual(record["title"], "A chapter")
        self.assertEqual(record["booktitle"], "A book")

    def test_zero_results_succeeds_without_fetch(self):
        records, opener = self.call(esearch([]))
        self.assertEqual(records, [])
        self.assertEqual(opener.call_count, 1)
        self.assertTrue(self.run.metadata["retrieval_complete"])
        self.assertEqual(self.run.metadata["returned_count"], 0)

    def test_cap_is_error_by_default_and_search_response_is_archived(self):
        with patch("researcher.pubmed.urllib.request.urlopen", return_value=Response(esearch(["123"], count=10001))) as opener:
            with self.assertRaisesRegex(PubMedError, "exceeding the cap"):
                search(self.run, "psychology", max_records=1)
        self.assertEqual(opener.call_count, 1)
        self.assertEqual(self.run.metadata["total_count"], 10001)
        self.assertFalse(self.run.metadata["retrieval_complete"])
        self.assertTrue((self.run.directory / "raw/esearch.json").is_file())

    def test_explicit_partial_retrieval_is_never_marked_complete(self):
        records, _ = self.call(esearch(["123"], count=10001), xml(article()), max_records=1, allow_partial=True)
        self.assertEqual(len(records), 1)
        self.assertTrue(self.run.metadata["partial"])
        self.assertFalse(self.run.metadata["retrieval_complete"])

    def test_invalid_caps_fail_before_network(self):
        with patch("researcher.pubmed.urllib.request.urlopen") as opener:
            for cap in (0, 10001, True, 1.5):
                with self.subTest(cap=cap), self.assertRaises(PubMedError):
                    search(self.run, "psychology", max_records=cap)
            opener.assert_not_called()

    def test_search_ids_must_match_count_and_be_unique(self):
        for ids, count in ((["123", "123"], 2), (["123"], 2), (["invalid"], 1)):
            with self.subTest(ids=ids):
                with patch("researcher.pubmed.urllib.request.urlopen", return_value=Response(esearch(ids, count=count))):
                    with self.assertRaises(PubMedError):
                        search(self.run, "psychology")

    def test_fetch_must_return_all_and_only_selected_ids(self):
        for response in (xml(), xml(article("456")), xml(article(), article())):
            with self.subTest(response=response):
                with self.assertRaisesRegex(PubMedError, "citation IDs"):
                    self.call(esearch(["123"]), response)

    def test_fetch_order_is_restored_to_search_order(self):
        records, _ = self.call(esearch(["123", "456"]), xml(article("456"), article("123")))
        self.assertEqual([record["pmid"] for record in records], ["123", "456"])

    def test_fetch_uses_batches_of_at_most_200(self):
        ids = [str(index) for index in range(1, 202)]
        records, opener = self.call(esearch(ids), xml(*(article(pmid) for pmid in ids[:200])),
                                    xml(article(ids[-1])), max_records=201)
        self.assertEqual(len(records), 201)
        self.assertEqual(opener.call_count, 3)
        self.assertTrue((self.run.directory / "raw/efetch-0002.xml").is_file())
        for call in opener.call_args_list[1:]:
            params = urllib.parse.parse_qs(call.args[0].data.decode())
            self.assertLessEqual(len(params["id"][0].split(",")), 200)

    def test_query_warnings_are_retained(self):
        warnings = {"outputmessages": ["No items found."]}
        self.call(esearch([], warninglist=warnings))
        self.assertEqual(self.run.metadata["warnings"], warnings)

    def test_http_retry_is_bounded_and_errors_do_not_leak_secrets(self):
        def fail(*args, **kwargs):
            raise urllib.error.HTTPError("https://example.test/?api_key=secret-key", 429,
                                         "secret-key someone@example.test", {"Retry-After": "900"},
                                         io.BytesIO(b"secret-key someone@example.test"))
        with patch("researcher.pubmed.urllib.request.urlopen", side_effect=fail) as opener:
            with self.assertRaises(PubMedError) as caught:
                search(self.run, "psychology", email="someone@example.test", api_key="secret-key")
        self.assertEqual(opener.call_count, 3)
        output = str(caught.exception) + json.dumps(self.run.events)
        self.assertNotIn("secret-key", output)
        self.assertNotIn("someone@example.test", output)
        self.assertTrue(all(call.args[0] <= 30 for call in self.sleep.call_args_list))
        failures = [event for event in self.run.events if event["event"] == "request_failed"]
        self.assertEqual(failures[0]["retry_delay_seconds"], 30)
        self.assertNotIn("retry_delay_seconds", failures[-1])
        for attempt in range(1, 4):
            body = (self.run.directory / f"raw/http-esearch-{attempt}.txt").read_text()
            self.assertEqual(body, "[REDACTED] [REDACTED]")

    def test_network_diagnostic_retains_reason_and_redacts_encoded_credentials(self):
        reason = OSError("TLS handshake failed at ?api_key=private%2Fkey&email=someone%40example.test")
        error = urllib.error.URLError(reason)
        with patch("researcher.pubmed.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(PubMedError) as caught:
                search(self.run, "psychology", email="someone@example.test", api_key="private/key")
        message = str(caught.exception)
        self.assertIn("URLError", message)
        self.assertIn("TLS handshake failed", message)
        failure = [event for event in self.run.events if event["event"] == "request_failed"][-1]
        self.assertEqual(failure["error_type"], "URLError")
        self.assertEqual(failure["reason_type"], "OSError")
        self.assertIn("TLS handshake failed", failure["error_detail"])
        output = message + json.dumps(self.run.events)
        for secret in ("private/key", "private%2Fkey", "someone@example.test", "someone%40example.test"):
            self.assertNotIn(secret, output)

    def test_timeout_reason_is_retained(self):
        with patch("researcher.pubmed.urllib.request.urlopen", side_effect=TimeoutError("response timed out")):
            with self.assertRaisesRegex(PubMedError, "TimeoutError: response timed out"):
                search(self.run, "psychology")

    def test_client_retries_transient_error_then_succeeds(self):
        error = urllib.error.HTTPError("https://example.test", 503, "temporary", {}, io.BytesIO())
        with patch("researcher.pubmed.urllib.request.urlopen", side_effect=[error, Response(esearch([]))]) as opener:
            self.assertEqual(search(self.run, "psychology"), [])
        self.assertEqual(opener.call_count, 2)

    def test_query_errors_are_explicit_and_archived_credentials_redacted(self):
        raw = esearch([], errorlist={"phrasesnotfound": ["secret-key someone@example.test"]})
        with self.assertRaisesRegex(PubMedError, "query error"):
            self.call(raw, api_key="secret-key", email="someone@example.test")
        archived = (self.run.directory / "raw/esearch.json").read_text()
        self.assertNotIn("secret-key", archived)
        self.assertNotIn("someone@example.test", archived)
        self.assertTrue(self.run.metadata["raw_response_credentials_redacted"])
        self.assertNotIn("secret-key", json.dumps(self.run.metadata))

    def test_malformed_or_unsupported_xml_fails(self):
        for data in (b"not xml", b"<ERROR>bad query</ERROR>", xml("<Unexpected/>")):
            with self.subTest(data=data), self.assertRaises(PubMedError):
                _parse_records(data)

    def test_retry_after_http_date_and_nonnumeric_value_are_safe(self):
        client = _Client(self.run)
        self.assertEqual(client._retry_delay("not a date", 2), 2)
        self.assertEqual(client._retry_delay("Fri, 31 Dec 9999 23:59:59 GMT", 1), 30)


if __name__ == "__main__":
    unittest.main()
