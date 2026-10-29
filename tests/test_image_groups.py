import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import cli
from downloader import (
    FILM_DATA_URL,
    DownloadError,
    SessionRejected,
    fetch_image_group,
    image_group_number,
    is_group_url,
    validate_source_url,
)

SEARCH_URL = "https://www.familysearch.org/en/records/images/search-results?imageGroupNumbers="
ARK_URL = "https://www.familysearch.org/ark:/61903/3:1:TEST-1"


def response(payload, status=200):
    result = Mock(status_code=status)
    result.json.return_value = payload
    return result


class ImageGroupTests(unittest.TestCase):
    def test_accepts_synthetic_group_numbers(self):
        for number in ["000000001", "000000002", "000000003", "000000004", "000000005"]:
            with self.subTest(number=number):
                url = SEARCH_URL + number
                validate_source_url(url)
                self.assertTrue(is_group_url(url))
                self.assertEqual(image_group_number(url), number)

    def test_rejects_invalid_group_numbers_and_domains(self):
        for url in [
            SEARCH_URL,
            SEARCH_URL + "../123",
            SEARCH_URL + "abc",
            SEARCH_URL + "123,456",
            SEARCH_URL + "123&imageGroupNumbers=456",
            (SEARCH_URL + "123").replace("www.familysearch.org", "example.com"),
        ]:
            with self.subTest(url=url), self.assertRaises(DownloadError):
                validate_source_url(url)

    @patch("downloader.RequestPacer.wait")
    @patch("downloader.requests.Session")
    def test_search_link_resolves_film_without_image_data(self, session_factory, wait):
        session = session_factory.return_value.__enter__.return_value
        session.post.side_effect = [
            response(
                {
                    "data": {
                        "search": {
                            "groups": [
                                {
                                    "id": "TH-123",
                                    "metadata": {
                                        "title": "Archive",
                                        "archivalReferenceNumber": "DEMO-1",
                                        "imageGroupNumber": "000000001",
                                    },
                                }
                            ]
                        }
                    }
                }
            ),
            response({"images": [ARK_URL + "/image.xml", ARK_URL.replace("TEST-1", "TEST-2")]}),
        ]
        group = fetch_image_group(SEARCH_URL + "000000001", "test-session")
        self.assertEqual(group.folder_name, "DEMO-1_000000001")
        self.assertEqual(group.group_id, "TH-123")
        self.assertEqual(
            group.image_urls, [ARK_URL + "?i=0", ARK_URL.replace("TEST-1", "TEST-2") + "?i=1"]
        )
        calls = session.post.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1].args[0], FILM_DATA_URL)
        self.assertEqual(calls[1].kwargs["json"]["args"]["dgsNum"], "000000001")
        self.assertEqual(calls[1].kwargs["json"]["type"], "film-data")
        session_factory.return_value.__exit__.assert_called_once()

    @patch("downloader.RequestPacer.wait")
    @patch("downloader.requests.Session")
    def test_existing_viewer_link_still_resolves_image_first(self, session_factory, wait):
        session = session_factory.return_value.__enter__.return_value
        session.post.side_effect = [
            response({"dgsNum": "000000001"}),
            response({"data": {"search": {"groups": []}}}),
            response({"images": [ARK_URL]}),
        ]
        group = fetch_image_group(ARK_URL + "?groupId=TH-123", "test-session")
        self.assertEqual(group.folder_name, "000000001")
        self.assertEqual(session.post.call_args_list[0].kwargs["json"]["type"], "image-data")
        self.assertEqual(
            session.post.call_args_list[2].kwargs["json"]["args"]["state"]["imageOrFilmUrl"],
            "/ark:/61903/3:1:TEST-1",
        )

    @patch("downloader.RequestPacer.wait")
    @patch("downloader.requests.Session")
    def test_metadata_failure_uses_number_as_folder(self, session_factory, wait):
        session = session_factory.return_value.__enter__.return_value
        session.post.side_effect = [response([]), response({"images": [ARK_URL]})]
        group = fetch_image_group(SEARCH_URL + "000000001", "test-session")
        self.assertEqual(group.folder_name, "000000001")
        self.assertEqual(group.title, "")

    @patch("downloader.RequestPacer.wait")
    @patch("downloader.requests.Session")
    def test_authorization_failure_is_not_swallowed(self, session_factory, wait):
        session = session_factory.return_value.__enter__.return_value
        session.post.return_value = response({}, 403)
        with self.assertRaises(SessionRejected):
            fetch_image_group(SEARCH_URL + "000000001", "test-session")
        self.assertEqual(session.post.call_count, 1)

    def test_reads_all_five_urls_from_markdown_table(self):
        numbers = ["000000001", "000000002", "000000003", "000000004", "000000005"]
        links = [f"[{number}]({SEARCH_URL}{number})" for number in numbers]
        table = (
            "| Priority | Archive | FS | Purpose |\n| --- | --- | --- | --- |\n"
            f"| 2 | DEMO-1 | {links[0]} | Example documents |\n"
            f"| 3 | DEMO-2…5 | {', '.join(links[1:])} | Example index |\n"
        )
        with TemporaryDirectory() as directory:
            source = Path(directory) / "cases.md"
            source.write_text(table, encoding="utf-8")
            args = cli.build_parser().parse_args(["download", "-f", str(source)])
            self.assertEqual(cli.collect_urls(args), [SEARCH_URL + number for number in numbers])

    @patch("cli.download_document")
    @patch("cli.fetch_image_group")
    @patch("cli.get_session", return_value="test-session")
    def test_cli_expands_search_link_into_pages(self, get_session, fetch_group, download):
        from downloader import ImageGroup

        fetch_group.return_value = ImageGroup(
            [ARK_URL + "?i=0"],
            "DEMO-1_000000001",
            "Archive",
            "DEMO-1",
            "000000001",
            "TH-123",
            SEARCH_URL + "000000001",
        )
        download.return_value = Mock(path="page.jpg", width=10, height=10)
        with TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            args = cli.build_parser().parse_args(
                ["download", SEARCH_URL + "000000001", "-o", directory]
            )
            result = cli.download_urls(args)
            self.assertEqual(result.saved, 1)
            self.assertEqual(
                download.call_args.args[:2],
                (ARK_URL + "?i=0", Path(directory) / "DEMO-1_000000001"),
            )
            self.assertTrue((Path(directory) / "DEMO-1_000000001" / "info.txt").is_file())
