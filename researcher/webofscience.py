"""Audited, optional Web of Science Starter v1 metadata search adapter.

Schema: https://developer.clarivate.com/apis/wos-starter/swagger
The API key must have an active Starter subscription; web login is not API access.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import http.client
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request


ENDPOINT = "https://api.clarivate.com/apis/wos-starter/v1/documents"
REQUEST_INTERVAL_SECONDS = 1.05
TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 3
MAX_RETRY_DELAY_SECONDS = 30


class WebOfScienceError(RuntimeError):
    """A failed or incomplete Web of Science retrieval."""


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A service redirect must never forward the API key to another host.
        return None


class _Client:
    def __init__(self, run, api_key, max_requests):
        self.run, self.api_key, self.max_requests = run, api_key, max_requests
        self.request_count = 0
        self.last_request = None
        self.opener = urllib.request.build_opener(_NoRedirect())

    def redact(self, value):
        text = str(value)
        for secret in (self.api_key, urllib.parse.quote(self.api_key, safe=""),
                       urllib.parse.quote_plus(self.api_key), json.dumps(self.api_key)[1:-1]):
            text = text.replace(secret, "[REDACTED]")
        return text

    def safe_bytes(self, data):
        safe = data
        for secret in (self.api_key, urllib.parse.quote(self.api_key, safe=""),
                       urllib.parse.quote_plus(self.api_key), json.dumps(self.api_key)[1:-1]):
            safe = safe.replace(secret.encode("utf-8"), b"[REDACTED]")
        if safe != data:
            self.run.metadata["raw_response_credentials_redacted"] = True
        return safe

    def _delay(self, header, attempt):
        delay = float(2 ** (attempt - 1))
        if header:
            try:
                delay = float(header)
            except (TypeError, ValueError):
                try:
                    parsed = email.utils.parsedate_to_datetime(header)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=dt.timezone.utc)
                    delay = (parsed - dt.datetime.now(dt.timezone.utc)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    pass
        if not math.isfinite(delay):
            delay = MAX_RETRY_DELAY_SECONDS
        return max(0, delay)

    def request(self, params):
        request = urllib.request.Request(
            ENDPOINT + "?" + urllib.parse.urlencode(params),
            headers={"X-ApiKey": self.api_key, "Accept": "application/json",
                     "User-Agent": "psychology-literature-researcher"}, method="GET")
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if self.request_count >= self.max_requests:
                raise WebOfScienceError(
                    f"Web of Science request budget ({self.max_requests}) exhausted; "
                    "retrieval is incomplete. Review your API quota before increasing --max-requests.")
            if self.last_request is not None:
                remaining = REQUEST_INTERVAL_SECONDS - (time.monotonic() - self.last_request)
                if remaining > 0:
                    time.sleep(remaining)
            self.last_request = time.monotonic()
            self.request_count += 1
            self.run.metadata["request_count"] = self.request_count
            common = {"endpoint": ENDPOINT, "method": "GET", "parameters": params,
                      "attempt": attempt, "request_number": self.request_count,
                      "authentication": "X-ApiKey: [REDACTED]"}
            self.run.event({"event": "request_started", "timestamp": _now(), **common})
            try:
                with self.opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                    data, status = response.read(), response.status
                if status != 200:
                    raise WebOfScienceError(f"Unexpected Web of Science response status {status}.")
                safe = self.safe_bytes(data)
                self.run.event({"event": "request_completed", "timestamp": _now(),
                                "status": status, "response_bytes": len(data), **common})
                return safe
            except urllib.error.HTTPError as error:
                status = error.code
                retry_after = self._delay(error.headers.get("Retry-After") if error.headers else None, attempt)
                detail = self.redact(error.reason or error)
                body_path = f"raw/http-{self.request_count:04d}.txt"
                try:
                    body = error.read()
                except (OSError, http.client.HTTPException) as body_error:
                    body = self.redact(body_error).encode("utf-8")
                finally:
                    error.close()
                self.run.write_bytes(body_path, self.safe_bytes(body))
                retrying = ((status == 429 or 500 <= status <= 599) and attempt < MAX_ATTEMPTS
                            and retry_after <= MAX_RETRY_DELAY_SECONDS
                            and self.request_count < self.max_requests)
                self.run.event({"event": "request_failed", "timestamp": _now(), "status": status,
                                "error_type": type(error).__name__, "error_detail": detail,
                                "response_body_path": body_path, "retrying": retrying,
                                **({"retry_delay_seconds": retry_after} if retrying else {}), **common})
                if retrying:
                    time.sleep(retry_after)
                    continue
                if status in (401, 403):
                    explanation = "check the API key, active Starter subscription and permitted collection"
                elif 300 <= status < 400:
                    explanation = "redirect blocked to protect the API key; verify the official API endpoint"
                elif status == 429:
                    explanation = "rate or daily quota reached; wait before retrying and review the portal quota"
                elif retry_after > MAX_RETRY_DELAY_SECONDS:
                    explanation = f"server requested a wait of {retry_after:g} seconds; retry later"
                else:
                    explanation = "inspect the archived response and API subscription limits"
                raise WebOfScienceError(f"Web of Science HTTP {status}: {detail}; {explanation}.") from None
            except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as error:
                reason = getattr(error, "reason", None) or error
                detail = self.redact(reason)
                retrying = attempt < MAX_ATTEMPTS and self.request_count < self.max_requests
                delay = self._delay(None, attempt)
                self.run.event({"event": "request_failed", "timestamp": _now(),
                                "error_type": type(error).__name__, "error_detail": detail,
                                "retrying": retrying,
                                **({"retry_delay_seconds": delay} if retrying else {}), **common})
                if retrying:
                    time.sleep(delay)
                    continue
                raise WebOfScienceError(f"Web of Science network request failed "
                                        f"({type(error).__name__}: {detail}); check DNS, TLS and network access.") from None
        raise WebOfScienceError("Web of Science request failed.")


def _mapping(value, name):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise WebOfScienceError(f"Invalid Web of Science {name}; inspect the archived response.")
    return value


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _record(hit):
    if not isinstance(hit, dict) or not _text(hit.get("uid")):
        raise WebOfScienceError("Web of Science record is missing its UID; retrieval is incomplete.")
    uid = hit["uid"]
    types = hit.get("types") or []
    if not isinstance(types, list) or any(not isinstance(t, str) for t in types):
        raise WebOfScienceError("Invalid Web of Science document types.")
    normalized_types = {t.casefold() for t in types}
    kind = ("CHAP" if "book chapter" in normalized_types else "book" if "book" in normalized_types
            else "article" if normalized_types & {"article", "review"} else "GEN")
    record = {"id": "webofscience:" + uid, "source": "webofscience", "accession": uid,
              "type": kind, "source_document_types": types, "authors": [], "keywords": []}
    title = _text(hit.get("title"))
    if title:
        record["title"] = title
    source = _mapping(hit.get("source"), "source metadata")
    container = _text(source.get("sourceTitle"))
    if container and kind == "CHAP":
        record["booktitle"] = container
    elif container and kind == "article":
        record["journal"] = container
    elif container:
        record["container_title"] = container
    year = source.get("publishYear")
    if type(year) is int:
        record["year"] = str(year)
        record["date"] = str(year) + (" " + _text(source.get("publishMonth")) if _text(source.get("publishMonth")) else "")
    for field in ("volume", "issue"):
        if _text(source.get(field)):
            record[field] = source[field]
    pages = _mapping(source.get("pages"), "pages")
    if _text(pages.get("range")):
        record["pages"] = pages["range"]
    elif _text(pages.get("begin")):
        start, end = pages["begin"], _text(pages.get("end"))
        record["pages"] = start + ("-" + end if end and end != start else "")
    elif _text(source.get("articleNumber")):
        record["pages"] = source["articleNumber"]
    names = _mapping(hit.get("names"), "names")
    authors = names.get("authors") or []
    if not isinstance(authors, list):
        raise WebOfScienceError("Invalid Web of Science authors list.")
    for author in authors:
        author = _mapping(author, "author")
        name = _text(author.get("displayName")) or _text(author.get("wosStandard"))
        if name:
            parts = name.split(",", 1)
            if len(parts) == 2 and all(p.strip() for p in parts):
                record["authors"].append({"family": parts[0].strip(), "given": parts[1].strip()})
            else:
                record["authors"].append({"literal": name})
    corporate_authors = names.get("corp") or []
    if not isinstance(corporate_authors, list):
        raise WebOfScienceError("Invalid Web of Science corporate authors list.")
    for author in corporate_authors:
        author = _mapping(author, "corporate author")
        name = _text(author.get("displayName"))
        if name and {"literal": name} not in record["authors"]:
            record["authors"].append({"literal": name})
    identifiers = _mapping(hit.get("identifiers"), "identifiers")
    for field in ("doi", "pmid"):
        if _text(identifiers.get(field)):
            record[field] = identifiers[field]
    links = _mapping(hit.get("links"), "links")
    if _text(links.get("record")):
        record["url"] = links["record"]
    keywords = _mapping(hit.get("keywords"), "keywords").get("authorKeywords") or []
    if not isinstance(keywords, list) or any(not isinstance(k, str) for k in keywords):
        raise WebOfScienceError("Invalid Web of Science keywords.")
    record["keywords"] = keywords
    # Starter does not provide abstracts: never manufacture or infer one.
    return record


def search(run, query, *, max_records=50, allow_partial=False, api_key=None,
           collection="WOS", edition=None, max_requests=10):
    """Search an authorized Starter account; preserve every requested page.

    Completion means all hits reported by this API and account were retrieved.
    It does not establish access to every WoS index or full-text publication.
    """
    run.metadata.update({"database": "webofscience", "platform": "Web of Science Starter API",
                         "api_version": "v1", "access_mode": "authorized_api", "query": query,
                         "query_translation": None, "query_translation_available": False,
                         "collection": collection, "requested_edition": edition,
                         "effective_scope": "Limited to API subscription entitlements; not independently verified",
                         "requested_cap": max_records, "allow_partial": bool(allow_partial),
                         "max_requests": max_requests, "request_count": 0, "sort": "LD+A",
                         "returned_count": 0, "downloaded_count": 0, "selected_ids": [],
                         "snapshot_consistency": "Page counts and UIDs checked; API provides no fixed snapshot token",
                         "retrieval_complete": False})
    if not isinstance(query, str) or not query.strip():
        raise WebOfScienceError("Web of Science requires a nonempty exact query.")
    if type(max_records) is not int or max_records < 1:
        raise WebOfScienceError("max_records must be a positive integer.")
    if type(max_requests) is not int or max_requests < 1:
        raise WebOfScienceError("max_requests must be a positive integer.")
    if collection != "WOS":
        raise WebOfScienceError("This adapter currently supports the WOS Core Collection only.")
    if edition is not None and (not isinstance(edition, str) or not edition.strip()):
        raise WebOfScienceError("edition must be a nonempty API edition string, or omitted.")
    if not isinstance(api_key, str) or not api_key.strip():
        raise WebOfScienceError("WOS_API_KEY is missing. Configure a runtime secret with an active Starter API subscription; do not paste the key into chat.")
    if any(ord(c) < 33 or ord(c) > 126 for c in api_key):
        raise WebOfScienceError("WOS_API_KEY must contain printable ASCII without whitespace.")
    client = _Client(run, api_key, max_requests)
    limit, page, total, records, seen = min(max_records, 50), 1, None, [], set()
    while True:
        params = {"db": collection, "q": query, "limit": limit, "page": page, "sortField": "LD+A"}
        if edition is not None:
            params["edition"] = edition
        raw = client.request(params)
        run.write_bytes(f"raw/wos-page-{page:04d}.json", raw)
        try:
            response = json.loads(raw)
            if not isinstance(response, dict) or response.get("error"):
                raise ValueError
            metadata, hits = response["metadata"], response["hits"]
            if not isinstance(metadata, dict) or not isinstance(hits, list):
                raise ValueError
            count = metadata["total"]
            if (type(count) is not int or count < 0 or type(metadata["page"]) is not int
                    or metadata["page"] != page or type(metadata["limit"]) is not int
                    or metadata["limit"] != limit):
                raise ValueError
        except (KeyError, ValueError, TypeError):
            raise WebOfScienceError("Web of Science returned invalid page metadata or an API error; inspect the archived response.") from None
        if total is None:
            total = count
            run.metadata.update(total_count=total, partial=total > max_records)
            if total > max_records and not allow_partial:
                raise WebOfScienceError(f"Web of Science found {total} records, exceeding the cap of {max_records}. "
                                        "Narrow the query, increase the cap within your quota, or explicitly allow partial retrieval.")
        elif count != total:
            raise WebOfScienceError("Web of Science result count changed between pages; rerun to obtain a consistent snapshot.")
        expected = max(0, min(limit, total - (page - 1) * limit))
        if len(hits) != expected:
            raise WebOfScienceError("Web of Science returned a missing or truncated page; retrieval is incomplete.")
        normalized = [_record(hit) for hit in hits]
        for record in normalized:
            uid = record["accession"]
            if uid in seen:
                raise WebOfScienceError("Web of Science returned duplicate UIDs across pages; retrieval is incomplete.")
            seen.add(uid)
        records.extend(normalized[:max_records - len(records)])
        run.metadata.update(returned_count=len(records), downloaded_count=len(seen),
                            selected_ids=[r["accession"] for r in records])
        if len(records) == min(total, max_records):
            break
        page += 1
    run.metadata["retrieval_complete"] = len(records) == total
    return records
