import unittest
from typing import Any, cast
from unittest import mock

from jobbot import matching
from jobbot.common import (
    fresh_applications_state,
)
from jobbot.models import AlertState, SearchConfig


class NormalizeCurrencyTokenTestCase(unittest.TestCase):
    def test_pound_sign(self) -> None:
        self.assertEqual(matching.normalize_currency_token("£"), "gbp")

    def test_gbp_string(self) -> None:
        self.assertEqual(matching.normalize_currency_token("GBP"), "gbp")

    def test_dollar_sign(self) -> None:
        self.assertEqual(matching.normalize_currency_token("$"), "usd")

    def test_usd_string(self) -> None:
        self.assertEqual(matching.normalize_currency_token("USD"), "usd")

    def test_euro_sign(self) -> None:
        self.assertEqual(matching.normalize_currency_token("€"), "eur")

    def test_eur_string(self) -> None:
        self.assertEqual(matching.normalize_currency_token("EUR"), "eur")

    def test_unknown_returns_empty(self) -> None:
        self.assertEqual(matching.normalize_currency_token("JPY"), "")


class DetectSalaryCadenceTestCase(unittest.TestCase):
    def test_hourly(self) -> None:
        self.assertEqual(matching.detect_salary_cadence("£25 per hour"), "hour")

    def test_daily(self) -> None:
        self.assertEqual(matching.detect_salary_cadence("£500 per day"), "day")

    def test_daily_rate(self) -> None:
        self.assertEqual(matching.detect_salary_cadence("£400 day rate"), "day")

    def test_monthly(self) -> None:
        self.assertEqual(matching.detect_salary_cadence("£3000 per month"), "month")

    def test_defaults_to_year(self) -> None:
        self.assertEqual(matching.detect_salary_cadence("£50,000 salary"), "year")


class ParseSalaryAmountTestCase(unittest.TestCase):
    def test_plain_number(self) -> None:
        self.assertEqual(matching.parse_salary_amount("50000", None), 50000.0)

    def test_k_suffix(self) -> None:
        self.assertEqual(matching.parse_salary_amount("50", "k"), 50000.0)

    def test_with_commas(self) -> None:
        self.assertEqual(matching.parse_salary_amount("50,000", None), 50000.0)


class AnnualizeSalaryToGbpTestCase(unittest.TestCase):
    def test_annual_gbp_unchanged(self) -> None:
        result = matching.annualize_salary_to_gbp(50000.0, "gbp", "year")
        self.assertEqual(result, 50000)

    def test_hourly_to_annual(self) -> None:
        result = matching.annualize_salary_to_gbp(25.0, "gbp", "hour")
        self.assertGreater(result, 40000)

    def test_usd_converted(self) -> None:
        result = matching.annualize_salary_to_gbp(100000.0, "usd", "year")
        self.assertGreater(result, 0)
        self.assertLess(result, 100000)


class ExtractSalaryRangeGbpTestCase(unittest.TestCase):
    def test_gbp_range(self) -> None:
        result = matching.extract_salary_range_gbp("£40,000 - £60,000 per year")
        self.assertIsNotNone(result)
        assert result is not None
        r = cast(dict[str, Any], result)
        self.assertEqual(r["currency"], "gbp")
        self.assertGreaterEqual(cast(float, r["min_gbp"]), 40000)
        self.assertLessEqual(cast(float, r["max_gbp"]), 60000)

    def test_gbp_with_k_suffix(self) -> None:
        result = matching.extract_salary_range_gbp("£40k - £60k")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertGreaterEqual(cast(float, result["min_gbp"]), 40000)

    def test_usd_range(self) -> None:
        result = matching.extract_salary_range_gbp("$80,000 - $100,000")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["currency"], "usd")

    def test_single_salary(self) -> None:
        result = matching.extract_salary_range_gbp("Salary: £55,000")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["min_gbp"], result["max_gbp"])

    def test_no_salary_returns_none(self) -> None:
        self.assertIsNone(matching.extract_salary_range_gbp("competitive salary offered"))

    def test_too_small_annual_salary_skipped(self) -> None:
        result = matching.extract_salary_range_gbp("£5 - £10 per year")
        self.assertIsNone(result)

    def test_trailing_currency_label(self) -> None:
        result = matching.extract_salary_range_gbp("50000 to 70000 GBP")
        self.assertIsNotNone(result)

    def test_hourly_rate(self) -> None:
        result = matching.extract_salary_range_gbp("£25 per hour")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["cadence"], "hour")


