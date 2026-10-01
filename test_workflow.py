from pathlib import Path
import tempfile
import unittest

from workflow import load_source, lookup, normalize_gtin, project


class MatchingTests(unittest.TestCase):
    def test_equivalent_upc_ean_and_gtin14(self):
        self.assertEqual(normalize_gtin("036000291452"), "00036000291452")
        self.assertEqual(normalize_gtin("0036000291452"), "00036000291452")
        self.assertEqual(normalize_gtin("00036000291452"), "00036000291452")

    def test_invalid_values_are_not_silently_repaired(self):
        for value in ("036000291453", "03600029145", "000000000000", "１２３４５６７８９０１２", "12345670", 36000291452):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_gtin(value)

    def test_zero_and_multiple_candidates(self):
        rows = [{"ttb_id": ident, "gtins_json": '["00036000291452"]'} for ident in ("a", "b")]
        self.assertEqual([r["ttb_id"] for r in lookup(rows, "036000291452")], ["a", "b"])
        self.assertEqual(lookup(rows, "4006381333931"), [])

    @staticmethod
    def source_fixture():
        return {
            "cola.csv": [{"TTB_ID": "approval-a", "BRAND_NAME": "Example",
                          "PRODUCT_NAME": "", "PRODUCT_TYPE": "wine",
                          "PERMIT_NUMBER": "", "APPROVAL_DATE": "2026-08-13"}],
            "cola_image.csv": [{"TTB_IMAGE_ID": "image-a", "TTB_ID": "approval-a"}],
            "cola_image_barcode.csv": [
                {"TTB_ID": "approval-a", "TTB_IMAGE_ID": "image-a",
                 "BARCODE_TYPE": "upca", "BARCODE_VALUE": "036000291452"},
                {"TTB_ID": "approval-a", "TTB_IMAGE_ID": "image-a",
                 "BARCODE_TYPE": "qrcode", "BARCODE_VALUE": "036000291452"},
                {"TTB_ID": "approval-a", "TTB_IMAGE_ID": "image-a",
                 "BARCODE_TYPE": "upca", "BARCODE_VALUE": "036000291453"},
            ],
        }

    def test_symbology_and_checksum_gate_preserve_raw_evidence(self):
        rows, decisions = project(self.source_fixture(), "snapshot-time")
        self.assertEqual(decisions, {"accepted_code_rows": 1,
                                    "invalid_check_digit_or_digits": 1,
                                    "unsupported_symbology": 1})
        self.assertEqual(rows[0]["product_name"], "")
        self.assertEqual(rows[0]["gtins_json"], '["00036000291452"]')
        self.assertIn('"value":"036000291452"', rows[0]["barcode_evidence_json"])
        self.assertEqual(rows[0]["source_generated_at"], "snapshot-time")

    def test_broken_image_join_is_rejected(self):
        tables = self.source_fixture()
        tables["cola_image.csv"][0]["TTB_ID"] = "other-approval"
        with self.assertRaisesRegex(ValueError, "broken approval/image join"):
            project(tables, "snapshot-time")

    def test_corrupt_archive_rejected_before_unpack(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "bad.zip"
            archive.write_bytes(b"corrupted source")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                load_source(archive)


if __name__ == "__main__":
    unittest.main()
