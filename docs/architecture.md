# Architecture

## From URL to image

1. The CLI collects URLs from arguments and an input file, removes exact duplicates, and validates formats before requesting a session.
2. For `groupId` links, `image-data` resolves the DGS number. For `imageGroupNumbers` links, the number comes directly from the URL.
3. A metadata query supplies the title and archive reference; `film-data` returns ARK links. Optional metadata failures do not prevent page downloads.
4. Pages enter the queue in source order. Existing JPEGs are decoded and skipped if readable.
5. The downloader detects the highest available DeepZoom level and grid dimensions. Boundary detection uses exponential and binary search.
6. Worker threads download tiles using separate HTTP sessions and a shared request pacer.
7. Pillow assembles tiles with their overlap. A JPEG is saved to a temporary file beside the destination and atomically replaces it after saving succeeds.

## Design decisions

- Two application modules keep the CLI runnable without packaging. A package would become useful with another interface or additional image sources.
- HTTP failures become `DownloadError`; authentication rejection becomes `SessionRejected`. The CLI owns session refresh and queue decisions.
- A failed group counts as one failure because its page count may be unknown.
- Limits are 100 tiles per axis, 2,500 tiles total, and 250 million pixels. Exceeding an axis limit raises an error instead of silently cropping the image.
- Session and JPEG writes use unique temporary files. Session values are not accepted as CLI arguments or logged.
- Failures and interruptions cancel pending tasks. In-flight HTTP requests may continue until completion or timeout.

## Limitations

- FamilySearch's internal API is not a stable public contract. Mock tests validate expected responses but cannot establish live access.
- Assembly keeps the full RGB image in memory. The upper pixel limit can require substantial RAM.
- Resume operates at page level. Forced process termination may leave a hidden temporary file, which is never treated as a completed JPEG.
- The `i` parameter controls viewer order, not a document's printed page numbers.
- Tables supply URLs; descriptions and priorities are not imported into `info.txt`.
- Concurrent runs targeting the same folder are not locked. Atomic replacement protects file integrity but does not prevent duplicate downloads.

## Possible improvements

- A persistent manifest with checksums and failed-page records for large batches.
- Retry handling that respects `Retry-After` for HTTP 429 and temporary server failures.
- Page range selection and group previews without downloading full images.
- A separate API adapter with synthetic response fixtures.
- Optional import of archive labels and priorities from research tables.

These features are not implemented yet.
