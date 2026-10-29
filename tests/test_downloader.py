import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from downloader import (
    DownloadError,
    RequestPacer,
    _detect_axis_length,
    archive_folder_name,
    clear_fssessionid,
    fssession_cookie,
    group_folder_name,
    group_image_urls,
    is_group_url,
    load_fssessionid,
    parse_familysearch_url,
    save_fssessionid,
)


class ParseFamilySearchUrlTests(unittest.TestCase):
    def test_parses_regular_url(self) -> None:
        document = parse_familysearch_url(
            "https://www.familysearch.org/ark:/61903/3:1:EXAMPLE-PAGE-1?i=611&cc=0000000"
        )

        self.assertEqual(document.ark_id, "3:1:EXAMPLE-PAGE-1")
        self.assertEqual(document.page_number, 612)
        self.assertEqual(document.filename, "0612_familysearch_EXAMPLE-PAGE-1.jpg")

    def test_parses_html_encoded_url(self) -> None:
        document = parse_familysearch_url(
            "https://www.familysearch.org/ark:/61903/3:1:EXAMPLE-PAGE-2"
            "?i=1201&amp%3Bcc=0000000&amp%3Bcat=000000&lang=en"
        )

        self.assertEqual(document.ark_id, "3:1:EXAMPLE-PAGE-2")
        self.assertEqual(document.page_number, 1202)

    def test_rejects_other_domains(self) -> None:
        with self.assertRaises(DownloadError):
            parse_familysearch_url("https://example.com/ark:/61903/3:1:EXAMPLE-PAGE-1?i=611")


class FssessionCookieTests(unittest.TestCase):
    def test_wraps_bare_value(self) -> None:
        self.assertEqual(fssession_cookie("abc123"), "fssessionid=abc123")

    def test_strips_cookie_name(self) -> None:
        self.assertEqual(
            fssession_cookie("Cookie: fssessionid=abc123"),
            "fssessionid=abc123",
        )

    def test_rejects_other_cookies(self) -> None:
        with self.assertRaises(DownloadError):
            fssession_cookie("fssessionid=abc; test=123")

    def test_rejects_multiline_value(self) -> None:
        with self.assertRaises(DownloadError):
            fssession_cookie("abc\nInjected: value")

    def test_rejects_empty_value(self) -> None:
        with self.assertRaises(DownloadError):
            fssession_cookie("   ")


class SessionCacheTests(unittest.TestCase):
    def test_saves_and_loads_value(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fssessionid"
            save_fssessionid("Cookie: fssessionid=abc123", path)

            self.assertEqual(load_fssessionid(path), "abc123")
            self.assertEqual(path.read_text(encoding="utf-8").strip(), "abc123")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

            clear_fssessionid(path)
            self.assertIsNone(load_fssessionid(path))

    def test_drops_invalid_cached_value(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fssessionid"
            path.write_text("abc; other=1\n", encoding="utf-8")

            self.assertIsNone(load_fssessionid(path))
            self.assertFalse(path.exists())


class RequestPacerTests(unittest.TestCase):
    def test_enforces_minimum_spacing(self) -> None:
        pacer = RequestPacer(
            delay_range=(0.05, 0.05),
            pause_every_range=(100, 100),
            pause_range=(0.0, 0.0),
        )
        start = time.monotonic()
        for _ in range(3):
            pacer.wait()
        self.assertGreaterEqual(time.monotonic() - start, 0.10)

    def test_inserts_long_pauses(self) -> None:
        pacer = RequestPacer(
            delay_range=(0.0, 0.0),
            pause_every_range=(2, 2),
            pause_range=(0.05, 0.05),
        )
        start = time.monotonic()
        for _ in range(3):
            pacer.wait()
        self.assertGreaterEqual(time.monotonic() - start, 0.05)


class GroupUrlTests(unittest.TestCase):
    def test_detects_group_url(self) -> None:
        self.assertTrue(
            is_group_url(
                "https://www.familysearch.org/ark:/61903/3:1:EXAMPLE-PAGE-3"
                "?view=explore&groupId=TH-EXAMPLE-1&grid=on"
            )
        )
        self.assertFalse(is_group_url("https://www.familysearch.org/ark:/61903/3:1:EXAMPLE-PAGE-3"))

    def test_detects_shell_escaped_group_url(self) -> None:
        escaped = (
            "https://www.familysearch.org/ark:/61903/3:1:EXAMPLE-PAGE-4"
            r"\?view\=explore\&groupId\=TH-EXAMPLE-2\&grid\=on\&lang\=en"
        )

        self.assertTrue(is_group_url(escaped))
        self.assertEqual(group_folder_name(escaped), "TH-EXAMPLE-2")

    def test_names_archive_from_reference_and_title(self) -> None:
        self.assertEqual(
            archive_folder_name(
                title="Synthetic archive title",
                reference="DEMO-ARCHIVE",
                dgs_number="000000001",
                group_id="TH-EXAMPLE-2",
            ),
            "DEMO-ARCHIVE_000000001",
        )

    def test_falls_back_to_image_group_number(self) -> None:
        self.assertEqual(
            archive_folder_name(dgs_number="000000001", group_id="TH-1"),
            "000000001",
        )

    def test_names_archive_folder_from_group_id(self) -> None:
        self.assertEqual(
            group_folder_name(
                "https://www.familysearch.org/ark:/61903/3:1:EXAMPLE-PAGE-3"
                "?view=explore&groupId=TH-EXAMPLE-1&grid=on"
            ),
            "TH-EXAMPLE-1",
        )

    def test_builds_numbered_image_urls(self) -> None:
        urls = group_image_urls(
            {
                "images": [
                    "https://familysearch.org/ark:/61903/3:1:AAA-1/image.xml",
                    "not-an-image",
                    "https://familysearch.org/ark:/61903/3:1:BBB-2/image.xml",
                ]
            }
        )

        self.assertEqual(
            urls,
            [
                "https://www.familysearch.org/ark:/61903/3:1:AAA-1?i=0",
                "https://www.familysearch.org/ark:/61903/3:1:BBB-2?i=2",
            ],
        )


class FakeTileClient:
    def __init__(self, columns: int, rows: int) -> None:
        self.columns = columns
        self.rows = rows

    def probe(self, level: int, column: int, row: int):
        if column >= self.columns or row >= self.rows:
            return None
        return b"tile", (256, 256)


class GridDetectionTests(unittest.TestCase):
    def test_detects_columns_with_bounded_probes(self) -> None:
        with TemporaryDirectory() as directory:
            columns = _detect_axis_length(
                FakeTileClient(columns=17, rows=13),
                level=13,
                tile_dir=Path(directory),
                axis="columns",
            )

        self.assertEqual(columns, 17)

    def test_detects_rows_with_bounded_probes(self) -> None:
        with TemporaryDirectory() as directory:
            rows = _detect_axis_length(
                FakeTileClient(columns=17, rows=13),
                level=13,
                tile_dir=Path(directory),
                axis="rows",
            )

        self.assertEqual(rows, 13)


if __name__ == "__main__":
    unittest.main()
