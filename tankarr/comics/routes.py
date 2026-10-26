from __future__ import annotations

import asyncio

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from tankarr.comics import importer as comic_import
from tankarr.comics.base import ComicProvider
from tankarr.comics.store import ComicStore
from tankarr.config import Settings
from tankarr.providers.base import ProviderRequestError
from tankarr.redaction import redact_secrets


class AddComicSeries(BaseModel):
    provider: str
    provider_id: str


class MonitoredBody(BaseModel):
    monitored: bool


class ImportItem(BaseModel):
    path: str
    series_id: str
    issue_id: str


class ComicImportRequest(BaseModel):
    items: list[ImportItem] = Field(min_length=1, max_length=5000)
    upload_id: str | None = None
    move: bool = False


def register_comic_routes(
    app: FastAPI,
    providers: dict[str, ComicProvider],
    store: ComicStore,
    settings: Settings,
    importer,
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

    def usable(provider: ComicProvider) -> bool:
        return (
            provider.enabled
            and provider.configured
            and not getattr(provider, "blocked_reason", None)
        )

    @app.get("/api/comics/search")
    async def comic_search(
        q: str = Query(min_length=2, max_length=200), provider: str = "all"
    ):
        """Search one catalogue, or every catalogue that is ready to be used."""

        if provider == "all":
            chosen = [p for p in providers.values() if usable(p)]
            if not chosen:
                raise HTTPException(
                    409,
                    "No comic catalogue is ready: enable ComicVine or Metron and "
                    "add its credentials in Settings",
                )
        else:
            chosen = [provider_for(provider)]
        outcomes = await asyncio.gather(
            *(p.search(q.strip()) for p in chosen), return_exceptions=True
        )
        tracked = {(row["provider"], row["provider_id"]) for row in store.list_series()}
        results: list[dict] = []
        errors: list[dict] = []
        for catalogue, outcome in zip(chosen, outcomes, strict=True):
            if isinstance(outcome, ProviderRequestError):
                errors.append(
                    {"provider": catalogue.label, "error": redact_secrets(str(outcome))}
                )
            elif isinstance(outcome, BaseException):
                raise outcome
            else:
                results.extend(
                    {
                        **item.as_dict(),
                        "in_library": (item.provider, item.provider_id) in tracked,
                    }
                    for item in outcome
                )
        if errors and len(errors) == len(chosen):
            raise HTTPException(502, "; ".join(e["error"] for e in errors))
        return {"results": results, "errors": errors}

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

    def import_root(upload_id: str | None):
        try:
            if upload_id:
                return importer._upload_root(upload_id)
            if importer.root is None:
                raise FileNotFoundError("No import directory is configured or mounted")
            return importer.root
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/comics/import/scan")
    async def comic_import_scan(upload_id: str | None = None):
        root = import_root(upload_id)
        return await asyncio.to_thread(comic_import.scan, root, store)

    @app.post("/api/comics/import", status_code=202)
    async def comic_import_run(body: ComicImportRequest):
        root = import_root(body.upload_id)
        return await asyncio.to_thread(
            comic_import.import_files,
            settings,
            store,
            root,
            [item.model_dump() for item in body.items],
            move=body.move,
        )
