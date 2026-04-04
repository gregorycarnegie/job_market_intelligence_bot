import unittest
from unittest import mock

import telegram_callback_worker


class TelegramCallbackWorkerTestCase(unittest.TestCase):
    def test_run_callback_worker_uses_long_polling(self) -> None:
        with (
            mock.patch("telegram_callback_worker.matching.load_telegram_settings", return_value=("token", "chat", "")),
            mock.patch(
                "telegram_callback_worker.matching.process_telegram_callback_updates",
                return_value=(0, ""),
            ) as process_updates,
            mock.patch("telegram_callback_worker.sleep") as sleep_mock,
        ):
            result = telegram_callback_worker.run_callback_worker(max_cycles=1)

        self.assertEqual(result, 0)
        process_updates.assert_called_once_with(timeout=telegram_callback_worker.LONG_POLL_TIMEOUT_SECONDS)
        sleep_mock.assert_not_called()

    def test_run_callback_worker_waits_for_credentials_without_busy_loop(self) -> None:
        with (
            mock.patch(
                "telegram_callback_worker.matching.load_telegram_settings",
                side_effect=[("", "", ""), ("token", "chat", "")],
            ),
            mock.patch(
                "telegram_callback_worker.matching.process_telegram_callback_updates",
                return_value=(0, ""),
            ) as process_updates,
            mock.patch("telegram_callback_worker.sleep") as sleep_mock,
        ):
            result = telegram_callback_worker.run_callback_worker(max_cycles=2)

        self.assertEqual(result, 0)
        process_updates.assert_called_once_with(timeout=telegram_callback_worker.LONG_POLL_TIMEOUT_SECONDS)
        sleep_mock.assert_called_once_with(telegram_callback_worker.MISSING_TOKEN_RETRY_SECONDS)


if __name__ == "__main__":
    unittest.main()
