from __future__ import annotations

import html
import io
import os
import random
import re
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, unquote, urlparse

import requests
from PIL import Image

TILE_SIZE = 256
TILE_OVERLAP = 1
MAX_GRID_SIDE = 100
MAX_TILES = 2_500
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137 Safari/537.36"
)

ProgressCallback = Callable[[float, str], None]


class TileProber(Protocol):
    def probe(self, level: int, column: int, row: int) -> tuple[bytes, tuple[int, int]] | None: ...


class DownloadError(RuntimeError):
    pass


class SessionRejected(DownloadError):
    pass


def _check_response(response: requests.Response) -> None:
    if response.status_code in {401, 403}:
        raise SessionRejected("FamilySearch rejected this fssessionid. Paste a new value.")
    try:
        response.raise_for_status()
    except requests.RequestException as error:
        raise DownloadError(
            f"FamilySearch returned HTTP {response.status_code}. Try again later."
        ) from error


def _json_object(response: requests.Response) -> dict:
    _check_response(response)
    try:
        data = response.json()
    except ValueError as error:
        raise DownloadError("FamilySearch returned an invalid JSON response.") from error
    if not isinstance(data, dict):
        raise DownloadError("FamilySearch returned an invalid JSON response.")
    return data


@contextmanager
def atomic_output(path: Path) -> Iterator[Path]:
    """Publish a complete file by replacing it from the same filesystem."""
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        yield temporary
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def is_complete_image(path: Path) -> bool:
    """Decode existing JPEGs before treating them as completed downloads."""
    try:
        with Image.open(path) as image:
            if image.format != "JPEG":
                return False
            image.load()
        return True
    except (OSError, ValueError):
        return False


class RequestPacer:
    """Spaces requests out with human-like jitter and reading pauses."""

    def __init__(
        self,
        rng: random.Random | None = None,
        delay_range: tuple[float, float] = (0.3, 0.8),
        pause_every_range: tuple[int, int] = (10, 16),
        pause_range: tuple[float, float] = (1.0, 2.5),
    ) -> None:
        self._rng = rng or random.Random()
        self._delay_range = delay_range
        self._pause_every_range = pause_every_range
        self._pause_range = pause_range
        self._next_slot = time.monotonic()
        self._requests_since_pause = 0
        self._requests_until_pause = self._rng.randint(*pause_every_range)
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_slot)
            delay = self._rng.uniform(*self._delay_range)
            self._requests_since_pause += 1
            if self._requests_since_pause >= self._requests_until_pause:
                delay += self._rng.uniform(*self._pause_range)
                self._requests_since_pause = 0
                self._requests_until_pause = self._rng.randint(*self._pause_every_range)
            self._next_slot = start + delay
            sleep_for = start - now
        if sleep_for > 0:
            time.sleep(sleep_for)


@dataclass(frozen=True)
class DocumentLink:
    original_url: str
    ark_id: str
    image_index: int | None

    @property
    def page_number(self) -> int | None:
        return self.image_index + 1 if self.image_index is not None else None

    @property
    def safe_id(self) -> str:
        return self.ark_id.removeprefix("3:1:")

    @property
    def filename(self) -> str:
        if self.page_number is None:
            return f"familysearch_{self.safe_id}.jpg"
        return f"{self.page_number:04d}_familysearch_{self.safe_id}.jpg"


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    width: int
    height: int
    level: int
    columns: int
    rows: int


def clean_familysearch_url(raw_url: str) -> str:
    cleaned = html.unescape(raw_url.strip())
    cleaned = unquote(cleaned.replace("&amp%3B", "&").replace("%26amp%253B", "&"))
    # A shell paste often escapes the query, so "?groupId=" arrives as "\?groupId\=".
    return re.sub(r"\\([?&=])", r"\1", cleaned)


def parse_familysearch_url(raw_url: str) -> DocumentLink:
    cleaned = clean_familysearch_url(raw_url)

    parsed = urlparse(cleaned)
    match = re.fullmatch(r"/ark:/61903/(3:1:[A-Za-z0-9-]+)/?", parsed.path)
    if not match:
        raise DownloadError("Could not find a FamilySearch identifier in the 3:1:... format.")

    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "familysearch.org",
        "www.familysearch.org",
    }:
        raise DownloadError("Only familysearch.org links are supported.")

    query = parse_qs(parsed.query)
    index = None
    if query.get("i"):
        try:
            index = int(query["i"][0])
        except ValueError as error:
            raise DownloadError("The image index 'i' must be a non-negative integer.") from error
        if index < 0:
            raise DownloadError("The image index 'i' must be a non-negative integer.")

    return DocumentLink(cleaned, match.group(1), index)


