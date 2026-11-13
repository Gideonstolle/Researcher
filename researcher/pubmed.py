"""Small, audited PubMed E-utilities adapter (Python standard library only)."""

from __future__ import annotations

import datetime as dt
import email.utils
import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
TOOL = "psychology-literature-researcher"
TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 3
REQUEST_INTERVAL_SECONDS = 0.4
MAX_RETRY_DELAY_SECONDS = 30


class PubMedError(RuntimeError):
    """An actionable error whose message never contains HTTP credentials."""


def _utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


class _Client:
    def __init__(self, run, *, email=None, api_key=None):
        self.run = run
        self.email = email
        self.api_key = api_key
        self._last_request = None

    def redact(self, text):
        for secret in (self.api_key, self.email):
            if secret:
                text = text.replace(secret, "[REDACTED]")
                text = text.replace(urllib.parse.quote(secret, safe=""), "[REDACTED]")
                text = text.replace(urllib.parse.quote_plus(secret), "[REDACTED]")
        return text

    def archive(self, name, data):
        # Responses normally do not echo credentials. Preserve their exact bytes
        # except if a service unexpectedly reflects a credential.
        safe = data
        for secret in (self.api_key, self.email):
            if secret:
                for value in (secret, urllib.parse.quote(secret, safe=""),
                              urllib.parse.quote_plus(secret)):
                    safe = safe.replace(value.encode("utf-8"), b"[REDACTED]")
        if safe != data:
            self.run.metadata["raw_response_credentials_redacted"] = True
        self.run.write_bytes(name, safe)

    def _retry_delay(self, header, attempt):
        delay = 2 ** (attempt - 1)
        if header:
            try:
                delay = float(header)
            except (ValueError, TypeError):
                try:
                    retry_at = email.utils.parsedate_to_datetime(header)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=dt.timezone.utc)
                    delay = (retry_at - dt.datetime.now(dt.timezone.utc)).total_seconds()
                except (ValueError, TypeError, OverflowError):
                    pass
        return max(0, min(delay, MAX_RETRY_DELAY_SECONDS))

    def request(self, utility, params):
        endpoint = BASE_URL + utility + ".fcgi"
        request_params = {**params, "tool": TOOL}
        if self.email:
            request_params["email"] = self.email
        if self.api_key:
            request_params["api_key"] = self.api_key
        public_params = {key: ("[REDACTED]" if key in {"api_key", "email"} else value)
                         for key, value in request_params.items()}
        request = urllib.request.Request(
            endpoint, data=urllib.parse.urlencode(request_params).encode("utf-8"),
            headers={"User-Agent": TOOL, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if self._last_request is not None:
                remaining = REQUEST_INTERVAL_SECONDS - (time.monotonic() - self._last_request)
                if remaining > 0:
                    time.sleep(remaining)
            self._last_request = time.monotonic()
            common = {"endpoint": endpoint, "method": "POST", "parameters": public_params,
                      "attempt": attempt}
            self.run.event({"event": "request_started", "timestamp": _utc_now(), **common})
            try:
                with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                    data = response.read()
                    status = response.status
                self.run.event({"event": "request_completed", "timestamp": _utc_now(),
                                "status": status, "response_bytes": len(data), **common})
                return data
            except urllib.error.HTTPError as error:
                status = error.code
                retry = status == 429 or 500 <= status <= 599
                delay = self._retry_delay(error.headers.get("Retry-After") if error.headers else None,
                                          attempt)
                detail = self.redact(str(error.reason or error))
                body_path = f"raw/http-{utility}-{attempt}.txt"
                suffix = 2
                while (self.run.directory / body_path).exists():
                    body_path = f"raw/http-{utility}-{attempt}-{suffix}.txt"
                    suffix += 1
                try:
                    body = error.read()
                except (OSError, http.client.HTTPException) as body_error:
                    body = ("Response body unavailable: " + self.redact(str(body_error))).encode("utf-8")
                finally:
                    error.close()
                self.archive(body_path, body)
                retrying = retry and attempt < MAX_ATTEMPTS
                self.run.event({"event": "request_failed", "timestamp": _utc_now(),
                                "status": status, "error_type": type(error).__name__,
                                "error_detail": detail, "response_body_path": body_path,
                                "retrying": retrying,
                                **({"retry_delay_seconds": delay} if retrying else {}),
                                **common})
                if retrying:
                    time.sleep(delay)
                    continue
                raise PubMedError(f"PubMed HTTP {status}: {detail}; inspect the archived response body.") from None
            except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as error:
                reason = getattr(error, "reason", None) or error
                detail = self.redact(str(reason))
                error_type = type(error).__name__
                delay = self._retry_delay(None, attempt)
                retrying = attempt < MAX_ATTEMPTS
                self.run.event({"event": "request_failed", "timestamp": _utc_now(),
                                "error": "network_or_timeout", "error_type": error_type,
                                "reason_type": type(reason).__name__, "error_detail": detail,
                                "retrying": retrying,
                                **({"retry_delay_seconds": delay} if retrying else {}),
                                **common})
                if retrying:
                    time.sleep(delay)
                    continue
                raise PubMedError(f"PubMed network request failed ({error_type}: {detail}); "
                                  "check internet access, DNS and TLS.") from None
        raise PubMedError("PubMed request failed.")


def _text(node):
    return re.sub(r"\s+", " ", "".join(node.itertext())).strip() if node is not None else ""


def _authors(node):
    authors = []
    for author in node.findall("AuthorList/Author"):
        collective = _text(author.find("CollectiveName"))
        if collective:
            authors.append({"literal": collective})
            continue
        family = _text(author.find("LastName"))
        given = _text(author.find("ForeName")) or _text(author.find("Initials"))
        if family or given:
            authors.append({key: value for key, value in (("family", family), ("given", given)) if value})
    return authors


def _publication_date(node):
    if node is None:
        return {}
    year = _text(node.find("Year"))
    medline = _text(node.find("MedlineDate"))
    values = {}
    if year:
        values["year"] = year
    elif medline:
        match = re.search(r"\b(\d{4})\b", medline)
        if match:
            values["year"] = match.group(1)
    if medline:
        values["date"] = medline
    elif year:
        # Keep the source precision; do not invent a month/day.
        components = [year, _text(node.find("Month")), _text(node.find("Day")),
                      _text(node.find("Season"))]
        values["date"] = " ".join(part for part in components if part)
    return values


def _record(element):
    is_book = element.tag == "PubmedBookArticle"
    document = element.find("BookDocument" if is_book else "MedlineCitation")
    if document is None:
        raise PubMedError("PubMed XML record is missing its citation document.")
    article = document if is_book else document.find("Article")
    if article is None:
        raise PubMedError("PubMed XML record is missing article metadata.")
    pmid = _text(document.find("PMID"))
    if not pmid.isdigit():
        raise PubMedError("PubMed XML record is missing a valid PMID.")
    record = {"id": "pubmed:" + pmid, "source": "pubmed", "type": "book" if is_book else "article",
              "pmid": pmid, "accession": pmid, "url": "https://pubmed.ncbi.nlm.nih.gov/" + pmid + "/",
              "authors": _authors(article), "keywords": []}
    title = _text(article.find("ArticleTitle"))
    if is_book:
        booktitle = _text(article.find("Book/BookTitle"))
        if title and booktitle:
            record["type"] = "CHAP"
            record["booktitle"] = booktitle
        elif not title:
            title = booktitle
    if title:
        record["title"] = title
    if is_book:
        record.update(_publication_date(article.find("Book/PubDate")))
    else:
        record.update(_publication_date(article.find("Journal/JournalIssue/PubDate")))
        for field, path in (("journal", "Journal/Title"), ("volume", "Journal/JournalIssue/Volume"),
                            ("issue", "Journal/JournalIssue/Issue"), ("pages", "Pagination/MedlinePgn")):
            value = _text(article.find(path))
            if value:
                record[field] = value
    data = element.find("PubmedBookData" if is_book else "PubmedData")
    doi = ""
    if data is not None:
        doi = next((_text(item) for item in data.findall("ArticleIdList/ArticleId")
                    if item.get("IdType") == "doi"), "")
    if not doi:
        doi = next((_text(item) for item in article.findall("ELocationID")
                    if item.get("EIdType") == "doi" and item.get("ValidYN", "Y") != "N"), "")
    if doi:
        record["doi"] = doi
    sections = []
    for section in article.findall("Abstract/AbstractText"):
        content = _text(section)
        if content:
            label = section.get("Label", "").strip()
            sections.append((label + ": " if label else "") + content)
    if sections:
        record["abstract"] = "\n".join(sections)
    record["keywords"] = [_text(item) for item in document.findall("KeywordList/Keyword") if _text(item)]
    return record


def _parse_records(data):
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise PubMedError("PubMed returned malformed XML; inspect the archived response.") from None
    if root.tag != "PubmedArticleSet" or root.find(".//ERROR") is not None:
        raise PubMedError("PubMed returned an XML error or an unexpected document.")
    records = []
    for element in root:
        if element.tag not in {"PubmedArticle", "PubmedBookArticle"}:
            raise PubMedError("PubMed returned an unsupported record type; no records were silently discarded.")
        records.append(_record(element))
    return records


def search(run, query, *, max_records=100, allow_partial=False, email=None, api_key=None, sort="pub_date"):
    """Execute and archive an exact PubMed query, returning normalized citations.

    A capped search is an error unless allow_partial is explicit. All requested
    identifiers must be returned exactly once. Network and API failures raise
    PubMedError; partial artifacts remain available in the run directory.
    """
    if not isinstance(query, str) or not query.strip():
        raise PubMedError("PubMed requires a nonempty text query.")
    if isinstance(max_records, bool) or not isinstance(max_records, int) or not 1 <= max_records <= 10000:
        raise PubMedError("max_records must be an integer from 1 to 10000 (the PubMed ESearch limit).")
    if sort not in {"pub_date", "relevance"}:
        raise PubMedError("PubMed sort must be pub_date or relevance.")
    client = _Client(run, email=email, api_key=api_key)
    run.metadata.update({"database": "pubmed", "query": query, "requested_cap": max_records,
                         "allow_partial": bool(allow_partial), "retrieval_complete": False,
                         "returned_count": 0, "sort": sort, "access_mode": "api",
                         "search_executed_by_program": True, "platform": "NCBI E-utilities"})
    raw = client.request("esearch", {"db": "pubmed", "term": query, "retmode": "json",
                                      "retmax": max_records, "retstart": 0, "sort": sort})
    client.archive("raw/esearch.json", raw)
    try:
        response = json.loads(raw)
        if not isinstance(response, dict) or response.get("error"):
            raise PubMedError("PubMed returned an API search error; inspect the archived response.")
        result = response["esearchresult"]
        if result.get("error") or result.get("ERROR") or result.get("errorlist"):
            run.metadata["search_errors"] = json.loads(client.redact(json.dumps(result.get("errorlist", {}))))
            raise PubMedError("PubMed reported a query error; inspect the archived response and correct the query.")
        count = int(result["count"])
        ids = result["idlist"]
        if count < 0 or not isinstance(ids, list) or any(not isinstance(pmid, str) or not pmid.isdigit() for pmid in ids):
            raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError):
        raise PubMedError("PubMed returned invalid search data; inspect the archived response.") from None
    warnings = result.get("warninglist", {})
    run.metadata.update({"query_translation": client.redact(str(result.get("querytranslation", ""))),
                         "warnings": json.loads(client.redact(json.dumps(warnings))),
                         "total_count": count, "selected_ids": ids, "partial": count > max_records})
    if count > max_records and not allow_partial:
        raise PubMedError(f"PubMed found {count} records, exceeding the cap of {max_records}. "
                          "Narrow/split the query, raise the cap up to 10000, or explicitly allow partial retrieval.")
    expected = min(count, max_records)
    if len(ids) != expected or len(set(ids)) != len(ids):
        raise PubMedError("PubMed returned missing or duplicate search identifiers; retrieval is incomplete.")
    records = []
    for offset in range(0, len(ids), 200):
        batch = ids[offset:offset + 200]
        raw = client.request("efetch", {"db": "pubmed", "id": ",".join(batch), "retmode": "xml"})
        client.archive(f"raw/efetch-{offset // 200 + 1:04d}.xml", raw)
        fetched = _parse_records(raw)
        returned = [record["pmid"] for record in fetched]
        if len(returned) != len(batch) or set(returned) != set(batch):
            raise PubMedError("PubMed returned missing, duplicate or unexpected citation IDs; retrieval is incomplete.")
        by_id = {record["pmid"]: record for record in fetched}
        records.extend(by_id[pmid] for pmid in batch)
        run.metadata["returned_count"] = len(records)
    run.metadata["retrieval_complete"] = len(records) == count
    return records

