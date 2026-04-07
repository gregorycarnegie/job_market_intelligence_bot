# Contributing

## Dev setup

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <repo-url>
cd job_market_intelligence_bot-main
uv sync --extra dev
```

Copy the example config files and fill them in:

```bash
cp .env.example .env
cp company_boards.json.example company_boards.json      # optional
cp job_search_config.json.example job_search_config.json  # optional
```

Edit `resume.json` with your own skills, target roles, and location preferences before running.

## Running the tests

```bash
uv run pytest tests/ --cov=jobbot --cov-report=term-missing
```

The CI enforces a minimum of **85% coverage**. New code should include tests.

## Code quality

All of the following must pass before merging:

```bash
uv run ruff check .          # linter
uv run ruff format --check . # formatter
uv run mypy .                # type checker
uv run pylint jobbot         # style/complexity
uv run uv audit              # dependency vulnerability scan
```

Run `uv run ruff format .` to auto-format before committing.

## Adding a new job source

1. Create a class in [jobbot/sources.py](jobbot/sources.py) that extends the abstract `Source` base class and implements `fetch() -> list[JobLead]`.
2. Register an instance of the new source in the `build_sources()` factory (also in `sources.py`).
3. Add tests in `tests/` covering both the happy path and at least one failure mode (e.g. HTTP error, empty response).
4. Document any required config keys in `company_boards.json.example` or `job_search_config.json.example` as appropriate.

## Project layout

```text
jobbot/
  models.py         # JobLead dataclass and abstract Source base class
  sources.py        # All source integrations (RSS, Greenhouse, Lever, Ashby, ...)
  matching.py       # Scoring pipeline, alerts, digest, feedback learning
  storage.py        # SQLite abstraction and schema migrations
  common.py         # Constants, config loading, text helpers
  logging_config.py # Structured logging setup
pull_jobs.py        # Main entrypoint — orchestrates fetch → score → alert
pull_desc.py        # Stages latest batch into desc.json for OpenClaw
telegram_callback_worker.py  # Long-polls Telegram callback_query updates
tests/              # unittest-based test suite
```
