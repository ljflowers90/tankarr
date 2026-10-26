import { useEffect, useState } from "react";
import { api } from "../api";
import { Cover, EmptyState, Icon, Spinner, StatusPill, navigate, useApp } from "../components";
import type { ComicSeries } from "../types";
import { t, tn } from "../i18n";

export default function ComicSeriesPage({ id }: { id: string }) {
  const { notify } = useApp();
  const [series, setSeries] = useState<ComicSeries | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .comicSeries(id)
      .then((value) => live && setSeries(value))
      .catch((caught) => {
        if (!live) return;
        if (String(caught).includes("404")) setMissing(true);
        else notify("error", String(caught));
      });
    return () => {
      live = false;
    };
  }, [id, notify]);

  if (missing) return <div className="page"><EmptyState icon="library" title={t("Comic series not found")} /></div>;
  if (!series) return <div className="page"><Spinner /></div>;

  const toggleMonitor = async () => {
    try {
      setSeries(await api.comicMonitor(series.id, !series.monitored));
    } catch (caught) {
      notify("error", String(caught));
    }
  };

  const remove = async () => {
    if (!window.confirm(t("Remove {title} from Tankarr? Files are not deleted.", { title: series.title }))) return;
    try {
      await api.comicDelete(series.id);
      navigate("/comics");
    } catch (caught) {
      notify("error", String(caught));
    }
  };

  const downloaded = series.issues.filter((issue) => issue.status === "downloaded").length;

  return (
    <div className="page">
      <a className="btn btn-ghost" href="#/comics">
        <Icon name="library" /> {t("Comics")}
      </a>
      <div className="result-card">
        <Cover url={series.cover_url} title={series.title} className="result-cover" />
        <div className="result-body">
          <div className="result-title-row">
            <h1 className="page-title">{series.title}</h1>
            {series.year ? <span className="muted">({series.year})</span> : null}
            <StatusPill kind={series.monitored ? "info" : "muted"}>
              {series.monitored ? t("Monitored") : t("Not monitored")}
            </StatusPill>
          </div>
          {series.publisher ? <div className="muted">{series.publisher}</div> : null}
          <div className="muted small">
            {tn(series.issues.length, "{count} issue", "{count} issues")} ·{" "}
            {t("{count} downloaded", { count: downloaded })}
          </div>
          <p className="result-description">{series.description || t("No description available.")}</p>
        </div>
        <div className="result-actions">
          <button type="button" className="btn" onClick={() => void toggleMonitor()}>
            {series.monitored ? t("Stop monitoring") : t("Monitor")}
          </button>
          <button type="button" className="btn btn-danger" onClick={() => void remove()}>
            <Icon name="trash" /> {t("Remove")}
          </button>
        </div>
      </div>
      <div className="data-table-frame">
        <table className="table">
          <thead>
            <tr>
              <th>#</th>
              <th>{t("Title")}</th>
              <th>{t("Cover date")}</th>
              <th>{t("Status")}</th>
            </tr>
          </thead>
          <tbody>
            {series.issues.map((issue) => (
              <tr key={issue.id}>
                <td>{issue.number}</td>
                <td>{issue.title ?? "—"}</td>
                <td>{issue.cover_date ?? "—"}</td>
                <td>
                  <StatusPill kind={issue.status === "downloaded" ? "success" : "muted"}>
                    {issue.status === "downloaded" ? t("Downloaded") : t("Wanted")}
                  </StatusPill>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
