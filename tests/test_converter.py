from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from converter import convert_file, output_paths, paths_for_directory, validate_input_file
from decoder import FIELDNAMES


class InputValidationTests(unittest.TestCase):
    def test_empty_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "empty.bin"
            path.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "vazio"):
                validate_input_file(path)

    def test_non_multiple_of_eight_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "invalid.bin"
            path.write_bytes(b"123456789")
            with self.assertRaisesRegex(ValueError, "multiplo de 8"):
                validate_input_file(path)


class OutputPathTests(unittest.TestCase):
    def test_default_output_paths(self) -> None:
        input_path = Path("C:/dados/data001.bin")
        csv_path, xlsx_path = output_paths(input_path, None, "both")
        self.assertEqual(csv_path, Path("C:/dados/data001_decoded.csv"))
        self.assertEqual(xlsx_path, Path("C:/dados/data001_decoded.xlsx"))

    def test_gui_directory_output_paths(self) -> None:
        input_path = Path("C:/dados/data001.bin")
        output_dir = Path("C:/resultado")
        csv_path, xlsx_path = paths_for_directory(input_path, output_dir, "xlsx")
        self.assertIsNone(csv_path)
        self.assertEqual(xlsx_path, Path("C:/resultado/data001_decoded.xlsx"))


class CsvConversionTests(unittest.TestCase):
    def test_csv_conversion_and_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            input_path = temp / "data001.bin"
            # SESSION_MARKER conforme a logica existente: header/payload zerados.
            input_path.write_bytes(bytes(8) + bytes(8))
            csv_path = temp / "data001_decoded.csv"
            progress: list[tuple[int, int]] = []

            result = convert_file(
                input_path,
                csv_path=csv_path,
                xlsx_path=None,
                delimiter=";",
                progress_callback=lambda current, total: progress.append((current, total)),
                progress_interval_records=1,
            )

            self.assertEqual(result.records, 2)
            self.assertTrue(csv_path.is_file())
            self.assertEqual(progress[0], (0, 2))
            self.assertEqual(progress[-1], (2, 2))

            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle, delimiter=";")
                rows = list(reader)
            self.assertEqual(reader.fieldnames, FIELDNAMES)
            self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
