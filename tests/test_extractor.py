"""Tests for the PDF extractor. Builds its own PDF so it runs anywhere."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pdf_mcp import extractor


def make_pdf(path):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    doc = SimpleDocTemplate(path, pagesize=A4)
    styles = getSampleStyleSheet()
    data = [["Item", "Qty", "Price"], ["Widget", "3", "12.50"],
            ["Gadget", "1", "40.00"], ["Bolt", "10", "0.25"]]
    t = Table(data)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    doc.build([Paragraph("Invoice #2024-001", styles["Title"]), Spacer(1, 12), t])


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
        rows = r["tables"][0]["rows"]
        self.assertEqual(rows[0], ["Item", "Qty", "Price"])
        self.assertEqual(rows[1], ["Widget", "3", "12.50"])
        self.assertEqual(len(rows), 4)

    def test_table_to_csv(self):
        csv = extractor.table_to_csv(self.path)
        self.assertIn("Item,Qty,Price", csv)
        self.assertIn("Bolt,10,0.25", csv)

    def test_extract_text_specific_page(self):
        r = extractor.extract_text(self.path, page=1)
        self.assertEqual(r["n_pages"], 1)


    def test_assessment_flags_ragged_and_empty(self):
        from pdf_mcp.extractor import _assess
        self.assertTrue(_assess([["A","B"],["1","2"]])["looks_clean"])          # clean
        self.assertFalse(_assess([["A","B","C"],["x","y"]])["looks_clean"])     # ragged
        self.assertFalse(_assess([["A","B"],["",""]])["looks_clean"])          # mostly empty

    def test_stitch_multipage_merges_and_drops_repeated_header(self):
        from pdf_mcp.extractor import _stitch_multipage
        page1 = {"page": 1, "rows": [["Item", "Qty"], ["Widget", "3"]], "column_count": 2,
                 "warnings": [], "looks_clean": True}
        page2 = {"page": 2, "rows": [["Item", "Qty"], ["Bolt", "10"]], "column_count": 2,
                 "warnings": [], "looks_clean": True}
        merged = _stitch_multipage([page1, page2])
        self.assertEqual(len(merged), 1)                          # joined into one
        self.assertEqual(merged[0]["merged_from_pages"], [1, 2])
        # header appears once, both data rows present
        self.assertEqual(merged[0]["rows"],
                         [["Item", "Qty"], ["Widget", "3"], ["Bolt", "10"]])
        self.assertFalse(merged[0]["looks_clean"])                # flagged as a heuristic

    def test_stitch_leaves_mismatched_column_tables_separate(self):
        from pdf_mcp.extractor import _stitch_multipage
        a = {"page": 1, "rows": [["A", "B"]], "column_count": 2, "warnings": [], "looks_clean": True}
        b = {"page": 2, "rows": [["A", "B", "C"]], "column_count": 3, "warnings": [], "looks_clean": True}
        self.assertEqual(len(_stitch_multipage([a, b])), 2)       # different widths, not merged



if __name__ == "__main__":
    unittest.main()
