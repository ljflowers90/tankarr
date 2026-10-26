import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { Cover, EmptyState, Icon, Spinner, StatusPill, useApp } from "../components";
import type {
  ComicProviderStatus,
  ComicSearchResponse,
  ComicSearchResult,
  ComicSeriesSummary,
  ComicWantedIssue,
} from "../types";
import { t, tn } from "../i18n";
import ComicImport from "./ComicImport";

type Tab = "library" | "search" | "wanted" | "import";

const TABS: { tab: Tab; path: string; label: () => string }[] = [
  { tab: "library", path: "#/comics", label: () => t("Library") },
  { tab: "search", path: "#/comics/search", label: () => t("Add New") },
  { tab: "import", path: "#/comics/import", label: () => t("Library Import") },
  { tab: "wanted", path: "#/comics/wanted", label: () => t("Wanted") },
];

export default function ComicsPage({ tab, query }: { tab: Tab; query?: string }) {
  return (
    <div className="page">
      <h1 className="page-title">{t("Comics")}</h1>
      <div className="toolbar" role="tablist" aria-label={t("Comics")}>
        {TABS.map((item) => (
          <a
            key={item.tab}
            role="tab"
            aria-selected={tab === item.tab}
            className={`btn${tab === item.tab ? " btn-primary" : ""}`}
            href={item.path}
          >
            {item.label()}
          </a>
        ))}
      </div>
      {tab === "library" ? (
        <ComicLibrary />
      ) : tab === "search" ? (
        <ComicSearch initialQuery={query ?? ""} />
      ) : tab === "import" ? (
        <ComicImport />
      ) : (
        <ComicWanted />
      )}
    </div>
  );
}

function ComicLibrary() {
  const { notify } = useApp();
  const [series, setSeries] = useState<ComicSeriesSummary[] | null>(null);

  useEffect(() => {
    let live = true;
    api
      .comicSeriesList()
      .then((rows) => live && setSeries(rows))
      .catch((caught) => live && notify("error", String(caught)));
    return () => {
      live = false;
    };
  }, [notify]);

  if (series === null) return <Spinner />;
  if (series.length === 0) {
    return (
      <EmptyState
        icon="library"
        title={t("No comic series yet")}
        hint={t("Use Add New to search ComicVine or Metron and add a series.")}
      />
    );
  }
  return (
    <div className="poster-grid">
      {series.map((item) => (
        <a
          key={item.id}
          className="poster-card"
          href={`#/comics/series/${encodeURIComponent(item.id)}`}
          title={item.title}
        >
          <div className="poster-frame">
            <Cover url={item.cover_url} title={item.title} className="poster-image" />
          </div>
          <div className="poster-meta">
            <span className="poster-title">{item.title}</span>
            <span className="muted small">
              {t("{downloaded} / {total} issues", { downloaded: item.downloaded, total: item.issues })}
            </span>
          </div>
        </a>
      ))}
    </div>
  );
}

function providerNote(provider: ComicProviderStatus | undefined): string | null {
  if (!provider) return null;
  if (provider.paused) return t("{provider} is paused: {reason}", { provider: provider.label, reason: provider.paused });
  if (!provider.enabled) return t("{provider} is disabled. Enable it and add your credentials in the configuration.", { provider: provider.label });
  if (!provider.configured) return t("{provider} has no credentials set.", { provider: provider.label });
  return null;
}

