"""Metron catalogue client (operator-supplied account)."""

from __future__ import annotations

import asyncio
import time

import httpx

from tankarr.comics.base import (
    ComicIssue,
    ComicSeries,
    clean_text,
    to_int,
    to_year,
)
from tankarr.config import Settings
from tankarr.providers.base import ProviderHTTP, ProviderRequestError
from tankarr.redaction import redact_secrets

NAME = "metron"
LABEL = "Metron"
USER_AGENT = "Tankarr (+https://github.com/Renzodef/tankarr)"
MAX_PAGES = 200
# Metron limits a client to 15 requests a minute and bans it for an hour when
# it goes over; one request every five seconds stays well under that.
SECONDS_BETWEEN_REQUESTS = 5.0
DEFAULT_LOCKOUT_SECONDS = 3600.0


class MetronError(ProviderRequestError):
    pass


def _header_int(response: httpx.Response, name: str) -> int | None:
    try:
        return int(response.headers[name])
    except (KeyError, ValueError):
        return None


def _name(value: object) -> str | None:
    if isinstance(value, dict):
        return clean_text(value.get("name"))
    return clean_text(value)


class MetronClient:
    name = NAME
    label = LABEL

    def __init__(self, settings: Settings):
        self.settings = settings
        auth = None
        if settings.metron_username and settings.metron_password:
            auth = httpx.BasicAuth(settings.metron_username, settings.metron_password)
        # Metron asks clients to stay under 30 requests a minute.
        self.http = ProviderHTTP(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            auth=auth,
            timeout_seconds=max(30.0, float(settings.request_timeout_seconds)),
            requests_per_second=1.0 / SECONDS_BETWEEN_REQUESTS,
            # Never resend: a retried request still counts against the limit.
            max_attempts=1,
        )
        self._gate = asyncio.Lock()
        self._halted: str | None = None
        self._blocked_until = 0.0
        self._blocked_reason = ""

    @property
    def enabled(self) -> bool:
        return bool(self.settings.metron_enabled)

    @property
    def configured(self) -> bool:
        return bool(self.settings.metron_username and self.settings.metron_password)

    @property
    def blocked_reason(self) -> str | None:
        """Why no request is being sent, or None when Metron can be called."""

        if self._halted:
            return self._halted
        remaining = self._blocked_until - time.time()
        if remaining > 0:
            return f"{self._blocked_reason}; retry in {int(remaining // 60) + 1} min"
        return None

    def _block(self, seconds: float, reason: str) -> None:
        self._blocked_until = max(self._blocked_until, time.time() + seconds)
        self._blocked_reason = reason

    def _record_limits(self, response: httpx.Response) -> None:
        now = time.time()
        for window in ("Burst", "Sustained"):
            remaining = _header_int(response, f"X-RateLimit-{window}-Remaining")
            reset = _header_int(response, f"X-RateLimit-{window}-Reset")
            if remaining is not None and remaining <= 0:
                wait = max(1.0, (reset - now) if reset else DEFAULT_LOCKOUT_SECONDS)
                self._block(wait, f"Metron {window.lower()} request limit used up")

    async def _get(self, path: str, params: dict | None = None) -> dict:
        if not self.configured:
            raise MetronError("Metron credentials are not set")
        base = self.settings.metron_api_url.rstrip("/")
        # One request at a time: after a refusal nothing else may be in flight.
        async with self._gate:
            reason = self.blocked_reason
            if reason:
                raise MetronError(f"Metron requests are paused: {reason}")
            try:
                response = await self.http.request(
                    "GET", f"{base}/{path}/", params=params
                )
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in (401, 403):
                    self._halted = (
                        f"Metron rejected the credentials (HTTP {status}); "
                        "fix them in Settings and restart Tankarr"
                    )
                    raise MetronError(self._halted, status_code=status) from None
                raise MetronError(
                    f"Metron returned HTTP {status}", status_code=status
                ) from None
            except ProviderRequestError as exc:
                if exc.status_code == 429:
                    self._block(DEFAULT_LOCKOUT_SECONDS, "Metron rate limit reached")
                    raise MetronError(
                        "Metron rate limit reached; requests are paused for an hour",
                        status_code=429,
                    ) from None
                raise MetronError(
                    redact_secrets(str(exc)), status_code=exc.status_code
                ) from None
            self._record_limits(response)
            payload = response.json()
        if not isinstance(payload, dict):
            raise MetronError("Metron returned an unusable response")
        return payload

    @staticmethod
    def _series(record: dict) -> ComicSeries:
        return ComicSeries(
            provider=NAME,
            provider_id=str(record["id"]),
            title=clean_text(record.get("name") or record.get("series")) or "Untitled",
            publisher=_name(record.get("publisher")),
            year=to_year(record.get("year_began")),
            description=clean_text(record.get("desc")),
            cover_url=record.get("image"),
            issue_count=to_int(record.get("issue_count")),
            status=clean_text(record.get("status")),
        )

    async def search(self, query: str, *, limit: int = 20) -> list[ComicSeries]:
        payload = await self._get("series", {"name": query})
        return [
            self._series(r)
            for r in (payload.get("results") or [])[:limit]
            if r.get("id")
        ]

    async def series(self, provider_id: str) -> ComicSeries:
        record = await self._get(f"series/{provider_id}")
        if not record.get("id"):
            raise MetronError("Metron series not found", status_code=404)
        return self._series(record)

    async def issues(self, provider_id: str) -> list[ComicIssue]:
        found: list[ComicIssue] = []
        for page in range(1, MAX_PAGES + 1):
            payload = await self._get("issue", {"series_id": provider_id, "page": page})
            for record in payload.get("results") or []:
                number = clean_text(record.get("number"))
                if record.get("id") and number:
                    found.append(
                        ComicIssue(
                            provider_id=str(record["id"]),
                            number=number,
                            title=clean_text(record.get("issue")),
                            cover_date=record.get("cover_date"),
                            store_date=record.get("store_date"),
                        )
                    )
            if not payload.get("next"):
                break
        return found

    async def aclose(self) -> None:
        await self.http.aclose()
