import re
import tempfile
import unittest
from pathlib import Path

from researcher.citations import parse_ris, write_exports


class RISImportTests(unittest.TestCase):
    def test_unicode_bom_repeated_unknown_tags_and_multiline(self):
        source = (
            "\ufeffTY  - JOUR\r\nTI  - Émotions & sleep\r\n"
            "AU  - García, María\r\nAU  - Research Consortium\r\n"
            "PY  - 2024/03/\r\nJF  - Journal\r\nSP  - 10\r\nEP  - 19\r\n"
            "AB  - First line\r\nsecond line\r\nKW  - mood\r\nKW  - sleep\r\n"
            "ZZ  - custom one\r\nZZ  - custom two\r\n"
            "AN  - WOS:000123\r\nDO  - https://doi.org/10.1/demo\r\nER  -\r\n"
        ).encode("utf-8")
        record, = parse_ris(source, "wos")
        self.assertEqual(record["authors"], [{"family": "García", "given": "María"}, {"literal": "Research Consortium"}])
        self.assertEqual(record["abstract"], "First line\nsecond line")
        self.assertEqual(record["raw_tags"]["ZZ"], ["custom one", "custom two"])
        self.assertEqual(record["keywords"], ["mood", "sleep"])
        self.assertEqual(record["pages"], "10-19")
        self.assertEqual(record["year"], "2024")
        self.assertEqual(record["date"], "2024/03/")
        self.assertEqual(record["accession"], "WOS:000123")
        self.assertNotIn("pmid", record)
        self.assertEqual(record["doi"], "10.1/demo")

    def test_aliases_and_missing_metadata_are_not_invented(self):
        record, = parse_ris(b"TY  - THES\nT1  - Thesis\nA1  - Mononym\nY1  - Spring 2020\nER  -\n", "psycinfo")
        self.assertEqual(record["type"], "THES")
        self.assertEqual(record["title"], "Thesis")
        self.assertEqual(record["authors"], [{"literal": "Mononym"}])
        self.assertNotIn("year", record)
        self.assertNotIn("doi", record)

    def test_bad_encoding_and_truncated_records_fail(self):
        for data in [b"TY  - JOUR\nTI  - x", b"TY  - JOUR\nTI  - x\nTY  - BOOK\nER  -\n",
                     b"TI  - x\nER  -\n", b"TY  - JOUR\nTI - bad\nER  -\n", b"TY  - JOUR\nTI  - \xff\nER  -\n"]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_ris(data, "psycinfo")

    def test_multiple_records_and_stable_ids(self):
        data = b"TY  - JOUR\nTI  - First\nER  -\n\nTY  - BOOK\nTI  - Second\nER  -\n"
        one = parse_ris(data, "psycinfo")
        self.assertEqual(len(one), 2)
        self.assertEqual(one, parse_ris(data, "psycinfo"))
        self.assertNotEqual(one[0]["id"], one[1]["id"])


class CitationExportTests(unittest.TestCase):
    def test_thesis_export_does_not_invent_a_doctorate(self):
        records = parse_ris(b"TY  - THES\nTI  - Synthetic thesis fixture\nER  -\n", "psycinfo")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_exports(records, root)
            bib = (root / "citations.bib").read_text()
            self.assertTrue(bib.startswith("@misc{"))
            self.assertNotIn("phdthesis", bib)
            self.assertIn("TY  - THES", (root / "citations.ris").read_text())

    def test_book_chapter_container_is_a_booktitle_not_a_journal(self):
        records = parse_ris(
            b"TY  - CHAP\nTI  - Synthetic chapter\nT2  - Synthetic edited book\nPY  - 2024\nER  -\n", "psycinfo"
        )
        self.assertEqual(records[0]["booktitle"], "Synthetic edited book")
        self.assertNotIn("journal", records[0])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_exports(records, root)
            bib = (root / "citations.bib").read_text()
            self.assertTrue(bib.startswith("@incollection{"))
            self.assertIn("booktitle = {Synthetic edited book}", bib)
            self.assertNotIn("journal =", bib)
            ris = (root / "citations.ris").read_bytes()
            self.assertIn(b"T2  - Synthetic edited book", ris)
            self.assertNotIn(b"JF  -", ris)
            imported, = parse_ris(ris, "psycinfo")
            self.assertEqual(imported["booktitle"], records[0]["booktitle"])
            self.assertEqual(imported["type"], "CHAP")

    def test_export_roundtrip_and_no_newline_injection(self):
        record = {
            "id": "pubmed:1", "source": "pubmed", "type": "article", "title": "A study\nER  -\nTY  - BOOK",
            "authors": [{"family": "García", "given": "María"}, {"literal": "Study Team"}],
            "journal": "Journal", "year": "2024", "doi": "10.1/example", "pages": "10-20", "pmid": "1",
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_exports([record], root)
            imported = parse_ris((root / "citations.ris").read_bytes(), "pubmed")
            self.assertEqual(len(imported), 1)
            self.assertEqual(imported[0]["title"], "A study ER - TY - BOOK")
            self.assertEqual(imported[0]["doi"], record["doi"])
            self.assertEqual(imported[0]["authors"], record["authors"])
            self.assertEqual(imported[0]["pages"], "10-20")
            self.assertIn("pages = {10--20}", (root / "citations.bib").read_text())

    def test_bibtex_escape_corporate_author_and_duplicate_keys(self):
        record = {"type": "article", "title": r"DNA {a} & 50% _# $ \ ~^", "authors": [{"literal": "A and B Study Group"}]}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_exports([record, record], root)
            first = (root / "citations.bib").read_bytes()
            text = first.decode()
            keys = re.findall(r"@article\{([^,]+),", text)
            self.assertEqual(len(keys), 2)
            self.assertEqual(len(set(keys)), 2)
            self.assertIn(r"title = {{DNA \{a\} \& 50\% \_\# \$ \textbackslash{} \textasciitilde{}\textasciicircum{}}}", text)
            self.assertIn("author = {{A and B Study Group}}", text)
            self.assertNotIn("year =", text)
            self.assertNotIn("doi =", text)
            write_exports([record, record], root)
            self.assertEqual(first, (root / "citations.bib").read_bytes())

    def test_empty_exports(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_exports([], root)
            self.assertEqual((root / "citations.ris").read_bytes(), b"")
            self.assertEqual((root / "citations.bib").read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