function ComicSearch({ initialQuery }: { initialQuery: string }) {
  const { notify } = useApp();
  const [providers, setProviders] = useState<ComicProviderStatus[]>([]);
  const [provider, setProvider] = useState("all");
  const [query, setQuery] = useState(initialQuery);
  const [results, setResults] = useState<ComicSearchResult[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState<string | null>(null);

  const loadProviders = useCallback(() => {
    api.comicProviders().then(setProviders).catch(() => setProviders([]));
  }, []);
  useEffect(loadProviders, [loadProviders]);

  const usable = providers.filter((item) => item.enabled && item.configured && !item.paused);
  const current = providers.find((item) => item.name === provider);
  const note =
    provider === "all"
      ? providers.length && !usable.length
        ? t("No catalogue is ready. Add ComicVine or Metron credentials in Settings.")
        : null
      : providerNote(current);
  const [partial, setPartial] = useState<ComicSearchResponse["errors"]>([]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (query.trim().length < 2 || busy) return;
    setBusy(true);
    try {
      const found = await api.comicSearch(query.trim(), provider);
      setResults(found.results);
      setPartial(found.errors);
    } catch (caught) {
      notify("error", String(caught));
    } finally {
      setBusy(false);
      // A refused credential pauses the catalogue; show it straight away.
      loadProviders();
    }
  };

  const add = async (item: ComicSearchResult) => {
    const key = `${item.provider}:${item.provider_id}`;
    setAdding(key);
    try {
      const added = await api.comicAdd(item.provider, item.provider_id);
      window.location.hash = `#/comics/series/${encodeURIComponent(added.id)}`;
    } catch (caught) {
      notify("error", String(caught));
    } finally {
      setAdding(null);
      loadProviders();
    }
  };

  return (
    <>
      <form className="toolbar add-search-toolbar" onSubmit={submit}>
        <div className="toolbar-group toolbar-grow">
          <input
            className="input input-grow"
            type="search"
            enterKeyHint="search"
            placeholder={t("Series title…")}
            aria-label={t("Search comic catalogues")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <select
            className="input"
            aria-label={t("Comic catalogue")}
            value={provider}
            onChange={(event) => setProvider(event.target.value)}
          >
            <option value="all">{t("All available")}</option>
            {providers.map((item) => (
              <option key={item.name} value={item.name}>
                {item.label}
              </option>
            ))}
          </select>
          <button type="submit" className="btn btn-primary" disabled={busy || Boolean(note) || query.trim().length < 2}>
            <Icon name="search" /> {t("Search")}
          </button>
        </div>
      </form>
      {note ? (
        <div className="banner banner-warn">
          <Icon name="alert" /> {note}
        </div>
      ) : null}
      {partial.map((item) => (
        <div className="banner banner-warn" key={item.provider}>
          <Icon name="alert" /> {t("{provider} could not be searched: {error}", { provider: item.provider, error: item.error })}
        </div>
      ))}
      {busy ? (
        <Spinner />
      ) : results === null ? (
        <EmptyState
          icon="search"
          title={t("Search the catalogue")}
          hint={t("Catalogue requests are rate limited, so each search is sent only when you submit it.")}
        />
      ) : results.length === 0 ? (
        <EmptyState icon="search" title={t("No series found")} />
      ) : (
        <div className="result-list">
          {results.map((item) => {
            const key = `${item.provider}:${item.provider_id}`;
            return (
              <div key={key} className={`result-card ${item.in_library ? "result-card-existing" : ""}`}>
                <Cover url={item.cover_url} title={item.title} className="result-cover" />
                <div className="result-body">
                  <div className="result-title-row">
                    <h3>{item.title}</h3>
                    {item.year ? <span className="muted">({item.year})</span> : null}
                    {item.in_library ? <StatusPill kind="muted">{t("In library")}</StatusPill> : null}
                  </div>
                  {item.publisher ? <div className="muted">{item.publisher}</div> : null}
                  {item.issue_count ? (
                    <div className="muted small">{tn(item.issue_count, "{count} issue", "{count} issues")}</div>
                  ) : null}
                  <p className="result-description">{item.description || t("No description available.")}</p>
                </div>
                <div className="result-actions">
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={adding !== null}
                    onClick={() => void add(item)}
                  >
                    <Icon name="add" /> {item.in_library ? t("Refresh") : adding === key ? t("Adding…") : t("Add")}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

function ComicWanted() {
  const { notify } = useApp();
  const [issues, setIssues] = useState<ComicWantedIssue[] | null>(null);

  useEffect(() => {
    let live = true;
    api
      .comicWanted()
      .then((rows) => live && setIssues(rows))
      .catch((caught) => live && notify("error", String(caught)));
    return () => {
      live = false;
    };
  }, [notify]);

  if (issues === null) return <Spinner />;
  if (issues.length === 0) {
    return <EmptyState icon="wanted" title={t("No wanted issues")} hint={t("Monitored issues that are not downloaded appear here.")} />;
  }
  return (
    <div className="data-table-frame">
      <table className="table">
        <thead>
          <tr>
            <th>{t("Series")}</th>
            <th>{t("Issue")}</th>
            <th>{t("Cover date")}</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((issue) => (
            <tr key={issue.id}>
              <td>
                <a className="table-link" href={`#/comics/series/${encodeURIComponent(issue.series_id)}`}>
                  {issue.series_title}
                </a>
              </td>
              <td>#{issue.number}</td>
              <td>{issue.cover_date ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
