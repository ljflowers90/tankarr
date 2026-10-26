"""Metron catalogue client (operator-supplied account)."""

from __future__ import annotations

import asyncio
import base64
import time

import httpx

from tankarr.comics.base import (
    ComicIssue,
    ComicSeries,
    RequestGuard,
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


class MetronClient(RequestGuard):
    name = NAME
    label = LABEL

    def __init__(self, settings: Settings):
        self.settings = settings
        # Credentials are read per request: saving new ones in Settings takes
        # effect without a restart.
        self.http = ProviderHTTP(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout_seconds=max(30.0, float(settings.request_timeout_seconds)),
            requests_per_second=1.0 / SECONDS_BETWEEN_REQUESTS,
            # Never resend: a retried request still counts against the limit.
            max_attempts=1,
        )
        self._gate = asyncio.Lock()
        RequestGuard.__init__(self, self._credentials)

    @property
    def enabled(self) -> bool:
        return bool(self.settings.metron_enabled)

    @property
    def configured(self) -> bool:
        return bool(self.settings.metron_username and self.settings.metron_password)

    def _credentials(self) -> tuple[str, ...]:
        return (
            self.settings.metron_username or "",
            self.settings.metron_password or "",
        )

    def _auth_header(self) -> dict[str, str]:
        token = base64.b64encode(":".join(self._credentials()).encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def _record_limits(self, response: httpx.Response) -> None:
        now = time.time()
        for window in ("Burst", "Sustained"):
            remaining = _header_int(response, f"X-RateLimit-{window}-Remaining")
            reset = _header_int(response, f"X-RateLimit-{window}-Reset")
            if remaining is not None and remaining <= 0:
                wait = max(1.0, (reset - now) if reset else DEFAULT_LOCKOUT_SECONDS)
                self.block(wait, f"Metron {window.lower()} request limit used up")

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
                    "GET",
                    f"{base}/{path}/",
                    params=params,
                    headers=self._auth_header(),
                )
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in (401, 403):
                    self.halt(
                        f"Metron rejected the credentials (HTTP {status}); "
                        "update them in Settings"
                    )
                    raise MetronError(self._halted, status_code=status) from None
                raise MetronError(
                    f"Metron returned HTTP {status}", status_code=status
                ) from None
            except ProviderRequestError as exc:
                if exc.status_code == 429:
                    self.block(DEFAULT_LOCKOUT_SECONDS, "Metron rate limit reached")
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

    async def probe(self) -> dict:
        """One real request, timed. A rejected credential halts the client."""

        started = time.monotonic()
        try:
            payload = await self._get("series", {"name": "batman"})
        except ProviderRequestError as exc:
            return {
                "ok": False,
                "enabled": self.enabled,
                "error": redact_secrets(str(exc))[:300],
                "latency_ms": round((time.monotonic() - started) * 1000),
            }
        return {
            "ok": True,
            "enabled": self.enabled,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "results": len(payload.get("results") or []),
        }

    async def aclose(self) -> None:
        await self.http.aclose()
