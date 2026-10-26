import time
from pathlib import Path

import respx
from fastapi.testclient import TestClient
from httpx import Response

from tankarr.app import create_app
from tankarr.config import Settings

CV = "https://cv.test/api"
METRON = "https://metron.test/api"


def make_client(tmp_path: Path, **overrides):
    frontend = tmp_path / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text("<title>t</title>", encoding="utf-8")
    settings = Settings(
        data_dir=tmp_path / "data",
        library_dir=tmp_path / "library",
        frontend_dir=frontend,
        metadata_enabled=False,
        monitor_enabled=False,
        comicvine_api_url=CV,
        metron_api_url=METRON,
        **overrides,
    )
    from tests.test_app_e2e import provision_library_identity

    provision_library_identity(settings)
    return TestClient(create_app(settings))


def metron_client(tmp_path: Path):
    client = make_client(
        tmp_path,
        metron_enabled=True,
        metron_username="fixture-user",
        metron_password="fixture-password",
    )
    return client


def unpaced(client) -> None:
    client.app.state.comic_providers["metron"].http.limiter.interval = 0.0


def cv_page(results, total=None):
    return Response(
        200,
        json={
            "status_code": 1,
            "number_of_page_results": len(results),
            "number_of_total_results": total if total is not None else len(results),
            "results": results,
        },
    )


@respx.mock
def test_comicvine_search_add_and_wanted(tmp_path: Path):
    respx.get(f"{CV}/search/").mock(
        return_value=cv_page(
            [
                {
                    "id": 4050,
                    "name": "Example Comic",
                    "start_year": "2019",
                    "count_of_issues": 123,
                    "publisher": {"name": "Example Press"},
                }
            ]
        )
    )
    respx.get(f"{CV}/volume/4050-4050/").mock(
        return_value=Response(
            200,
            json={
                "status_code": 1,
                "results": {
                    "id": 4050,
                    "name": "Example Comic",
                    "start_year": "2019",
                    "count_of_issues": 123,
                },
            },
        )
    )
    respx.get(f"{CV}/issues/").mock(
        return_value=cv_page(
            [
                {"id": 1, "issue_number": "1", "cover_date": "2019-01-01"},
                {"id": 2, "issue_number": "10", "cover_date": "2019-10-01"},
                {"id": 3, "issue_number": "2", "cover_date": "2019-02-01"},
            ]
        )
    )
    with make_client(
        tmp_path, comicvine_enabled=True, comicvine_api_key="fixture-key"
    ) as client:
        found = client.get("/api/comics/search", params={"q": "example"}).json()[
            "results"
        ]
        assert found[0]["title"] == "Example Comic"
        assert found[0]["issue_count"] == 123
        assert found[0]["year"] == 2019
        assert found[0]["in_library"] is False

        added = client.post(
            "/api/comics/series",
            json={"provider": "comicvine", "provider_id": "4050"},
        ).json()
        assert [i["number"] for i in added["issues"]] == ["1", "2", "10"]
        assert {i["status"] for i in added["issues"]} == {"wanted"}

        again = client.post(
            "/api/comics/series",
            json={"provider": "comicvine", "provider_id": "4050"},
        ).json()
        assert again["id"] == added["id"]
        assert len(client.get("/api/comics/series").json()) == 1
        assert len(client.get("/api/comics/wanted").json()) == 3
        assert (
            client.get("/api/comics/search", params={"q": "example"}).json()["results"][
                0
            ]["in_library"]
            is True
        )

        client.put(
            f"/api/comics/series/{added['id']}/monitored", json={"monitored": False}
        )
        assert client.get("/api/comics/wanted").json() == []
        assert client.delete(f"/api/comics/series/{added['id']}").status_code == 200
        assert client.get(f"/api/comics/series/{added['id']}").status_code == 404


@respx.mock
def test_comicvine_errors_never_carry_the_key(tmp_path: Path):
    respx.get(f"{CV}/search/").mock(return_value=Response(403))
    with make_client(
        tmp_path, comicvine_enabled=True, comicvine_api_key="fixture-secret-key"
    ) as client:
        response = client.get("/api/comics/search", params={"q": "example"})
        assert response.status_code == 502
        assert "fixture-secret-key" not in response.text
        assert "403" in response.text


