from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ax_scanner.models import DataType
from ax_scanner.parsers import parse_file
from scripts.create_mini_dataset import create_mini_dataset


class ParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        cls.root = create_mini_dataset(Path(cls._temp.name) / "mini_company")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    def test_txt_parser(self) -> None:
        parsed = parse_file(self.root / "docs" / "contact.txt", "FILE_txt")
        self.assertEqual(parsed.parser, "txt")
        self.assertIn("owner@example.com", parsed.text)

    def test_pdf_parser_and_ocr_required_detection(self) -> None:
        readable = parse_file(self.root / "docs" / "shipping_policy.pdf", "FILE_pdf")
        scanned = parse_file(self.root / "scans" / "invoice_scan.pdf", "FILE_scan")
        self.assertIn("Shipping delay compensation", readable.text)
        self.assertFalse(readable.requires_ocr)
        self.assertTrue(scanned.requires_ocr)
        self.assertEqual(scanned.unreadable_reason, "PDF_TEXT_BELOW_OCR_THRESHOLD")

    def test_docx_parser_reads_paragraphs_and_tables(self) -> None:
        parsed = parse_file(self.root / "docs" / "warehouse_guide.docx", "FILE_docx")
        self.assertIn("Warehouse operating guide", parsed.text)
        self.assertIn("C013 | Hanbit Trading", parsed.text)
        self.assertEqual(parsed.metadata["table_count"], 1)

    def test_csv_parser_profiles_structure(self) -> None:
        parsed = parse_file(self.root / "tables" / "customers.csv", "FILE_csv")
        table = parsed.tables[0]
        self.assertEqual(table.sheet_name, "CSV")
        self.assertEqual(table.row_count, 2)
        self.assertEqual(table.column_count, 4)
        self.assertEqual(table.column_names, ["customer_id", "customer_name", "email", "active"])
        by_name = {column.name: column for column in table.columns}
        self.assertEqual(by_name["active"].inferred_type, DataType.BOOLEAN)
        self.assertEqual(by_name["email"].null_ratio, 0.5)

    def test_xlsx_parser_profiles_sheets_types_nulls_and_merges(self) -> None:
        parsed = parse_file(self.root / "tables" / "orders.xlsx", "FILE_xlsx")
        by_sheet = {table.sheet_name: table for table in parsed.tables}
        orders = by_sheet["Orders"]
        self.assertEqual(orders.row_count, 3)
        self.assertEqual(orders.column_count, 5)
        by_name = {column.name: column for column in orders.columns}
        self.assertEqual(by_name["amount"].inferred_type, DataType.INTEGER)
        self.assertAlmostEqual(by_name["memo"].null_ratio, 2 / 3)
        self.assertTrue(by_sheet["MergedNote"].merged_cell_present)
        self.assertEqual(by_sheet["MergedNote"].merged_ranges, ["A1:B1"])


if __name__ == "__main__":
    unittest.main()

