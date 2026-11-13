"""Build an evidence-review workspace without inventing screening or findings."""
from __future__ import annotations

import copy
import csv
import json
import re
import shutil
from pathlib import Path
from urllib.parse import unquote

from .citations import write_exports
from .provenance import json_bytes, sha256, utcnow, verify


RETRIEVABLE = {"complete", "partial", "imported"}
UNSEARCHED = {"planned", "blocked", "failed"}
EVIDENCE_FIELDS = (
    "evidence_id", "title", "authors", "year", "doi", "pmid", "url", "discovered_in",
    "screening_decision", "exclusion_reason", "evidence_level", "population", "design",
    "sample_size", "measures", "outcomes", "findings", "limitations", "source_locator",
    "quality_notes", "metadata_conflicts",
)


def _identity(record):
    """Only syntactically plausible DOI/PMID values establish duplicate identity."""
    tokens = set()
    doi = unquote(str(record.get("doi") or "")).strip()
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I).strip().lower()
    if re.fullmatch(r"10\.\d{4,9}/\S+", doi):
        tokens.add("doi:" + doi)
    pmid = str(record.get("pmid") or "").strip()
    if re.fullmatch(r"[1-9]\d*", pmid):
        tokens.add("pmid:" + pmid)
    return tokens


def _deduplicate(occurrences):
    """Union strong identifiers; refuse to merge groups with conflicting IDs."""
    parents = list(range(len(occurrences)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    identities, seen = [], {}
    for index, occurrence in enumerate(occurrences):
        tokens = _identity(occurrence["record"])
        identities.append(tokens)
        for token in tokens:
            if token in seen:
                parents[root(index)] = root(seen[token])
            else:
                seen[token] = index
    groups = {}
    for index in range(len(occurrences)):
        groups.setdefault(root(index), []).append(index)
    resolved, warnings = [], []
    for group in groups.values():
        tokens = set().union(*(identities[i] for i in group))
        conflicting = any(sum(token.startswith(prefix) for token in tokens) > 1
                          for prefix in ("doi:", "pmid:"))
        if conflicting:
            warnings.append("Conflicting DOI/PMID identity: kept separate for manual checking: " + ", ".join(sorted(tokens)))
            resolved.extend(([index], True) for index in group)
        else:
            resolved.append((group, False))
    records = []
    for indices, identity_conflict in resolved:
        members = sorted((occurrences[i] for i in indices), key=lambda o: (o["run_id"], o["position"]))
        tokens = sorted(set().union(*(_identity(m["record"]) for m in members)))
        identity = tokens if tokens and not identity_conflict else [(m["run_id"], m["position"], m["record"].get("id")) for m in members]
        evidence_id = "E-" + sha256(json_bytes(identity))[:16]
        record = copy.deepcopy(members[0]["record"])
        conflicts = []
        fields = sorted(set().union(*(m["record"].keys() for m in members)) - {"id", "source", "raw_tags", "rank", "page", "discovery"})
        for field in fields:
            values = []
            for member in members:
                value = member["record"].get(field)
                if value not in (None, "", [], {}) and value not in values:
                    values.append(value)
            if len(values) > 1:
                conflicts.append({"field": field, "values": values})
            if record.get(field) in (None, "", [], {}) and values:
                record[field] = copy.deepcopy(values[0])
        if identity_conflict:
            conflicts.append({"field": "identity", "values": tokens})
        record.update(evidence_id=evidence_id, discovery_occurrences=members, metadata_conflicts=conflicts)
        records.append(record)
    return sorted(records, key=lambda r: r["evidence_id"]), warnings


def _csv(path, fields, rows):
    # CSV quoting preserves commas and line breaks. Treat downloaded metadata as
    # text when opening this artifact in spreadsheet applications.
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _known(mapping, *keys):
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def create_review(run_directories, output, question):
    """Verify, snapshot and combine runs into a new, editable review directory.

    Planned, blocked and failed runs appear only in the coverage log. A blank
    evidence table and gap-analysis scaffold require actual reading by the agent
    or researcher; this function performs no scientific synthesis.
    """
    output = Path(output)
    if output.exists():
        raise ValueError("Review output already exists; choose a new directory")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("A nonempty research question is required")
    if not run_directories:
        raise ValueError("At least one saved search run is required")
    sources, occurrences, warnings, ids = [], [], [], set()
    for directory in run_directories:
        directory = Path(directory).resolve()
        if output.resolve().is_relative_to(directory):
            raise ValueError("Review output must be outside its source run directories")
        verify(directory)
        if any(p.is_symlink() for p in directory.rglob("*")):
            raise ValueError("Source runs must contain ordinary files, not symlinks")
        manifest = json.loads((directory / "manifest.json").read_bytes())
        if not isinstance(manifest, dict):
            raise ValueError("Source manifest must be an object")
        run_id = manifest.get("run_id")
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
            raise ValueError("Source run_id must be a safe nonempty identifier")
        if run_id in ids:
            raise ValueError("Duplicate source run_id: " + run_id)
        ids.add(run_id)
        status = manifest.get("status")
        if status not in RETRIEVABLE | UNSEARCHED:
            raise ValueError("Source run must be finished; unsupported status: " + str(status))
        records = []
        if status in RETRIEVABLE:
            records = json.loads((directory / "records.json").read_bytes())
            if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
                raise ValueError("Source records.json must contain a list of record objects")
            for record in records:
                authors = record.get("authors", [])
                if not isinstance(authors, list) or any(not isinstance(a, dict) for a in authors):
                    raise ValueError("Source record authors must be a list of objects")
                if record.get("discovery") is not None and not isinstance(record["discovery"], dict):
                    raise ValueError("Source record discovery must be an object")
            if "returned_count" in manifest and manifest["returned_count"] != len(records):
                raise ValueError("Source returned_count does not match records.json")
        else:
            warnings.append(f"{run_id}: {manifest.get('database', 'unknown database')} is {status}; no records ingested from this attempt.")
        if status in {"partial", "imported"}:
            warnings.append(f"{run_id}: {status} coverage; do not interpret this as a comprehensive search.")
        query_path = directory / "query.txt"
        query = query_path.read_bytes().decode("utf-8") if query_path.is_file() else None
        original = manifest.get("original_search") or {}
        if not isinstance(original, dict):
            original = {}
        filters = original.get("filters", manifest.get("filters"))
        nested_sort = filters.get("sort") if isinstance(filters, dict) else None
        row = {
            "run_id": run_id, "database": manifest.get("database"),
            "platform": manifest.get("platform", original.get("platform")),
            "status": status, "search_started_at": manifest.get("started_at"),
            "original_searched_at": original.get("searched_at", manifest.get("searched_at")),
            "exact_query": query, "filters": filters,
            "sort": original.get("sort", manifest.get("sort", nested_sort)),
            "total_matched": _known(manifest, "total_count", "total_results"),
            "displayed_count": manifest.get("displayed_count"),
            "displayed_count_is_approximate": manifest.get("displayed_count_is_approximate"),
            "records_ingested": len(records), "retrieval_complete": manifest.get("retrieval_complete"),
            "coverage": manifest.get("coverage"), "error": manifest.get("error"),
            "search_reason": manifest.get("search_reason"), "parent_run_id": manifest.get("parent_run_id"),
            "original_run_directory": str(directory), "snapshot": "sources/" + run_id,
        }
        if row["total_matched"] is None:
            row["total_matched"] = _known(original, "total_results")
        sources.append((directory, manifest, row))
        for position, record in enumerate(records, 1):
            discovery = record.get("discovery") or {}
            occurrences.append({"run_id": run_id, "database": manifest.get("database"),
                                "record_id": record.get("id"), "position": position,
                                "rank": record.get("rank", discovery.get("rank")),
                                "page": record.get("page", discovery.get("page")),
                                "record": copy.deepcopy(record)})
    records, identity_warnings = _deduplicate(occurrences)
    warnings.extend(identity_warnings)
    metadata_conflicts = sum(bool(r["metadata_conflicts"]) for r in records)
    if metadata_conflicts:
        warnings.append(f"{metadata_conflicts} evidence records have metadata conflicts; check source snapshots before citing.")
    # All source validation happens before creating any user-facing output.
    output.mkdir(parents=True, exist_ok=False)
    for directory, manifest, row in sources:
        shutil.copytree(directory, output / row["snapshot"])
        verify(output / row["snapshot"])
    (output / "records.json").write_bytes(json_bytes(records))
    write_exports(records, output)
    evidence_rows = []
    for record in records:
        row = {field: "" for field in EVIDENCE_FIELDS}
        for field in ("evidence_id", "title", "year", "doi", "pmid", "url"):
            row[field] = record.get(field, "")
        row["authors"] = "; ".join(a.get("literal") or ", ".join(filter(None, (a.get("family"), a.get("given")))) for a in record.get("authors", []))
        row["discovered_in"] = "; ".join(sorted({o["run_id"] for o in record["discovery_occurrences"]}))
        row["metadata_conflicts"] = json.dumps(record["metadata_conflicts"], ensure_ascii=False) if record["metadata_conflicts"] else ""
        evidence_rows.append(row)
    _csv(output / "evidence.csv", EVIDENCE_FIELDS, evidence_rows)
    search_rows = [row for _, _, row in sources]
    _csv(output / "search-log.csv", list(search_rows[0]),
         [{k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()} for row in search_rows])
    log = ["# Search coverage", "", "Only the supplied runs are represented. Omitted databases remain unsearched or unknown.",
           "Unknown counts are blank in CSV and null in review.json; they are not zero hits.",
           "Recorded result counts describe search retrieval, not eligible studies. Counts from different engines must not be added as unique studies.",
           "Exact query bytes, raw evidence, events and checksums are preserved in sources/.", ""]
    for row in search_rows:
        total = "unknown" if row["total_matched"] is None else str(row["total_matched"])
        approximate = (f" Displayed approximate count: {row['displayed_count']}."
                       if row['displayed_count_is_approximate'] and row['displayed_count'] is not None else "")
        log.extend([f"## {row['run_id']}", "", f"Database: {row['database']}. Status: {row['status']}. Matched: {total}. Records ingested: {row['records_ingested']}.{approximate}",
                    f"Snapshot: [{row['snapshot']}/manifest.json]({row['snapshot']}/manifest.json). Exact query: [{row['snapshot']}/query.txt]({row['snapshot']}/query.txt).", ""])
    log.extend(["## Limits", ""] + ["- " + warning for warning in warnings])
    (output / "search-log.md").write_text("\n".join(log) + "\n", encoding="utf-8")
    gap = """# Candidate research gaps — working document

Research question: {question}

This file is a scaffold, not a finding that a gap exists. The retrieved records
have not been screened or appraised automatically. Start with search-log.md.
Read abstracts and available full texts; record the actual evidence level and
source page/section in evidence.csv. Leave unavailable information blank.
Record inclusion/exclusion decisions and reasons before interpreting coverage.

## Evidence synthesis

- Inclusion/exclusion criteria and rationale:
- What findings converge? Cite evidence IDs from evidence.csv:
- Which findings conflict, and might methods or populations explain this?
- What can only be inferred from abstracts or citation metadata?
- Which databases, populations, dates or designs remain insufficiently searched?

## Candidate gap (repeat for each candidate)

- Gap type: population / method / mechanism / inconsistent findings / replication:
- Evidence IDs and exact passages supporting the candidate:
- Evidence that contradicts or narrows the candidate:
- Why the unanswered question matters beyond "few papers found":
- Targeted follow-up query, engine, filters and rationale:
- Follow-up run IDs and what they changed:
- Alternative terms, recent reviews and backward/forward citations checked:
- Confidence and remaining coverage limits (novelty is not established by absence):

## Feasible study proposal

- Specific research question and population:
- Testable hypothesis or exploratory objective:
- Design, variables, measures and comparison:
- How this design addresses the evidence-backed candidate gap:
- Feasibility, recruitment, ethics and precision/power considerations:
- What evidence would change or invalidate this proposal?

When editing evidence.csv, import all columns as text in spreadsheet software.
Keep source snapshots unchanged; save new searches as new runs and build a new
review directory when updating the evidence base. Preserve screening decisions
explicitly when carrying them forward; this builder does not migrate them.
""".format(question=question)
    (output / "gap-analysis.md").write_text(gap, encoding="utf-8")
    summary = {"review_directory": str(output), "created_at": utcnow(), "question": question,
               "source_runs": len(sources), "retrieved_records": len(occurrences),
               "unique_records": len(records), "duplicate_occurrences": len(occurrences) - len(records),
               "warnings": warnings, "searches": search_rows,
               "screening_status": "not_started", "gap_analysis_status": "scaffold_only"}
    (output / "review.json").write_bytes(json_bytes(summary))
    return summary
