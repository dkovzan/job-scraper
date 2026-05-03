from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, eq=False)
class Job:
    id: str
    source: str
    title: str
    company: str
    location: str
    seniority: str | None
    salary: str | None
    url: str
    posted_at: datetime | None

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Job) and self.id == other.id


@dataclass
class Profile:
    name: str
    keywords: list[str] = field(default_factory=list)
