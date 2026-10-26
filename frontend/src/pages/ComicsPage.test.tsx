import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../api";
import { AppContext } from "../components";
import type { ComicProviderStatus, ComicSeries, ComicSeriesSummary } from "../types";
import ComicSeriesPage from "./ComicSeriesPage";
import ComicsPage from "./ComicsPage";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const notify = vi.fn();
function app(node: React.ReactNode) {
  return render(
    <AppContext.Provider value={{ health: null, notify, refreshJobs: vi.fn(), refreshHealth: vi.fn() }}>{node}</AppContext.Provider>,
  );
}

const provider: ComicProviderStatus = { name: "comicvine", label: "ComicVine", enabled: true, configured: true, paused: null };
const summary: ComicSeriesSummary = {
  id: "s1", provider: "comicvine", provider_id: "4050", title: "Example Comic", publisher: "Example Press", year: 2019,
  description: null, cover_url: null, issue_count: 2, status: null, monitored: 1, issues: 2, downloaded: 1, wanted: 1,
};
const detail: ComicSeries = {
  ...summary,
  issues: [
    { id: "i1", series_id: "s1", provider_id: "1", number: "1", title: null, cover_date: "2019-01-01", store_date: null, status: "downloaded", monitored: 1, file_path: null },
    { id: "i2", series_id: "s1", provider_id: "2", number: "2", title: null, cover_date: "2019-02-01", store_date: null, status: "wanted", monitored: 1, file_path: null },
  ],
};

it("lists tracked comic series with their download progress", async () => {
  vi.spyOn(api, "comicSeriesList").mockResolvedValue([summary]);
  app(<ComicsPage tab="library" />);
  const card = await screen.findByRole("link", { name: /Example Comic/ });
  expect(card.getAttribute("href")).toBe("#/comics/series/s1");
  expect(screen.getByText("1 / 2 issues")).toBeTruthy();
});

it("shows the empty state when no series is tracked", async () => {
  vi.spyOn(api, "comicSeriesList").mockResolvedValue([]);
  app(<ComicsPage tab="library" />);
  expect(await screen.findByText("No comic series yet")).toBeTruthy();
});

it("searches only on submit and adds the chosen series", async () => {
  vi.spyOn(api, "comicProviders").mockResolvedValue([provider]);
  const search = vi.spyOn(api, "comicSearch").mockResolvedValue({ errors: [], results: [
    { provider: "comicvine", provider_id: "4050", title: "Example Comic", publisher: "Example Press", year: 2019, description: null, cover_url: null, issue_count: 2, status: null, in_library: false },
  ] });
  const add = vi.spyOn(api, "comicAdd").mockResolvedValue(detail);
  app(<ComicsPage tab="search" />);
  const input = await screen.findByLabelText("Search comic catalogues");
  fireEvent.change(input, { target: { value: "exam" } });
  fireEvent.change(input, { target: { value: "example" } });
  expect(search).not.toHaveBeenCalled();
  fireEvent.submit(input.closest("form")!);
  await waitFor(() => expect(search).toHaveBeenCalledWith("example", "all"));
  fireEvent.click(await screen.findByRole("button", { name: /Add/ }));
  await waitFor(() => expect(add).toHaveBeenCalledWith("comicvine", "4050"));
});

it("disables search and explains why while a catalogue is paused", async () => {
  vi.spyOn(api, "comicProviders").mockResolvedValue([{ ...provider, paused: "Metron rejected the credentials (HTTP 401)" }]);
  const search = vi.spyOn(api, "comicSearch");
  app(<ComicsPage tab="search" />);
  expect(await screen.findByText(/No catalogue is ready/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Comic catalogue"), { target: { value: "comicvine" } });
  expect(await screen.findByText(/is paused: Metron rejected the credentials/)).toBeTruthy();
  const button = screen.getByRole("button", { name: /Search/ }) as HTMLButtonElement;
  fireEvent.change(screen.getByLabelText("Search comic catalogues"), { target: { value: "example" } });
  expect(button.disabled).toBe(true);
  expect(search).not.toHaveBeenCalled();
});

it("shows a series' issues and toggles monitoring", async () => {
  vi.spyOn(api, "comicSeries").mockResolvedValue(detail);
  const monitor = vi.spyOn(api, "comicMonitor").mockResolvedValue({ ...detail, monitored: 0 });
  app(<ComicSeriesPage id="s1" />);
  expect(await screen.findByRole("heading", { name: "Example Comic" })).toBeTruthy();
  expect(screen.getByText("1 downloaded", { exact: false })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Stop monitoring" }));
  await waitFor(() => expect(monitor).toHaveBeenCalledWith("s1", false));
  expect(await screen.findByText("Not monitored")).toBeTruthy();
});

it("scans for comics to import and files only the ready ones", async () => {
  vi.spyOn(api, "comicProviders").mockResolvedValue([provider]);
  const scan = {
    root: "/import",
    skipped: [],
    truncated: false,
    groups: [
      {
        key: "series:s1",
        label: "Example Comic",
        year: 2019,
        series_id: "s1",
        files: [
          { path: "a/Example Comic 002.cbz", name: "Example Comic 002.cbz", size: 2048, issue: "002", year: 2019, issue_id: "i2", status: "ready" as const },
        ],
      },
      {
        key: "guess:stranger:",
        label: "Stranger",
        year: null,
        series_id: null,
        files: [{ path: "Stranger 004.cbz", name: "Stranger 004.cbz", size: 1024, issue: "004", year: null, issue_id: null, status: "unmatched" as const }],
      },
    ],
  };
  vi.spyOn(api, "comicImportScan").mockResolvedValue(scan);
  const run = vi.spyOn(api, "comicImport").mockResolvedValue({ imported: ["a/Example Comic 002.cbz"], errors: [] });
  app(<ComicsPage tab="import" />);
  fireEvent.click(await screen.findByRole("button", { name: /Scan import folder/ }));
  expect(await screen.findByText("Stranger")).toBeTruthy();
  expect(screen.getByRole("link", { name: /Find in catalogue/ }).getAttribute("href")).toBe("#/comics/search?q=Stranger");
  fireEvent.click(screen.getByRole("button", { name: /Import 1 issue/ }));
  await waitFor(() =>
    expect(run).toHaveBeenCalledWith([{ path: "a/Example Comic 002.cbz", series_id: "s1", issue_id: "i2" }], { uploadId: undefined, move: false }),
  );
});
