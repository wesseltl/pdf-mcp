"""Tests for the PDF extractor. Builds its own PDFs so it runs anywhere."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pdf_mcp import extractor


def _table(data):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle
    t = Table(data)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    return t


def make_pdf(path):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    doc = SimpleDocTemplate(path, pagesize=A4)
    styles = getSampleStyleSheet()
    data = [["Item", "Qty", "Price"], ["Widget", "3", "12.50"],
            ["Gadget", "1", "40.00"], ["Bolt", "10", "0.25"]]
    doc.build([Paragraph("Invoice #2024-001", styles["Title"]), Spacer(1, 12), _table(data)])


def make_multipage_pdf(path, repeat_header=True):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
    doc = SimpleDocTemplate(path, pagesize=A4)
    styles = getSampleStyleSheet()
    first_page = [["Test", "Value"], ["pH", "7.2"], ["Glucose", "5.1"]]
    second_page = [["Test", "Value"], ["Sodium", "140"], ["Potassium", "4.2"]]
    if not repeat_header:
        second_page = second_page[1:]
    doc.build([
        Paragraph("Lab results", styles["Title"]), Spacer(1, 12), _table(first_page),
        PageBreak(),
        Paragraph("Lab results continued", styles["Title"]), Spacer(1, 12), _table(second_page),
    ])


def make_two_tables_one_page_pdf(path):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    doc = SimpleDocTemplate(path, pagesize=A4)
    styles = getSampleStyleSheet()
    doc.build([
        Paragraph("Two separate tables", styles["Title"]),
        Spacer(1, 12),
        _table([["Analyte", "Value"], ["pH", "7.2"]]),
        Spacer(1, 36),
        _table([["Analyte", "Value"], ["Sodium", "140"]]),
    ])


def make_blank_pdf(path):
    from reportlab.pdfgen import canvas
    pdf = canvas.Canvas(path)
    pdf.showPage()
    pdf.save()


def make_text_only_pdf(path):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate
    doc = SimpleDocTemplate(path, pagesize=A4)
    doc.build([Paragraph("No structured table on this page", getSampleStyleSheet()["BodyText"])])


class TestExtractor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = os.path.join(tempfile.mkdtemp(), "invoice.pdf")
        make_pdf(cls.path)

    def test_page_count(self):
        self.assertEqual(extractor.page_count(self.path), 1)

    def test_extract_text(self):
        r = extractor.extract_text(self.path)
        self.assertEqual(r["n_pages"], 1)
        self.assertIn("Invoice #2024-001", r["pages"][0]["text"])

    def test_extract_tables(self):
        r = extractor.extract_tables(self.path)
        self.assertEqual(r["n_tables"], 1)
        table = r["tables"][0]
        rows = table["rows"]
        self.assertEqual(rows[0], ["Item", "Qty", "Price"])
        self.assertEqual(rows[1], ["Widget", "3", "12.50"])
        self.assertEqual(len(rows), 4)
        self.assertEqual(table["index"], 0)
        self.assertEqual(len(table["bbox"]), 4)
        evidence = table["cell_provenance"][1][0]
        self.assertEqual(
            (evidence["page"], evidence["table_index"], evidence["row"], evidence["column"]),
            (1, 0, 1, 0),
        )
        self.assertEqual(len(evidence["bbox"]), 4)

    def test_table_to_csv(self):
        csv = extractor.table_to_csv(self.path)
        self.assertIn("Item,Qty,Price", csv)
        self.assertIn("Bolt,10,0.25", csv)

    def test_extract_text_specific_page(self):
        r = extractor.extract_text(self.path, page=1)
        self.assertEqual(r["n_pages"], 1)

    def test_page_number_must_be_valid_and_one_based(self):
        for invalid in (0, 2, -1, True, 1.5):
            with self.subTest(page=invalid):
                with self.assertRaises(ValueError):
                    extractor.extract_text(self.path, page=invalid)
                with self.assertRaises(ValueError):
                    extractor.extract_tables(self.path, page=invalid)

    def test_blank_pdf_reports_ocr_warning(self):
        path = os.path.join(tempfile.mkdtemp(), "blank.pdf")
        make_blank_pdf(path)
        text_result = extractor.extract_text(path)
        table_result = extractor.extract_tables(path)
        self.assertTrue(any("OCR" in warning for warning in text_result["warnings"]))
        self.assertTrue(any("OCR" in warning for warning in table_result["warnings"]))

    def test_text_only_pdf_reports_no_tables(self):
        path = os.path.join(tempfile.mkdtemp(), "text-only.pdf")
        make_text_only_pdf(path)
        result = extractor.extract_tables(path)
        self.assertEqual(result["n_tables"], 0)
        self.assertTrue(result["warnings"])

    def test_table_index_must_exist(self):
        with self.assertRaises(ValueError):
            extractor.table_to_csv(self.path, index=1)

    def test_assessment_flags_ragged_and_empty(self):
        from pdf_mcp.extractor import _assess
        self.assertTrue(_assess([["A", "B"], ["1", "2"]])["looks_clean"])
        self.assertFalse(_assess([["A", "B", "C"], ["x", "y"]])["looks_clean"])
        self.assertFalse(_assess([["A", "B"], ["", ""]])["looks_clean"])

    def test_stitch_multipage_merges_and_drops_repeated_header(self):
        from pdf_mcp.extractor import _stitch_multipage
        page1 = {"page": 1, "rows": [["Item", "Qty"], ["Widget", "3"]], "column_count": 2,
                 "cell_provenance": [[{"page": 1}], [{"page": 1}]],
                 "warnings": [], "looks_clean": True}
        page2 = {"page": 2, "rows": [["Item", "Qty"], ["Bolt", "10"]], "column_count": 2,
                 "cell_provenance": [[{"page": 2}], [{"page": 2}]],
                 "warnings": [], "looks_clean": True}
        merged = _stitch_multipage([page1, page2])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["merged_from_pages"], [1, 2])
        self.assertEqual(merged[0]["rows"],
                         [["Item", "Qty"], ["Widget", "3"], ["Bolt", "10"]])
        self.assertEqual([row[0]["page"] for row in merged[0]["cell_provenance"]], [1, 1, 2])
        self.assertIsNone(merged[0]["bbox"])
        self.assertEqual([item["page"] for item in merged[0]["bboxes_by_page"]], [1, 2])
        self.assertFalse(merged[0]["looks_clean"])

    def test_stitch_multipage_merges_without_repeated_header(self):
        from pdf_mcp.extractor import _stitch_multipage
        page1 = {"page": 1, "rows": [["Item", "Qty"], ["Widget", "3"]], "column_count": 2,
                 "warnings": [], "looks_clean": True}
        page2 = {"page": 2, "rows": [["Bolt", "10"]], "column_count": 2,
                 "warnings": [], "looks_clean": True}
        merged = _stitch_multipage([page1, page2])
        self.assertEqual(merged[0]["rows"],
                         [["Item", "Qty"], ["Widget", "3"], ["Bolt", "10"]])

    def test_stitch_leaves_mismatched_column_tables_separate(self):
        from pdf_mcp.extractor import _stitch_multipage
        a = {"page": 1, "rows": [["A", "B"]], "column_count": 2, "warnings": [], "looks_clean": True}
        b = {"page": 2, "rows": [["A", "B", "C"]], "column_count": 3, "warnings": [], "looks_clean": True}
        self.assertEqual(len(_stitch_multipage([a, b])), 2)

    def test_stitch_leaves_same_page_tables_separate(self):
        from pdf_mcp.extractor import _stitch_multipage
        a = {"page": 1, "rows": [["A", "B"], ["1", "2"]], "column_count": 2,
             "warnings": [], "looks_clean": True}
        b = {"page": 1, "rows": [["A", "B"], ["3", "4"]], "column_count": 2,
             "warnings": [], "looks_clean": True}
        self.assertEqual(len(_stitch_multipage([a, b])), 2)

    def test_extract_tables_keeps_multipage_pdf_separate_by_default(self):
        path = os.path.join(tempfile.mkdtemp(), "multipage.pdf")
        make_multipage_pdf(path)
        r = extractor.extract_tables(path)
        self.assertEqual(r["n_tables"], 2)
        self.assertEqual([t["page"] for t in r["tables"]], [1, 2])

    def test_extract_tables_merges_multipage_pdf_and_flags_heuristic(self):
        path = os.path.join(tempfile.mkdtemp(), "multipage.pdf")
        make_multipage_pdf(path)
        r = extractor.extract_tables(path, merge_multipage=True)
        self.assertEqual(r["n_tables"], 1)
        table = r["tables"][0]
        self.assertEqual(table["merged_from_pages"], [1, 2])
        self.assertEqual(table["rows"],
                         [["Test", "Value"], ["pH", "7.2"], ["Glucose", "5.1"],
                          ["Sodium", "140"], ["Potassium", "4.2"]])
        self.assertFalse(table["looks_clean"])
        self.assertTrue(any("merged across pages" in w for w in table["warnings"]))

    def test_extract_tables_merges_multipage_pdf_without_repeated_header(self):
        path = os.path.join(tempfile.mkdtemp(), "multipage-no-header.pdf")
        make_multipage_pdf(path, repeat_header=False)
        r = extractor.extract_tables(path, merge_multipage=True)
        self.assertEqual(r["n_tables"], 1)
        self.assertEqual(r["tables"][0]["rows"],
                         [["Test", "Value"], ["pH", "7.2"], ["Glucose", "5.1"],
                          ["Sodium", "140"], ["Potassium", "4.2"]])

    def test_extract_tables_does_not_merge_same_page_tables(self):
        path = os.path.join(tempfile.mkdtemp(), "same-page.pdf")
        make_two_tables_one_page_pdf(path)
        r = extractor.extract_tables(path, merge_multipage=True)
        self.assertEqual(r["n_tables"], 2)


if __name__ == "__main__":
    unittest.main()
