import abc
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypedDict

PatternEntry = tuple[str, re.Pattern[str]]

FeedState = dict[str, dict[str, float]]


@dataclass
class JobLead:  # pylint: disable=too-many-instance-attributes
    """
    Standardized data model representing a single job posting retrieved from a source.

    This dataclass ensures that all job leads, regardless of their origin (RSS, JSON, HTML, etc.),
    follow a consistent structure for scoring and storage.

    Attributes:
        title (str): The job title as provided by the source.
        link (str): The canonical URL to the job listing or application page.
        source (str): The common name of the source platform (e.g., "Greenhouse").
        company (str): The name of the hiring organization.
        location (str): Geographic or remote status string.
        salary (str): Raw salary or compensation text.
        description (str): The main body text of the job posting.
        employment_type (str): Category of employment (Full-time, Contract, etc.).
        date_posted (str): ISO or relative date string when the job was published.
    """

    title: str
    link: str
    source: str = ""
    company: str = ""
    location: str = ""
    salary: str = ""
    description: str = ""
    employment_type: str = ""
    date_posted: str = ""

    def to_dict(self) -> dict[str, str]:
        """
        Convert the JobLead instance to a flat dictionary of strings.

        Returns:
            A dictionary representation of the job lead.
        """
        return {
            "title": self.title,
            "link": self.link,
            "source": self.source,
            "company": self.company,
            "location": self.location,
            "salary": self.salary,
            "description": self.description,
            "employment_type": self.employment_type,
            "date_posted": self.date_posted,
        }


class Source(abc.ABC):
    """
    Abstract base class for all job source implementations.

    A Source implementation is responsible for interacting with a specific platform's
    API or web interface to retrieve a list of JobLead objects.

    Subclasses must implement the 'fetch' method.
    """

    def __init__(self, config: Mapping[str, object]):
        """
        Initialize the source with a configuration mapping.

        Args:
            config: A dictionary containing source-specific settings (URLs, API keys, etc.).
        """
        self.config = config

    @abc.abstractmethod
    def fetch(self) -> list[JobLead]:
        """
        Fetch new job leads from the source.

        Returns:
            A list of JobLead objects.
        """


class AlertState(TypedDict):
    """Persistent state for the Telegram alert queue and delivery history."""

    alerted_links: list[str]
    pending_alerts: list[dict[str, object]]
    last_run_utc: str
    last_delivery_utc: str
    last_delivery_error: str


class SeenJobsState(TypedDict):
    """Persistent state tracking which job fingerprints have already been reviewed."""

    reviewed_fingerprints: list[str]
    last_run_utc: str


class ApplicationsState(TypedDict):
    """Persistent state for application records and digest/feedback metadata."""

    applications: list[dict[str, object]]
    last_updated_utc: str
    last_digest_utc: str
    last_digest_date_utc: str
    last_digest_error: str
    last_feedback_utc: str
    last_cleanup_utc: str


class ResumeProfile(TypedDict):
    """Pre-processed resume data with compiled pattern entries for matching."""

    resume: dict[str, object]
    candidate_name: str
    candidate_title: str
    resume_summary: str
    prefs: dict[str, object]
    preferred_locations: list[str]
    target_role_entries: list[PatternEntry]
    skill_entries: list[PatternEntry]
    competency_entries: list[PatternEntry]
    experience_entries: list[dict[str, str]]


class SearchConfig(TypedDict):
    """Processed job-search configuration with compiled company-control pattern entries."""

    company_whitelist: list[str]
    company_blacklist: list[str]
    priority_companies: list[str]
    company_whitelist_entries: list[PatternEntry]
    company_blacklist_entries: list[PatternEntry]
    priority_company_entries: list[PatternEntry]
    role_profiles: list[dict[str, object]]
    daily_digest: dict[str, Any]
    feedback: dict[str, Any]
