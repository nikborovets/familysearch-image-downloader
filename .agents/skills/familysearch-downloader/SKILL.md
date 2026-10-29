---
name: familysearch-downloader
description: Download FamilySearch archive pages or complete image groups from ARK, groupId, or imageGroupNumbers links, including Markdown research tables; maintain and verify this Python CLI repository.
---

# FamilySearch downloader

Use the repository's CLI to download documents, and follow these shared instructions when changing its code. This file is the canonical instruction for all agents; `AGENTS.md` points here.

## Locate and run

Find the checkout by its `cli.py`, `downloader.py`, and `requirements.txt`. When this skill is installed as a symlink, resolve its target to locate the checkout. Run commands from the repository root. If working from a different machine, use that machine's checkout rather than a hard-coded author path.

- macOS: `./run.command download "URL"` bootstraps the local virtual environment.
- Other systems: create `.venv`, install `requirements.txt`, and run `python cli.py download "URL"` with that environment activated.
- Batch: `python cli.py download --from-file cases.md --out downloads`.
- Saved authentication: `python cli.py login`; removal: `python cli.py logout`.

`login` requires the user to paste their browser's `fssessionid` into a hidden terminal prompt. Reuse the saved session without printing it. If no session is available, ask the user to run `login` in their terminal; do not ask them to send the cookie through chat. Do not include cookies, authorization headers, or their cache in artifacts or commits.

## Choose the download scope

- `/ark:/61903/3:1:…?i=0` downloads one image; `i` is zero-based.
- An ARK viewer link with `groupId=TH-…` downloads its entire group.
- `/en/records/images/search-results?imageGroupNumbers=000000001` downloads the complete DGS group. Use one numeric DGS per URL.
- `--from-file` reads URL lists and extracts links from Markdown tables, including several links in a cell. It preserves link order and removes exact duplicates. Table priorities and archival references do not override API metadata.

Quote URLs in shell commands. Preserve the built-in pacing; `--workers` controls concurrent tile requests, not simultaneous pages. For a request to verify access, resolve group metadata and download one representative page instead of starting hundreds of pages. For an explicit request to download complete groups, run the complete requested batch.

## Verify and report

Completed files are named by page and ARK ID. Group folders use archival reference plus DGS, or DGS alone when metadata is unavailable. `info.txt` retains the source information.

An interrupted batch can be rerun: readable JPEGs are skipped and damaged files are replaced. Resume is per page; temporary tiles do not survive between runs. Exit codes: `0` success or skipped, `1` download/input/access failure, `2` invalid CLI arguments, `130` interruption.

Report the actual saved location, counts and failures. Distinguish metadata verification, mock tests, and a real completed download. Decode a representative JPEG to verify it. On session rejection in unattended mode, stop and ask the user to refresh login. Avoid indefinite retries against rejected sessions or persistent server failures.

## Maintain the repository

Read [README.md](../../../README.md) for usage and [docs/architecture.md](../../../docs/architecture.md) when changing URL resolution, API calls, grid detection or image assembly.

- `cli.py` owns commands, input files, the batch queue, progress and exit codes.
- `downloader.py` owns URLs, API access, session storage, pacing, tiles and assembly.
- Preserve atomic publication of JPEGs and credentials, image checks before skipping, overlap handling, grid limits, cancellation of pending futures, and closure of HTTP sessions.
- Keep session rejection separate from general download errors so the CLI can refresh authentication.
- FamilySearch's internal API may change. Use mock responses for offline regression tests and, when a saved session exists and the task warrants it, a small live check. Do not treat mock tests as evidence of live access.

For relevant code changes, install `requirements-dev.txt` and run:

```bash
python -m unittest discover -s tests -v
python -m ruff check .
python -m ruff format --check .
```

Publish source, tests, documentation, examples and this skill. Keep downloaded images, local credentials, caches, research notes and transcriptions out of Git. Preserve the README attribution to `thefirans/familysearch-image-downloader`. Check the actual upstream license before adding or changing licensing claims; attribution alone does not establish a license.

## Publication and examples

Use visibly fictional identifiers and generic descriptions in documentation, fixtures and tests. Do not copy user-provided URLs, archive references, names, research questions or live-check results into publishable files. Keep personal URL lists in the ignored `private/` directory. A successful live check does not make its inputs suitable for publication.

Before publishing or recreating a remote repository, show the user the exact proposed file list and summarize the privacy checks, then wait for explicit confirmation for that upload. Do not treat permission from an earlier upload as approval for a replacement publication. Scan the complete reachable Git history as well as the current files; deleting a value in a later commit does not remove it from older commits.
