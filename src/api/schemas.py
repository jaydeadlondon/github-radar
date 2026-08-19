from datetime import datetime
from typing import Generic, TypeVar
from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Paginated(BaseModel, Generic[T]):
    total: int
    offset: int
    limit: int
    next_offset: int | None
    items: list[T]


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stargazers_count: int
    forks_count: int
    open_issues_count: int
    observed_at: datetime


class RepoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    description: str | None = None
    html_url: str
    language: str | None = None
    stargazers_count: int = 0
    forks_count: int = 0


class RepoDetailOut(BaseModel):
    id: int
    full_name: str
    description: str | None = None
    html_url: str
    language: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    latest_snapshot: SnapshotOut | None = None


class ErrorOut(BaseModel):
    detail: str
    code: int