class FormatSalaryInfoForReasonTestCase(unittest.TestCase):
    def test_gbp_annual_format(self) -> None:
        info = {"min_gbp": 40000, "max_gbp": 60000, "currency": "gbp", "cadence": "year"}
        result = matching.format_salary_info_for_reason(info)
        self.assertIn("40,000", result)
        self.assertIn("60,000", result)
        self.assertNotIn("from", result)

    def test_usd_includes_currency(self) -> None:
        info = {"min_gbp": 50000, "max_gbp": 70000, "currency": "usd", "cadence": "year"}
        result = matching.format_salary_info_for_reason(info)
        self.assertIn("USD", result)

    def test_hourly_includes_cadence(self) -> None:
        info = {"min_gbp": 40000, "max_gbp": 40000, "currency": "gbp", "cadence": "hour"}
        result = matching.format_salary_info_for_reason(info)
        self.assertIn("hour", result)


class EvaluateCompanyPreferencesTestCase(unittest.TestCase):
    def _config(self, **kwargs) -> SearchConfig:
        from jobbot.common import build_pattern_entries

        return {
            "company_whitelist": [],
            "company_blacklist": [],
            "priority_companies": [],
            "company_blacklist_entries": build_pattern_entries(kwargs.get("blacklist", [])),
            "priority_company_entries": build_pattern_entries(kwargs.get("priority", [])),
            "company_whitelist_entries": build_pattern_entries(kwargs.get("whitelist", [])),
            "role_profiles": [],
            "daily_digest": {},
            "feedback": {},
        }

    def test_empty_company_always_qualifies(self) -> None:
        result = matching.evaluate_company_preferences("", self._config())
        self.assertTrue(result["qualified"])
        self.assertEqual(result["control"], "none")

    def test_blacklisted_company_disqualified(self) -> None:
        config = self._config(blacklist=["bad recruiter"])
        result = matching.evaluate_company_preferences("Bad Recruiter Ltd", config)
        self.assertFalse(result["qualified"])
        self.assertEqual(result["control"], "blacklist")

    def test_priority_company_shortlisted(self) -> None:
        config = self._config(priority=["monzo"])
        result = matching.evaluate_company_preferences("Monzo", config)
        self.assertTrue(result["qualified"])
        self.assertTrue(result["shortlisted"])
        self.assertEqual(result["control"], "priority")

    def test_whitelisted_company_scores_higher(self) -> None:
        config = self._config(whitelist=["acme"])
        result = matching.evaluate_company_preferences("Acme Corp", config)
        self.assertTrue(result["qualified"])
        self.assertFalse(result["shortlisted"])
        self.assertEqual(result["control"], "whitelist")
        self.assertGreater(cast(int, result["score_delta"]), 0)

    def test_unknown_company_qualifies_with_no_boost(self) -> None:
        result = matching.evaluate_company_preferences("Unknown Co", self._config())
        self.assertTrue(result["qualified"])
        self.assertEqual(result["score_delta"], 0)
        self.assertEqual(result["control"], "none")


class EvaluateLocationFitTestCase(unittest.TestCase):
    def test_relocation_always_fits(self) -> None:
        ok, reason = matching.evaluate_location_fit("on site in tokyo", [], {"relocation": True}, [])
        self.assertTrue(ok)
        self.assertIn("relocation", reason)

    def test_remote_pref_fits_remote_job(self) -> None:
        ok, _reason = matching.evaluate_location_fit("remote position anywhere in the uk", ["uk"], {"remote": True}, [])
        self.assertTrue(ok)

    def test_locked_out_location_rejected(self) -> None:
        ok, reason = matching.evaluate_location_fit("remote us only", ["uk"], {"remote": True}, ["remote us"])
        self.assertFalse(ok)
        self.assertIn("lockout", reason)

    def test_hybrid_pref_fits_local_hybrid(self) -> None:
        ok, _reason = matching.evaluate_location_fit("hybrid london role", ["london"], {"hybrid": True}, [])
        self.assertTrue(ok)

    def test_onsite_pref_fits_local_onsite(self) -> None:
        ok, _reason = matching.evaluate_location_fit("in office london position", ["london"], {"onsite": True}, [])
        self.assertTrue(ok)

    def test_no_match_rejected(self) -> None:
        ok, _reason = matching.evaluate_location_fit("dubai office based role", ["london"], {"onsite": True}, [])
        self.assertFalse(ok)


