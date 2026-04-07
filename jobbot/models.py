import abc
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass
class JobLead:
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
        pass