@dataclass(frozen=True)
class ImageGroup:
    image_urls: list[str]
    folder_name: str
    title: str
    reference: str
    dgs_number: str
    group_id: str
    source_url: str


ORCHESTRATION_URL = "https://www.familysearch.org/records/images/orchestration/"
FILM_DATA_URL = "https://www.familysearch.org/search/filmdatainfo/image-data"
ARCHIVE_QUERY = """
query ArchiveTitle($searchInput: SearchInput!) {
  search(searchInput: $searchInput) {
    groups {
      id
      metadata {
        title
        archivalReferenceNumber
        imageGroupNumber
        volume
      }
    }
  }
}
"""


def _familysearch_query(raw_url: str) -> dict[str, list[str]]:
    parsed = urlparse(clean_familysearch_url(raw_url))
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "familysearch.org",
        "www.familysearch.org",
    }:
        return {}
    return parse_qs(parsed.query)


def is_group_url(raw_url: str) -> bool:
    query = _familysearch_query(raw_url)
    return bool(query.get("groupId") or "imageGroupNumbers" in query)


def image_group_number(raw_url: str) -> str | None:
    """Read a DGS number from an Images search-results link."""
    query = parse_qs(urlparse(clean_familysearch_url(raw_url)).query, keep_blank_values=True)
    if "imageGroupNumbers" not in query:
        return None
    if not _familysearch_query(raw_url):
        raise DownloadError("Only familysearch.org links are supported.")
    values = query["imageGroupNumbers"]
    if len(values) != 1 or not re.fullmatch(r"[0-9]+", values[0]):
        raise DownloadError(
            "imageGroupNumbers must contain one numeric image group number per URL."
        )
    return values[0]


def validate_source_url(raw_url: str) -> None:
    if image_group_number(raw_url) is None:
        parse_familysearch_url(raw_url)
        if is_group_url(raw_url):
            group_folder_name(raw_url)


def group_folder_name(raw_url: str) -> str:
    values = _familysearch_query(raw_url).get("groupId") or []
    raw_name = values[0] if values else ""
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._")
    if not safe_name:
        raise DownloadError("Could not find a group id in the link.")
    return safe_name


def archive_folder_name(
    *,
    title: str = "",
    reference: str = "",
    dgs_number: str = "",
    group_id: str = "",
) -> str:
    reference_token = re.sub(r"[^A-Za-z0-9._-]+", "", reference).strip("._")
    dgs_token = re.sub(r"[^A-Za-z0-9._-]+", "", dgs_number).strip("._")
    group_token = re.sub(r"[^A-Za-z0-9._-]+", "", group_id).strip("._")
    if reference_token and dgs_token:
        return f"{reference_token}_{dgs_token}"
    folder = reference_token or dgs_token or group_token
    if not folder:
        raise DownloadError("Could not determine a safe image group folder name.")
    return folder


def lookup_archive(group_id: str, fssessionid: str) -> tuple[str, str, str, str]:
    """Return folder name, title, archival reference, and image group number."""
    session_id = fssession_cookie(fssessionid).split("=", 1)[1]
    headers = {
        "Cookie": f"fssessionid={session_id}",
        "Authorization": f"bearer {session_id}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
    }
    name_url = (
        f"https://sg30p0.familysearch.org/service/records/storage/dascloud/das/v2/{group_id}/name"
    )
    try:
        response = requests.get(name_url, headers=headers, timeout=30)
    except requests.RequestException as error:
        raise DownloadError(f"Could not connect to FamilySearch: {error}") from error
    _check_response(response)
    dgs_number = response.text.strip().removeprefix("dgs:").strip()
    title = ""
    reference = ""
    if dgs_number:
        try:
            found = requests.post(
                ORCHESTRATION_URL,
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "query": ARCHIVE_QUERY,
                    "variables": {"searchInput": {"imageGroupNumbers": [dgs_number]}},
                },
                timeout=30,
            )
        except requests.RequestException as error:
            raise DownloadError(f"Could not connect to FamilySearch: {error}") from error
        payload = _json_object(found)
        search = (
            payload.get("data", {}).get("search", {})
            if isinstance(payload.get("data"), dict)
            else {}
        )
        groups = search.get("groups") if isinstance(search, dict) else None
        if isinstance(groups, list):
            title, reference = _archive_fields(_find_archive(groups, dgs_number), dgs_number)
    folder_name = archive_folder_name(
        title=title,
        reference=reference,
        dgs_number=dgs_number,
        group_id=group_id,
    )
    return folder_name, title, reference, dgs_number


