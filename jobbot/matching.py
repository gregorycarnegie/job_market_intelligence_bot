import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from jobbot import storage
from jobbot.common import (
    APPLICATION_READY_SCORE,
    APPLICATION_STATUSES,
    BORDERLINE_MATCH_MARGIN,
    CADENCE_TO_ANNUAL_MULTIPLIER,
    COMPANY_CONTROL_ORDER,
    CURRENCY_TO_GBP,
    FETCH_TIMEOUT_SECONDS,
    MAX_ALERTED_LINKS,
    MAX_APPLICATION_RECORDS,
    MIN_MATCH_SCORE,
    NEGATIVE_TITLE_WEIGHTS,
    OUTCOME_RELEVANT_STATUSES,
    POSITIVE_TITLE_WEIGHTS,
    SENIORITY_PENALTIES,
    STATE_DB_FILE,
    USER_AGENT,
    PatternEntry,
    append_reason,
    atomic_write_json,
    build_focus_phrases,
    build_pattern_entries,
    build_review_fingerprints,
    clean_text,
    contains_phrase,
    dedupe_preserving_order,
    ensure_sentence,
    find_pattern_matches,
    latest_application_timestamp,
    normalize_application_status,
    normalize_company_control,
    normalize_company_name,
    normalize_text,
    parse_bool,
    parse_iso_utc,
    safe_int,
    split_title_and_company,
    stronger_company_control,
    truncate_text,
)


def normalize_application_record(payload: dict[str, object]) -> dict[str, object] | None:
    title = clean_text(str(payload.get("title", "")))
    link = clean_text(str(payload.get("link", "")))
    description = clean_text(str(payload.get("description", "")))[:1500]
    company = clean_text(str(payload.get("company", "")))
    if not company and title:
        _, company = split_title_and_company(title)
    source = clean_text(str(payload.get("source", "")))

    raw_fingerprints = payload.get("fingerprints", [])
    if not isinstance(raw_fingerprints, list):
        raw_fingerprints = [raw_fingerprints] if raw_fingerprints else []
    fingerprints = [clean_text(str(fingerprint)) for fingerprint in raw_fingerprints if clean_text(str(fingerprint))]
    if not fingerprints and (title or link):
        fingerprints = build_review_fingerprints(title, description, link)

    raw_links = payload.get("links", [])
    if not isinstance(raw_links, list):
        raw_links = [raw_links] if raw_links else []
    links = [clean_text(str(item)) for item in raw_links if clean_text(str(item))]
    if link:
        links.insert(0, link)

    raw_sources = payload.get("sources", [])
    if not isinstance(raw_sources, list):
        raw_sources = [raw_sources] if raw_sources else []
    sources = [clean_text(str(item)) for item in raw_sources if clean_text(str(item))]
    if source:
        sources.insert(0, source)

    if not title or not links or not fingerprints:
        return None

    raw_reasons = payload.get("reasons", [])
    if not isinstance(raw_reasons, list):
        raw_reasons = [raw_reasons] if raw_reasons else []
    reasons = [clean_text(str(reason)) for reason in raw_reasons if clean_text(str(reason))]

    raw_fit_notes = payload.get("why_this_fits", [])
    if not isinstance(raw_fit_notes, list):
        raw_fit_notes = [raw_fit_notes] if raw_fit_notes else []
    why_this_fits = [ensure_sentence(note) for note in raw_fit_notes if clean_text(str(note))]

    raw_resume_bullets = payload.get("resume_bullet_suggestions", [])
    if not isinstance(raw_resume_bullets, list):
        raw_resume_bullets = [raw_resume_bullets] if raw_resume_bullets else []
    resume_bullet_suggestions = [ensure_sentence(bullet) for bullet in raw_resume_bullets if clean_text(str(bullet))]

    raw_feedback_keywords = payload.get("feedback_keywords", [])
    if not isinstance(raw_feedback_keywords, list):
        raw_feedback_keywords = [raw_feedback_keywords] if raw_feedback_keywords else []
    feedback_keywords = [
        normalize_text(str(keyword)) for keyword in raw_feedback_keywords if normalize_text(str(keyword))
    ]

    score = safe_int(payload.get("score", 0), 0)
    best_score = max(score, safe_int(payload.get("best_score", score), score))
    company_control = normalize_company_control(payload.get("company_control", "none"))
    shortlisted = parse_bool(payload.get("shortlisted", company_control == "priority"), company_control == "priority")
    application_ready = parse_bool(
        payload.get("application_ready", shortlisted or best_score >= APPLICATION_READY_SCORE),
        shortlisted or best_score >= APPLICATION_READY_SCORE,
    )

    return {
        "title": title,
        "description": description,
        "company": company,
        "link": links[0],
        "links": dedupe_preserving_order(links),
        "source": sources[0] if sources else "",
        "sources": dedupe_preserving_order(sources),
        "status": normalize_application_status(payload.get("status", "new")),
        "shortlisted": shortlisted,
        "company_control": "priority" if shortlisted else company_control,
        "role_profile": clean_text(str(payload.get("role_profile", ""))),
        "score": score,
        "best_score": best_score,
        "reasons": reasons[:6],
        "why_this_fits": dedupe_preserving_order(why_this_fits)[:3],
        "resume_bullet_suggestions": dedupe_preserving_order(resume_bullet_suggestions)[:3],
        "intro_message": clean_text(str(payload.get("intro_message", ""))),
        "application_ready": application_ready,
        "notes": clean_text(str(payload.get("notes", ""))),
        "feedback_keywords": dedupe_preserving_order(feedback_keywords)[:8],
        "status_observed_utc": clean_text(str(payload.get("status_observed_utc", ""))),
        "applied_at_utc": clean_text(str(payload.get("applied_at_utc", ""))),
        "interviewed_at_utc": clean_text(str(payload.get("interviewed_at_utc", ""))),
        "rejected_at_utc": clean_text(str(payload.get("rejected_at_utc", ""))),
        "first_seen_utc": clean_text(str(payload.get("first_seen_utc", ""))),
        "last_seen_utc": clean_text(str(payload.get("last_seen_utc", ""))),
        "match_count": max(1, safe_int(payload.get("match_count", 1), 1)),
        "fingerprints": dedupe_preserving_order(fingerprints),
    }


def load_applications_state(applications_file: str) -> dict[str, object]:
    data = storage.load_applications_state(STATE_DB_FILE)
    applications = []
    seen_keys = set()
    for payload in data.get("applications", []):
        if not isinstance(payload, dict):
            continue
        normalized = normalize_application_record(payload)
        if normalized is None:
            continue
        dedupe_key = normalized["link"]
        if dedupe_key in seen_keys:
            continue
        applications.append(normalized)
        seen_keys.add(dedupe_key)

    state = {
        "applications": applications[-MAX_APPLICATION_RECORDS:],
        "last_updated_utc": clean_text(str(data.get("last_updated_utc", ""))),
        "last_digest_utc": clean_text(str(data.get("last_digest_utc", ""))),
        "last_digest_date_utc": clean_text(str(data.get("last_digest_date_utc", ""))),
        "last_digest_error": clean_text(str(data.get("last_digest_error", ""))),
        "last_feedback_utc": clean_text(str(data.get("last_feedback_utc", ""))),
        "last_cleanup_utc": clean_text(str(data.get("last_cleanup_utc", ""))),
    }
    return state


def save_applications_state(applications_file: str, applications_state: dict[str, object]) -> None:
    storage.save_applications_state(STATE_DB_FILE, applications_state)
    atomic_write_json(Path(applications_file), applications_state)


def evaluate_location_fit(
    normalized_full_text: str,
    preferred_locations: list[str],
    prefs: dict,
    lockouts: list[str],
) -> tuple[bool, str]:
    location_context = normalized_full_text[:1000]
    is_remote = any(re.search(rf"\b{word}\b", location_context) for word in ["remote", "anywhere", "wfh"])
    is_hybrid = "hybrid" in location_context
    is_onsite = any(
        term in location_context
        for term in [
            "in office",
            "in-office",
            "onsite",
            "on site",
            "on-site",
            "office based",
            "office-based",
        ]
    )
    is_local = any(term in location_context for term in preferred_locations)
    is_locked_out = any(lock in location_context for lock in lockouts)

    if prefs.get("relocation", False):
        return True, "location fit: relocation allowed"
    if prefs.get("remote") and is_remote and not is_locked_out:
        return True, "location fit: remote compatible"
    if prefs.get("hybrid") and is_local and (is_hybrid or not is_remote):
        return True, "location fit: local/hybrid compatible"
    if prefs.get("onsite") and is_local and (is_onsite or not is_remote):
        return True, "location fit: local/onsite compatible"
    if is_locked_out:
        return False, "location reject: explicit geographic lockout"
    return False, "location reject: not aligned with preferences"


