from pydantic import BaseModel


class RepoSummary(BaseModel):
    id: int
    full_name: str
    description: str | None = None
    html_url: str
    language: str | None = None
    stargazers_count: int
    forks_count: int
    created_at: str | None = None
    pushed_at: str | None = None
    default_branch: str | None = None
    archived: bool = False
    open_issues_count: int = 0


class RepoSearchResponse(BaseModel):
    total_count: int
    incomplete_results: bool = False
    items: list[RepoSummary]