class FormatAlertMessageTestCase(unittest.TestCase):
    def _alert(self, **kwargs) -> dict:
        base = {
            "title": "IT Support Engineer",
            "link": "https://example.com/job/1",
            "score": 55,
            "reasons": ["strong skill match"],
            "company": "Monzo",
            "shortlisted": False,
            "company_control": "none",
            "role_profile": "",
            "source": "good_board",
        }
        base.update(kwargs)
        return base

    def test_includes_title_and_score(self) -> None:
        msg = matching.format_alert_message(self._alert())
        self.assertIn("IT Support Engineer", msg)
        self.assertIn("55", msg)

    def test_includes_company(self) -> None:
        msg = matching.format_alert_message(self._alert(company="Monzo"))
        self.assertIn("Company: Monzo", msg)

    def test_shortlisted_label(self) -> None:
        msg = matching.format_alert_message(self._alert(shortlisted=True))
        self.assertIn("shortlisted", msg)

    def test_whitelist_label(self) -> None:
        msg = matching.format_alert_message(self._alert(company_control="whitelist"))
        self.assertIn("whitelist", msg)

    def test_role_profile_included(self) -> None:
        msg = matching.format_alert_message(self._alert(role_profile="IT Support"))
        self.assertIn("Role Profile", msg)

    def test_includes_link(self) -> None:
        msg = matching.format_alert_message(self._alert())
        self.assertIn("https://example.com/job/1", msg)

    def test_no_company_section_when_empty(self) -> None:
        msg = matching.format_alert_message(self._alert(company=""))
        self.assertNotIn("Company:", msg)


class QueuePendingAlertsTestCase(unittest.TestCase):
    def test_queues_new_alerts(self) -> None:
        alert_state: AlertState = {
            "pending_alerts": [],
            "alerted_links": [],
            "last_run_utc": "",
            "last_delivery_utc": "",
            "last_delivery_error": "",
        }
        matches = [
            {
                "link": "https://example.com/job/1",
                "title": "IT Support",
                "time": "2026-04-04T10:00:00Z",
                "score": 55,
                "reasons": ["skill match"],
                "source": "board",
                "company": "Monzo",
                "shortlisted": False,
                "company_control": "none",
                "role_profile": "",
            }
        ]
        queued = matching.queue_pending_alerts(alert_state, matches)
        self.assertEqual(queued, 1)
        self.assertEqual(len(cast(list[object], alert_state["pending_alerts"])), 1)

    def test_does_not_queue_already_alerted(self) -> None:
        alert_state: AlertState = {
            "pending_alerts": [],
            "alerted_links": ["https://example.com/job/1"],
            "last_run_utc": "",
            "last_delivery_utc": "",
            "last_delivery_error": "",
        }
        matches = [
            {
                "link": "https://example.com/job/1",
                "title": "IT Support",
                "time": "2026-04-04T10:00:00Z",
                "score": 55,
                "reasons": [],
                "source": "board",
                "company": "",
                "shortlisted": False,
                "company_control": "none",
                "role_profile": "",
            }
        ]
        queued = matching.queue_pending_alerts(alert_state, matches)
        self.assertEqual(queued, 0)

    def test_does_not_queue_already_pending(self) -> None:
        existing = {
            "link": "https://example.com/job/1",
            "title": "IT Support",
            "time": "",
            "score": 50,
            "reasons": [],
            "source": "",
            "company": "",
            "shortlisted": False,
            "company_control": "none",
            "role_profile": "",
        }
        alert_state: AlertState = {
            "pending_alerts": [existing],
            "alerted_links": [],
            "last_run_utc": "",
            "last_delivery_utc": "",
            "last_delivery_error": "",
        }
        queued = matching.queue_pending_alerts(alert_state, [existing])
        self.assertEqual(queued, 0)