def group_image_urls(film_data: dict) -> list[str]:
    urls: list[str] = []
    images = film_data.get("images")
    if not isinstance(images, list):
        return urls
    for index, entry in enumerate(images):
        if not isinstance(entry, str):
            continue
        match = re.search(r"/ark:/61903/(3:1:[A-Za-z0-9-]+)", entry)
        if match:
            urls.append(f"https://www.familysearch.org/ark:/61903/{match.group(1)}?i={index}")
    return urls


def _archive_fields(group: dict, dgs_number: str) -> tuple[str, str]:
    raw_metadata = group.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    title = str(metadata.get("title") or "").strip()
    reference = str(metadata.get("archivalReferenceNumber") or metadata.get("volume") or "").strip()
    number = str(metadata.get("imageGroupNumber") or dgs_number).strip()
    if reference == number:
        reference = ""
    return title, reference


def _find_archive(groups: list, dgs_number: str) -> dict:
    for group in groups:
        if not isinstance(group, dict):
            continue
        raw_metadata = group.get("metadata")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        if str(metadata.get("imageGroupNumber") or "") == dgs_number:
            return group
    for group in groups:
        if isinstance(group, dict):
            return group
    return {}


def fetch_image_group(raw_url: str, fssessionid: str) -> ImageGroup:
    validate_source_url(raw_url)
    source_url = clean_familysearch_url(raw_url)
    dgs_number = image_group_number(raw_url)
    group_id = dgs_number or group_folder_name(raw_url)
    image_path = "" if dgs_number else urlparse(source_url).path
    session_id = fssession_cookie(fssessionid).split("=", 1)[1]
    headers = {
        "Cookie": f"fssessionid={session_id}",
        "Authorization": f"bearer {session_id}",
        "Referer": source_url,
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
    }
    pacer = RequestPacer()
    with requests.Session() as session:
        session.headers.update(headers)

        def post(url: str, payload: dict) -> dict:
            pacer.wait()
            try:
                response = session.post(url, json=payload, timeout=30)
            except requests.RequestException as error:
                raise DownloadError(f"Could not connect to FamilySearch: {error}") from error
            data = _json_object(response)
            error_info = data.get("error")
            if isinstance(error_info, dict) and error_info.get("statusCode"):
                try:
                    status = int(error_info["statusCode"])
                except (TypeError, ValueError) as error:
                    raise DownloadError("FamilySearch returned an invalid error status.") from error
                if status in {401, 403}:
                    raise SessionRejected(
                        "FamilySearch rejected this fssessionid. Paste a new value."
                    )
                message = error_info.get("message") or f"status {status}"
                raise DownloadError(f"Could not read the image group: {message}")
            return data

        if dgs_number is None:
            image_data = post(
                FILM_DATA_URL,
                {
                    "type": "image-data",
                    "args": {
                        "imageURL": source_url,
                        "state": {
                            "imageOrFilmUrl": "",
                            "viewMode": "i",
                            "selectedImageIndex": -1,
                        },
                        "locale": "en",
                    },
                },
            )
            dgs_number = str(image_data.get("dgsNum") or "").strip()
            if not dgs_number:
                raise DownloadError("Could not resolve this link to an image group.")

        title = ""
        reference = ""
        try:
            found = post(
                ORCHESTRATION_URL,
                {
                    "query": ARCHIVE_QUERY,
                    "variables": {"searchInput": {"imageGroupNumbers": [dgs_number]}},
                },
            )
        except SessionRejected:
            raise
        except DownloadError:
            found = {}
        search = (
            found.get("data", {}).get("search", {}) if isinstance(found.get("data"), dict) else {}
        )
        groups = search.get("groups") if isinstance(search, dict) else None
        if isinstance(groups, list):
            archive = _find_archive(groups, dgs_number)
            title, reference = _archive_fields(archive, dgs_number)
            if archive.get("id"):
                safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", str(archive["id"])).strip("._")
                group_id = safe_id or group_id

        film_data = post(
            FILM_DATA_URL,
            {
                "type": "film-data",
                "args": {
                    "dgsNum": dgs_number,
                    "state": {
                        "i": "",
                        "cat": "",
                        "imageOrFilmUrl": image_path,
                        "catalogContext": "",
                        "viewMode": "i",
                        "selectedImageIndex": -1,
                    },
                    "locale": "en",
                    "sessionId": f"bearer {session_id}",
                    "loggedIn": True,
                },
            },
        )
        urls = group_image_urls(film_data)
        if not urls:
            raise DownloadError("No images were found in this group.")
        return ImageGroup(
            image_urls=urls,
            folder_name=archive_folder_name(
                title=title,
                reference=reference,
                dgs_number=dgs_number,
                group_id=group_id,
            ),
            title=title,
            reference=reference,
            dgs_number=dgs_number,
            group_id=group_id,
            source_url=source_url,
        )


