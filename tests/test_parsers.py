from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from ax_scanner.models import DataType
from ax_scanner.ocr import OcrCapability, OcrPageResult
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
        self.assertEqual(scanned.metadata["ocr_status"], "UNAVAILABLE")

    def test_legacy_pdf_mode_preserves_frozen_scanner_metadata(self) -> None:
        parsed = parse_file(
            self.root / "docs" / "shipping_policy.pdf",
            "FILE_pdf_legacy",
            pdf_enhancements=False,
        )
        self.assertEqual(
            set(parsed.metadata),
            {"page_count", "non_whitespace_char_count", "ocr_threshold"},
        )
        self.assertEqual(parsed.tables, [])

    def test_pdf_table_is_profiled_without_breaking_text_extraction(self) -> None:
        path = self.root / "docs" / "orders-table.pdf"
        document = SimpleDocTemplate(str(path))
        table = Table([
            ["order_id", "amount", "memo"],
            ["A-1", "12000", "정상"],
            ["A-2", "", "확인 필요"],
        ])
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ]))
        document.build([table])

        parsed = parse_file(path, "FILE_pdf_table")
        self.assertGreaterEqual(len(parsed.tables), 1)
        profiled = parsed.tables[0]
        self.assertEqual(profiled.sheet_name, "PDF p1 table 1")
        self.assertEqual(profiled.column_names, ["order_id", "amount", "memo"])
        self.assertEqual(profiled.row_count, 2)
        self.assertAlmostEqual(
            next(column for column in profiled.columns if column.name == "amount").null_ratio,
            0.5,
        )
        self.assertEqual(parsed.metadata["pdf_table_extraction_status"], "COMPLETED")

    def test_scanned_pdf_uses_optional_ocr_and_records_confidence(self) -> None:
        scanned_path = self.root / "scans" / "invoice_scan.pdf"
        with (
            patch(
                "ax_scanner.parsers.pdf.detect_ocr_capability",
                return_value=OcrCapability(True, "Tesseract test", ("eng", "kor")),
            ),
            patch(
                "ax_scanner.parsers.pdf.ocr_pdf_pages",
                return_value=[OcrPageResult(1, "Invoice total amount is 12000 KRW", 91.4)],
            ),
        ):
            parsed = parse_file(scanned_path, "FILE_scan_ocr")
        self.assertFalse(parsed.requires_ocr)
        self.assertIn("Invoice total amount", parsed.text)
        self.assertEqual(parsed.metadata["ocr_status"], "COMPLETED")
        self.assertEqual(parsed.metadata["ocr_processed_page_numbers"], [1])
        self.assertEqual(parsed.metadata["ocr_mean_confidence"], 91.4)

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
