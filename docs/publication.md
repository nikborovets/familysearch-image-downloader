# Publication review

The repository owner approved publication of the reviewed contents on October 30, 2026. This document records the publication scope and checks for future updates.

## Proposed file list

Only these project files are prepared for publication:

```text
.agents/skills/familysearch-downloader/SKILL.md
.editorconfig
.github/workflows/ci.yml
.gitignore
AGENTS.md
README.md
cli.py
docs/architecture.md
docs/publication.md
downloader.py
examples/cases.md
examples/urls.txt
pyproject.toml
requirements-dev.txt
requirements.txt
run.command
tests/test_downloader.py
tests/test_image_groups.py
tests/test_reliability.py
```

Offline test fixtures and generic folder layouts use fictional identifiers. Runnable examples use one independently sourced public census page, as requested by the user. Its provenance is recorded in the README and example files.

Approved public example URLs:

- Census page: https://www.familysearch.org/ark:/61903/3:1:S3HT-6WLQ-WX3?i=13
- Optional whole-group link: https://www.familysearch.org/en/records/images/search-results?imageGroupNumbers=004115246
- Provenance: https://community.familysearch.org/en/discussion/92300/why-cant-i-find-a-name-in-a-fs-census-record-but-i-can-find-it-on-ancestry-com
- Collection description: https://www.familysearch.org/en/search/collection/1325221

Replace example URLs with personal inputs only in the ignored `private/` directory.

Downloaded images, session credentials, research materials, transcriptions, local input files, caches, and temporary live-check results are excluded.

## Checks before upload

- Inspect the exact file list and every reachable commit, including file names and commit messages.
- Scan for personal research URLs, archive references, research descriptions, personal paths, and saved credentials. Allow only the independently sourced public example URLs listed above in documentation; keep test fixtures synthetic.
- Confirm runnable examples cite their public source and generic layouts and test fixtures are clearly synthetic.
- Run the offline tests, lint checks, formatting checks, and skill validation.
- Show the prepared contents to the user and wait for explicit approval before creating a remote repository or pushing.

Keep the attribution to [the original project](https://github.com/thefirans/familysearch-image-downloader).