def test_disabled_or_unconfigured_provider_is_refused(tmp_path: Path):
    with make_client(tmp_path) as client:
        assert (
            client.get("/api/comics/search", params={"q": "example"}).status_code == 409
        )
        providers = {p["name"]: p for p in client.get("/api/comics/providers").json()}
        assert providers["comicvine"] == {
            "name": "comicvine",
            "label": "ComicVine",
            "enabled": False,
            "configured": False,
            "paused": None,
        }
        assert "api_key" not in str(providers)


@respx.mock
def test_metron_search_and_add_paginates(tmp_path: Path):
    respx.get(f"{METRON}/series/").mock(
        return_value=Response(
            200,
            json={
                "results": [
                    {"id": 7, "series": "Example Comic (2020)", "year_began": 2020}
                ]
            },
        )
    )
    respx.get(f"{METRON}/series/7/").mock(
        return_value=Response(
            200,
            json={
                "id": 7,
                "name": "Example Comic",
                "year_began": 2020,
                "issue_count": 2,
                "publisher": {"id": 1, "name": "Example Press"},
            },
        )
    )
    route = respx.get(f"{METRON}/issue/").mock(
        side_effect=[
            Response(
                200,
                json={"next": "x", "results": [{"id": 11, "number": "1"}]},
            ),
            Response(
                200,
                json={"next": None, "results": [{"id": 12, "number": "2"}]},
            ),
        ]
    )
    with metron_client(tmp_path) as client:
        unpaced(client)
        found = client.get(
            "/api/comics/search", params={"q": "example", "provider": "metron"}
        ).json()["results"]
        assert found[0]["provider_id"] == "7"
        added = client.post(
            "/api/comics/series", json={"provider": "metron", "provider_id": "7"}
        ).json()
        assert added["publisher"] == "Example Press"
        assert [i["number"] for i in added["issues"]] == ["1", "2"]
        assert route.call_count == 2


def test_metron_is_paced_under_its_minute_limit(tmp_path: Path):
    with metron_client(tmp_path) as client:
        limiter = client.app.state.comic_providers["metron"].http.limiter
        assert limiter.interval >= 5.0  # at most 12 requests a minute


@respx.mock
def test_metron_stops_for_good_after_a_credential_rejection(tmp_path: Path):
    route = respx.get(f"{METRON}/series/").mock(return_value=Response(401))
    with metron_client(tmp_path) as client:
        unpaced(client)
        params = {"q": "example", "provider": "metron"}
        first = client.get("/api/comics/search", params=params)
        assert first.status_code == 502
        assert "credentials" in first.text
        for _ in range(3):
            assert client.get("/api/comics/search", params=params).status_code == 409
        added = client.post(
            "/api/comics/series", json={"provider": "metron", "provider_id": "7"}
        )
        assert added.status_code == 409
        assert route.call_count == 1
        listed = {p["name"]: p for p in client.get("/api/comics/providers").json()}
        assert "rejected the credentials" in listed["metron"]["paused"]
        assert "fixture-password" not in str(listed)


@respx.mock
def test_metron_pauses_after_a_rate_limit_response(tmp_path: Path):
    route = respx.get(f"{METRON}/series/").mock(return_value=Response(429))
    with metron_client(tmp_path) as client:
        unpaced(client)
        params = {"q": "example", "provider": "metron"}
        assert client.get("/api/comics/search", params=params).status_code == 502
        assert client.get("/api/comics/search", params=params).status_code == 409
        assert route.call_count == 1


@respx.mock
def test_metron_honours_an_exhausted_quota_header(tmp_path: Path):
    route = respx.get(f"{METRON}/series/").mock(
        return_value=Response(
            200,
            json={"results": []},
            headers={
                "X-RateLimit-Sustained-Remaining": "0",
                "X-RateLimit-Sustained-Reset": str(int(time.time()) + 600),
            },
        )
    )
    with metron_client(tmp_path) as client:
        unpaced(client)
        params = {"q": "example", "provider": "metron"}
        assert client.get("/api/comics/search", params=params).status_code == 200
        assert client.get("/api/comics/search", params=params).status_code == 409
        assert route.call_count == 1


def cv_search_hit():
    return cv_page([{"id": 4050, "name": "Example Comic", "start_year": "2019"}])


