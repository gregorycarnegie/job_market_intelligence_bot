import logging
import os


def setup_logging() -> None:
    """
    Configure the root logger based on the LOG_LEVEL environment variable.

    Subsequent calls are no-ops because basicConfig is skipped when the
    root logger already has handlers. Default level is INFO.
    """
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