def fssession_cookie(raw_value: str) -> str:
    value = raw_value.strip()
    if value.lower().startswith("cookie:"):
        value = value.split(":", 1)[1].strip()
    prefix = "fssessionid="
    if value.lower().startswith(prefix):
        value = value[len(prefix) :].strip()
    if not value:
        raise DownloadError("Paste the fssessionid value.")
    if any(char in value for char in "\r\n;"):
        raise DownloadError("Paste only the fssessionid value, without other cookies.")
    return f"{prefix}{value}"


def session_cache_path() -> Path:
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches"
    elif os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "familysearch-image-downloader" / "fssessionid"


def load_fssessionid(path: Path | None = None) -> str | None:
    cache_path = path or session_cache_path()
    try:
        raw = cache_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    if not raw:
        return None
    try:
        value = fssession_cookie(raw).split("=", 1)[1]
    except DownloadError:
        clear_fssessionid(cache_path)
        return None
    return value


def save_fssessionid(raw_value: str, path: Path | None = None) -> None:
    value = fssession_cookie(raw_value).split("=", 1)[1]
    cache_path = path or session_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.parent.chmod(0o700)
    with atomic_output(cache_path) as temporary:
        temporary.write_text(f"{value}\n", encoding="utf-8")


def clear_fssessionid(path: Path | None = None) -> None:
    cache_path = path or session_cache_path()
    try:
        cache_path.unlink()
    except FileNotFoundError:
        return


class TileClient:
    def __init__(
        self,
        document: DocumentLink,
        cookie_header: str,
        pacer: RequestPacer | None = None,
    ) -> None:
        self.document = document
        self.headers = {
            "Cookie": cookie_header,
            "Referer": document.original_url,
            "User-Agent": USER_AGENT,
        }
        self._pacer = pacer
        self._thread_local = threading.local()
        self._sessions: list[requests.Session] = []
        self._sessions_lock = threading.Lock()

    def close(self) -> None:
        for session in self._sessions:
            session.close()

    def _session(self) -> requests.Session:
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(self.headers)
            self._thread_local.session = session
            with self._sessions_lock:
                self._sessions.append(session)
        return session

    def tile_url(self, level: int, column: int, row: int) -> str:
        return (
            "https://sg30p0.familysearch.org/service/records/storage/"
            f"deepzoomcloud/dz/v1/{self.document.ark_id}/image_files/"
            f"{level}/{column}_{row}.jpg"
        )

    def get_tile(self, level: int, column: int, row: int, timeout: int = 25) -> bytes:
        if self._pacer:
            self._pacer.wait()
        try:
            response = self._session().get(
                self.tile_url(level, column, row),
                timeout=timeout,
            )
        except requests.RequestException as error:
            raise DownloadError(f"Could not connect to FamilySearch: {error}") from error
        if response.status_code in {401, 403}:
            raise SessionRejected("FamilySearch rejected this fssessionid. Paste a new value.")
        if response.status_code == 404:
            raise FileNotFoundError
        _check_response(response)
        return response.content

    def probe(self, level: int, column: int, row: int) -> tuple[bytes, tuple[int, int]] | None:
        try:
            data = self.get_tile(level, column, row, timeout=15)
        except FileNotFoundError:
            return None
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
                size = image.size
        except (OSError, ValueError) as error:
            raise DownloadError("FamilySearch returned an invalid image tile.") from error
        return data, size


def _detect_level(client: TileProber) -> int:
    for level in range(18, -1, -1):
        if client.probe(level, 0, 0) is not None:
            return level
    raise DownloadError("Could not find DeepZoom tiles for this document.")


def _detect_axis_length(
    client: TileProber,
    level: int,
    tile_dir: Path,
    axis: str,
) -> int:
    def probe(index: int) -> bool:
        column, row = (index, 0) if axis == "columns" else (0, index)
        result = client.probe(level, column, row)
        if result is None:
            return False
        data, _ = result
        (tile_dir / f"{column}_{row}.jpg").write_bytes(data)
        return True

    if not probe(0):
        return 0

    lower = 0
    upper = 1
    while upper < MAX_GRID_SIDE and probe(upper):
        lower = upper
        upper *= 2
    upper = min(upper, MAX_GRID_SIDE)

    while lower + 1 < upper:
        middle = (lower + upper) // 2
        if probe(middle):
            lower = middle
        else:
            upper = middle
    if lower + 1 == MAX_GRID_SIDE and probe(MAX_GRID_SIDE):
        raise DownloadError("The image tile grid exceeds the supported size.")
    return lower + 1


