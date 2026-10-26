"""Persistence for tracked comic series and their issues."""

from __future__ import annotations

import uuid

from tankarr.comics.base import ComicIssue, ComicSeries
from tankarr.database import Database, utc_now


class ComicStore:
    def __init__(self, database: Database):
        self.database = database

    def add_series(self, series: ComicSeries, issues: list[ComicIssue]) -> dict:
        """Track a series and its issues. Re-adding refreshes it in place."""

        now = utc_now()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id FROM comic_series WHERE provider=? AND provider_id=?",
                (series.provider, series.provider_id),
            ).fetchone()
            series_id = row["id"] if row else uuid.uuid4().hex
            if row:
                connection.execute(
                    "UPDATE comic_series SET title=?, publisher=?, year=?,"
                    " description=?, cover_url=?, issue_count=?, status=?,"
                    " updated_at=? WHERE id=?",
                    (
                        series.title,
                        series.publisher,
                        series.year,
                        series.description,
                        series.cover_url,
                        series.issue_count,
                        series.status,
                        now,
                        series_id,
                    ),
                )
            else:
                connection.execute(
                    "INSERT INTO comic_series (id, provider, provider_id, title,"
                    " publisher, year, description, cover_url, issue_count,"
                    " status, added_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        series_id,
                        series.provider,
                        series.provider_id,
                        series.title,
                        series.publisher,
                        series.year,
                        series.description,
                        series.cover_url,
                        series.issue_count,
                        series.status,
                        now,
                        now,
                    ),
                )
            # New issues arrive as wanted; existing rows keep their status.
            for issue in issues:
                connection.execute(
                    "INSERT INTO comic_issue (id, series_id, provider_id, number,"
                    " title, cover_date, store_date) VALUES (?,?,?,?,?,?,?)"
                    " ON CONFLICT(series_id, provider_id) DO UPDATE SET"
                    " number=excluded.number, title=excluded.title,"
                    " cover_date=excluded.cover_date,"
                    " store_date=excluded.store_date",
                    (
                        uuid.uuid4().hex,
                        series_id,
                        issue.provider_id,
                        issue.number,
                        issue.title,
                        issue.cover_date,
                        issue.store_date,
                    ),
                )
        return self.get_series(series_id)

    def list_series(self) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT s.*,"
                " COUNT(i.id) AS issues,"
                " COALESCE(SUM(i.status='downloaded'), 0) AS downloaded,"
                " COALESCE(SUM(i.status='wanted' AND i.monitored=1), 0) AS wanted"
                " FROM comic_series s LEFT JOIN comic_issue i ON i.series_id=s.id"
                " GROUP BY s.id ORDER BY s.title COLLATE NOCASE"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_series(self, series_id: str) -> dict:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM comic_series WHERE id=?", (series_id,)
            ).fetchone()
            if row is None:
                raise KeyError(series_id)
            issues = connection.execute(
                "SELECT * FROM comic_issue WHERE series_id=?"
                " ORDER BY CAST(number AS REAL), number",
                (series_id,),
            ).fetchall()
        return {**dict(row), "issues": [dict(issue) for issue in issues]}

    def wanted(self) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT i.*, s.title AS series_title FROM comic_issue i"
                " JOIN comic_series s ON s.id=i.series_id"
                " WHERE i.status='wanted' AND i.monitored=1 AND s.monitored=1"
                " ORDER BY s.title COLLATE NOCASE, CAST(i.number AS REAL)"
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_downloaded(self, issue_id: str, file_path: str) -> None:
        with self.database.connect() as connection:
            changed = connection.execute(
                "UPDATE comic_issue SET status='downloaded', file_path=? WHERE id=?",
                (file_path, issue_id),
            ).rowcount
        if not changed:
            raise KeyError(issue_id)

    def set_series_monitored(self, series_id: str, monitored: bool) -> None:
        with self.database.connect() as connection:
            changed = connection.execute(
                "UPDATE comic_series SET monitored=?, updated_at=? WHERE id=?",
                (int(monitored), utc_now(), series_id),
            ).rowcount
        if not changed:
            raise KeyError(series_id)

    def delete_series(self, series_id: str) -> None:
        with self.database.connect() as connection:
            changed = connection.execute(
                "DELETE FROM comic_series WHERE id=?", (series_id,)
            ).rowcount
        if not changed:
            raise KeyError(series_id)
