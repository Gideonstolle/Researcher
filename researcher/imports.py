"""Database-specific adapters for authorized RIS exports, not online searches."""
from __future__ import annotations

import json
from datetime import datetime

from .citations import parse_ris


PLATFORMS = {
    "psycinfo": {"APA PsycNet", "EBSCOhost", "Ovid", "ProQuest"},
    "webofscience": {"Web of Science"},
}


def import_export(run, database, data, metadata_bytes):
    run.write_bytes("raw/export.ris", data)
    run.write_bytes("raw/search-metadata.json", metadata_bytes)
    metadata = json.loads(metadata_bytes.decode("utf-8-sig"))
    if not isinstance(metadata, dict):
        raise ValueError("Import metadata must be a JSON object")
    if metadata.get("database") != database:
        raise ValueError("Metadata database must match the selected import adapter")
    if metadata.get("platform") not in PLATFORMS[database]:
        raise ValueError("Use the actual platform: " + ", ".join(sorted(PLATFORMS[database])))
    for field in ("searched_at", "filters", "total_results", "exported_range", "collection", "timespan"):
        if field not in metadata:
            raise ValueError("Missing import metadata field: " + field + "; use null for an unknown value")
    if metadata["filters"] is not None and not isinstance(metadata["filters"], dict):
        raise ValueError("filters must be an object, or null if unknown")
    searched_at = metadata["searched_at"]
    if searched_at is not None:
        if not isinstance(searched_at, str):
            raise ValueError("searched_at must be an ISO timestamp with timezone, or null")
        parsed = datetime.fromisoformat(searched_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("searched_at requires an explicit timezone, e.g. +01:00")
    total = metadata["total_results"]
    if total is not None and (type(total) is not int or total < 0):
        raise ValueError("total_results must be a nonnegative integer or null")
    for field in ("collection", "timespan"):
        if metadata[field] is not None and not isinstance(metadata[field], str):
            raise ValueError(field + " must be text or null")
    records = parse_ris(data, source=database)
    if total is not None and len(records) > total:
        raise ValueError("Imported record count exceeds the stated search result count")
    span = metadata["exported_range"]
    if span is not None:
        if (not isinstance(span, list) or len(span) != 2 or
                any(type(x) is not int for x in span) or span[0] < 1 or span[1] < span[0]):
            raise ValueError("exported_range must be [first, last] with one-based inclusive positions, or null")
        if span[1] - span[0] + 1 != len(records):
            raise ValueError("Exported range does not match the number of RIS records")
        if total is not None and span[1] > total:
            raise ValueError("Exported range exceeds the stated search result count")
    complete = total is not None and ((total == 0 and len(records) == 0) or span == [1, total])
    run.metadata.update({
        "access_mode": "authorized_export", "original_search": metadata,
        "query_origin": "user_supplied_search_history", "search_executed_by_program": False,
        "returned_count": len(records), "retrieval_complete": None,
        "coverage": "user_reported_complete" if complete else "partial_or_unverified",
    })
    run.event({"event": "imported", "database": database, "records": len(records),
               "platform": metadata["platform"], "search_executed_by_program": False})
    return records