def normalize_currency_token(token: str) -> str:
    normalized = token.strip().lower()
    if normalized in {"£", "gbp", "pound", "pounds"}:
        return "gbp"
    if normalized in {"$", "usd", "us$", "dollar", "dollars"}:
        return "usd"
    if normalized in {"€", "eur", "euro", "euros"}:
        return "eur"
    return ""


def detect_salary_cadence(context: str) -> str:
    normalized = normalize_text(context)
    if re.search(r"\b(per|a)\s+hour\b|/hour\b|\bhourly\b", normalized):
        return "hour"
    if re.search(r"\b(per|a)\s+day\b|/day\b|\bdaily\b|\bday rate\b|\bday-rate\b", normalized):
        return "day"
    if re.search(r"\b(per|a)\s+month\b|/month\b|\bmonthly\b", normalized):
        return "month"
    return "year"


def parse_salary_amount(raw_amount: str, has_k_suffix: str | None) -> float:
    amount = float(raw_amount.replace(",", ""))
    if has_k_suffix:
        amount *= 1000
    return amount


def annualize_salary_to_gbp(amount: float, currency: str, cadence: str) -> int:
    rate = CURRENCY_TO_GBP[currency]
    multiplier = CADENCE_TO_ANNUAL_MULTIPLIER[cadence]
    return round(amount * rate * multiplier)


def build_salary_info(
    minimum_amount: float,
    maximum_amount: float,
    currency: str,
    cadence: str,
) -> dict[str, object]:
    low = annualize_salary_to_gbp(minimum_amount, currency, cadence)
    high = annualize_salary_to_gbp(maximum_amount, currency, cadence)
    return {
        "min_gbp": min(low, high),
        "max_gbp": max(low, high),
        "currency": currency,
        "cadence": cadence,
    }


def extract_salary_range_gbp(text: str) -> dict[str, object] | None:
    normalized = clean_text(text).lower().replace(",", "")
    range_patterns = [
        re.compile(
            r"(?P<currency>£|gbp|us\$|usd|\$|eur|€)\s*"
            r"(?P<minimum>\d+(?:\.\d+)?)\s*(?P<minimum_k>k)?\s*"
            r"(?:-|–|—|to)\s*"  # noqa: RUF001
            r"(?:(?:£|gbp|us\$|usd|\$|eur|€)\s*)?"
            r"(?P<maximum>\d+(?:\.\d+)?)\s*(?P<maximum_k>k)?",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?P<minimum>\d+(?:\.\d+)?)\s*(?P<minimum_k>k)?\s*"
            r"(?:-|–|—|to)\s*"  # noqa: RUF001
            r"(?P<maximum>\d+(?:\.\d+)?)\s*(?P<maximum_k>k)?\s*"
            r"(?P<currency>gbp|usd|eur|pounds?|dollars?|euros?)",
            re.IGNORECASE,
        ),
    ]
    single_patterns = [
        re.compile(
            r"(?P<currency>£|gbp|us\$|usd|\$|eur|€)\s*"
            r"(?P<amount>\d+(?:\.\d+)?)\s*(?P<amount_k>k)?",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?P<amount>\d+(?:\.\d+)?)\s*(?P<amount_k>k)?\s*"
            r"(?P<currency>gbp|usd|eur|pounds?|dollars?|euros?)",
            re.IGNORECASE,
        ),
    ]

    for pattern in range_patterns:
        match = pattern.search(normalized)
        if not match:
            continue
        currency = normalize_currency_token(match.group("currency"))
        if currency not in CURRENCY_TO_GBP:
            continue
        cadence = detect_salary_cadence(normalized[match.start() : match.end() + 32])
        minimum_amount = parse_salary_amount(match.group("minimum"), match.group("minimum_k"))
        maximum_amount = parse_salary_amount(match.group("maximum"), match.group("maximum_k"))
        if cadence == "year" and max(minimum_amount, maximum_amount) < 1000:
            continue
        return build_salary_info(minimum_amount, maximum_amount, currency, cadence)

    for pattern in single_patterns:
        match = pattern.search(normalized)
        if not match:
            continue
        currency = normalize_currency_token(match.group("currency"))
        if currency not in CURRENCY_TO_GBP:
            continue
        cadence = detect_salary_cadence(normalized[match.start() : match.end() + 32])
        amount = parse_salary_amount(match.group("amount"), match.group("amount_k"))
        if cadence == "year" and amount < 1000:
            continue
        return build_salary_info(amount, amount, currency, cadence)

    return None


def format_salary_info_for_reason(salary_info: dict[str, object]) -> str:
    base = f"estimated GBP {salary_info['min_gbp']:,}-{salary_info['max_gbp']:,}"
    suffix = []
    if salary_info["currency"] != "gbp":
        suffix.append(str(salary_info["currency"]).upper())
    if salary_info["cadence"] != "year":
        suffix.append(str(salary_info["cadence"]))
    if suffix:
        return f"{base} from {' '.join(suffix)}"
    return base


def apply_weight_map(text: str, weights: dict[str, int], reasons: list[str], prefix: str) -> int:
    matched_phrases = [phrase for phrase in weights if contains_phrase(text, phrase)]
    if not matched_phrases:
        return 0
    append_reason(reasons, f"{prefix}: {', '.join(matched_phrases[:3])}")
    return sum(weights[phrase] for phrase in matched_phrases)


def evaluate_company_preferences(company_name: str, search_config: dict[str, object]) -> dict[str, object]:
    normalized_company = normalize_company_name(company_name)
    if not normalized_company:
        return {"qualified": True, "score_delta": 0, "reason": "", "control": "none", "shortlisted": False}
    blacklist_match = find_pattern_matches(normalized_company, search_config["company_blacklist_entries"], limit=1)
    if blacklist_match:
        return {
            "qualified": False,
            "score_delta": 0,
            "reason": f"company reject: blacklisted employer {blacklist_match[0]}",
            "control": "blacklist",
            "shortlisted": False,
        }
    priority_match = find_pattern_matches(normalized_company, search_config["priority_company_entries"], limit=1)
    if priority_match:
        return {
            "qualified": True,
            "score_delta": 14,
            "reason": f"company shortlist: {priority_match[0]}",
            "control": "priority",
            "shortlisted": True,
        }
    whitelist_match = find_pattern_matches(normalized_company, search_config["company_whitelist_entries"], limit=1)
    if whitelist_match:
        return {
            "qualified": True,
            "score_delta": 8,
            "reason": f"company whitelist: {whitelist_match[0]}",
            "control": "whitelist",
            "shortlisted": False,
        }
    return {"qualified": True, "score_delta": 0, "reason": "", "control": "none", "shortlisted": False}


def evaluate_role_profile(
    normalized_title: str,
    normalized_desc: str,
    search_config: dict[str, object],
) -> dict[str, object] | None:
    best_match = None
    best_sort_key = None
    for profile in search_config["role_profiles"]:
        title_matches = find_pattern_matches(normalized_title, profile["title_entries"], limit=3)
        description_matches = [
            match
            for match in find_pattern_matches(normalized_desc, profile["description_entries"], limit=3)
            if match not in title_matches
        ]
        if not title_matches and not description_matches:
            continue
        score_delta = len(title_matches) * int(profile["title_boost"]) + len(description_matches) * int(
            profile["description_boost"]
        )
        sort_key = (score_delta, int(profile["priority"]), len(title_matches), len(description_matches))
        if best_sort_key is None or sort_key > best_sort_key:
            best_sort_key = sort_key
            best_match = {
                "name": str(profile["name"]),
                "display_name": str(profile["display_name"]),
                "score_delta": score_delta,
                "title_matches": title_matches,
                "description_matches": description_matches,
            }
    return best_match


def select_resume_evidence(
    profile: dict[str, object], focus_phrases: list[str], limit: int = 3
) -> list[dict[str, object]]:
    experience_entries = list(profile.get("experience_entries", []))
    if not experience_entries:
        return []
    focus_entries = build_pattern_entries(focus_phrases)
    ranked_entries = []
    fallback_entries = []
    for index, entry in enumerate(experience_entries):
        if not isinstance(entry, dict):
            continue
        entry_text = clean_text(str(entry.get("text", "")))
        if not entry_text:
            continue
        matches = (
            find_pattern_matches(str(entry.get("normalized_text", "")), focus_entries, limit=4) if focus_entries else []
        )
        candidate = {
            "label": clean_text(str(entry.get("label", ""))) or "Experience",
            "role": clean_text(str(entry.get("role", ""))),
            "organization": clean_text(str(entry.get("organization", ""))),
            "text": entry_text,
            "matches": matches,
        }
        if matches:
            rank = (
                len(matches) * 6
                + (1 if candidate["organization"] else 0)
                + (1 if candidate["label"] != "Resume summary" else 0)
            )
            ranked_entries.append((rank, -index, candidate))
        elif candidate["label"] != "Resume summary":
            fallback_entries.append(candidate)
    if ranked_entries:
        ranked_entries.sort(reverse=True)
        return [candidate for _, _, candidate in ranked_entries[:limit]]
    return fallback_entries[:limit]


