"""Provider-neutral comic catalogue types."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ComicSeries:
    provider: str
    provider_id: str
    title: str
    publisher: str | None = None
    year: int | None = None
    description: str | None = None
    cover_url: str | None = None
    issue_count: int | None = None
    status: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ComicIssue:
    provider_id: str
    number: str
    title: str | None = None
    cover_date: str | None = None
    store_date: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ComicProvider(Protocol):
    name: str
    label: str

    @property
    def enabled(self) -> bool: ...

    @property
    def configured(self) -> bool: ...

    async def search(self, query: str, *, limit: int = 20) -> list[ComicSeries]: ...

    async def series(self, provider_id: str) -> ComicSeries: ...

    async def issues(self, provider_id: str) -> list[ComicIssue]: ...

    async def aclose(self) -> None: ...


def to_int(value: object) -> int | None:
    try:
        return int(str(value).strip()) if value not in (None, "") else None
    except ValueError:
        return None


def to_year(value: object) -> int | None:
    """The year of a ``YYYY`` or ``YYYY-MM-DD`` value."""

    return to_int(str(value or "").strip()[:4])


def clean_text(value: object) -> str | None:
    text = " ".join(str(value or "").split())
    return text or None
