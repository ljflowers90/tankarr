"""Provider-neutral comic catalogue types."""

from __future__ import annotations

import time
from collections.abc import Callable
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


class RequestGuard:
    """Stops a catalogue client from hammering a service that said no.

    A rejected credential halts the client until the credentials change; a
    rate limit pauses it for a while. Neither state is left by retrying.
    """

    def __init__(self, credentials: Callable[[], tuple[str, ...]]):
        self._credentials = credentials
        self._halted: str | None = None
        self._halted_credentials: tuple[str, ...] | None = None
        self._blocked_until = 0.0
        self._blocked_reason = ""

    def halt(self, reason: str) -> None:
        self._halted = reason
        self._halted_credentials = self._credentials()

    def block(self, seconds: float, reason: str) -> None:
        self._blocked_until = max(self._blocked_until, time.time() + seconds)
        self._blocked_reason = reason

    def adopt_lockout(self, other: RequestGuard) -> None:
        """Carry over a pause another client of the same service just hit."""

        if other.lockout_reason:
            self._blocked_until = max(self._blocked_until, other._blocked_until)
            self._blocked_reason = other._blocked_reason

    @property
    def lockout_reason(self) -> str | None:
        """A time-based pause (rate limit), whatever the credentials are."""

        remaining = self._blocked_until - time.time()
        if remaining > 0:
            return f"{self._blocked_reason}; retry in {int(remaining // 60) + 1} min"
        return None

    @property
    def blocked_reason(self) -> str | None:
        """Why no request is being sent, or None when the service can be called."""

        if self._halted and self._halted_credentials != self._credentials():
            self._halted = None
        return self._halted or self.lockout_reason
