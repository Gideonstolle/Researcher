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
    database = args.database if args.command in {"import", "doctor"} else args.command
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
        run.event({"event": "query_recorded", "query": query})
        if args.command == "import":
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
                             email=os.environ.get("NCBI_EMAIL"), api_key=os.environ.get("NCBI_API_KEY"))
            status = "complete" if run.metadata.get("retrieval_complete") else "partial"
        run.write_bytes("records.json", json_bytes(records))
        from .citations import write_exports
        write_exports(records, run.directory)
        run.finish(status)
        print(json.dumps({"run_directory": str(run.directory), "status": status,
                          "records": len(records)}, indent=2))
        return 0
    except (Exception, KeyboardInterrupt) as error:
        message = safe_error(error) or type(error).__name__
        run.finish("failed", message)
        print(json.dumps({"run_directory": str(run.directory), "status": "failed", "error": message}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
