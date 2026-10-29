<div align="center">

# FamilySearch Image Downloader

**Download archive pages as full-resolution JPEGs, in reading order.**

Python 3.11+ · CLI · Individual pages and complete image groups · Resume support

[Quick start](#quick-start) · [Links and tables](#links-and-tables) · [Options](#options) · [Development](#development)

</div>

---

Based on [thefirans/familysearch-image-downloader](https://github.com/thefirans/familysearch-image-downloader). Thanks to the original author for the foundation. This version expands the CLI, batch downloading, and support for digital image group links.

The downloader retrieves available FamilySearch DeepZoom tiles and assembles them at the highest detected resolution. Complete image groups receive a separate folder containing numbered pages and source metadata.

- **Three link formats:** ARK pages, viewers with `groupId`, and searches with `imageGroupNumbers`.
- **Batch input:** command-line arguments, text files, or Markdown tables.
- **Resume support:** readable JPEGs are skipped; damaged files are downloaded again.
- **Atomic output:** the final JPEG is published only after saving succeeds.
- **Clear results:** saved, skipped, and failed counts, with a nonzero exit code on failure.

## Quick start

The runnable example downloads one page from the **United States Census, 1900**: [open the census image](https://www.familysearch.org/ark:/61903/3:1:S3HT-6WLQ-WX3?i=13). This example was selected independently from a [public FamilySearch Community discussion](https://community.familysearch.org/en/discussion/92300/why-cant-i-find-a-name-in-a-fs-census-record-but-i-can-find-it-on-ancestry-com), rather than from personal research inputs. Store your own URL lists in the ignored `private/` directory.

The image preview and its group metadata were checked with a signed-in session on October 30, 2026. FamilySearch may require you to sign in; access depends on your account. Offline tests continue to use synthetic fixtures.

Requires Python 3.11+ and a signed-in FamilySearch session with access to the requested images.

### macOS

From the repository directory:

```bash
./run.command login
./run.command download "https://www.familysearch.org/ark:/61903/3:1:S3HT-6WLQ-WX3?i=13"
```

The launcher creates `.venv` and installs dependencies when needed.

### Linux / Windows

```bash
python -m venv .venv
# Linux:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt
python cli.py login
python cli.py download "https://www.familysearch.org/ark:/61903/3:1:S3HT-6WLQ-WX3?i=13"
```

### Authentication

Open a document in a browser where you are signed in to FamilySearch. In DevTools → Network, select a `familysearch.org` request, then find Cookies → `fssessionid`. Paste its value at the hidden `login` prompt. The `fssessionid=value` form is also accepted.

The session is stored locally, outside the repository:

| Platform | Location |
| --- | --- |
| macOS | `~/Library/Caches/familysearch-image-downloader/fssessionid` |
| Linux | `$XDG_CACHE_HOME/familysearch-image-downloader/fssessionid`, defaulting to `~/.cache/…` |
| Windows | `%LOCALAPPDATA%\familysearch-image-downloader\fssessionid` |

On POSIX systems, the file is created with mode `600`. If FamilySearch rejects the session, an interactive run asks for a replacement; an unattended run exits with an error. To remove the saved value:

```bash
python cli.py logout
```

## Links and tables

Quote URLs containing `&` or `?` in shell commands.

| Link format | Download scope |
| --- | --- |
| `/ark:/61903/3:1:…?i=0` | One page; `i` is zero-based |
| `/ark:/61903/3:1:…?groupId=TH-…` | Every page in the group |
| `/en/records/images/search-results?imageGroupNumbers=004115246` | Every page in the specified DGS image group |

Each search link must contain one numeric `imageGroupNumbers` value. The public census page belongs to [DGS 004115246](https://www.familysearch.org/en/records/images/search-results?imageGroupNumbers=004115246), titled *12th Census of Population 1900*. The group contained **1,128 images** when checked. A group link downloads the entire group; use the single-page example above for a quick first run.

Pass several URLs as arguments, or use an input file:

```bash
python cli.py download --from-file examples/urls.txt
```

Markdown tables work too. Save personal tables under `private/`, or try the supplied public example:

```markdown
| Priority | Document | FS |
| --- | --- | --- |
| 1 | United States Census, 1900 — sample page | [Open image](https://www.familysearch.org/ark:/61903/3:1:S3HT-6WLQ-WX3?i=13) |
```

```bash
python cli.py download --from-file examples/cases.md
```

Markdown input supports multiple links in one cell. Other columns do not affect downloading: links are processed in their input order, and folder names come from FamilySearch metadata. Exact duplicate input links are processed once.

See the public single-page example in [`examples/cases.md`](examples/cases.md).

For `.txt` files, use one URL per line. Blank lines and lines starting with `#` are ignored. See [`examples/urls.txt`](examples/urls.txt).

## Options

| Option | Default | Purpose |
| --- | --- | --- |
| `-f, --from-file FILE` | — | URL list or Markdown table |
| `-o, --out DIR` | `downloads` | Output directory |
| `--quality 70…100` | `95` | JPEG quality |
| `--workers 1…16` | `4` | Concurrent tile download workers |

```bash
python cli.py download --from-file private/cases.md --out ./archive --quality 95 --workers 4
python cli.py download --help
```

`run.command` runs from the repository directory, so relative paths are resolved from there. When calling `python cli.py` directly, paths are relative to the terminal's current directory.

## Output and resuming

The single-page example saves `downloads/0014_familysearch_S3HT-6WLQ-WX3.jpg`. The generic group layout below uses fictional names:

```text
downloads/
└── DEMO-ARCHIVE_000000001/
    ├── info.txt
    ├── 0001_familysearch_EXAMPLE-PAGE-1.jpg
    └── 0002_familysearch_EXAMPLE-PAGE-2.jpg
```

Group folders use the archive reference and DGS number. If the reference is unavailable, the DGS number is used alone. `info.txt` records the title, reference, identifiers, page count, and source URL. Individual image links without `i` produce filenames without a page prefix.

Rerun the same command to resume an interrupted batch. Existing images are fully decoded before being skipped. An unfinished page is downloaded again; individual tiles are not retained between runs. Checking a large collection can take time.

Requests are paced, with a 10–25 second pause between newly downloaded pages. Download time depends on the number of tiles and server response times.

| Exit code | Meaning |
| --- | --- |
| `0` | All requested images were downloaded or already present |
| `1` | Input, access, filesystem, or download failure |
| `2` | Invalid CLI arguments |
| `130` | Interrupted with Ctrl+C |

A failed download does not stop the remaining queue. Filesystem errors or a rejected session during an unattended run stop the batch.

## Troubleshooting

| Message or situation | Action |
| --- | --- |
| `No saved fssessionid` | Run `login` |
| `FamilySearch rejected…` | Sign in through the browser and save a fresh cookie |
| HTTP 429 / 5xx | Retry later; completed pages will be skipped |
| `No images were found…` | Check the link and your access in the browser |
| `invalid JSON response` | The server returned an unexpected response; retry later |
| Interrupted download | Repeat the original command |

The tool uses internal FamilySearch endpoints, which may change. Your session must have access to the requested images in the browser.

## Development

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m ruff check .
python -m ruff format --check .
```

Tests run offline without an account. They cover URL parsing, CLI behavior, session storage, grid bounds, tile assembly, failure recovery, and API response handling. The GitHub Actions configuration tests Python 3.11–3.14.

| File | Responsibility |
| --- | --- |
| [`cli.py`](cli.py) | Commands, input files, queue, progress, and results |
| [`downloader.py`](downloader.py) | URLs, API access, sessions, tiles, and JPEG assembly |
| [`tests/`](tests/) | Offline regression tests with synthetic inputs |
| [`docs/architecture.md`](docs/architecture.md) | Design, limitations, and possible improvements |
| [`docs/publication.md`](docs/publication.md) | Proposed publication contents and review procedure |
| [`run.command`](run.command) | macOS launcher using a local environment |

## Agent instructions

The shared instruction lives in [`.agents/skills/familysearch-downloader/SKILL.md`](.agents/skills/familysearch-downloader/SKILL.md). Root [`AGENTS.md`](AGENTS.md) directs agents to that same file, keeping usage and development guidance in one place.

The skill covers pages and groups, Markdown tables, local authentication, verification, and publication review. Agents supporting `SKILL.md` can load it directly; other agents can follow the reference in `AGENTS.md`.
