import logging
from time import sleep

from jobbot import matching

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

LONG_POLL_TIMEOUT_SECONDS = 25
ERROR_RETRY_SECONDS = 5
MISSING_TOKEN_RETRY_SECONDS = 30


def run_callback_worker(
    poll_timeout: int = LONG_POLL_TIMEOUT_SECONDS,
    error_retry_seconds: int = ERROR_RETRY_SECONDS,
    missing_token_retry_seconds: int = MISSING_TOKEN_RETRY_SECONDS,
    max_cycles: int | None = None,
) -> int:
    warned_missing_token = False
    cycles_completed = 0

    while max_cycles is None or cycles_completed < max_cycles:
        cycles_completed += 1
        token, _, _ = matching.load_telegram_settings()
        if not token:
            if not warned_missing_token:
                logger.warning("Telegram worker: TELEGRAM_BOT_TOKEN not configured; waiting for credentials.")
            warned_missing_token = True
            sleep(max(1, missing_token_retry_seconds))
            continue

        warned_missing_token = False
        _, error = matching.process_telegram_callback_updates(timeout=max(0, poll_timeout))
        if error:
            logger.error(f"Telegram worker: {error}")
            sleep(max(1, error_retry_seconds))

    return 0


def main() -> int:
    return run_callback_worker()


if __name__ == "__main__":
    raise SystemExit(main())