def _detect_grid(client: TileProber, level: int, tile_dir: Path) -> tuple[int, int]:
    columns = _detect_axis_length(client, level, tile_dir, "columns")
    rows = _detect_axis_length(client, level, tile_dir, "rows")

    if not columns or not rows:
        raise DownloadError("Could not determine the image tile grid.")
    if columns * rows > MAX_TILES:
        raise DownloadError("The image contains too many tiles to process safely.")
    return columns, rows


def download_document(
    raw_url: str,
    output_dir: Path,
    fssessionid: str,
    jpeg_quality: int = 95,
    workers: int = 4,
    progress: ProgressCallback | None = None,
) -> DownloadResult:
    if not 70 <= jpeg_quality <= 100:
        raise DownloadError("JPEG quality must be between 70 and 100.")
    if not 1 <= workers <= 16:
        raise DownloadError("Workers must be between 1 and 16.")
    document = parse_familysearch_url(raw_url)
    header = fssession_cookie(fssessionid)

    def report(value: float, message: str) -> None:
        if progress:
            progress(max(0.0, min(1.0, value)), message)

    report(0.02, "Checking the supplied fssessionid")
    pacer = RequestPacer()
    client = TileClient(document, header, pacer)
    try:
        if client.probe(8, 0, 0) is None:
            raise DownloadError("Could not open the image with this fssessionid.")
        report(0.08, "Using the supplied fssessionid")

        level = _detect_level(client)
        report(0.13, f"Highest available quality level: {level}")

        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="familysearch-tiles-") as temp_dir:
            tile_dir = Path(temp_dir)
            columns, rows = _detect_grid(client, level, tile_dir)
            total = columns * rows
            report(0.18, f"Tile grid: {columns} x {rows} ({total} tiles)")

            def fetch(column: int, row: int) -> Path:
                path = tile_dir / f"{column}_{row}.jpg"
                if path.exists() and path.stat().st_size:
                    return path

                last_error: Exception | None = None
                for attempt in range(4):
                    try:
                        data = client.get_tile(level, column, row, timeout=30)
                        with Image.open(io.BytesIO(data)) as image:
                            image.verify()
                        path.write_bytes(data)
                        return path
                    except SessionRejected:
                        raise
                    except (DownloadError, OSError, ValueError) as error:
                        last_error = error
                        if attempt < 3:
                            time.sleep(0.35 * (attempt + 1))
                raise DownloadError(f"Could not download tile {column}_{row}: {last_error}")

            jobs = [(column, row) for row in range(rows) for column in range(columns)]
            completed = 0
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(fetch, column, row) for column, row in jobs]
                try:
                    for future in as_completed(futures):
                        future.result()
                        completed += 1
                        report(
                            0.18 + 0.65 * completed / total,
                            f"Downloaded tiles: {completed} / {total}",
                        )
                except BaseException:
                    for future in futures:
                        future.cancel()
                    raise

            with Image.open(tile_dir / f"{columns - 1}_0.jpg") as tile:
                last_width = tile.width
            with Image.open(tile_dir / f"0_{rows - 1}.jpg") as tile:
                last_height = tile.height
            width = (
                last_width
                if columns == 1
                else (columns - 1) * TILE_SIZE - TILE_OVERLAP + last_width
            )
            height = (
                last_height if rows == 1 else (rows - 1) * TILE_SIZE - TILE_OVERLAP + last_height
            )
            if width <= 0 or height <= 0 or width * height > 250_000_000:
                raise DownloadError("The assembled image has invalid dimensions.")

            report(0.88, f"Assembling image: {width} x {height}")
            with Image.new("RGB", (width, height), "black") as canvas:
                for row in range(rows):
                    for column in range(columns):
                        with Image.open(tile_dir / f"{column}_{row}.jpg") as source:
                            with source.convert("RGB") as tile:
                                x = max(0, column * TILE_SIZE - TILE_OVERLAP)
                                y = max(0, row * TILE_SIZE - TILE_OVERLAP)
                                canvas.paste(tile, (x, y))

                output_path = output_dir / document.filename
                with atomic_output(output_path) as temporary:
                    canvas.save(
                        temporary,
                        "JPEG",
                        quality=jpeg_quality,
                        subsampling=0,
                        optimize=True,
                    )

        report(1.0, "Done")
        return DownloadResult(
            path=output_path,
            width=width,
            height=height,
            level=level,
            columns=columns,
            rows=rows,
        )
    finally:
        client.close()