def build_why_this_fits_notes(
    company_name: str,
    company_preferences: dict[str, object],
    role_profile_match: dict[str, object],
    title_alignment_matches: list[str],
    skill_focus_phrases: list[str],
    evidence_entries: list[dict[str, object]],
) -> list[str]:
    notes = []
    if company_preferences["control"] == "priority" and company_name:
        notes.append(
            ensure_sentence(f"{company_name} is on your priority-employer shortlist, so this role deserves fast review")
        )
    if role_profile_match.get("display_name"):
        if title_alignment_matches:
            notes.append(
                ensure_sentence(
                    f"The role sits in your {role_profile_match['display_name']} lane"
                    f" and overlaps with target titles like {', '.join(title_alignment_matches[:3])}"
                )
            )
        else:
            notes.append(ensure_sentence(f"The role sits in your {role_profile_match['display_name']} lane"))
    elif title_alignment_matches:
        notes.append(
            ensure_sentence(
                f"The title overlaps directly with your target role focus: {', '.join(title_alignment_matches[:3])}"
            )
        )
    if skill_focus_phrases:
        notes.append(
            ensure_sentence(f"The job text overlaps with your hands-on stack in {', '.join(skill_focus_phrases[:4])}")
        )
    if evidence_entries:
        top_evidence = evidence_entries[0]
        notes.append(
            ensure_sentence(
                f"You already have direct evidence from {top_evidence['label']}:"
                f" {truncate_text(top_evidence['text'], 170)}"
            )
        )
    return dedupe_preserving_order([note for note in notes if note])[:3]


def build_resume_bullet_suggestions(evidence_entries: list[dict[str, object]]) -> list[str]:
    suggestions = []
    for entry in evidence_entries:
        bullet = ensure_sentence(truncate_text(entry.get("text", ""), 220))
        if bullet:
            suggestions.append(bullet)
    return dedupe_preserving_order(suggestions)[:3]


def build_intro_message(
    profile: dict[str, object],
    role_title: str,
    company_name: str,
    skill_focus_phrases: list[str],
    evidence_entries: list[dict[str, object]],
) -> str:
    candidate_name = clean_text(str(profile.get("candidate_name", "")))
    candidate_title = clean_text(str(profile.get("candidate_title", ""))) or "IT support professional"
    greeting = f"Hi {company_name} team," if company_name else "Hi hiring team,"
    intro_subject = (
        f"I'm {candidate_name}, currently working as {candidate_title}"
        if candidate_name
        else f"I'm a {candidate_title}"
    )
    skill_clause = (
        ", ".join(skill_focus_phrases[:3])
        if skill_focus_phrases
        else "IT support, Microsoft 365, and identity/access administration"
    )
    role_name = role_title or "this role"
    evidence_clause = ""
    if evidence_entries:
        evidence_clause = truncate_text(evidence_entries[0]["text"], 120).rstrip(".")
    lines = [
        f"{greeting} {intro_subject} with hands-on experience in {skill_clause}.",
        f"I'm interested in the {role_name} role because it lines up closely"
        " with the support and systems work I already do.",
    ]
    if evidence_clause:
        lines.append(f"A relevant example from my recent work is: {evidence_clause}.")
    lines.append("I'd welcome the chance to discuss how I could contribute.")
    return " ".join(lines)


def build_application_materials(
    profile: dict[str, object],
    role_title: str,
    company_name: str,
    score: int,
    company_preferences: dict[str, object],
    role_profile_match: dict[str, object],
    title_alignment_matches: list[str],
    skill_focus_phrases: list[str],
) -> dict[str, object]:
    evidence_entries = select_resume_evidence(
        profile, build_focus_phrases(title_alignment_matches, skill_focus_phrases), limit=3
    )
    why_this_fits = build_why_this_fits_notes(
        company_name,
        company_preferences,
        role_profile_match,
        title_alignment_matches,
        skill_focus_phrases,
        evidence_entries,
    )
    return {
        "why_this_fits": why_this_fits,
        "resume_bullet_suggestions": build_resume_bullet_suggestions(evidence_entries),
        "intro_message": build_intro_message(profile, role_title, company_name, skill_focus_phrases, evidence_entries),
        "application_ready": bool(company_preferences.get("shortlisted") or score >= APPLICATION_READY_SCORE),
    }


def apply_feedback_adjustments(
    score: int,
    reasons: list[str],
    source_label: str,
    feedback_keywords: list[str],
    feedback_profile: dict[str, object],
) -> int:
    if not feedback_profile.get("enabled", False):
        return score
    score_delta = 0
    source_key = normalize_text(source_label)
    source_adjustment = safe_int(feedback_profile["source_adjustments"].get(source_key, 0), 0)
    if source_adjustment:
        score_delta += source_adjustment
        append_reason(
            reasons,
            f"feedback source {'boost' if source_adjustment > 0 else 'penalty'}:"
            f" {clean_text(source_label)} ({source_adjustment:+d})",
        )
    keyword_adjustments = []
    for keyword in dedupe_preserving_order(feedback_keywords):
        adjustment = safe_int(feedback_profile["keyword_adjustments"].get(keyword, 0), 0)
        if adjustment:
            keyword_adjustments.append((keyword, adjustment))
    keyword_adjustments.sort(key=lambda item: (abs(item[1]), item[1], item[0]), reverse=True)
    selected_adjustments = keyword_adjustments[: int(feedback_profile["keyword_limit"])]
    if selected_adjustments:
        total_keyword_delta = sum(item[1] for item in selected_adjustments)
        max_keyword_delta = int(feedback_profile["max_keyword_adjustment"])
        total_keyword_delta = max(-max_keyword_delta, min(max_keyword_delta, total_keyword_delta))
        if total_keyword_delta:
            score_delta += total_keyword_delta
            adjustment_text = ", ".join(
                f"{keyword} ({adjustment:+d})" for keyword, adjustment in selected_adjustments[:3]
            )
            append_reason(
                reasons, f"feedback keywords {'boost' if total_keyword_delta > 0 else 'penalty'}: {adjustment_text}"
            )
    return score + score_delta


def _calculate_target_role_score(
    normalized_title: str, normalized_desc: str, target_role_entries: list[PatternEntry], reasons: list[str]
) -> tuple[int, list[str]]:
    """
    Calculate score contribution based on target role matches in title and description.

    Args:
        normalized_title: The normalized job title.
        normalized_desc: The normalized job description.
        target_role_entries: A list of pattern entries for target roles.
        reasons: A list to append scoring reasons to.

    Returns:
        A tuple of (score delta, target title matches).
    """
    score = 0
    target_title_matches = find_pattern_matches(normalized_title, target_role_entries, limit=3)
    if target_title_matches:
        score += min(48, 34 + 7 * (len(target_title_matches) - 1))
        append_reason(reasons, f"target role in title: {', '.join(target_title_matches)}")
    target_desc_matches = [
        match
        for match in find_pattern_matches(normalized_desc, target_role_entries, limit=3)
        if match not in target_title_matches
    ]
    if target_desc_matches:
        score += min(18, 9 * len(target_desc_matches))
        append_reason(reasons, f"target role in description: {', '.join(target_desc_matches)}")
    return score, target_title_matches


def _calculate_skill_score(
    normalized_title: str, normalized_desc: str, skill_entries: list[PatternEntry], reasons: list[str]
) -> tuple[int, list[str], list[str]]:
    """
    Calculate score contribution based on skill matches in title and description.

    Args:
        normalized_title: The normalized job title.
        normalized_desc: The normalized job description.
        skill_entries: A list of pattern entries for desired skills.
        reasons: A list to append scoring reasons to.

    Returns:
        A tuple of (score delta, title skill matches, description skill matches).
    """
    score = 0
    skill_title_matches = find_pattern_matches(normalized_title, skill_entries, limit=4)
    if skill_title_matches:
        score += min(18, 6 * len(skill_title_matches))
        append_reason(reasons, f"skills in title: {', '.join(skill_title_matches)}")
    skill_desc_matches = [
        match
        for match in find_pattern_matches(normalized_desc, skill_entries, limit=5)
        if match not in skill_title_matches
    ]
    if skill_desc_matches:
        score += min(20, 4 * len(skill_desc_matches))
        append_reason(reasons, f"skills in description: {', '.join(skill_desc_matches)}")
    return score, skill_title_matches, skill_desc_matches


