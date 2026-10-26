import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { EmptyState, Icon, Spinner, useApp } from "../components";
import type { ComicImportFile, ComicImportGroup, ComicImportResult, ComicImportScan } from "../types";
import { t, tn } from "../i18n";

const ARCHIVE = /\.(cbz|cbr|cb7|cbt|pdf|epub)$/i;

const STATUS: Record<ComicImportFile["status"], () => string> = {
  ready: () => t("Ready"),
  already_have: () => t("Already in library"),
  no_issue: () => t("Issue not in series"),
  unmatched: () => t("Not in library"),
  unsupported: () => t("Not a single issue"),
};

function size(bytes: number) {
  return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export default function ComicImport() {
  const { notify } = useApp();
  const [scan, setScan] = useState<ComicImportScan | null>(null);
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [move, setMove] = useState(false);
  const [result, setResult] = useState<ComicImportResult | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    folderInput.current?.setAttribute("webkitdirectory", "");
    folderInput.current?.setAttribute("directory", "");
  }, []);

  const load = useCallback((next: ComicImportScan) => {
    setScan(next);
    setResult(null);
    setSelected(
      new Set(next.groups.flatMap((group) => group.files.filter((file) => file.status === "ready").map((file) => file.path))),
    );
  }, []);

  const discard = useCallback(async (id: string | null) => {
    if (id) await api.importDeleteUpload(id).catch(() => undefined);
  }, []);

  const scanFolder = async () => {
    setBusy(t("Scanning…"));
    try {
      load(await api.comicImportScan());
      await discard(uploadId);
      setUploadId(null);
    } catch (caught) {
      notify("error", String(caught));
    } finally {
      setBusy(null);
    }
  };

  const upload = async (list: FileList | null) => {
    const files = Array.from(list ?? []).filter((file) => ARCHIVE.test(file.name));
    if (!files.length) {
      if (list?.length) notify("error", t("No supported comic archives selected."));
      return;
    }
    let id: string | null = null;
    try {
      setBusy(t("Uploading…"));
      id = (await api.importCreateUpload()).upload_id;
      for (const file of files) {
        const path = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
        await api.importUploadFile(id, path, file);
      }
      load(await api.comicImportScan(id));
      await discard(uploadId);
      setUploadId(id);
    } catch (caught) {
      await discard(id);
      notify("error", String(caught));
    } finally {
      setBusy(null);
      if (fileInput.current) fileInput.current.value = "";
      if (folderInput.current) folderInput.current.value = "";
    }
  };

  const toggle = (path: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (!next.delete(path)) next.add(path);
      return next;
    });

  const importSelected = async () => {
    if (!scan) return;
    const items = scan.groups.flatMap((group) =>
      group.files
        .filter((file) => selected.has(file.path) && file.status === "ready" && group.series_id && file.issue_id)
        .map((file) => ({ path: file.path, series_id: group.series_id!, issue_id: file.issue_id! })),
    );
    if (!items.length) return;
    setBusy(t("Importing…"));
    try {
      const done = await api.comicImport(items, { uploadId: uploadId ?? undefined, move });
      setResult(done);
      notify(
        done.errors.length ? "error" : "success",
        tn(done.imported.length, "{count} issue imported.", "{count} issues imported."),
      );
      load(await api.comicImportScan(uploadId ?? undefined));
      setResult(done);
    } catch (caught) {
      notify("error", String(caught));
    } finally {
      setBusy(null);
    }
  };

  const ready = scan ? scan.groups.reduce((n, g) => n + g.files.filter((f) => f.status === "ready").length, 0) : 0;
  const chosen = scan
    ? scan.groups.reduce((n, g) => n + g.files.filter((f) => f.status === "ready" && selected.has(f.path)).length, 0)
    : 0;

  return (
    <>
      <input
        ref={fileInput}
        className="visually-hidden"
        type="file"
        multiple
        accept=".cbz,.cbr,.cb7,.cbt,.pdf,.epub"
        aria-label={t("Choose comic files")}
        onChange={(event) => void upload(event.target.files)}
      />
      <input
        ref={folderInput}
        className="visually-hidden"
        type="file"
        multiple
        aria-label={t("Choose comic folder")}
        onChange={(event) => void upload(event.target.files)}
      />
      <div className="toolbar">
        <div className="toolbar-group">
          <button type="button" className="btn" disabled={Boolean(busy)} onClick={() => void scanFolder()}>
            <Icon name="refresh" /> {t("Scan import folder")}
          </button>
          <button type="button" className="btn" disabled={Boolean(busy)} onClick={() => fileInput.current?.click()}>
            <Icon name="upload" /> {t("Choose files")}
          </button>
          <button type="button" className="btn" disabled={Boolean(busy)} onClick={() => folderInput.current?.click()}>
            <Icon name="upload" /> {t("Choose folder")}
          </button>
        </div>
        {scan ? (
          <div className="toolbar-group">
            <label className="muted small">
              <input type="checkbox" checked={move} onChange={(event) => setMove(event.target.checked)} />{" "}
              {t("Move files instead of copying")}
            </label>
            <button
              type="button"
              className="btn btn-primary"
              disabled={Boolean(busy) || chosen === 0}
              onClick={() => void importSelected()}
            >
              <Icon name="check" /> {tn(chosen, "Import {count} issue", "Import {count} issues")}
            </button>
          </div>
        ) : null}
      </div>
      <p className="muted small">
        {t("Only issues of series already in your library are imported. Add other series first, then scan again.")}
      </p>
      {busy ? <Spinner /> : null}
      {result?.errors.length ? (
        <div className="banner banner-warn">
          <Icon name="alert" /> {result.errors.map((item) => `${item.path}: ${item.error}`).join("; ")}
        </div>
      ) : null}
      {!scan ? (
        <EmptyState
          icon="upload"
          title={t("Import existing comics")}
          hint={t("Scan the import folder or choose CBZ, CBR or PDF files to match them to the series you track.")}
        />
      ) : scan.groups.length === 0 ? (
        <EmptyState icon="upload" title={t("No comic files found")} hint={scan.root} />
      ) : (
        <>
          <p className="muted small">
            {tn(ready, "{count} issue ready to import", "{count} issues ready to import")}
            {scan.truncated ? ` · ${t("The scan stopped at the file limit.")}` : ""}
          </p>
          {scan.groups.map((group) => (
            <ImportGroup key={group.key} group={group} selected={selected} toggle={toggle} />
          ))}
        </>
      )}
    </>
  );
}

function ImportGroup({
  group,
  selected,
  toggle,
}: {
  group: ComicImportGroup;
  selected: Set<string>;
  toggle: (path: string) => void;
}) {
  return (
    <section className="card">
      <h3>
        {group.series_id ? (
          <a href={`#/comics/series/${encodeURIComponent(group.series_id)}`}>{group.label}</a>
        ) : (
          group.label
        )}
        {group.year ? <span className="muted"> ({group.year})</span> : null}
        {group.series_id ? null : (
          <a className="btn btn-small" href={`#/comics/search?q=${encodeURIComponent(group.label)}`}>
            <Icon name="search" /> {t("Find in catalogue")}
          </a>
        )}
      </h3>
      <ul className="plain-list">
        {group.files.map((file) => (
          <li key={file.path}>
            <label>
              <input
                type="checkbox"
                disabled={file.status !== "ready"}
                checked={selected.has(file.path)}
                onChange={() => toggle(file.path)}
              />{" "}
              {file.name}
            </label>{" "}
            <span className="muted small">
              {file.issue ? `#${file.issue} · ` : ""}
              {size(file.size)} · {STATUS[file.status]()}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
