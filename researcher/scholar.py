"""Google Scholar search plans and auditable observations, without a scraper.

The program does not open Scholar, solve access challenges or verify a supplied
observation against the live service. Planned, partial and blocked are distinct.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from .provenance import json_bytes, sha256


def _text(value, name, *, nullable=False):
    if nullable and value is None:
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + " must be nonempty text" + (" or null" if nullable else ""))
    return value


def _timestamp(value, name):
    _text(value, name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(name + " must be an ISO timestamp with timezone") from error
    if parsed.tzinfo is None:
        raise ValueError(name + " requires an explicit timezone")
    return parsed


def _url(value, name, *, scholar=False):
    _text(value, name)
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError(name + " must be a valid HTTP(S) URL") from error
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or any(ord(char) < 32 for char in value)):
        raise ValueError(name + " must be an HTTP(S) URL without credentials")
    if scholar and (parsed.scheme != "https" or port not in (None, 443)
                    or not re.fullmatch(r"scholar\.google\.(?:com|[a-z]{2}|(?:co|com)\.[a-z]{2})", parsed.hostname)
                    or parsed.path not in {"/scholar", "/scholar/"}):
        raise ValueError(name + " must be a Google Scholar HTTPS search URL")
    return parsed


def _filters(year_from, year_to, sort):
    for name, year in (("year_from", year_from), ("year_to", year_to)):
        if year is not None and (type(year) is not int or not 1000 <= year <= 9999):
            raise ValueError(name + " must be a four-digit year or null")
    if year_from is not None and year_to is not None and year_from > year_to:
        raise ValueError("year_from must not be later than year_to")
    if sort not in {"relevance", "date"}:
        raise ValueError("sort must be relevance or date")
    return {"year_from": year_from, "year_to": year_to, "sort": sort, "other": None}


def search_url(query, year_from=None, year_to=None, sort="relevance"):
    """Encode the exact query, including whitespace, without sending a request."""
    _text(query, "query")
    _filters(year_from, year_to, sort)
    params = {"q": query, "hl": "en"}
    if year_from is not None:
        params["as_ylo"] = year_from
    if year_to is not None:
        params["as_yhi"] = year_to
    if sort == "date":
        params["scisbd"] = "1"
    return "https://scholar.google.com/scholar?" + urlencode(params)


def prepare(run, query, year_from=None, year_to=None, sort="relevance"):
    """Write an unexecuted plan. The caller must finish it with status planned."""
    url = search_url(query, year_from, year_to, sort)
    filters = _filters(year_from, year_to, sort)
    template = {
        "query": query, "search_url": url, "searched_at": None,
        "status": None, "filters": filters,
        "displayed_count": None, "displayed_count_text": None,
        "pages_checked": [], "steps": [], "results": [], "stop_reason": None,
        "notes": "Fill from an actual permitted observation; do not invent unavailable values.",
        "planned_run_id": run.metadata["run_id"],
    }
    run.metadata.update(
        platform="Google Scholar", access_mode="browser_assisted",
        search_executed_by_program=False, retrieval_complete=None,
        coverage="not_searched", planned_url=url, search_url=url, filters=filters,
        url_parameters=parse_qs(urlsplit(url).query, keep_blank_values=True),
        total_count=None, returned_count=0,
        warnings=["A generated URL is not an executed search. Google Scholar has no bulk retrieval route here."],
    )
    run.write_bytes("search-url.txt", (url + "\n").encode("utf-8"))
    run.write_bytes("observation-template.json", json_bytes(template))
    run.write_bytes("instructions.md", (
        "# Google Scholar search plan — not executed\n\n"
        "Open search-url.txt through permitted interactive access. This program does not scrape Scholar. "
        "Respect access restrictions; stop on CAPTCHA, login, denial or unavailability.\n\n"
        "Copy observation-template.json outside this finished run before filling it. Record the actual "
        "query and URL, search/attempt timestamp with timezone, filters (other={} means no others; "
        "other=null means unknown), sort, exact displayed-count wording and approximate number if shown. "
        "Record each action in steps as {at, action, details, url}, including pages inspected, "
        "citation chasing and reasons for changes. List the one-based pages inspected in pages_checked. "
        "Use a separate run for each changed query.\n\n"
        "Set status to partial for observed results (including an observed empty set), or blocked "
        "for an unsuccessful attempt. Never use complete. Every selected result needs rank, page, "
        "title and paper URL; optional authors are strings or name objects, with year, DOI and abstract "
        "only when observed. evidence_level is metadata, abstract or full_text; a snippet alone is metadata. "
        "Record why observation stopped. Keep unavailable counts null. Do not include result records "
        "for a blocked attempt; log a later interruption after successful pages as partial.\n\n"
        "The results list contains only ranked hits from the recorded query URL. Do not mix in "
        "papers discovered on Cited by, Related articles or reference pages: log those separately "
        "with their actual discovery URL and parent paper. This adapter does not import citation-only "
        "Scholar URLs without a q parameter. A new keyword query needs its own run.\n\n"
        "Record the observation into a NEW run with the scholar-record command. Attach saved screenshots "
        "or page extracts using --evidence, when permitted. The stored observation is observer-supplied "
        "evidence, not proof that this program executed or independently verified the search.\n"
    ).encode("utf-8"))
    run.event({"event": "scholar_plan_created", "search_url": url, "filters": filters,
               "search_executed_by_program": False})
    return []


def _check_url_filters(url, query, filters):
    parsed = _url(url, "search_url", scholar=True)
    params = parse_qs(parsed.query, keep_blank_values=True)
    if params.get("q") != [query]:
        raise ValueError("search_url q must match the exact recorded query")
    for key, field in (("as_ylo", "year_from"), ("as_yhi", "year_to")):
        expected = filters[field]
        values = params.get(key)
        if (expected is None and values not in (None, [""])) or (
                expected is not None and values != [str(expected)]):
            raise ValueError("search_url " + key + " disagrees with filters." + field)
    sort = params.get("scisbd", ["0"])
    if sort != (["1"] if filters["sort"] == "date" else ["0"]):
        raise ValueError("search_url sort disagrees with filters.sort")


def record(run, query, observation_bytes, evidence_files=()):
    """Preserve and validate a supplied observation, returning citation records."""
    run.write_bytes("raw/observation.json", observation_bytes)
    evidence = []
    for index, filename in enumerate(evidence_files, 1):
        path = Path(filename)
        # Prefix prevents basename collisions; only a basename is used as a destination.
        destination = "raw/evidence/" + str(index) + "-" + path.name
        data = path.read_bytes()
        run.write_bytes(destination, data)
        evidence.append({"artifact": destination, "sha256": sha256(data)})
    observation = json.loads(observation_bytes.decode("utf-8-sig"))
    if not isinstance(observation, dict):
        raise ValueError("Scholar observation must be a JSON object")
    if observation.get("query") != query:
        raise ValueError("Observation query must match the exact query file, including whitespace")
    searched_at = observation.get("searched_at")
    _timestamp(searched_at, "searched_at")
    status = observation.get("status")
    if status not in {"partial", "blocked"}:
        raise ValueError("Observation status must be partial or blocked; completeness cannot be established")
    filters = observation.get("filters")
    if not isinstance(filters, dict) or not {"year_from", "year_to", "sort", "other"}.issubset(filters):
        raise ValueError("filters requires year_from, year_to, sort and other (object or null)")
    _filters(filters["year_from"], filters["year_to"], filters["sort"])
    if filters["other"] is not None and not isinstance(filters["other"], dict):
        raise ValueError("filters.other must be an object or null if unknown")
    _check_url_filters(observation.get("search_url"), query, filters)
    for field in ("displayed_count", "displayed_count_text"):
        if field not in observation:
            raise ValueError(field + " is required; use null if unavailable")
    count = observation["displayed_count"]
    if count is not None and (type(count) is not int or count < 0):
        raise ValueError("displayed_count must be a nonnegative integer or null")
    _text(observation["displayed_count_text"], "displayed_count_text", nullable=True)
    if count is not None and observation["displayed_count_text"] is None:
        raise ValueError("Preserve displayed_count_text when recording a displayed_count")
    _text(observation.get("stop_reason"), "stop_reason")
    steps = observation.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must record at least one actual search or access attempt")
    previous = None
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("Each step must be an object with at, action and details")
        at = _timestamp(step.get("at"), "steps.at")
        if previous is not None and at < previous:
            raise ValueError("steps must be in chronological order")
        previous = at
        _text(step.get("action"), "steps.action")
        _text(step.get("details"), "steps.details")
        if step.get("url") is not None:
            _url(step["url"], "steps.url")
    results = observation.get("results")
    if not isinstance(results, list):
        raise ValueError("results must be a list, empty for a blocked attempt")
    if count == 0 and results:
        raise ValueError("A zero-result observation cannot contain result records")
    if status == "blocked" and (results or count is not None or observation["displayed_count_text"] is not None):
        raise ValueError("A blocked attempt must not contain results or displayed counts; use partial after successful pages")
    pages = observation.get("pages_checked")
    if (not isinstance(pages, list) or any(type(page) is not int or page < 1 for page in pages)
            or len(pages) != len(set(pages))):
        raise ValueError("pages_checked must be a list of unique positive one-based page numbers")
    if status == "blocked" and pages:
        raise ValueError("A blocked attempt cannot claim inspected result pages")
    if status == "partial" and not pages:
        raise ValueError("An observed partial search needs at least one checked page")
    records, ranks = [], set()
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("Each result must be an object")
        for field in ("rank", "page"):
            if type(result.get(field)) is not int or result[field] < 1:
                raise ValueError("Result " + field + " must be a positive one-based integer")
        if result["page"] not in pages:
            raise ValueError("Result page must be in pages_checked")
        if result["rank"] in ranks:
            raise ValueError("Result ranks must be unique within one search")
        ranks.add(result["rank"])
        title = _text(result.get("title"), "result.title")
        _url(result.get("url"), "result.url")
        level = result.get("evidence_level", "metadata")
        if level not in {"metadata", "abstract", "full_text"}:
            raise ValueError("evidence_level must be metadata, abstract or full_text")
        authors = result.get("authors", [])
        if not isinstance(authors, list):
            raise ValueError("Result authors must be a list")
        normalized_authors = []
        for author in authors:
            if isinstance(author, str):
                normalized_authors.append({"literal": _text(author, "author")})
            elif isinstance(author, dict) and set(author).issubset({"literal", "given", "family"}) and author:
                for value in author.values():
                    _text(value, "author name")
                if "literal" not in author and "family" not in author:
                    raise ValueError("Author name objects require literal or family")
                normalized_authors.append(author)
            else:
                raise ValueError("Authors must be text or literal/family/given objects")
        item = {"source": "google-scholar", "type": "GEN", "title": title,
                "url": result["url"], "authors": normalized_authors,
                "discovery": {"rank": result["rank"], "page": result["page"],
                              "search_url": observation["search_url"], "searched_at": searched_at,
                              "evidence_level": level}}
        for field in ("doi", "abstract", "journal", "year"):
            if result.get(field) is not None:
                value = result[field]
                if field == "year" and type(value) is int:
                    value = str(value)
                _text(value, "result." + field)
                if field == "year" and not re.fullmatch(r"\d{4}", value):
                    raise ValueError("Result year must be four digits")
                item[field] = value
        identity = json_bytes({"title": title, "url": item["url"]})
        item["id"] = "google-scholar:" + sha256(identity)[:20]
        records.append(item)
    run.metadata.update(
        platform="Google Scholar", access_mode="browser_assisted_observation",
        search_executed_by_program=False, retrieval_complete=None,
        observation_status=status, searched_at=searched_at,
        original_search=observation, search_url=observation["search_url"],
        url_parameters=parse_qs(urlsplit(observation["search_url"]).query, keep_blank_values=True),
        filters=filters, pages_checked=pages,
        total_count=None, displayed_count=count, displayed_count_is_approximate=True,
        returned_count=len(records), evidence=evidence,
        coverage="blocked" if status == "blocked" else "observed_subset_not_exhaustive",
        warnings=["Observer-supplied search log; live execution is not independently verified.",
                  "Scholar counts and rankings can vary; this run does not establish exhaustive coverage."],
    )
    if count is not None and count < len(records):
        run.metadata["warnings"].append(
            "The displayed estimate is below the number of supplied records; verify the original observation.")
    for step in steps:
        run.event({"event": "scholar_observed_step", "observed_at": step["at"],
                   "action": step["action"], "details": step["details"], "url": step.get("url")})
    run.event({"event": "scholar_observation_recorded", "observation_status": status,
               "records": len(records), "search_executed_by_program": False})
    return records