def _calculate_competency_score(
    normalized_full_text: str, competency_entries: list[PatternEntry], reasons: list[str]
) -> tuple[int, list[str]]:
    """
    Calculate score contribution based on competency matches in the full text.

    Args:
        normalized_full_text: The normalized job title and description.
        competency_entries: A list of pattern entries for desired competencies.
        reasons: A list to append scoring reasons to.

    Returns:
        A tuple of (score delta, competency matches).
    """
    score = 0
    competency_matches = find_pattern_matches(normalized_full_text, competency_entries, limit=4)
    if competency_matches:
        score += min(12, 3 * len(competency_matches))
        append_reason(reasons, f"competencies matched: {', '.join(competency_matches)}")
    return score, competency_matches


def _apply_title_weights(normalized_title: str, reasons: list[str]) -> int:
    """
    Apply title weights (bonuses and penalties) based on seniority and keywords.

    Args:
        normalized_title: The normalized job title.
        reasons: A list to append scoring reasons to.

    Returns:
        The total score delta from title weights.
    """
    score = 0
    score += apply_weight_map(normalized_title, POSITIVE_TITLE_WEIGHTS, reasons, "title boost")
    score -= apply_weight_map(normalized_title, NEGATIVE_TITLE_WEIGHTS, reasons, "title penalty")
    score -= apply_weight_map(normalized_title, SENIORITY_PENALTIES, reasons, "seniority penalty")
    return score


def _apply_salary_preferences(raw_title: str, raw_desc: str, prefs: dict[str, object], reasons: list[str]) -> int:
    """
    Apply generic salary preferences, boosting jobs above minimum or penalizing jobs below.

    Args:
        raw_title: The raw job title.
        raw_desc: The raw job description.
        prefs: Dictionary of user preferences, expecting 'minimum_salary_gbp'.
        reasons: A list to append scoring reasons to.

    Returns:
        The score delta based on salary evaluation.
    """
    score = 0
    salary_range = extract_salary_range_gbp(f"{raw_title} {raw_desc}")
    minimum_salary_gbp = int(prefs.get("minimum_salary_gbp", 0) or 0)
    if salary_range and minimum_salary_gbp:
        salary_min = safe_int(salary_range["min_gbp"])
        salary_max = safe_int(salary_range["max_gbp"])
        salary_reason = format_salary_info_for_reason(salary_range)
        if salary_max < minimum_salary_gbp:
            score -= 18
            append_reason(reasons, f"salary penalty: {salary_reason} is below preference")
        elif salary_min >= minimum_salary_gbp:
            score += 4
            append_reason(reasons, f"salary fit: {salary_reason}")
    return score


def score_job(
    item: dict[str, str],
    source_label: str,
    profile: dict[str, object],
    search_config: dict[str, object],
    feedback_profile: dict[str, object],
    current_run_ts: str,
    lockouts: list[str],
) -> dict[str, object]:
    """
    Score a job item and generate a candidate profile based on skills, role fit, and preferences.

    Args:
        item: The job posting (requires 'title', 'description', 'link').
        source_label: The source of the job posting (e.g. greenhouse).
        profile: Dictionary containing user target profiles and preferences.
        search_config: Config for search logic and company overrides.
        feedback_profile: Adaptive feedback model adjusting scores based on user feedback.
        current_run_ts: Timestamp to assign to generated candidates.
        lockouts: List of strings/expressions for lockout rules.

    Returns:
        A dict containing qualification status, score, reasons, and a candidate object.
    """
    raw_title = clean_text(item["title"])
    raw_desc = clean_text(item["description"])
    role_title, company = split_title_and_company(raw_title)
    normalized_title = normalize_text(role_title or raw_title)
    normalized_desc = normalize_text(raw_desc)
    normalized_full_text = normalize_text(f"{raw_title} {raw_desc}")
    reasons: list[str] = []

    prefs = profile["prefs"]
    preferred_locations = profile["preferred_locations"]
    target_role_entries = profile["target_role_entries"]
    skill_entries = profile["skill_entries"]
    competency_entries = profile["competency_entries"]

    location_ok, location_reason = evaluate_location_fit(normalized_full_text, preferred_locations, prefs, lockouts)
    append_reason(reasons, location_reason)
    if not location_ok:
        return {"qualified": False, "score": 0, "reasons": reasons}

    score = 0
    company_name = company or source_label
    company_preferences = evaluate_company_preferences(company_name, search_config)
    if company_preferences["reason"]:
        append_reason(reasons, str(company_preferences["reason"]))
    if not company_preferences["qualified"]:
        return {"qualified": False, "score": 0, "reasons": reasons}
    score += int(company_preferences["score_delta"])

    tr_score, target_title_matches = _calculate_target_role_score(
        normalized_title, normalized_desc, target_role_entries, reasons
    )
    score += tr_score

    sk_score, skill_title_matches, skill_desc_matches = _calculate_skill_score(
        normalized_title, normalized_desc, skill_entries, reasons
    )
    score += sk_score

    comp_score, competency_matches = _calculate_competency_score(normalized_full_text, competency_entries, reasons)
    score += comp_score

    score += _apply_title_weights(normalized_title, reasons)

    role_profile_match = evaluate_role_profile(normalized_title, normalized_desc, search_config)
    if role_profile_match:
        score += int(role_profile_match["score_delta"])
        role_profile_reason_parts = []
        if role_profile_match["title_matches"]:
            role_profile_reason_parts.append(f"title: {', '.join(role_profile_match['title_matches'])}")
        if role_profile_match["description_matches"]:
            role_profile_reason_parts.append(f"description: {', '.join(role_profile_match['description_matches'])}")
        append_reason(
            reasons, f"role profile {role_profile_match['display_name']}: {'; '.join(role_profile_reason_parts)}"
        )
    else:
        role_profile_match = {
            "name": "",
            "display_name": "",
            "score_delta": 0,
            "title_matches": [],
            "description_matches": [],
        }

    score += _apply_salary_preferences(raw_title, raw_desc, prefs, reasons)

    title_alignment_matches = dedupe_preserving_order(target_title_matches + role_profile_match["title_matches"])
    skill_focus_phrases = build_focus_phrases(
        skill_title_matches, skill_desc_matches, competency_matches, role_profile_match["description_matches"]
    )
    feedback_keywords = dedupe_preserving_order(build_focus_phrases(title_alignment_matches, skill_focus_phrases))[:8]
    score = apply_feedback_adjustments(score, reasons, source_label, feedback_keywords, feedback_profile)
    application_materials = build_application_materials(
        profile,
        role_title or raw_title,
        company_name,
        score,
        company_preferences,
        role_profile_match,
        title_alignment_matches,
        skill_focus_phrases,
    )

    candidate = {
        "time": current_run_ts,
        "title": raw_title,
        "description": raw_desc[:1500],
        "link": clean_text(item["link"]),
        "source": source_label,
        "company": company_name,
        "score": score,
        "reasons": reasons[:6],
        "shortlisted": bool(company_preferences["shortlisted"]),
        "company_control": str(company_preferences["control"]),
        "role_profile": str(role_profile_match["display_name"] or role_profile_match["name"]),
        "why_this_fits": application_materials["why_this_fits"],
        "resume_bullet_suggestions": application_materials["resume_bullet_suggestions"],
        "intro_message": application_materials["intro_message"],
        "application_ready": bool(application_materials["application_ready"]),
        "feedback_keywords": feedback_keywords,
    }
    return {
        "qualified": score >= MIN_MATCH_SCORE,
        "score": score,
        "reasons": reasons[:6],
        "candidate": candidate,
        "match": candidate if score >= MIN_MATCH_SCORE else None,
    }


def queue_pending_alerts(alert_state: dict[str, object], matches: list[dict[str, object]]) -> int:
    pending_alerts = alert_state["pending_alerts"]
    pending_links = {str(alert["link"]) for alert in pending_alerts}
    alerted_links = {str(link) for link in alert_state["alerted_links"]}
    queued = 0
    for match in matches:
        link = str(match["link"])
        if link in pending_links or link in alerted_links:
            continue
        pending_alerts.append(
            {
                "time": match["time"],
                "title": match["title"],
                "link": link,
                "score": match["score"],
                "reasons": match["reasons"],
                "source": match["source"],
                "company": match.get("company", ""),
                "shortlisted": bool(match.get("shortlisted", False)),
                "company_control": clean_text(str(match.get("company_control", ""))),
                "role_profile": clean_text(str(match.get("role_profile", ""))),
            }
        )
        pending_links.add(link)
        queued += 1
    return queued


