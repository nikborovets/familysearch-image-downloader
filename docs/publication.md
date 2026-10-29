# Publication review

Publication is pending user approval. No remote upload is part of this cleanup.

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

Examples and fixtures use fictional identifiers and generic descriptions. Replace example URLs with personal inputs only in the ignored `private/` directory.

Downloaded images, session credentials, research materials, transcriptions, local input files, caches, and temporary live-check results are excluded.

## Checks before upload

- Inspect the exact file list and every reachable commit, including file names and commit messages.
- Scan for real document URLs, archive references, research descriptions, personal paths, and saved credentials.
- Confirm examples are clearly labeled as fictional.
- Run the offline tests, lint checks, formatting checks, and skill validation.
- Show the prepared contents to the user and wait for explicit approval before creating a remote repository or pushing.

Keep the attribution to [the original project](https://github.com/thefirans/familysearch-image-downloader).
