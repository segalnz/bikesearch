# Contributing

Use Python 3.11 or later in a virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m ruff check src scripts tests
.venv/bin/python -m ruff format --check src scripts tests
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_publication.py
```

Tests use synthetic fixtures and mocked network services. Do not run production
collection or paid API calls from CI. Use `scripts/demo.py` for an offline preview.

Keep eligibility rules independent of network/database code. Add source-specific
HTML knowledge in acquisition adapters; propagate uncertain facts as unknown.
A new source must describe how complete its collection is. Partial discovery
must not drive missing-listing transitions. Reproduce parser bugs with small,
sanitized fixtures, never saved customer details, tokens or full copied websites.

Before publishing, stage only source/configuration examples and run
`.venv/bin/python scripts/check_publication.py --index`. Keep credentials,
local profiles, real configuration, logs, databases, caches and backups private.
The repository does not grant a reuse license until its owner adds one.
