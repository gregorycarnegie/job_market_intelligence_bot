"""
Job Market Intelligence Bot core package.

This package provides the core logic for the job market intelligence bot,
including source ingestion, job matching, scoring, and persistence.
"""

from jobbot.common import load_job_search_config, load_resume_profile
from jobbot.logging_config import setup_logging
from jobbot.matching import (
    deliver_pending_alerts,
    maybe_send_daily_digest,
    queue_pending_alerts,
    score_job,
)
from jobbot.models import JobLead, Source
from jobbot.sources import create_source

__version__ = "1.1.0"

__all__ = [
    "JobLead",
    "Source",
    "create_source",
    "deliver_pending_alerts",
    "load_job_search_config",
    "load_resume_profile",
    "maybe_send_daily_digest",
    "queue_pending_alerts",
    "score_job",
    "setup_logging",
]
