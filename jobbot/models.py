import abc
from dataclasses import dataclass


@dataclass
class JobLead:
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
    def __init__(self, config: dict[str, object]):
        self.config = config

    @abc.abstractmethod
    def fetch(self) -> list[JobLead]:
        pass