class DeliverPendingAlertsTestCase(unittest.TestCase):
    def test_returns_zero_when_no_pending(self) -> None:
        alert_state: AlertState = {
            "pending_alerts": [],
            "alerted_links": [],
            "last_run_utc": "",
            "last_delivery_utc": "",
            "last_delivery_error": "old error",
        }
        count, error = matching.deliver_pending_alerts(alert_state, "2026-04-04T10:00:00Z")
        self.assertEqual(count, 0)
        self.assertEqual(error, "")
        self.assertEqual(alert_state["last_delivery_error"], "")

    def test_returns_error_when_credentials_missing(self) -> None:
        alert_state: AlertState = {
            "pending_alerts": [{"link": "https://example.com/job/1", "title": "X", "score": 50, "reasons": []}],
            "alerted_links": [],
            "last_run_utc": "",
            "last_delivery_utc": "",
            "last_delivery_error": "",
        }
        with mock.patch.object(matching, "load_telegram_settings", return_value=("", "", "")):
            count, error = matching.deliver_pending_alerts(alert_state, "2026-04-04T10:00:00Z")
        self.assertEqual(count, 0)
        self.assertIn("Telegram credentials not configured", error)

    def test_sends_alerts_and_clears_pending(self) -> None:
        alert_state: AlertState = {
            "pending_alerts": [
                {
                    "link": "https://example.com/job/1",
                    "title": "IT Support",
                    "score": 55,
                    "reasons": ["skill match"],
                    "company": "Monzo",
                    "shortlisted": False,
                    "company_control": "none",
                    "role_profile": "",
                    "source": "board",
                }
            ],
            "alerted_links": [],
            "last_run_utc": "",
            "last_delivery_utc": "",
            "last_delivery_error": "",
        }
        with (
            mock.patch.object(matching, "load_telegram_settings", return_value=("token", "chat", "")),
            mock.patch.object(matching, "send_telegram_message", return_value=(True, "")),
        ):
            count, error = matching.deliver_pending_alerts(alert_state, "2026-04-04T10:00:00Z")

        self.assertEqual(count, 1)
        self.assertEqual(error, "")
        self.assertEqual(alert_state["pending_alerts"], [])
        self.assertIn("https://example.com/job/1", cast(list[str], alert_state["alerted_links"]))

    def test_stops_on_send_failure(self) -> None:
        alert_state: AlertState = {
            "pending_alerts": [
                {
                    "link": "https://example.com/job/1",
                    "title": "A",
                    "score": 50,
                    "reasons": [],
                    "company": "",
                    "shortlisted": False,
                    "company_control": "none",
                    "role_profile": "",
                    "source": "",
                },
                {
                    "link": "https://example.com/job/2",
                    "title": "B",
                    "score": 50,
                    "reasons": [],
                    "company": "",
                    "shortlisted": False,
                    "company_control": "none",
                    "role_profile": "",
                    "source": "",
                },
            ],
            "alerted_links": [],
            "last_run_utc": "",
            "last_delivery_utc": "",
            "last_delivery_error": "",
        }
        with (
            mock.patch.object(matching, "load_telegram_settings", return_value=("token", "chat", "")),
            mock.patch.object(matching, "send_telegram_message", return_value=(False, "network error")),
        ):
            count, error = matching.deliver_pending_alerts(alert_state, "2026-04-04T10:00:00Z")

        self.assertEqual(count, 0)
        self.assertIn("network error", error)
        self.assertEqual(len(cast(list[object], alert_state["pending_alerts"])), 2)


class ParseDigestCallbackDataTestCase(unittest.TestCase):
    def test_parses_valid_callback(self) -> None:
        session_id, page_token = matching.parse_digest_callback_data("dg:session123:1")
        self.assertEqual(session_id, "session123")
        self.assertEqual(page_token, "1")

    def test_returns_none_for_wrong_prefix(self) -> None:
        session_id, page_token = matching.parse_digest_callback_data("other:session:1")
        self.assertIsNone(session_id)
        self.assertIsNone(page_token)

    def test_returns_none_for_missing_parts(self) -> None:
        session_id, page_token = matching.parse_digest_callback_data("dg:only-two")
        self.assertIsNone(session_id)
        self.assertIsNone(page_token)

    def test_returns_none_for_empty_session_id(self) -> None:
        session_id, _page_token = matching.parse_digest_callback_data("dg::1")
        self.assertIsNone(session_id)


class BuildDailyDigestKeyboardTestCase(unittest.TestCase):
    def test_single_page_returns_none(self) -> None:
        self.assertIsNone(matching.build_daily_digest_keyboard("session1", 0, 1))

    def test_multi_page_returns_keyboard(self) -> None:
        keyboard = matching.build_daily_digest_keyboard("session1", 1, 3)
        self.assertIsNotNone(keyboard)
        assert keyboard is not None
        kb = cast(dict[str, Any], keyboard)
        buttons = kb["inline_keyboard"][0]
        self.assertEqual(len(buttons), 3)
        self.assertIn("2/3", buttons[1]["text"])

    def test_first_page_prev_is_noop(self) -> None:
        keyboard = matching.build_daily_digest_keyboard("session1", 0, 3)
        self.assertIsNotNone(keyboard)
        assert keyboard is not None
        prev_data = cast(dict[str, Any], keyboard)["inline_keyboard"][0][0]["callback_data"]
        self.assertIn("noop", prev_data)

    def test_last_page_next_is_noop(self) -> None:
        keyboard = matching.build_daily_digest_keyboard("session1", 2, 3)
        self.assertIsNotNone(keyboard)
        assert keyboard is not None
        next_data = cast(dict[str, Any], keyboard)["inline_keyboard"][0][2]["callback_data"]
        self.assertIn("noop", next_data)


