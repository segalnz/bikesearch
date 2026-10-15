"""Small application ports; adapters implement these without framework coupling."""

from pathlib import Path
from typing import Protocol

from .schema import Listing


class PageFetcher(Protocol):
    requests: int
    last_request: float
    cache_dir: Path | None

    def get(self, url: str, hosts: list[str], *, data: dict | None = None) -> str: ...
    def close(self) -> None: ...


class CandidateReviewer(Protocol):
    """Advisory enrichment only: implementations must not change eligibility."""

    def review(self, listing: Listing, search: dict) -> None: ...
    def close(self) -> None: ...
