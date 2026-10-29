import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from PIL import Image
from test_downloader import FakeTileClient

import cli
from downloader import (
    DownloadError,
    SessionRejected,
    _detect_axis_length,
    _json_object,
    archive_folder_name,
    atomic_output,
    download_document,
    is_complete_image,
    parse_familysearch_url,
)

URL = "https://www.familysearch.org/ark:/61903/3:1:TEST-1?i=0"


class ReliabilityTests(unittest.TestCase):
    def test_atomic_write_preserves_original_on_interruption(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "page.jpg"
            target.write_bytes(b"original")
            with self.assertRaises(KeyboardInterrupt):
                with atomic_output(target) as temporary:
                    temporary.write_bytes(b"incomplete")
                    raise KeyboardInterrupt
            self.assertEqual(target.read_bytes(), b"original")
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_resume_rejects_truncated_jpeg(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "page.jpg"
            Image.new("RGB", (64, 64), "red").save(target)
            self.assertTrue(is_complete_image(target))
            target.write_bytes(target.read_bytes()[:-20])
            self.assertFalse(is_complete_image(target))

    def test_rejects_invalid_urls_and_indices(self):
        for url in [
            URL.replace("https:", "ftp:"),
            URL + "junk",
            URL.replace("i=0", "i=-1"),
            "https://familysearch.org/?redirect=/ark:/61903/3:1:TEST",
        ]:
            with self.subTest(url=url), self.assertRaises(DownloadError):
                parse_familysearch_url(url)

    def test_folder_name_cannot_escape_output(self):
        self.assertEqual(archive_folder_name(reference="..", group_id="TH-1"), "TH-1")
        with self.assertRaises(DownloadError):
            archive_folder_name(reference="..")

    def test_grid_limit_does_not_silently_crop_image(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(DownloadError):
                _detect_axis_length(FakeTileClient(101, 1), 8, Path(directory), "columns")
            self.assertEqual(
                _detect_axis_length(FakeTileClient(100, 1), 8, Path(directory), "columns"), 100
            )

    def test_bad_json_and_rejected_session(self):
        response = Mock(status_code=200)
        response.json.return_value = []
        with self.assertRaises(DownloadError):
            _json_object(response)
        response.status_code = 403
        with self.assertRaises(SessionRejected):
            _json_object(response)

    def test_assembles_overlapping_tiles_and_closes_client(self):
        def tile_bytes(column, row):
            buffer = io.BytesIO()
            Image.new("RGB", (257 if column == 0 else 45, 257 if row == 0 else 25), "red").save(
                buffer, "JPEG"
            )
            return buffer.getvalue()

        client = Mock()
        client.probe.side_effect = lambda level, column, row: (
            (tile_bytes(column, row), (257, 257)) if level <= 9 and column < 2 and row < 2 else None
        )
        client.get_tile.side_effect = lambda level, column, row, timeout: tile_bytes(column, row)
        with TemporaryDirectory() as directory, patch("downloader.TileClient", return_value=client):
            result = download_document(URL, Path(directory), "test-session")
            self.assertEqual((result.width, result.height, result.level), (300, 280, 9))
            self.assertTrue(is_complete_image(result.path))
            with Image.open(result.path) as image:
                self.assertGreater(image.getpixel((299, 279))[0], 240)
            self.assertEqual(list(Path(directory).iterdir()), [result.path])
        client.close.assert_called_once()

    def test_detection_failure_closes_client(self):
        client = Mock()
        client.probe.side_effect = DownloadError("network unavailable")
        with TemporaryDirectory() as directory, patch("downloader.TileClient", return_value=client):
            with self.assertRaises(DownloadError):
                download_document(URL, Path(directory), "test-session")
            self.assertEqual(list(Path(directory).iterdir()), [])
        client.close.assert_called_once()


class CliTests(unittest.TestCase):
    def test_url_file_supports_comments_bom_and_duplicates(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "urls.txt"
            source.write_text(f"\ufeff# comment\n\n{URL}\n{URL}\n", encoding="utf-8")
            args = cli.build_parser().parse_args(["download", URL, "-f", str(source)])
            self.assertEqual(cli.collect_urls(args), [URL])

    def test_rejects_out_of_range_options(self):
        for option, value in [
            ("--quality", "69"),
            ("--quality", "101"),
            ("--workers", "0"),
            ("--workers", "17"),
        ]:
            with self.subTest(option=option, value=value), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    cli.build_parser().parse_args(["download", URL, option, value])
                self.assertEqual(error.exception.code, 2)

    def test_partial_failure_returns_nonzero_and_continues(self):
        with (
            TemporaryDirectory() as directory,
            patch("cli.get_session", return_value="test"),
            patch(
                "cli.download_document",
                side_effect=[DownloadError("failed"), Mock(path="page.jpg", width=300, height=280)],
            ) as download,
            patch(
                "sys.argv",
                ["fsd", "download", URL, URL.replace("TEST-1", "TEST-2"), "-o", directory],
            ),
            redirect_stdout(io.StringIO()) as output,
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(cli.main(), 1)
            self.assertEqual(download.call_count, 2)
            self.assertIn("1 saved, 0 skipped, 1 failed", output.getvalue())

    def test_invalid_input_does_not_request_session(self):
        with (
            patch("cli.get_session") as session,
            patch("sys.argv", ["fsd", "download"]),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(cli.main(), 1)
            session.assert_not_called()

    def test_valid_existing_image_is_skipped(self):
        with (
            TemporaryDirectory() as directory,
            patch("cli.get_session", return_value="test"),
            patch("cli.download_document") as download,
            redirect_stdout(io.StringIO()),
        ):
            Image.new("RGB", (10, 10)).save(Path(directory) / parse_familysearch_url(URL).filename)
            args = cli.build_parser().parse_args(["download", URL, "-o", directory])
            result = cli.download_urls(args)
            self.assertEqual(result, cli.BatchResult(skipped=1))
            download.assert_not_called()
