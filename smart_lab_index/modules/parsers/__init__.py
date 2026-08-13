"""Normalized built-in document parser modules."""

from smart_lab_index.modules.parsers.csv_parser import CsvParser
from smart_lab_index.modules.parsers.docx_parser import DocxParser
from smart_lab_index.modules.parsers.pdf_parser import PdfParser
from smart_lab_index.modules.parsers.text_parser import TextParser
from smart_lab_index.modules.parsers.xlsx_parser import XlsxParser

__all__ = ["CsvParser", "DocxParser", "PdfParser", "TextParser", "XlsxParser"]