def load_telegram_settings() -> tuple[str, str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    thread_id = os.environ.get("TELEGRAM_THREAD_ID", "").strip()
    return token, chat_id, thread_id


def _telegram_payload_value(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def telegram_api_request(
    method: str,
    token: str,
    payload: dict[str, object] | None = None,
    request_timeout_seconds: float | None = None,
) -> tuple[bool, object, str]:
    request_payload = {
        key: _telegram_payload_value(value)
        for key, value in (payload or {}).items()
        if value is not None and value != ""
    }
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=urlencode(request_payload).encode("utf-8"),
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    effective_timeout = (
        FETCH_TIMEOUT_SECONDS if request_timeout_seconds is None else max(1.0, float(request_timeout_seconds))
    )
    try:
        with urlopen(request, timeout=effective_timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, OSError, ValueError) as exc:
        return False, None, clean_text(str(exc))
    try:
        payload_json = json.loads(body)
    except json.JSONDecodeError:
        return False, None, "Telegram API returned invalid JSON"
    if payload_json.get("ok") is True:
        return True, payload_json.get("result"), ""
    return False, None, clean_text(str(payload_json.get("description", "Telegram API error")))


def format_alert_message(alert: dict[str, object]) -> str:
    lines = [f"Job Match ({alert['score']}): {alert['title']}"]
    if alert.get("company"):
        lines.append(f"Company: {alert['company']}")
    if alert.get("shortlisted"):
        lines.append("Priority: shortlisted employer")
    elif alert.get("company_control") == "whitelist":
        lines.append("Priority: company whitelist")
    if alert.get("role_profile"):
        lines.append(f"Role Profile: {alert['role_profile']}")
    if alert.get("source"):
        lines.append(f"Source: {alert['source']}")
    if alert.get("reasons"):
        reasons = "; ".join(str(reason) for reason in alert["reasons"][:2])
        lines.append(f"Why: {reasons}")
    lines.append(str(alert["link"]))
    return "\n".join(lines)


def send_telegram_message_with_markup(
    message: str,
    token: str,
    chat_id: str,
    thread_id: str,
    reply_markup: dict[str, object] | None = None,
) -> tuple[bool, dict[str, object] | None, str]:
    payload: dict[str, object] = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }
    if thread_id:
        payload["message_thread_id"] = thread_id
    if reply_markup:
        payload["reply_markup"] = reply_markup
    ok, result, error = telegram_api_request("sendMessage", token, payload)
    return ok, result if isinstance(result, dict) else None, error


def send_telegram_message(message: str, token: str, chat_id: str, thread_id: str) -> tuple[bool, str]:
    ok, _, error = send_telegram_message_with_markup(message, token, chat_id, thread_id)
    return ok, error


def edit_telegram_message(
    message: str,
    token: str,
    chat_id: str,
    message_id: int,
    reply_markup: dict[str, object] | None = None,
) -> tuple[bool, str]:
    payload: dict[str, object] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": message,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    ok, _, error = telegram_api_request("editMessageText", token, payload)
    return ok, error


def answer_telegram_callback_query(
    callback_query_id: str,
    token: str,
    text: str = "",
    show_alert: bool = False,
) -> tuple[bool, str]:
    payload: dict[str, object] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text[:200]
        payload["show_alert"] = show_alert
    ok, _, error = telegram_api_request("answerCallbackQuery", token, payload)
    return ok, error


def fetch_telegram_updates(
    token: str,
    offset: int,
    allowed_updates: list[str] | None = None,
    limit: int = 20,
    timeout: int = 0,
) -> tuple[bool, list[dict[str, object]], str]:
    payload: dict[str, object] = {
        "offset": offset,
        "limit": max(1, min(100, limit)),
        "timeout": max(0, timeout),
    }
    if allowed_updates is not None:
        payload["allowed_updates"] = allowed_updates
    request_timeout_seconds = max(float(FETCH_TIMEOUT_SECONDS), float(timeout) + 5.0)
    ok, result, error = telegram_api_request(
        "getUpdates",
        token,
        payload,
        request_timeout_seconds=request_timeout_seconds,
    )
    if not ok:
        return False, [], error
    if not isinstance(result, list):
        return True, [], ""
    return True, [item for item in result if isinstance(item, dict)], ""


def deliver_pending_alerts(alert_state: dict[str, object], current_run_ts: str) -> tuple[int, str]:
    pending_alerts = list(alert_state["pending_alerts"])
    if not pending_alerts:
        alert_state["last_delivery_error"] = ""
        return 0, ""
    token, chat_id, thread_id = load_telegram_settings()
    if not token or not chat_id:
        message = "Telegram credentials not configured; alerts left queued in alerts_state.json."
        alert_state["last_delivery_error"] = message
        return 0, message
    alerted_links = list(alert_state["alerted_links"])
    alerted_link_set = set(alerted_links)
    sent_count = 0
    for index, alert in enumerate(pending_alerts):
        link = str(alert["link"])
        if link in alerted_link_set:
            continue
        ok, error = send_telegram_message(format_alert_message(alert), token, chat_id, thread_id)
        if not ok:
            alert_state["pending_alerts"] = pending_alerts[index:]
            alert_state["alerted_links"] = dedupe_preserving_order(alerted_links)[-MAX_ALERTED_LINKS:]
            alert_state["last_delivery_error"] = error
            return sent_count, error
        alerted_links.append(link)
        alerted_link_set.add(link)
        sent_count += 1
    alert_state["pending_alerts"] = []
    alert_state["alerted_links"] = dedupe_preserving_order(alerted_links)[-MAX_ALERTED_LINKS:]
    alert_state["last_delivery_utc"] = current_run_ts
    alert_state["last_delivery_error"] = ""
    return sent_count, ""


def sync_application_outcomes(applications_state: dict[str, object], observed_at_utc: str) -> None:
    for application in applications_state["applications"]:
        status = normalize_application_status(application.get("status", "new"))
        application["status"] = status
        fallback_observed_utc = (
            clean_text(str(application.get("last_seen_utc", "")))
            or clean_text(str(application.get("first_seen_utc", "")))
            or observed_at_utc
        )
        if not clean_text(str(application.get("status_observed_utc", ""))):
            application["status_observed_utc"] = fallback_observed_utc
        if status in {"applied", "interview", "rejected"} and not clean_text(
            str(application.get("applied_at_utc", ""))
        ):
            application["applied_at_utc"] = fallback_observed_utc
        if status == "interview" and not clean_text(str(application.get("interviewed_at_utc", ""))):
            application["interviewed_at_utc"] = fallback_observed_utc
        if status == "rejected" and not clean_text(str(application.get("rejected_at_utc", ""))):
            application["rejected_at_utc"] = fallback_observed_utc


def prune_applications_state(
    applications_state: dict[str, object],
    search_config: dict[str, object],
    current_run_ts: str,
) -> dict[str, object]:
    current_dt = parse_iso_utc(current_run_ts) or datetime.now(timezone.utc)
    feedback_settings = search_config["feedback"]
    before_count = len(applications_state["applications"])
    removed_by_status: dict[str, int] = {}
    retained = []
    for application in applications_state["applications"]:
        status = normalize_application_status(application.get("status", "new"))
        if status in {"new", "reviewed"}:
            retention_days = int(feedback_settings["new_reviewed_retention_days"])
        elif status == "rejected":
            retention_days = int(feedback_settings["rejected_retention_days"])
        elif status == "interview":
            retention_days = int(feedback_settings["interview_retention_days"])
        else:
            retention_days = int(feedback_settings["applied_retention_days"])
        if parse_bool(application.get("shortlisted", False), False):
            retention_days *= 2
        reference_dt = latest_application_timestamp(application)
        if reference_dt is None:
            retained.append(application)
            continue
        age_days = max(0, int((current_dt - reference_dt).days))
        if age_days > retention_days:
            removed_by_status[status] = removed_by_status.get(status, 0) + 1
            continue
        retained.append(application)
    applications_state["applications"] = retained[-MAX_APPLICATION_RECORDS:]
    applications_state["last_cleanup_utc"] = current_run_ts
    return {
        "before_count": before_count,
        "after_count": len(applications_state["applications"]),
        "removed_count": before_count - len(applications_state["applications"]),
        "removed_by_status": removed_by_status,
        "retention_days": {
            "new_reviewed": int(feedback_settings["new_reviewed_retention_days"]),
            "rejected": int(feedback_settings["rejected_retention_days"]),
            "applied": int(feedback_settings["applied_retention_days"]),
            "interview": int(feedback_settings["interview_retention_days"]),
        },
    }


def fresh_feedback_counts() -> dict[str, int]:
    return {"total": 0, "applied": 0, "interview": 0, "rejected": 0}


def increment_feedback_counts(counter: dict[str, int], status: str) -> None:
    if status not in OUTCOME_RELEVANT_STATUSES:
        return
    counter["total"] += 1
    counter[status] += 1


def compute_feedback_adjustment(counts: dict[str, int], max_adjustment: int, min_samples: int) -> int:
    total = int(counts.get("total", 0))
    if total < min_samples:
        return 0
    interview_rate = counts.get("interview", 0) / total
    applied_rate = counts.get("applied", 0) / total
    rejected_rate = counts.get("rejected", 0) / total
    raw_score = interview_rate + (applied_rate * 0.2) - (rejected_rate * 0.7)
    return max(-max_adjustment, min(max_adjustment, round(raw_score * max_adjustment)))


def build_feedback_metrics(
    current_run_ts: str,
    applications_state: dict[str, object],
    search_config: dict[str, object],
    cleanup_summary: dict[str, object],
) -> dict[str, object]:
    feedback_settings = search_config["feedback"]
    status_counts = dict.fromkeys(sorted(APPLICATION_STATUSES), 0)
    outcome_sample_count = 0
    source_counters: dict[str, dict[str, int]] = {}
    keyword_counters: dict[str, dict[str, int]] = {}
    source_labels: dict[str, str] = {}
    for application in applications_state["applications"]:
        status = normalize_application_status(application.get("status", "new"))
        status_counts[status] += 1
        if status not in OUTCOME_RELEVANT_STATUSES:
            continue
        outcome_sample_count += 1
        source_values = [normalize_text(value) for value in application.get("sources", []) if normalize_text(value)]
        if not source_values and normalize_text(application.get("source", "")):
            source_values = [normalize_text(application.get("source", ""))]
        for source_key in dedupe_preserving_order(source_values):
            source_counters.setdefault(source_key, fresh_feedback_counts())
            increment_feedback_counts(source_counters[source_key], status)
            source_labels.setdefault(source_key, clean_text(str(application.get("source", ""))) or source_key)
        keyword_values = [
            normalize_text(value) for value in application.get("feedback_keywords", []) if normalize_text(value)
        ]
        for keyword in dedupe_preserving_order(keyword_values):
            keyword_counters.setdefault(keyword, fresh_feedback_counts())
            increment_feedback_counts(keyword_counters[keyword], status)

    def build_metric_rows(
        counters: dict[str, dict[str, int]], max_adjustment: int, label_resolver
    ) -> list[dict[str, object]]:
        rows = []
        for key, counts in counters.items():
            adjustment = compute_feedback_adjustment(
                counts, max_adjustment=max_adjustment, min_samples=int(feedback_settings["min_samples"])
            )
            total = int(counts["total"])
            interview_rate = round((counts["interview"] / total) if total else 0.0, 3)
            rejected_rate = round((counts["rejected"] / total) if total else 0.0, 3)
            rows.append(
                {
                    "key": key,
                    "label": label_resolver(key),
                    "total": total,
                    "applied": int(counts["applied"]),
                    "interview": int(counts["interview"]),
                    "rejected": int(counts["rejected"]),
                    "interview_rate": interview_rate,
                    "rejected_rate": rejected_rate,
                    "recommended_adjustment": adjustment,
                }
            )
        rows.sort(
            key=lambda row: (
                int(row["recommended_adjustment"]),
                int(row["interview"]),
                -int(row["rejected"]),
                int(row["total"]),
                clean_text(str(row["label"])),
            ),
            reverse=True,
        )
        return rows

    source_metrics = build_metric_rows(
        source_counters,
        max_adjustment=int(feedback_settings["max_source_adjustment"]),
        label_resolver=lambda key: source_labels.get(key, key),
    )
    keyword_metrics = build_metric_rows(
        keyword_counters,
        max_adjustment=int(feedback_settings["max_keyword_adjustment"]),
        label_resolver=lambda key: key,
    )
    snapshot = {
        "generated_at": current_run_ts,
        "feedback_enabled": bool(feedback_settings["enabled"]),
        "status_counts": status_counts,
        "outcome_sample_count": outcome_sample_count,
        "top_positive_sources": [row for row in source_metrics if int(row["recommended_adjustment"]) > 0][:5],
        "top_negative_sources": [row for row in source_metrics if int(row["recommended_adjustment"]) < 0][:5],
        "top_positive_keywords": [row for row in keyword_metrics if int(row["recommended_adjustment"]) > 0][:8],
        "top_negative_keywords": [row for row in keyword_metrics if int(row["recommended_adjustment"]) < 0][:8],
        "source_metrics": source_metrics[:25],
        "keyword_metrics": keyword_metrics[:40],
        "cleanup": cleanup_summary,
    }
    return {
        "snapshot": snapshot,
        "enabled": bool(feedback_settings["enabled"]),
        "keyword_limit": int(feedback_settings["keyword_limit"]),
        "max_keyword_adjustment": int(feedback_settings["max_keyword_adjustment"]),
        "source_adjustments": {
            row["key"]: int(row["recommended_adjustment"])
            for row in source_metrics
            if int(row["recommended_adjustment"]) != 0
        },
        "keyword_adjustments": {
            row["key"]: int(row["recommended_adjustment"])
            for row in keyword_metrics
            if int(row["recommended_adjustment"]) != 0
        },
    }


def save_feedback_metrics_snapshot(feedback_metrics_file: str, snapshot: dict[str, object]) -> None:
    atomic_write_json(Path(feedback_metrics_file), snapshot)


def _merge_application_record(
    existing: dict[str, object],
    application: dict[str, object],
    seen_at_utc: str,
) -> None:
    existing["title"] = application["title"] or existing["title"]
    if application["description"] and len(application["description"]) >= len(str(existing.get("description", ""))):
        existing["description"] = application["description"]
    existing["company"] = application["company"] or existing["company"]
    existing["link"] = application["link"] or existing["link"]
    existing["links"] = dedupe_preserving_order(application["links"] + list(existing.get("links", [])))
    existing["source"] = application["source"] or existing["source"]
    existing["sources"] = dedupe_preserving_order(application["sources"] + list(existing.get("sources", [])))
    existing["status"] = normalize_application_status(existing.get("status", application["status"]))
    existing["shortlisted"] = bool(existing.get("shortlisted", False) or application["shortlisted"])
    existing["company_control"] = stronger_company_control(
        normalize_company_control(existing.get("company_control", "none")),
        normalize_company_control(application["company_control"]),
    )
    if existing["shortlisted"]:
        existing["company_control"] = "priority"
    existing["role_profile"] = application["role_profile"] or clean_text(str(existing.get("role_profile", "")))
    existing["score"] = max(safe_int(existing.get("score", 0), 0), application["score"])
    existing["best_score"] = max(
        safe_int(existing.get("best_score", 0), 0), application["best_score"], existing["score"]
    )
    existing["reasons"] = dedupe_preserving_order(application["reasons"] + list(existing.get("reasons", [])))[:6]
    existing["why_this_fits"] = dedupe_preserving_order(
        application["why_this_fits"] + list(existing.get("why_this_fits", []))
    )[:3]
    existing["resume_bullet_suggestions"] = dedupe_preserving_order(
        application["resume_bullet_suggestions"] + list(existing.get("resume_bullet_suggestions", []))
    )[:3]
    existing["intro_message"] = application["intro_message"] or clean_text(str(existing.get("intro_message", "")))
    existing["application_ready"] = bool(
        parse_bool(existing.get("application_ready", False), False) or application["application_ready"]
    )
    existing["feedback_keywords"] = dedupe_preserving_order(
        application["feedback_keywords"] + list(existing.get("feedback_keywords", []))
    )[:8]
    existing["status_observed_utc"] = clean_text(str(existing.get("status_observed_utc", ""))) or clean_text(
        str(application.get("status_observed_utc", ""))
    )
    existing["applied_at_utc"] = clean_text(str(existing.get("applied_at_utc", ""))) or clean_text(
        str(application.get("applied_at_utc", ""))
    )
    existing["interviewed_at_utc"] = clean_text(str(existing.get("interviewed_at_utc", ""))) or clean_text(
        str(application.get("interviewed_at_utc", ""))
    )
    existing["rejected_at_utc"] = clean_text(str(existing.get("rejected_at_utc", ""))) or clean_text(
        str(application.get("rejected_at_utc", ""))
    )
    existing["notes"] = clean_text(str(existing.get("notes", "")))
    existing["first_seen_utc"] = clean_text(str(existing.get("first_seen_utc", ""))) or seen_at_utc
    existing["last_seen_utc"] = seen_at_utc
    existing["match_count"] = max(1, safe_int(existing.get("match_count", 1), 1) + 1)
    existing["fingerprints"] = dedupe_preserving_order(
        list(existing.get("fingerprints", [])) + application["fingerprints"]
    )


def find_application_record(
    applications: list[dict[str, object]],
    fingerprints: list[str],
    link: str,
) -> dict[str, object] | None:
    fingerprint_set = set(fingerprints)
    for application in applications:
        existing_links = {str(item) for item in application.get("links", [])}
        if link and link in existing_links:
            return application
        existing_fingerprints = {str(item) for item in application.get("fingerprints", [])}
        if fingerprint_set and existing_fingerprints.intersection(fingerprint_set):
            return application
    return None


def upsert_application_record(
    applications_state: dict[str, object],
    payload: dict[str, object],
    seen_at_utc: str,
) -> bool:
    application = normalize_application_record(
        {
            **payload,
            "first_seen_utc": clean_text(str(payload.get("first_seen_utc", ""))) or seen_at_utc,
            "last_seen_utc": seen_at_utc,
        }
    )
    if application is None:
        return False
    existing = find_application_record(
        applications_state["applications"], application["fingerprints"], application["link"]
    )
    if existing is None:
        applications_state["applications"].append(application)
        applications_state["applications"] = applications_state["applications"][-MAX_APPLICATION_RECORDS:]
        return True
    _merge_application_record(existing, application, seen_at_utc)
    return False


def upsert_application_record_in_storage(payload: dict[str, object], seen_at_utc: str) -> bool:
    application = normalize_application_record(
        {
            **payload,
            "first_seen_utc": clean_text(str(payload.get("first_seen_utc", ""))) or seen_at_utc,
            "last_seen_utc": seen_at_utc,
        }
    )
    if application is None:
        return False

    existing_link, existing = storage.find_application_by_link_or_fingerprints(
        STATE_DB_FILE,
        application["link"],
        application["fingerprints"],
    )
    if existing is None:
        storage.save_application_record(STATE_DB_FILE, application)
        return True

    normalized_existing = normalize_application_record(existing)
    if normalized_existing is None:
        storage.save_application_record(STATE_DB_FILE, application, previous_link=existing_link)
        return True

    _merge_application_record(normalized_existing, application, seen_at_utc)
    storage.save_application_record(STATE_DB_FILE, normalized_existing, previous_link=existing_link)
    return False


def seed_applications_from_existing_jobs(
    applications_state: dict[str, object],
    existing_jobs: list[dict[str, str]],
) -> int:
    if applications_state["applications"] or not existing_jobs:
        return 0
    created = 0
    for job in existing_jobs:
        if upsert_application_record(
            applications_state,
            {
                "title": job["title"],
                "description": job["description"],
                "link": job["link"],
                "company": split_title_and_company(job["title"])[1],
                "status": "new",
                "score": 0,
                "best_score": 0,
                "reasons": [],
            },
            job["time"] or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        ):
            created += 1
    return created


def rank_application_for_digest(application: dict[str, object], current_dt: datetime) -> tuple[int, float]:
    last_seen_dt = parse_iso_utc(application.get("last_seen_utc", "")) or parse_iso_utc(
        application.get("first_seen_utc", "")
    )
    age_hours = 9999.0
    freshness_bonus = 0.0
    if last_seen_dt is not None:
        age_hours = max(0.0, (current_dt - last_seen_dt).total_seconds() / 3600)
        freshness_bonus = max(0.0, 72.0 - age_hours) / 6.0
    company_control = normalize_company_control(application.get("company_control", "none"))
    status = normalize_application_status(application.get("status", "new"))
    status_bonus = {"new": 8, "reviewed": 4, "applied": 1, "interview": 2, "rejected": -50}.get(status, 0)
    company_bonus = (
        16 if parse_bool(application.get("shortlisted", False), False) else 8 if company_control == "whitelist" else 0
    )
    rank = round(
        max(safe_int(application.get("score", 0), 0), safe_int(application.get("best_score", 0), 0))
        + freshness_bonus
        + company_bonus
        + status_bonus
    )
    return rank, age_hours


def build_daily_digest_snapshot(
    current_run_ts: str,
    applications_state: dict[str, object],
    search_config: dict[str, object],
) -> dict[str, object]:
    current_dt = parse_iso_utc(current_run_ts) or datetime.now(timezone.utc)
    digest_settings = search_config["daily_digest"]
    items = []
    for application in applications_state["applications"]:
        status = normalize_application_status(application.get("status", "new"))
        if status not in digest_settings["include_statuses"]:
            continue
        rank, age_hours = rank_application_for_digest(application, current_dt)
        items.append(
            {
                "title": str(application["title"]),
                "company": clean_text(str(application.get("company", "")))
                or clean_text(str(application.get("source", ""))),
                "link": str(application["link"]),
                "status": status,
                "score": max(safe_int(application.get("score", 0), 0), safe_int(application.get("best_score", 0), 0)),
                "rank": rank,
                "shortlisted": parse_bool(application.get("shortlisted", False), False),
                "company_control": normalize_company_control(application.get("company_control", "none")),
                "role_profile": clean_text(str(application.get("role_profile", ""))),
                "reasons": list(application.get("reasons", []))[:3],
                "first_seen_utc": clean_text(str(application.get("first_seen_utc", ""))),
                "last_seen_utc": clean_text(str(application.get("last_seen_utc", ""))),
                "age_hours": round(age_hours, 1),
            }
        )
    items.sort(
        key=lambda item: (
            int(item["shortlisted"]),
            COMPANY_CONTROL_ORDER.get(str(item["company_control"]), 0),
            int(item["rank"]),
            int(item["score"]),
            clean_text(str(item["last_seen_utc"])),
            clean_text(str(item["title"])),
        ),
        reverse=True,
    )
    limited_items = items[: int(digest_settings["max_items"])]
    return {
        "generated_at": current_run_ts,
        "digest_date_utc": current_dt.date().isoformat(),
        "item_count": len(limited_items),
        "items": limited_items,
        "include_statuses": list(digest_settings["include_statuses"]),
    }


def save_daily_digest_snapshot(daily_digest_file: str, snapshot: dict[str, object]) -> None:
    atomic_write_json(Path(daily_digest_file), snapshot)


def _format_daily_digest_item(item: dict[str, object], index: int) -> str:
    badges = [f"score {item['score']}", str(item["status"])]
    if item["shortlisted"]:
        badges.insert(0, "shortlist")
    elif item["company_control"] == "whitelist":
        badges.insert(0, "whitelist")

    lines = [
        f"{index}. {' | '.join(badges)}",
        f"{item['title']} at {item['company']}",
    ]
    if item.get("reasons"):
        lines.append(f"Why: {item['reasons'][0]}")
    lines.append(str(item["link"]))
    return "\n".join(lines)


def format_daily_digest_messages(
    snapshot: dict[str, object],
    page_size: int,
    max_chars: int = 3500,
) -> list[str]:
    items = list(snapshot.get("items", []))
    if not items:
        return [f"Daily Job Digest: {snapshot['digest_date_utc']}\nNo items."]

    page_size = max(1, int(page_size))
    item_blocks = [_format_daily_digest_item(item, index) for index, item in enumerate(items, start=1)]
    pages: list[list[str]] = []
    current_page: list[str] = []
    current_length = 0
    header_budget = 120

    for block in item_blocks:
        block_length = len(block) + 2
        if current_page and (
            len(current_page) >= page_size or current_length + block_length + header_budget > max_chars
        ):
            pages.append(current_page)
            current_page = []
            current_length = 0
        current_page.append(block)
        current_length += block_length

    if current_page:
        pages.append(current_page)

    total_pages = len(pages)
    messages = []
    first_item_index = 1
    for page_number, page_blocks in enumerate(pages, start=1):
        last_item_index = first_item_index + len(page_blocks) - 1
        lines = [
            f"Daily Job Digest: {snapshot['digest_date_utc']}",
            f"Page {page_number}/{total_pages} | Jobs {first_item_index}-{last_item_index} of {snapshot['item_count']}",
            "",
            "\n\n".join(page_blocks),
        ]
        messages.append("\n".join(lines).strip())
        first_item_index = last_item_index + 1
    return messages


def format_daily_digest_message(snapshot: dict[str, object]) -> str:
    return format_daily_digest_messages(snapshot, page_size=max(1, len(snapshot.get("items", []))))[0]


_DIGEST_CALLBACK_PREFIX = "dg:"
_NOOP_PAGE_TOKEN = "noop"


def _build_digest_callback_data(session_id: str, page_token: int | str) -> str:
    return f"{_DIGEST_CALLBACK_PREFIX}{session_id}:{page_token}"


def parse_digest_callback_data(value: object) -> tuple[str | None, str | None]:
    data = clean_text(str(value))
    if not data.startswith(_DIGEST_CALLBACK_PREFIX):
        return None, None
    parts = data.split(":", 2)
    if len(parts) != 3:
        return None, None
    session_id = clean_text(parts[1])
    page_token = clean_text(parts[2])
    if not session_id or not page_token:
        return None, None
    return session_id, page_token


def build_daily_digest_keyboard(session_id: str, page_index: int, total_pages: int) -> dict[str, object] | None:
    if total_pages <= 1:
        return None
    previous_target: int | str = page_index - 1 if page_index > 0 else _NOOP_PAGE_TOKEN
    next_target: int | str = page_index + 1 if page_index < total_pages - 1 else _NOOP_PAGE_TOKEN
    return {
        "inline_keyboard": [
            [
                {"text": "◀ Prev", "callback_data": _build_digest_callback_data(session_id, previous_target)},
                {
                    "text": f"{page_index + 1}/{total_pages}",
                    "callback_data": _build_digest_callback_data(session_id, _NOOP_PAGE_TOKEN),
                },
                {"text": "Next ▶", "callback_data": _build_digest_callback_data(session_id, next_target)},
            ]
        ]
    }


def _ack_callback(callback_query_id: str, token: str, text: str = "", show_alert: bool = False) -> None:
    if callback_query_id:
        answer_telegram_callback_query(callback_query_id, token, text, show_alert)


def process_telegram_callback_updates(timeout: int = 0, limit: int = 20) -> tuple[int, str]:
    token, _, _ = load_telegram_settings()
    if not token:
        return 0, ""

    update_offset = storage.load_telegram_update_offset(STATE_DB_FILE)
    ok, updates, error = fetch_telegram_updates(
        token,
        update_offset,
        allowed_updates=["callback_query"],
        limit=limit,
        timeout=timeout,
    )
    if not ok:
        return 0, error

    handled_count = 0
    last_error = ""
    next_offset = update_offset
    for update in updates:
        update_id = safe_int(update.get("update_id", 0), 0)
        next_offset = max(next_offset, update_id + 1)

        callback_query = update.get("callback_query")
        if not isinstance(callback_query, dict):
            continue

        callback_query_id = clean_text(str(callback_query.get("id", "")))
        session_id, page_token = parse_digest_callback_data(callback_query.get("data", ""))
        if session_id is None or page_token is None:
            _ack_callback(callback_query_id, token)
            continue

        if page_token == _NOOP_PAGE_TOKEN:
            _ack_callback(callback_query_id, token)
            continue

        session = storage.load_telegram_digest_session(STATE_DB_FILE, session_id)
        if session is None:
            _ack_callback(callback_query_id, token, "This digest is no longer available.")
            continue

        pages = session["pages"]
        if not pages:
            _ack_callback(callback_query_id, token, "This digest is empty.")
            continue

        page_index = max(0, min(len(pages) - 1, safe_int(page_token, 0)))
        message = callback_query.get("message")
        if not isinstance(message, dict):
            _ack_callback(callback_query_id, token, "Message context missing.", True)
            continue

        chat = message.get("chat")
        chat_id = ""
        if isinstance(chat, dict):
            chat_id = clean_text(str(chat.get("id", "")))
        message_id = safe_int(message.get("message_id", 0), 0)
        if not chat_id or not message_id:
            _ack_callback(callback_query_id, token, "Message context missing.", True)
            continue

        keyboard = build_daily_digest_keyboard(session_id, page_index, len(pages))
        ok, edit_error = edit_telegram_message(
            pages[page_index],
            token,
            chat_id,
            message_id,
            keyboard,
        )
        if not ok:
            last_error = edit_error
            _ack_callback(callback_query_id, token, f"Unable to change page: {edit_error}", True)
            continue

        _ack_callback(callback_query_id, token)
        handled_count += 1

    if next_offset != update_offset:
        storage.save_telegram_update_offset(STATE_DB_FILE, next_offset)
    return handled_count, last_error


def maybe_send_daily_digest(
    applications_state: dict[str, object],
    snapshot: dict[str, object],
    current_run_ts: str,
    search_config: dict[str, object],
) -> tuple[bool, str]:
    digest_settings = search_config["daily_digest"]
    current_dt = parse_iso_utc(current_run_ts) or datetime.now(timezone.utc)
    digest_date = current_dt.date().isoformat()
    if not digest_settings["enabled"]:
        applications_state["last_digest_error"] = ""
        return False, ""
    if current_dt.hour < int(digest_settings["hour_utc"]):
        return False, ""
    if clean_text(str(applications_state.get("last_digest_date_utc", ""))) == digest_date:
        return False, ""
    if not snapshot["items"]:
        applications_state["last_digest_utc"] = current_run_ts
        applications_state["last_digest_date_utc"] = digest_date
        applications_state["last_digest_error"] = ""
        return False, ""
    token, chat_id, thread_id = load_telegram_settings()
    if not token or not chat_id:
        error = "Telegram credentials not configured; daily digest not sent."
        applications_state["last_digest_error"] = error
        return False, error
    digest_messages = format_daily_digest_messages(snapshot, int(digest_settings["page_size"]))
    session_id = uuid.uuid4().hex[:12]
    storage.save_telegram_digest_session(STATE_DB_FILE, session_id, current_run_ts, digest_messages)
    keyboard = build_daily_digest_keyboard(session_id, 0, len(digest_messages))
    ok, _, error = send_telegram_message_with_markup(
        digest_messages[0],
        token,
        chat_id,
        thread_id,
        keyboard,
    )
    if not ok:
        applications_state["last_digest_error"] = error
        return False, error
    applications_state["last_digest_utc"] = current_run_ts
    applications_state["last_digest_date_utc"] = digest_date
    applications_state["last_digest_error"] = ""
    return True, ""


def build_application_briefs_snapshot(
    current_run_ts: str,
    applications_state: dict[str, object],
    max_items: int,
) -> dict[str, object]:
    current_dt = parse_iso_utc(current_run_ts) or datetime.now(timezone.utc)
    items = []
    for application in applications_state["applications"]:
        if not parse_bool(application.get("application_ready", False), False):
            continue
        status = normalize_application_status(application.get("status", "new"))
        if status == "rejected":
            continue
        rank, age_hours = rank_application_for_digest(application, current_dt)
        items.append(
            {
                "title": clean_text(str(application.get("title", ""))),
                "company": clean_text(str(application.get("company", ""))),
                "link": clean_text(str(application.get("link", ""))),
                "status": status,
                "score": max(safe_int(application.get("score", 0), 0), safe_int(application.get("best_score", 0), 0)),
                "rank": rank,
                "shortlisted": parse_bool(application.get("shortlisted", False), False),
                "company_control": normalize_company_control(application.get("company_control", "none")),
                "role_profile": clean_text(str(application.get("role_profile", ""))),
                "why_this_fits": list(application.get("why_this_fits", []))[:3],
                "resume_bullet_suggestions": list(application.get("resume_bullet_suggestions", []))[:3],
                "intro_message": clean_text(str(application.get("intro_message", ""))),
                "notes": clean_text(str(application.get("notes", ""))),
                "last_seen_utc": clean_text(str(application.get("last_seen_utc", ""))),
                "age_hours": round(age_hours, 1),
            }
        )
    items.sort(
        key=lambda item: (
            int(item["shortlisted"]),
            COMPANY_CONTROL_ORDER.get(str(item["company_control"]), 0),
            int(item["rank"]),
            int(item["score"]),
            clean_text(str(item["last_seen_utc"])),
        ),
        reverse=True,
    )
    limited_items = items[:max_items]
    return {"generated_at": current_run_ts, "brief_count": len(limited_items), "items": limited_items}


def save_application_briefs_snapshot(application_briefs_file: str, snapshot: dict[str, object]) -> None:
    atomic_write_json(Path(application_briefs_file), snapshot)


def save_borderline_matches_snapshot(
    borderline_matches_file: str,
    current_run_ts: str,
    candidates: list[dict[str, object]],
    max_items: int,
) -> None:
    sorted_candidates = sorted(
        candidates,
        key=lambda item: (
            safe_int(item.get("score", 0), 0),
            int(parse_bool(item.get("shortlisted", False), False)),
            clean_text(str(item.get("title", ""))),
        ),
        reverse=True,
    )
    snapshot = {
        "generated_at": current_run_ts,
        "min_match_score": MIN_MATCH_SCORE,
        "review_band": {
            "min_score": max(0, MIN_MATCH_SCORE - BORDERLINE_MATCH_MARGIN),
            "max_score": MIN_MATCH_SCORE - 1,
        },
        "candidate_count": len(sorted_candidates[:max_items]),
        "candidates": sorted_candidates[:max_items],
    }
    atomic_write_json(Path(borderline_matches_file), snapshot)
