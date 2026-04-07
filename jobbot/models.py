import abc
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass
class JobLead:
    """
    Structured representation of a job listing from any source.

    Attributes:
        title: The job title.
        link: The direct URL to the job listing.
        source: The name of the source platform.
        company: The hiring company name.
        location: Job location.
        salary: Salary information.
        description: Full or snippet description.
        employment_type: Type of employment (e.g. full-time).
        date_posted: The date the job was posted.
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

    Subclasses must implement the 'fetch' method to retrieve job leads.
    """

    def __init__(self, config: Mapping[str, object]):
        """
        Initialize the source with a configuration mapping.

        Args:
            config: A mapping containing source-specific settings.
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
