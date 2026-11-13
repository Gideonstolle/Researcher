"""Small, loss-aware RIS reader and citation exporters (Python standard library).

The raw RIS file remains the archival source. ``raw_tags`` also retains every
parsed tag, including repeated and unfamiliar tags; normalized fields are a
convenience, not a claim that all RIS dialects have identical semantics.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


_TAG = re.compile(r"^([A-Z0-9]{2})  -(?: ?(.*))?$")
_TYPE_TO_NORMALIZED = {
    "JOUR": "article", "EJOUR": "article", "JFULL": "article",
    "MGZN": "article", "BOOK": "book", "EBOOK": "book",
}


def _first(tags: dict, *names: str) -> str:
    for name in names:
        for value in tags.get(name, []):
            if value.strip():
                return value.strip()
    return ""


def _author(value: str) -> dict:
    """Only split explicit comma-separated names; never infer surname order."""
    value = value.strip()
    if "," in value:
        family, given = value.split(",", 1)
        if family.strip() and given.strip():
            return {"family": family.strip(), "given": given.strip()}
    return {"literal": value}


def _normalize(tags: dict, source: str) -> dict:
    canonical = json.dumps(tags, ensure_ascii=False, sort_keys=True).encode("utf-8")
    accession = _first(tags, "AN")
    record = {
        "id": f"{source}:{accession}" if accession else (
            f"{source}:ris:{hashlib.sha256(canonical).hexdigest()[:20]}"
        ),
        "source": source,
        "type": _TYPE_TO_NORMALIZED.get(_first(tags, "TY"), _first(tags, "TY")),
        "authors": [_author(x) for x in tags.get("AU", tags.get("A1", [])) if x.strip()],
        "keywords": [x for x in tags.get("KW", []) if x.strip()],
        "raw_tags": tags,
    }
    fields = {
        "title": _first(tags, "TI", "T1", "CT"),
        "date": _first(tags, "PY", "Y1", "DA"),
        "journal": "" if record["type"] == "CHAP" else _first(tags, "JF", "JO", "T2", "JA"),
        "booktitle": _first(tags, "T2") if record["type"] == "CHAP" else "",
        "volume": _first(tags, "VL"),
        "issue": _first(tags, "IS"),
        "doi": _first(tags, "DO"),
        "url": _first(tags, "UR"),
        "abstract": _first(tags, "AB", "N2"),
        "accession": accession,
    }
    if fields["doi"]:
        fields["doi"] = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", fields["doi"], flags=re.I)
    start, end = _first(tags, "SP"), _first(tags, "EP")
    fields["pages"] = f"{start}-{end}" if start and end and start != end else start or end
    year = re.match(r"^(\d{4})(?:\D|$)", fields["date"])
    if year:
        fields["year"] = year.group(1)
    record.update({key: value for key, value in fields.items() if value})
    return record


def parse_ris(data: bytes, source: str) -> list[dict]:
    """Read UTF-8 RIS; reject broken records rather than silently dropping data.

    UTF-8 BOM and CRLF are accepted. Untagged lines within a record continue the
    preceding field. A malformed tag delimiter raises instead of being swallowed
    as continuation text. No unknown record type is converted into a journal.
    """
    if not source.strip():
        raise ValueError("RIS source/database is required")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("RIS must be UTF-8. Re-export or convert the file to UTF-8; keep the original.") from exc
    if "\x00" in text:
        raise ValueError("RIS contains NUL bytes; check that the file is a UTF-8 RIS export")
    records, tags, last_tag = [], None, None
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        match = _TAG.match(line)
        if match:
            tag, value = match.group(1), match.group(2) or ""
            if tag == "TY":
                if tags is not None:
                    raise ValueError(f"RIS line {number}: new TY before previous ER (truncated record)")
                if not value.strip():
                    raise ValueError(f"RIS line {number}: TY needs a record type")
                tags, last_tag = {"TY": [value.strip()]}, "TY"
            elif tags is None:
                raise ValueError(f"RIS line {number}: expected TY at the start of a record")
            elif tag == "ER":
                if value.strip():
                    raise ValueError(f"RIS line {number}: ER must not contain a value")
                records.append(_normalize(tags, source))
                tags, last_tag = None, None
            else:
                tags.setdefault(tag, []).append(value)
                last_tag = tag
        elif tags is not None and last_tag != "TY":
            if re.match(r"^[A-Z0-9]{2}\s*-", line):
                raise ValueError(f"RIS line {number}: malformed tag delimiter; expected 'XX  - value'")
            tags[last_tag][-1] += "\n" + line
        else:
            raise ValueError(f"RIS line {number}: text outside a valid RIS field")
    if tags is not None:
        raise ValueError("RIS ended before ER; the final record is truncated")
    return records


def _flat(value) -> str:
    """Flatten all line breaks to avoid turning metadata into RIS structure."""
    return " ".join(str(value).split())


def _bib(value) -> str:
    replacements = {
        "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}",
        "&": r"\&", "%": r"\%", "_": r"\_", "#": r"\#",
        "$": r"\$", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in _flat(value))


def _author_ris(author: dict) -> str:
    if "literal" in author:
        return _flat(author["literal"])
    family, given = _flat(author.get("family", "")), _flat(author.get("given", ""))
    return f"{family}, {given}" if family and given else family or given


def _author_bib(author: dict) -> str:
    if "literal" in author:
        return "{" + _bib(author["literal"]) + "}"
    family, given = _bib(author.get("family", "")), _bib(author.get("given", ""))
    # Protect surname particles and family names containing the token "and".
    return "{" + family + "}, {" + given + "}" if family and given else "{" + (family or given) + "}"


def write_exports(records: list[dict], output_dir: Path) -> None:
    """Export RIS and BibTeX with stable keys and no invented missing fields."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ris, bib, key_counts = [], [], {}
    for record in records:
        kind = record.get("type", "")
        ris_type = {"article": "JOUR", "book": "BOOK"}.get(kind, kind)
        if not re.fullmatch(r"[A-Z0-9]{2,8}", str(ris_type)):
            ris_type = "GEN"
        lines = [f"TY  - {ris_type}"]

        def add(tag: str, value) -> None:
            if value is not None and _flat(value):
                lines.append(f"{tag}  - {_flat(value)}")

        add("TI", record.get("title"))
        for author in record.get("authors", []):
            add("AU", _author_ris(author))
        for tag, field in [("JF", "journal"), ("T2", "booktitle"), ("VL", "volume"), ("IS", "issue"), ("DO", "doi"),
                           ("UR", "url"), ("AB", "abstract"), ("AN", "accession"), ("DB", "source")]:
            add(tag, record.get(field))
        add("PY", record.get("date") or record.get("year"))
        # Keep complex page ranges/e-locators intact in SP rather than guessing.
        add("SP", record.get("pages"))
        for keyword in record.get("keywords", []):
            add("KW", keyword)
        if record.get("pmid"):
            add("N1", "PMID: " + str(record["pmid"]))
        lines.append("ER  -")
        ris.append("\n".join(lines))

        identity = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        key_base = "ref_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        key_counts[key_base] = key_counts.get(key_base, 0) + 1
        key = key_base if key_counts[key_base] == 1 else f"{key_base}_{key_counts[key_base]}"
        # RIS THES does not establish whether a thesis is doctoral or master's.
        bib_kind = {"article": "article", "book": "book", "CHAP": "incollection", "CONF": "inproceedings",
                    "RPRT": "techreport"}.get(kind, "misc")
        fields = []
        if record.get("title"):
            fields.append("  title = {{" + _bib(record["title"]) + "}}")
        authors = [_author_bib(x) for x in record.get("authors", []) if _author_ris(x)]
        if authors:
            fields.append("  author = {" + " and ".join(authors) + "}")
        for field in ("year", "journal", "booktitle", "volume", "doi", "url", "abstract"):
            if record.get(field):
                fields.append("  " + field + " = {" + _bib(record[field]) + "}")
        if record.get("issue"):
            fields.append("  number = {" + _bib(record["issue"]) + "}")
        if record.get("pages"):
            pages = re.sub(r"(?<=\d)[-–](?=\d)", "--", str(record["pages"]))
            fields.append("  pages = {" + _bib(pages) + "}")
        bib.append("@" + bib_kind + "{" + key + ",\n" + ",\n".join(fields) + "\n}")
    (output_dir / "citations.ris").write_text("\n\n".join(ris) + ("\n" if ris else ""), encoding="utf-8")
    (output_dir / "citations.bib").write_text("\n\n".join(bib) + ("\n" if bib else ""), encoding="utf-8")