class FormatDailyDigestMessagesTestCase(unittest.TestCase):
    def test_empty_items_returns_single_no_items_message(self) -> None:
        snapshot = {"digest_date_utc": "2026-04-04", "item_count": 0, "items": []}
        messages = matching.format_daily_digest_messages(snapshot, page_size=5)
        self.assertEqual(len(messages), 1)
        self.assertIn("No items", messages[0])

    def test_whitelist_badge_included(self) -> None:
        snapshot = {
            "digest_date_utc": "2026-04-04",
            "item_count": 1,
            "items": [
                {
                    "title": "Role",
                    "company": "Acme",
                    "link": "https://example.com/job/1",
                    "status": "new",
                    "score": 50,
                    "rank": 60,
                    "shortlisted": False,
                    "company_control": "whitelist",
                    "role_profile": "",
                    "reasons": ["skill match"],
                    "first_seen_utc": "2026-04-04T00:00:00Z",
                    "last_seen_utc": "2026-04-04T00:00:00Z",
                    "age_hours": 1.0,
                }
            ],
        }
        messages = matching.format_daily_digest_messages(snapshot, page_size=5)
        self.assertEqual(len(messages), 1)
        self.assertIn("whitelist", messages[0])


class SeedApplicationsFromExistingJobsTestCase(unittest.TestCase):
    def test_seeds_when_state_empty(self) -> None:
        state = fresh_applications_state()
        jobs = [
            {
                "time": "2026-04-04T10:00:00Z",
                "title": "IT Support Engineer at Monzo",
                "description": "London hybrid role",
                "link": "https://example.com/jobs/1",
            }
        ]
        created = matching.seed_applications_from_existing_jobs(state, jobs)
        self.assertEqual(created, 1)
        self.assertEqual(len(state["applications"]), 1)

    def test_does_not_seed_when_applications_exist(self) -> None:
        state = fresh_applications_state()
        state["applications"] = [{"title": "Existing", "link": "https://example.com/old"}]
        jobs = [{"time": "", "title": "New", "description": "", "link": "https://example.com/new"}]
        created = matching.seed_applications_from_existing_jobs(state, jobs)
        self.assertEqual(created, 0)
        self.assertEqual(len(state["applications"]), 1)

    def test_does_not_seed_when_no_jobs(self) -> None:
        state = fresh_applications_state()
        created = matching.seed_applications_from_existing_jobs(state, [])
        self.assertEqual(created, 0)


class NormalizeApplicationRecordTestCase(unittest.TestCase):
    def test_returns_none_when_no_title_or_link(self) -> None:
        self.assertIsNone(matching.normalize_application_record({}))

    def test_handles_non_list_fingerprints(self) -> None:
        payload = {
            "title": "IT Support Engineer",
            "link": "https://example.com/jobs/1",
            "fingerprints": "single-fingerprint",
        }
        result = matching.normalize_application_record(payload)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("single-fingerprint", cast(list[str], result["fingerprints"]))

    def test_handles_non_list_links(self) -> None:
        payload = {
            "title": "IT Support Engineer",
            "link": "https://example.com/jobs/1",
            "links": "https://example.com/jobs/1",
        }
        result = matching.normalize_application_record(payload)
        self.assertIsNotNone(result)

    def test_handles_non_list_sources(self) -> None:
        payload = {
            "title": "IT Support Engineer",
            "link": "https://example.com/jobs/1",
            "sources": "board_name",
        }
        result = matching.normalize_application_record(payload)
        self.assertIsNotNone(result)

    def test_extracts_company_from_title(self) -> None:
        payload = {
            "title": "IT Support Engineer at Monzo",
            "link": "https://example.com/jobs/1",
        }
        result = matching.normalize_application_record(payload)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["company"], "Monzo")

    def test_application_ready_when_score_high(self) -> None:
        from jobbot.common import APPLICATION_READY_SCORE

        payload = {
            "title": "IT Support Engineer",
            "link": "https://example.com/jobs/1",
            "score": APPLICATION_READY_SCORE + 1,
        }
        result = matching.normalize_application_record(payload)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["application_ready"])

    def test_handles_non_list_reasons(self) -> None:
        payload = {
            "title": "IT Support",
            "link": "https://example.com/1",
            "reasons": "single reason",
        }
        result = matching.normalize_application_record(payload)
        self.assertIsNotNone(result)

    def test_handles_non_list_fit_notes(self) -> None:
        payload = {
            "title": "IT Support",
            "link": "https://example.com/1",
            "why_this_fits": "Good overlap",
        }
        result = matching.normalize_application_record(payload)
        self.assertIsNotNone(result)

    def test_handles_non_list_resume_bullets(self) -> None:
        payload = {
            "title": "IT Support",
            "link": "https://example.com/1",
            "resume_bullet_suggestions": "Managed AD accounts",
        }
        result = matching.normalize_application_record(payload)
        self.assertIsNotNone(result)


