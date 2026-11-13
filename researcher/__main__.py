"""Usage: python3 -m researcher --help."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .provenance import Run, json_bytes, verify


def parser():
    root = argparse.ArgumentParser(description="Logged literature searches and authorized RIS imports")
    sub = root.add_subparsers(dest="command", required=True)
    pubmed = sub.add_parser("pubmed", help="Execute an exact PubMed query through NCBI E-utilities")
    pubmed.add_argument("--query-file", type=Path, required=True)
    pubmed.add_argument("--max-records", type=int, default=100)
    pubmed.add_argument("--allow-partial", action="store_true", help="Explicitly permit a capped result subset")
    pubmed.add_argument("--sort", choices=("pub_date", "relevance"), default="pub_date")
    pubmed.add_argument("--out", type=Path, default=Path("runs"))
    wos = sub.add_parser("webofscience", help="Search Web of Science Starter API using an authorized API key")
    wos.add_argument("--query-file", type=Path, required=True)
    wos.add_argument("--max-records", type=int, default=50)
    wos.add_argument("--allow-partial", action="store_true")
    wos.add_argument("--collection", choices=("WOS",), default="WOS")
    wos.add_argument("--edition", help="Optional subscribed editions, e.g. WOS+SSCI; otherwise your API entitlement applies")
    wos.add_argument("--max-requests", type=int, default=10, help="Per-run request budget including retries; not a daily quota tracker")
    wos.add_argument("--out", type=Path, default=Path("runs"))
    imported = sub.add_parser("import", help="Import an authorized PsycINFO or Web of Science RIS export")
    imported.add_argument("--database", choices=("psycinfo", "webofscience"), required=True)
    imported.add_argument("--file", type=Path, required=True)
    imported.add_argument("--query-file", type=Path, required=True)
    imported.add_argument("--metadata", type=Path, required=True)
    imported.add_argument("--out", type=Path, default=Path("runs"))
    doctor = sub.add_parser("doctor", help="Check runtime and optionally perform a small logged database probe")
    doctor.add_argument("--online", action="store_true")
    doctor.add_argument("--database", choices=("pubmed", "webofscience"), default="pubmed")
    doctor.add_argument("--out", type=Path, default=Path("runs"))
    checked = sub.add_parser("verify", help="Check saved artifact checksums; not a cryptographic signature")
    checked.add_argument("run", type=Path)
    search = sub.add_parser("search", help="Choose a public source: execute PubMed or prepare an assisted Scholar search")
    search.add_argument("--engine", choices=("pubmed", "google-scholar"), default="pubmed")
    search.add_argument("--query-file", type=Path, required=True)
    search.add_argument("--max-records", type=int, help="PubMed cap (default 100); not a Scholar retrieval option")
    search.add_argument("--allow-partial", action="store_true")
    search.add_argument("--year-from", type=int)
    search.add_argument("--year-to", type=int)
    search.add_argument("--sort", choices=("pub_date", "relevance", "date"))
    search.add_argument("--out", type=Path, default=Path("runs"))
    scholar = sub.add_parser("scholar-plan", help="Prepare a Google Scholar link and observation form; does not execute a search")
    scholar.add_argument("--query-file", type=Path, required=True)
    scholar.add_argument("--year-from", type=int)
    scholar.add_argument("--year-to", type=int)
    scholar.add_argument("--sort", choices=("relevance", "date"), default="relevance")
    scholar.add_argument("--out", type=Path, default=Path("runs"))
    observed = sub.add_parser("scholar-record", help="Archive an actual assisted Google Scholar observation")
    observed.add_argument("--query-file", type=Path, required=True)
    observed.add_argument("--observation", type=Path, required=True)
    observed.add_argument("--evidence", type=Path, nargs="*", default=[])
    observed.add_argument("--out", type=Path, default=Path("runs"))
    review = sub.add_parser("review", help="Combine verified search runs into an evidence and candidate-gap workspace")
    review.add_argument("--runs", type=Path, nargs="+", required=True)
    review.add_argument("--question", required=True)
    review.add_argument("--out", type=Path, required=True, help="New review directory, e.g. private/reviews/play-v1")
    for command in (pubmed, wos, imported, search, scholar, observed):
        command.add_argument("--reason", help="Why this query or revision was run")
        command.add_argument("--parent-run", help="Prior run ID when refining a query or following citations")
    return root


def safe_error(error):
    message = str(error)
    from urllib.parse import quote, quote_plus
    for name in ("NCBI_API_KEY", "NCBI_EMAIL", "WOS_API_KEY"):
        secret = os.environ.get(name)
        if secret:
            for form in (secret, quote(secret, safe=""), quote_plus(secret)):
                message = message.replace(form, "[REDACTED]")
    return message


def main(argv=None):
    args = parser().parse_args(argv)
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required. Select a newer Python interpreter.", file=sys.stderr)
        return 2
    if args.command == "review":
        try:
            from .review import create_review
            report = create_review(args.runs, args.out, args.question)
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(safe_error(error), file=sys.stderr)
            return 1
        print(json.dumps(report, indent=2))
        return 0
    if args.command == "search":
        if args.engine == "pubmed":
            if args.year_from is not None or args.year_to is not None or args.sort == "date":
                print("For PubMed put dates in the exact query; use --sort pub_date or relevance.", file=sys.stderr)
                return 2
            args.command = "pubmed"
            args.sort = args.sort or "pub_date"
            args.max_records = 100 if args.max_records is None else args.max_records
        else:
            if args.allow_partial or args.max_records is not None or args.sort == "pub_date":
                print("Scholar prepares a link only; record the actual observed range later. Use --sort relevance or date.", file=sys.stderr)
                return 2
            args.command = "scholar-plan"
            args.sort = args.sort or "relevance"
    if args.command == "verify":
        try:
            count = verify(args.run)
        except (OSError, ValueError) as error:
            print(safe_error(error), file=sys.stderr)
            return 1
        print(f"Verified {count} saved artifacts in {args.run}")
        return 0
    if args.command == "doctor":
        report = {"python": sys.version.split()[0], "dependencies": "standard library only",
                  "working_directory": str(Path.cwd()),
                  "agent_instructions_present": Path("AGENTS.md").is_file(),
                  "ncbi_email_configured": bool(os.environ.get("NCBI_EMAIL")),
                  "ncbi_api_key_configured": bool(os.environ.get("NCBI_API_KEY")),
                  "wos_api_key_configured": bool(os.environ.get("WOS_API_KEY")),
                  "online_database": args.database,
                  "online_test": "requested" if args.online else "not_run"}
        print(json.dumps(report, indent=2))
        if not args.online:
            return 0
    database = (args.database if args.command in {"import", "doctor"} else
                "google-scholar" if args.command in {"scholar-plan", "scholar-record"} else args.command)
    run = Run(args.out, database)
    try:
        if args.command == "doctor":
            query_bytes = (b'TI=(psychology) AND PY=2020' if database == "webofscience"
                           else b'psychology[Title] AND 2020[Date - Publication]')
            run.metadata["purpose"] = "connectivity_smoke_test_not_a_review"
        else:
            query_bytes = args.query_file.read_bytes()
        # Preserve even BOM/CRLF bytes in the snapshot; reject BOM instead of silently editing the query.
        run.write_bytes("query.txt", query_bytes)
        query = query_bytes.decode("utf-8")
        if query.startswith("\ufeff"):
            raise ValueError("Save the query as UTF-8 without a byte-order mark")
        if not query.strip():
            raise ValueError("Query file must contain the actual nonempty search string")
        run.metadata["query"] = query
        run.metadata["search_reason"] = getattr(args, "reason", None)
        run.metadata["parent_run_id"] = getattr(args, "parent_run", None)
        run.event({"event": "query_recorded", "query": query})
        if args.command == "scholar-plan":
            from .scholar import prepare
            records = prepare(run, query, year_from=args.year_from, year_to=args.year_to, sort=args.sort)
            status = "planned"
        elif args.command == "scholar-record":
            from .scholar import record
            records = record(run, query, args.observation.read_bytes(), evidence_files=args.evidence)
            status = run.metadata["observation_status"]
        elif args.command == "import":
            from .imports import import_export
            records = import_export(run, database, args.file.read_bytes(), args.metadata.read_bytes())
            status = "imported"
        elif database == "webofscience":
            from .webofscience import search
            records = search(run, query,
                             max_records=1 if args.command == "doctor" else args.max_records,
                             allow_partial=True if args.command == "doctor" else args.allow_partial,
                             api_key=os.environ.get("WOS_API_KEY"),
                             collection="WOS" if args.command == "doctor" else args.collection,
                             edition=None if args.command == "doctor" else args.edition,
                             max_requests=3 if args.command == "doctor" else args.max_requests)
            status = "complete" if run.metadata.get("retrieval_complete") else "partial"
        else:
            from .pubmed import search
            records = search(run, query,
                             max_records=1 if args.command == "doctor" else args.max_records,
                             allow_partial=True if args.command == "doctor" else args.allow_partial,
                             email=os.environ.get("NCBI_EMAIL"), api_key=os.environ.get("NCBI_API_KEY"),
                             sort="pub_date" if args.command == "doctor" else args.sort)
            status = "complete" if run.metadata.get("retrieval_complete") else "partial"
        run.write_bytes("records.json", json_bytes(records))
        from .citations import write_exports
        write_exports(records, run.directory)
        run.finish(status)
        print(json.dumps({"run_directory": str(run.directory), "status": status,
                          "records": len(records),
                          **({"search_url": run.metadata["search_url"]} if "search_url" in run.metadata else {})}, indent=2))
        return 0
    except (Exception, KeyboardInterrupt) as error:
        message = safe_error(error) or type(error).__name__
        run.finish("failed", message)
        print(json.dumps({"run_directory": str(run.directory), "status": "failed", "error": message}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

