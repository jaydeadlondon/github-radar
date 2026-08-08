"""Custom exceptions raised by the GitHub API client."""


class GitHubError(Exception):
    """Base class for all GitHub client errors."""


class ApiError(GitHubError):
    """Generic API error with an optional HTTP status code."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RateLimitError(GitHubError):
    """Raised when the GitHub API rate limit is exceeded."""


class NotFoundError(ApiError):
    """Raised when a requested resource does not exist."""


class AuthenticationError(ApiError):
    """Raised when authentication with the GitHub API fails."""


class InvalidQueryError(ApiError):
    """Raised when the GitHub API rejects a query (HTTP 422)."""