@respx.mock
def test_a_single_configured_catalogue_works_without_the_other(tmp_path: Path):
    cv = respx.get(f"{CV}/search/").mock(return_value=cv_search_hit())
    metron = respx.get(f"{METRON}/series/").mock(return_value=Response(401))
    with make_client(
        tmp_path, comicvine_enabled=True, comicvine_api_key="fixture-key"
    ) as client:
        body = client.get("/api/comics/search", params={"q": "example"}).json()
        assert [r["provider"] for r in body["results"]] == ["comicvine"]
        assert body["errors"] == []
        assert cv.call_count == 1
        assert metron.call_count == 0

    with metron_client(tmp_path / "second") as client:
        unpaced(client)
        respx.get(f"{METRON}/series/").mock(
            return_value=Response(200, json={"results": [{"id": 7, "name": "Other"}]})
        )
        body = client.get("/api/comics/search", params={"q": "example"}).json()
        assert [r["provider"] for r in body["results"]] == ["metron"]


@respx.mock
def test_search_all_merges_catalogues_and_reports_a_failing_one(tmp_path: Path):
    respx.get(f"{CV}/search/").mock(return_value=cv_search_hit())
    respx.get(f"{METRON}/series/").mock(return_value=Response(401))
    with make_client(
        tmp_path,
        comicvine_enabled=True,
        comicvine_api_key="fixture-key",
        metron_enabled=True,
        metron_username="fixture-user",
        metron_password="fixture-password",
    ) as client:
        unpaced(client)
        body = client.get("/api/comics/search", params={"q": "example"}).json()
        assert [r["provider"] for r in body["results"]] == ["comicvine"]
        assert [e["provider"] for e in body["errors"]] == ["Metron"]
        assert "fixture-password" not in str(body)
        # Metron is now halted, so the next search no longer asks it.
        again = client.get("/api/comics/search", params={"q": "example"}).json()
        assert again["errors"] == []


