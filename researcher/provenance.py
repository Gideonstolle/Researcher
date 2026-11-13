"""Run directories and checksums. Runs never overwrite an earlier run."""
from __future__ import annotations

import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from . import __version__


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class Run:
    def __init__(self, output_root, database):
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
        self.directory = Path(output_root) / run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.metadata = {
            "schema_version": 1, "run_id": run_id, "database": database,
            "started_at": utcnow(), "status": "running", "program_version": __version__,
            "python_version": platform.python_version(),
            "source_sha256": {p.name: sha256(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))},
        }
        self.write_bytes("manifest.json", json_bytes(self.metadata))
        self.event({"event": "started", "database": database})

    def write_bytes(self, relative_name, data):
        path = self.directory / relative_name
        if not path.resolve().is_relative_to(self.directory.resolve()):
            raise ValueError("Run artifact path must remain inside its run directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def event(self, value):
        with (self.directory / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"timestamp": utcnow(), **value}, ensure_ascii=False) + "\n")

    def finish(self, status, error=None):
        self.metadata.update(status=status, finished_at=utcnow())
        if error is not None:
            self.metadata["error"] = error
        self.event({"event": "finished", "status": status, **({"error": error} if error else {})})
        self.write_bytes("manifest.json", json_bytes(self.metadata))
        hashes = {str(p.relative_to(self.directory)): sha256(p.read_bytes())
                  for p in sorted(self.directory.rglob("*"))
                  if p.is_file() and p.name != "checksums.json"}
        self.write_bytes("checksums.json", json_bytes(hashes))


def verify(directory):
    directory = Path(directory).resolve()
    hashes = json.loads((directory / "checksums.json").read_text(encoding="utf-8"))
    if not isinstance(hashes, dict) or not {"manifest.json", "events.jsonl"}.issubset(hashes):
        raise ValueError("Invalid or incomplete checksum inventory")
    failures = []
    for name, expected in hashes.items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory):
            failures.append(name + ": unsafe path")
        elif not path.is_file() or sha256(path.read_bytes()) != expected:
            failures.append(name + ": missing or changed")
    actual = {str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file()}
    failures.extend(name + ": untracked artifact" for name in sorted(actual - set(hashes) - {"checksums.json"}))
    if failures:
        raise ValueError("Checksum verification failed: " + "; ".join(failures))
    return len(hashes)
