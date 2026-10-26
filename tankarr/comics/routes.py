from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from tankarr.comics.base import ComicProvider
from tankarr.comics.store import ComicStore
from tankarr.providers.base import ProviderRequestError
from tankarr.redaction import redact_secrets


class AddComicSeries(BaseModel):
    provider: str
    provider_id: str


class MonitoredBody(BaseModel):
    monitored: bool


def register_comic_routes(
    app: FastAPI, providers: dict[str, ComicProvider], store: ComicStore
):
    def provider_for(name: str) -> ComicProvider:
        provider = providers.get(name)
        if provider is None:
            raise HTTPException(404, "Unknown comic catalogue")
        if not provider.enabled:
            raise HTTPException(409, f"{provider.label} is disabled in Settings")
        if not provider.configured:
            raise HTTPException(409, f"{provider.label} credentials are not set")
        paused = getattr(provider, "blocked_reason", None)
        if paused:
            raise HTTPException(409, f"{provider.label} requests are paused: {paused}")
        return provider

    def upstream(exc: ProviderRequestError) -> HTTPException:
        return HTTPException(502, redact_secrets(str(exc)))

    @app.get("/api/comics/providers")
    async def comic_providers():
        return [
            {
                "name": p.name,
                "label": p.label,
                "enabled": p.enabled,
                "configured": p.configured,
                "paused": getattr(p, "blocked_reason", None),
            }
            for p in providers.values()
        ]

    @app.get("/api/comics/search")
    async def comic_search(
        q: str = Query(min_length=2, max_length=200), provider: str = "comicvine"
    ):
        try:
            found = await provider_for(provider).search(q.strip())
        except ProviderRequestError as exc:
            raise upstream(exc) from exc
        tracked = {(row["provider"], row["provider_id"]) for row in store.list_series()}
        return [
            {
                **item.as_dict(),
                "in_library": (item.provider, item.provider_id) in tracked,
            }
            for item in found
        ]

    @app.post("/api/comics/series")
    async def comic_add(body: AddComicSeries):
        catalogue = provider_for(body.provider)
        try:
            series = await catalogue.series(body.provider_id)
            issues = await catalogue.issues(body.provider_id)
        except ProviderRequestError as exc:
            raise upstream(exc) from exc
        return store.add_series(series, issues)

    @app.get("/api/comics/series")
    async def comic_list():
        return store.list_series()

    @app.get("/api/comics/series/{series_id}")
    async def comic_get(series_id: str):
        try:
            return store.get_series(series_id)
        except KeyError as exc:
            raise HTTPException(404, "Comic series not found") from exc

    @app.put("/api/comics/series/{series_id}/monitored")
    async def comic_monitor(series_id: str, body: MonitoredBody):
        try:
            store.set_series_monitored(series_id, body.monitored)
        except KeyError as exc:
            raise HTTPException(404, "Comic series not found") from exc
        return store.get_series(series_id)

    @app.delete("/api/comics/series/{series_id}")
    async def comic_delete(series_id: str):
        try:
            store.delete_series(series_id)
        except KeyError as exc:
            raise HTTPException(404, "Comic series not found") from exc
        return {"deleted": series_id}

    @app.get("/api/comics/wanted")
    async def comic_wanted():
        return store.wanted()
