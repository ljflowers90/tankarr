"""ComicVine catalogue client (operator-supplied API key)."""

from __future__ import annotations

import asyncio
import re
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

NAME = "comicvine"
LABEL = "ComicVine"
USER_AGENT = "Tankarr (+https://github.com/Renzodef/tankarr)"
RATE_LIMIT_PAUSE_SECONDS = 3600.0
_TAGS = re.compile(r"<[^>]+>")


class ComicVineError(ProviderRequestError):
    pass


def _description(record: dict) -> str | None:
    return clean_text(_TAGS.sub(" ", str(record.get("deck") or "")))


class ComicVineClient(RequestGuard):
    name = NAME
    label = LABEL

    def __init__(self, settings: Settings):
        self.settings = settings
        # ComicVine allows about 200 requests per resource per hour.
        self.http = ProviderHTTP(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout_seconds=max(30.0, float(settings.request_timeout_seconds)),
            requests_per_second=0.5,
            max_attempts=1,
        )
        self._gate = asyncio.Lock()
        RequestGuard.__init__(self, self._credentials)

    def _credentials(self) -> tuple[str, ...]:
        return (self.settings.comicvine_api_key or "",)

    @property
    def enabled(self) -> bool:
        return bool(self.settings.comicvine_enabled)

    @property
    def configured(self) -> bool:
        return bool(self.settings.comicvine_api_key)

    async def _get(self, path: str, params: dict) -> dict:
        if not self.configured:
            raise ComicVineError("ComicVine API key is not set")
        base = self.settings.comicvine_api_url.rstrip("/")
        query = {
            **params,
            "api_key": self.settings.comicvine_api_key,
            "format": "json",
        }
        async with self._gate:
            reason = self.blocked_reason
            if reason:
                raise ComicVineError(f"ComicVine requests are paused: {reason}")
            try:
                payload = await self.http.get_json(f"{base}/{path}/", params=query)
            except httpx.HTTPStatusError as exc:
                # The key travels in the query string: report the status only.
                status = exc.response.status_code
                if status in (401, 403):
                    self.halt(
                        f"ComicVine rejected the API key (HTTP {status}); "
                        "update it in Settings"
                    )
                    raise ComicVineError(self._halted, status_code=status) from None
                if status == 420:
                    self.block(RATE_LIMIT_PAUSE_SECONDS, "ComicVine rate limit reached")
                raise ComicVineError(
                    f"ComicVine returned HTTP {status}", status_code=status
                ) from None
            except ProviderRequestError as exc:
                if exc.status_code == 429:
                    self.block(RATE_LIMIT_PAUSE_SECONDS, "ComicVine rate limit reached")
                raise ComicVineError(
                    redact_secrets(str(exc)), status_code=exc.status_code
                ) from None
            code = payload.get("status_code") if isinstance(payload, dict) else None
            if code == 100:
                self.halt("ComicVine rejected the API key; update it in Settings")
                raise ComicVineError(self._halted, status_code=401)
            if code == 107:
                self.block(RATE_LIMIT_PAUSE_SECONDS, "ComicVine rate limit reached")
            if code != 1:
                error = payload.get("error") if isinstance(payload, dict) else None
                raise ComicVineError(f"ComicVine error: {error or 'unusable response'}")
        return payload

    @staticmethod
    def _series(record: dict) -> ComicSeries:
        image = record.get("image") or {}
        publisher = record.get("publisher") or {}
        return ComicSeries(
            provider=NAME,
            provider_id=str(record["id"]),
            title=clean_text(record.get("name")) or "Untitled",
            publisher=clean_text(publisher.get("name")),
            year=to_year(record.get("start_year")),
            description=_description(record),
            cover_url=image.get("medium_url") or image.get("original_url"),
            issue_count=to_int(record.get("count_of_issues")),
        )

    async def search(self, query: str, *, limit: int = 20) -> list[ComicSeries]:
        payload = await self._get(
            "search",
            {"query": query, "resources": "volume", "limit": min(limit, 50)},
        )
        return [self._series(r) for r in payload.get("results") or [] if r.get("id")]

    async def series(self, provider_id: str) -> ComicSeries:
        payload = await self._get(f"volume/4050-{provider_id}", {})
        record = payload.get("results") or {}
        if not record.get("id"):
            raise ComicVineError("ComicVine volume not found", status_code=404)
        return self._series(record)

    async def issues(self, provider_id: str) -> list[ComicIssue]:
        found: list[ComicIssue] = []
        offset = 0
        while True:
            payload = await self._get(
                "issues",
                {"filter": f"volume:{provider_id}", "offset": offset, "limit": 100},
            )
            for record in payload.get("results") or []:
                number = clean_text(record.get("issue_number"))
                if record.get("id") and number:
                    found.append(
                        ComicIssue(
                            provider_id=str(record["id"]),
                            number=number,
                            title=clean_text(record.get("name")),
                            cover_date=record.get("cover_date"),
                            store_date=record.get("store_date"),
                        )
                    )
            offset += int(payload.get("number_of_page_results") or 0)
            if not payload.get("number_of_page_results") or offset >= int(
                payload.get("number_of_total_results") or 0
            ):
                return found

    async def probe(self) -> dict:
        """One real request, timed."""

        started = time.monotonic()
        try:
            await self._get("volumes", {"limit": 1, "field_list": "id"})
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
        }

    async def aclose(self) -> None:
        await self.http.aclose()
