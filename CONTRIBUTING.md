# Contributing

## Dev Setup

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/gregorycarnegie/job_market_intelligence_bot.git
cd job_market_intelligence_bot
uv sync --extra dev
```

Optional local setup files:

```bash
cp .env.example .env
```

If you need `company_boards.json` or `job_search_config.json`, create them manually. Example values are documented in `README.md`, but example files are not currently committed to the repo.

Edit `resume.json` with your own skills, target roles, and location preferences before running the bot locally.

## Running The Tests

Quick full-suite run:

```bash
uv run python -m unittest discover -s tests -v
```

CI-equivalent coverage run:

```bash
uv run --extra dev pytest --cov=jobbot tests/ --cov-fail-under=85 --cov-report=term-missing
```

The GitHub Actions workflow currently enforces a minimum of **85% coverage**.

## Code Quality

All the following should pass before merging:

```bash
uv run ruff check .          # linter
uv run ruff format --check . # formatter
uv run mypy .                # type checker
uv run pylint jobbot         # style/complexity
uv audit                     # dependency vulnerability scan
```

Auto-format before committing with:

```bash
uv run ruff format .
```

## Adding A New Job Source

1. Create a class in `jobbot/sources.py` that extends the abstract `Source` base class and implements `fetch() -> list[JobLead]`.
2. Register it in `create_source()` in `jobbot/sources.py`.
3. If you are adding a new company-board platform, also update the board-specific dispatch and normalization paths in `jobbot/sources.py`.
4. Add tests in `tests/` covering the happy path and at least one failure mode.
5. Document any new config keys in `README.md`. If the repo later gains committed example config files, update those too.

## Project Layout

```text
jobbot/
  models.py         # JobLead dataclass and shared typed state models
  sources.py        # Source integrations and company-board loaders
  matching.py       # Scoring pipeline, alerts, digest, feedback learning
  storage.py        # SQLite abstraction and schema migrations
  common.py         # Constants, built-in feeds, config loading, text helpers
  logging_config.py # Structured logging setup
pull_jobs.py        # Main entrypoint: fetch -> score -> persist -> alert
pull_desc.py        # Stages the latest matched batch into desc.json
telegram_callback_worker.py  # Long-polls Telegram callback_query updates
tests/              # unittest/pytest-compatible test suite
```
