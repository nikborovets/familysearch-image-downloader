from __future__ import annotations

import argparse
import getpass
import random
import re
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from downloader import (
    DownloadError,
    ImageGroup,
    SessionRejected,
    atomic_output,
    clear_fssessionid,
    download_document,
    fetch_image_group,
    is_complete_image,
    is_group_url,
    load_fssessionid,
    parse_familysearch_url,
    save_fssessionid,
    validate_source_url,
)

DEFAULT_OUTPUT_DIR = Path("downloads")
PAGE_PAUSE_RANGE = (4.0, 10.0)


def console_progress(value: float, message: str) -> None:
    if sys.stdout.isatty():
        sys.stdout.write(f"\r{value:5.1%}  {message:<64}")
        sys.stdout.flush()
    elif not message.startswith("Downloaded tiles:"):
        print(f"{value:5.1%}  {message}")


def ask_fssessionid() -> str:
    print(
        "Open a document page in your signed-in browser: DevTools -> Network -> "
        "a familysearch.org request -> Cookies -> the fssessionid value."
    )
    while True:
        raw = getpass.getpass("fssessionid: ").strip()
        if not raw:
            print("Empty value, try again.")
            continue
        try:
            save_fssessionid(raw)
        except DownloadError as error:
            print(error)
            continue
        return load_fssessionid() or raw


def get_session(interactive: bool) -> str:
    value = load_fssessionid()
    if value:
        print("Using the saved fssessionid.")
        return value
    if not interactive:
        raise DownloadError("No saved fssessionid. Run 'fsd login' first.")
    return ask_fssessionid()


def collect_urls(args: argparse.Namespace) -> list[str]:
    urls: list[str] = list(args.urls)
    if args.from_file:
        content = args.from_file.read_text(encoding="utf-8-sig")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            links = re.findall(r"https?://[^\s<>\[\]\"|)]+", line)
            if links:
                urls.extend(links)
            elif args.from_file.suffix.lower() not in {".md", ".markdown"}:
                urls.append(line)
    if not urls:
        raise DownloadError("No URLs. Pass them as arguments or use --from-file.")
    return list(dict.fromkeys(url.strip() for url in urls))


def _write_archive_info(directory: Path, group: ImageGroup) -> None:
    lines = [
        f"Title: {group.title or '-'}",
        f"Archival reference: {group.reference or '-'}",
        f"Image group number: {group.dgs_number}",
        f"Group id: {group.group_id}",
        f"Images: {len(group.image_urls)}",
        f"Source: {group.source_url}",
        "",
    ]
    with atomic_output(directory / "info.txt") as temporary:
        temporary.write_text("\n".join(lines), encoding="utf-8")


@dataclass
class BatchResult:
    saved: int = 0
    skipped: int = 0
    failed: int = 0


def download_urls(args: argparse.Namespace) -> BatchResult:
    urls = collect_urls(args)
    for url in urls:
        validate_source_url(url)
    result = BatchResult()
    interactive = sys.stdin.isatty()
    session_value = get_session(interactive)
    base_output: Path = args.out
    base_output.mkdir(parents=True, exist_ok=True)

    jobs = deque((url, base_output) for url in urls)
    print(f"{len(jobs)} document(s), saving to {base_output.resolve()}")

    def refresh_session() -> str:
        print()
        print("FamilySearch rejected this fssessionid.")
        clear_fssessionid()
        if not interactive:
            raise DownloadError("Run 'fsd login' with a fresh value, then retry.")
        return ask_fssessionid()

    while jobs:
        raw_url, output_dir = jobs[0]
        if is_group_url(raw_url):
            try:
                group = fetch_image_group(raw_url, session_value)
            except SessionRejected:
                session_value = refresh_session()
                continue
            except DownloadError as error:
                print(f"Failed: {error}", file=sys.stderr)
                result.failed += 1
                jobs.popleft()
                continue
            group_dir = output_dir / group.folder_name
            legacy_dir = output_dir / group.group_id
            if legacy_dir.is_dir() and legacy_dir != group_dir and not group_dir.exists():
                legacy_dir.rename(group_dir)
            group_dir.mkdir(parents=True, exist_ok=True)
            _write_archive_info(group_dir, group)
            print(
                f"{group.folder_name}: {len(group.image_urls)} image(s), "
                f"saving to {group_dir.resolve()}"
            )
            jobs.popleft()
            jobs.extendleft((image_url, group_dir) for image_url in reversed(group.image_urls))
            continue
        try:
            document = parse_familysearch_url(raw_url)
        except DownloadError as error:
            print(f"Failed: {error}", file=sys.stderr)
            result.failed += 1
            jobs.popleft()
            continue

        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / document.filename
        legacy = base_output / document.filename
        if not target.exists() and legacy != target and legacy.is_file():
            legacy.rename(target)
        if is_complete_image(target):
            print(f"Already downloaded: {target.name}")
            result.skipped += 1
            jobs.popleft()
            continue

        try:
            downloaded = download_document(
                raw_url,
                output_dir,
                session_value,
                jpeg_quality=args.quality,
                workers=args.workers,
                progress=console_progress,
            )
        except SessionRejected:
            session_value = refresh_session()
            continue
        except DownloadError as error:
            print()
            print(f"Failed: {error}", file=sys.stderr)
            result.failed += 1
            jobs.popleft()
            continue

        print()
        print(f"Saved: {downloaded.path} ({downloaded.width} × {downloaded.height})")
        result.saved += 1
        jobs.popleft()

        if jobs:
            pause = random.uniform(*PAGE_PAUSE_RANGE)
            print(f"Next page in {pause:.0f}s...")
            time.sleep(pause)

    print(f"Finished: {result.saved} saved, {result.skipped} skipped, {result.failed} failed.")
    return result


def bounded_integer(minimum: int, maximum: int):
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError as error:
            raise argparse.ArgumentTypeError("expected an integer") from error
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(f"must be between {minimum} and {maximum}")
        return number

    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fsd",
        description="Download FamilySearch document images as single JPEG files.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("login", help="save a fresh fssessionid value")
    subparsers.add_parser("logout", help="remove the saved fssessionid")

    download = subparsers.add_parser("download", help="download document images")
    download.add_argument("urls", nargs="*", help="FamilySearch document URLs")
    download.add_argument(
        "-f",
        "--from-file",
        type=Path,
        help="URL list or Markdown file (including tables)",
    )
    download.add_argument(
        "-o",
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    download.add_argument(
        "--quality",
        type=bounded_integer(70, 100),
        default=95,
        help="JPEG quality, 70-100 (default: 95)",
    )
    download.add_argument(
        "--workers",
        type=bounded_integer(1, 16),
        default=8,
        help="parallel tile requests (default: 8)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "login":
            ask_fssessionid()
            print("Saved. It will be reused until FamilySearch rejects it.")
        elif args.command == "logout":
            clear_fssessionid()
            print("Saved session removed.")
        else:
            return 1 if download_urls(args).failed else 0
    except (DownloadError, OSError, EOFError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted. Run the same command to resume.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