class SyncApplicationOutcomesTestCase(unittest.TestCase):
    def test_sets_applied_at_utc_for_applied_status(self) -> None:
        state = fresh_applications_state()
        state["applications"] = [
            {
                "title": "Role",
                "link": "https://example.com/1",
                "status": "applied",
                "last_seen_utc": "2026-04-01T10:00:00Z",
            }
        ]
        matching.sync_application_outcomes(state, "2026-04-04T10:00:00Z")
        app = state["applications"][0]
        self.assertTrue(app.get("applied_at_utc"))

    def test_sets_interviewed_at_utc_for_interview_status(self) -> None:
        state = fresh_applications_state()
        state["applications"] = [
            {
                "title": "Role",
                "link": "https://example.com/1",
                "status": "interview",
                "last_seen_utc": "2026-04-01T10:00:00Z",
            }
        ]
        matching.sync_application_outcomes(state, "2026-04-04T10:00:00Z")
        app = state["applications"][0]
        self.assertTrue(app.get("interviewed_at_utc"))

    def test_sets_rejected_at_utc_for_rejected_status(self) -> None:
        state = fresh_applications_state()
        state["applications"] = [
            {
                "title": "Role",
                "link": "https://example.com/1",
                "status": "rejected",
                "last_seen_utc": "2026-04-01T10:00:00Z",
            }
        ]
        matching.sync_application_outcomes(state, "2026-04-04T10:00:00Z")
        app = state["applications"][0]
        self.assertTrue(app.get("rejected_at_utc"))


class TelegramPayloadValueTestCase(unittest.TestCase):
    def test_dict_is_json_serialized(self) -> None:
        result = matching._telegram_payload_value({"key": "val"})
        self.assertIn("key", result)
        self.assertIn("val", result)

    def test_list_is_json_serialized(self) -> None:
        result = matching._telegram_payload_value([1, 2, 3])
        self.assertIn("1", result)

    def test_bool_true(self) -> None:
        self.assertEqual(matching._telegram_payload_value(True), "true")

    def test_bool_false(self) -> None:
        self.assertEqual(matching._telegram_payload_value(False), "false")

    def test_string_passthrough(self) -> None:
        self.assertEqual(matching._telegram_payload_value("hello"), "hello")

    def test_int_to_string(self) -> None:
        self.assertEqual(matching._telegram_payload_value(42), "42")


class RankApplicationForDigestTestCase(unittest.TestCase):
    def test_shortlisted_scores_higher(self) -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        shortlisted = {
            "score": 50,
            "best_score": 50,
            "shortlisted": True,
            "company_control": "priority",
            "status": "new",
            "last_seen_utc": now.isoformat().replace("+00:00", "Z"),
        }
        normal = {
            "score": 50,
            "best_score": 50,
            "shortlisted": False,
            "company_control": "none",
            "status": "new",
            "last_seen_utc": now.isoformat().replace("+00:00", "Z"),
        }
        rank_shortlisted, _ = matching.rank_application_for_digest(shortlisted, now)
        rank_normal, _ = matching.rank_application_for_digest(normal, now)
        self.assertGreater(rank_shortlisted, rank_normal)

    def test_rejected_scores_low(self) -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        rejected = {
            "score": 80,
            "best_score": 80,
            "shortlisted": False,
            "company_control": "none",
            "status": "rejected",
            "last_seen_utc": now.isoformat().replace("+00:00", "Z"),
        }
        rank, _ = matching.rank_application_for_digest(rejected, now)
        self.assertLess(rank, 50)


if __name__ == "__main__":
    unittest.main()