def test_search_all_refuses_when_no_catalogue_is_ready(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.get("/api/comics/search", params={"q": "example"})
        assert response.status_code == 409
        assert "Settings" in response.text


def test_comic_credentials_save_masked_and_either_can_stay_empty(tmp_path: Path):
    with make_client(tmp_path) as client:
        saved = client.put(
            "/api/settings",
            json={"comicvine_enabled": "true", "comicvine_api_key": "fixture-key"},
        )
        assert saved.status_code == 200, saved.text
        view = client.get("/api/settings").json()
        assert view["comicvine_api_key"]["value"] != "fixture-key"
        assert view["comicvine_enabled"]["value"] in (True, "true")
        assert "fixture-key" not in client.get("/api/settings").text
        providers = {p["name"]: p for p in client.get("/api/comics/providers").json()}
        assert providers["comicvine"]["configured"] is True
        assert providers["metron"]["configured"] is False

        refused = client.put("/api/settings", json={"metron_enabled": "true"})
        assert refused.status_code == 400
        assert "Metron" in refused.text
        refused = client.put(
            "/api/settings", json={"comicvine_api_key": "", "comicvine_enabled": "true"}
        )
        assert refused.status_code == 400
        assert "ComicVine" in refused.text


@respx.mock
def test_comicvine_test_button_reports_success_and_failure(tmp_path: Path):
    route = respx.get(f"{CV}/volumes/").mock(return_value=cv_page([{"id": 1}]))
    with make_client(tmp_path) as client:
        empty = client.post("/api/settings/test/comicvine", json={})
        assert empty.json()["ok"] is False
        assert route.call_count == 0

        ok = client.post(
            "/api/settings/test/comicvine", json={"comicvine_api_key": "fixture-key"}
        ).json()
        assert ok["ok"] is True
        assert route.call_count == 1

        route.mock(return_value=Response(200, json={"status_code": 100, "error": "x"}))
        bad = client.post(
            "/api/settings/test/comicvine", json={"comicvine_api_key": "fixture-secret"}
        ).json()
        assert bad["ok"] is False
        assert "fixture-secret" not in str(bad)


@respx.mock
def test_metron_test_button_uses_form_values_and_halts_on_a_rejection(tmp_path: Path):
    route = respx.get(f"{METRON}/series/").mock(
        return_value=Response(200, json={"results": []})
    )
    with make_client(tmp_path) as client:
        empty = client.post("/api/settings/test/metron", json={})
        assert empty.json()["ok"] is False
        assert route.call_count == 0

        form = {
            "metron_username": "fixture-user",
            "metron_password": "fixture-password",
        }
        assert client.post("/api/settings/test/metron", json=form).json()["ok"]
        assert route.call_count == 1

        # Save the credentials, then test them again: a 401 halts the live client.
        client.put("/api/settings", json={**form, "metron_enabled": "true"})
        route.mock(return_value=Response(401))
        unpaced(client)
        failed = client.post("/api/settings/test/metron", json=form).json()
        assert failed["ok"] is False
        assert "rejected the credentials" in failed["error"]
        calls = route.call_count
        again = client.post("/api/settings/test/metron", json=form).json()
        assert again["ok"] is False
        assert route.call_count == calls  # nothing more was sent
        paused = {p["name"]: p for p in client.get("/api/comics/providers").json()}
        assert paused["metron"]["paused"]

        # New credentials lift the halt.
        client.put(
            "/api/settings",
            json={"metron_username": "other-user", "metron_password": "other-pass"},
        )
        lifted = {p["name"]: p for p in client.get("/api/comics/providers").json()}
        assert lifted["metron"]["paused"] is None


@respx.mock
def test_metron_test_with_unsaved_values_respects_a_pause_already_in_force(
    tmp_path: Path,
):
    route = respx.get(f"{METRON}/series/").mock(return_value=Response(429))
    form = {"metron_username": "fixture-user", "metron_password": "fixture-password"}
    with make_client(tmp_path) as client:
        first = client.post("/api/settings/test/metron", json=form).json()
        assert first["ok"] is False
        assert route.call_count == 1
        other = {"metron_username": "second-user", "metron_password": "second-pass"}
        second = client.post("/api/settings/test/metron", json=other).json()
        assert second["ok"] is False and "paused" in second["error"]
        assert route.call_count == 1


@respx.mock
def test_comic_import_scans_matches_and_files_issues(tmp_path: Path):
    import_dir = tmp_path / "incoming"
    (import_dir / "Example Comic (2019)").mkdir(parents=True)
    source = import_dir / "Example Comic (2019)" / "Example Comic 001 (2019).cbz"
    source.write_bytes(b"PK-issue-one")
    (import_dir / "Stranger 004 (2001).cbz").write_bytes(b"PK-other")
    respx.get(f"{CV}/volume/4050-4050/").mock(
        return_value=Response(
            200,
            json={
                "status_code": 1,
                "results": {"id": 4050, "name": "Example Comic", "start_year": "2019"},
            },
        )
    )
    respx.get(f"{CV}/issues/").mock(
        return_value=cv_page(
            [{"id": 1, "issue_number": "1", "cover_date": "2019-01-01"}]
        )
    )
    with make_client(
        tmp_path,
        comicvine_enabled=True,
        comicvine_api_key="fixture-key",
        import_dir=import_dir,
    ) as client:
        added = client.post(
            "/api/comics/series",
            json={"provider": "comicvine", "provider_id": "4050"},
        ).json()
        scan = client.get("/api/comics/import/scan").json()
        by_label = {g["label"]: g for g in scan["groups"]}
        ready = by_label["Example Comic"]["files"][0]
        assert ready["status"] == "ready" and ready["issue_id"]
        assert by_label["Stranger"]["series_id"] is None
        assert by_label["Stranger"]["files"][0]["status"] == "unmatched"

        item = {
            "path": ready["path"],
            "series_id": added["id"],
            "issue_id": ready["issue_id"],
        }
        escape = {**item, "path": "../escape.cbz"}
        result = client.post(
            "/api/comics/import", json={"items": [item, escape]}
        ).json()
        assert result["imported"] == [ready["path"]]
        assert len(result["errors"]) == 1
        assert source.exists()  # copied, not moved
        issue = client.get(f"/api/comics/series/{added['id']}").json()["issues"][0]
        assert issue["status"] == "downloaded"
        assert Path(issue["file_path"]).read_bytes() == b"PK-issue-one"
        assert str(tmp_path / "library" / "Comics") in issue["file_path"]

        again = client.get("/api/comics/import/scan").json()
        statuses = {f["status"] for g in again["groups"] for f in g["files"]}
        assert "already_have" in statuses
