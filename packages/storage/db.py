from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL,
    retmax INTEGER NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS query_results (
    query_id INTEGER NOT NULL,
    pmid TEXT NOT NULL,
    rank INTEGER NOT NULL,
    PRIMARY KEY (query_id, pmid),
    FOREIGN KEY (query_id) REFERENCES queries(id)
);

CREATE TABLE IF NOT EXISTS records (
    pmid TEXT PRIMARY KEY,
    title TEXT,
    abstract TEXT,
    journal TEXT,
    year TEXT,
    authors_json TEXT,
    doi TEXT,
    pmcid TEXT,
    publication_types_json TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS scores (
    pmid TEXT NOT NULL,
    readability_score REAL NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (pmid)
);

CREATE TABLE IF NOT EXISTS artifacts (
    pmid TEXT PRIMARY KEY,
    headline TEXT,
    standfirst TEXT,
    story TEXT,
    prompt_text TEXT,
    abstract_snapshot TEXT,
    metadata_snapshot TEXT,
    featured_rank INTEGER,
    published_at REAL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS rate_limits (
    key TEXT PRIMARY KEY,
    last_request_at REAL NOT NULL
);
"""


def _utc_now_ts() -> float:
    return time.time()


class Storage:
    def __init__(self, path: str) -> None:
        self.path = path
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterable[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def acquire_rate_limit(self, key: str, min_interval: float) -> None:
        if min_interval <= 0:
            return
        wait_for = 0.0
        now = _utc_now_ts()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT last_request_at FROM rate_limits WHERE key = ?",
                (key,),
            ).fetchone()
            if row:
                last_request = float(row["last_request_at"])
                elapsed = now - last_request
                if elapsed < min_interval:
                    wait_for = min_interval - elapsed
                    now += wait_for
            conn.execute(
                "INSERT INTO rate_limits (key, last_request_at) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET last_request_at=excluded.last_request_at",
                (key, now),
            )
        if wait_for > 0:
            time.sleep(wait_for)

    def get_cached_search(
        self,
        term: str,
        retmax: int,
        max_age_seconds: Optional[float],
    ) -> Optional[List[str]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, created_at FROM queries WHERE term = ? AND retmax = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (term, retmax),
            ).fetchone()
            if not row:
                return None
            created_at = float(row["created_at"])
            if max_age_seconds is not None:
                age = _utc_now_ts() - created_at
                if age > max_age_seconds:
                    return None
            pmid_rows = conn.execute(
                "SELECT pmid FROM query_results WHERE query_id = ? ORDER BY rank ASC",
                (row["id"],),
            ).fetchall()
        return [pmid_row["pmid"] for pmid_row in pmid_rows]

    def save_search(self, term: str, retmax: int, pmids: List[str]) -> None:
        now = _utc_now_ts()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO queries (term, retmax, created_at) VALUES (?, ?, ?)",
                (term, retmax, now),
            )
            query_id = int(cur.lastrowid)
            if pmids:
                rows = [(query_id, pmid, idx) for idx, pmid in enumerate(pmids)]
                conn.executemany(
                    "INSERT INTO query_results (query_id, pmid, rank) VALUES (?, ?, ?)",
                    rows,
                )

    def find_latest_query_for_pmid(
        self,
        pmid: str,
        before_created_at: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        if not pmid:
            return None
        with self._connect() as conn:
            params: List[Any] = [pmid]
            where_clause = "WHERE qr.pmid = ?"
            if before_created_at is not None:
                where_clause += " AND q.created_at <= ?"
                params.append(before_created_at)
            row = conn.execute(
                "SELECT q.term, q.retmax, q.created_at "
                "FROM queries q "
                "JOIN query_results qr ON qr.query_id = q.id "
                f"{where_clause} "
                "ORDER BY q.created_at DESC LIMIT 1",
                params,
            ).fetchone()
            if row is None and before_created_at is not None:
                row = conn.execute(
                    "SELECT q.term, q.retmax, q.created_at "
                    "FROM queries q "
                    "JOIN query_results qr ON qr.query_id = q.id "
                    "WHERE qr.pmid = ? "
                    "ORDER BY q.created_at DESC LIMIT 1",
                    (pmid,),
                ).fetchone()
        if not row:
            return None
        return {
            "term": row["term"] or "",
            "retmax": int(row["retmax"]) if row["retmax"] is not None else 0,
            "created_at": float(row["created_at"]) if row["created_at"] is not None else None,
        }

    def upsert_records(self, records: List[Dict[str, Any]]) -> None:
        if not records:
            return
        now = _utc_now_ts()
        rows = []
        for record in records:
            pmid = record.get("pmid")
            if not pmid:
                continue
            authors = record.get("authors")
            publication_types = record.get("publication_types")
            rows.append(
                (
                    pmid,
                    record.get("title"),
                    record.get("abstract"),
                    record.get("journal"),
                    record.get("year"),
                    json.dumps(authors) if authors is not None else None,
                    record.get("doi"),
                    record.get("pmcid"),
                    json.dumps(publication_types) if publication_types is not None else None,
                    now,
                )
            )
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO records (pmid, title, abstract, journal, year, authors_json, doi, pmcid, "
                "publication_types_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(pmid) DO UPDATE SET "
                "title=excluded.title, abstract=excluded.abstract, journal=excluded.journal, "
                "year=excluded.year, authors_json=excluded.authors_json, doi=excluded.doi, "
                "pmcid=excluded.pmcid, publication_types_json=excluded.publication_types_json",
                rows,
            )

    def get_records(self, pmids: List[str]) -> Dict[str, Dict[str, Any]]:
        if not pmids:
            return {}
        placeholders = ",".join(["?"] * len(pmids))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT pmid, title, abstract, journal, year, authors_json, doi, pmcid, "
                f"publication_types_json FROM records WHERE pmid IN ({placeholders})",
                pmids,
            ).fetchall()
        return {row["pmid"]: self._row_to_record(row) for row in rows}

    def get_record(self, pmid: str) -> Optional[Dict[str, Any]]:
        records = self.get_records([pmid])
        return records.get(pmid)

    def get_scores(self, pmids: List[str]) -> Dict[str, float]:
        if not pmids:
            return {}
        placeholders = ",".join(["?"] * len(pmids))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT pmid, readability_score FROM scores WHERE pmid IN ({placeholders})",
                pmids,
            ).fetchall()
        return {row["pmid"]: float(row["readability_score"]) for row in rows}

    def upsert_scores(self, scores: Dict[str, float]) -> None:
        if not scores:
            return
        now = _utc_now_ts()
        rows = [(pmid, score, now) for pmid, score in scores.items()]
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO scores (pmid, readability_score, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(pmid) DO UPDATE SET readability_score=excluded.readability_score",
                rows,
            )

    def upsert_artifact(
        self,
        pmid: str,
        headline: str,
        standfirst: str,
        story: Dict[str, Any],
        prompt_text: str,
        abstract_snapshot: str,
        metadata_snapshot: Dict[str, Any],
    ) -> None:
        now = _utc_now_ts()
        story_json = json.dumps(story)
        metadata_json = json.dumps(metadata_snapshot)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO artifacts (pmid, headline, standfirst, story, prompt_text, abstract_snapshot, "
                "metadata_snapshot, featured_rank, published_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, "
                "(SELECT featured_rank FROM artifacts WHERE pmid = ?), "
                "(SELECT published_at FROM artifacts WHERE pmid = ?), ?) "
                "ON CONFLICT(pmid) DO UPDATE SET "
                "headline=excluded.headline, standfirst=excluded.standfirst, story=excluded.story, "
                "prompt_text=excluded.prompt_text, abstract_snapshot=excluded.abstract_snapshot, "
                "metadata_snapshot=excluded.metadata_snapshot, featured_rank=excluded.featured_rank, "
                "published_at=excluded.published_at, created_at=excluded.created_at",
                (
                    pmid,
                    headline,
                    standfirst,
                    story_json,
                    prompt_text,
                    abstract_snapshot,
                    metadata_json,
                    pmid,
                    pmid,
                    now,
                ),
            )

    def publish_artifact(self, pmid: str, featured_rank: Optional[int]) -> None:
        now = _utc_now_ts()
        with self._connect() as conn:
            if featured_rank is None:
                row = conn.execute(
                    "SELECT MAX(featured_rank) AS max_rank FROM artifacts WHERE featured_rank IS NOT NULL"
                ).fetchone()
                max_rank = row["max_rank"] if row and row["max_rank"] is not None else 0
                featured_rank = int(max_rank) + 1
            conn.execute(
                "UPDATE artifacts SET published_at = ?, featured_rank = ? WHERE pmid = ?",
                (now, featured_rank, pmid),
            )

    def unpublish_artifact(self, pmid: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE artifacts SET published_at = NULL, featured_rank = NULL WHERE pmid = ?",
                (pmid,),
            )

    def update_featured_rank(self, pmid: str, featured_rank: Optional[int]) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE artifacts SET featured_rank = ? WHERE pmid = ?",
                (featured_rank, pmid),
            )

    def update_artifact_metadata_snapshot(self, pmid: str, metadata_snapshot: Dict[str, Any]) -> None:
        metadata_json = json.dumps(metadata_snapshot)
        with self._connect() as conn:
            conn.execute(
                "UPDATE artifacts SET metadata_snapshot = ? WHERE pmid = ?",
                (metadata_json, pmid),
            )

    def get_artifact(self, pmid: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT pmid, headline, standfirst, story, prompt_text, abstract_snapshot, "
                "metadata_snapshot, featured_rank, published_at, created_at "
                "FROM artifacts WHERE pmid = ?",
                (pmid,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_artifact(row)

    def list_artifacts(self, published_only: bool = True) -> List[Dict[str, Any]]:
        where_clause = "WHERE published_at IS NOT NULL" if published_only else ""
        order_clause = (
            "ORDER BY CASE WHEN featured_rank IS NULL THEN 1 ELSE 0 END, "
            "featured_rank ASC, published_at DESC"
        )
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT pmid, headline, standfirst, story, prompt_text, abstract_snapshot, "
                "metadata_snapshot, featured_rank, published_at, created_at "
                f"FROM artifacts {where_clause} {order_clause}"
            ).fetchall()
        return [self._row_to_artifact(row) for row in rows]

    @staticmethod
    def _row_to_artifact(row: sqlite3.Row) -> Dict[str, Any]:
        story_raw = row["story"]
        metadata_raw = row["metadata_snapshot"]
        try:
            story = json.loads(story_raw) if story_raw else {}
        except json.JSONDecodeError:
            story = {}
        try:
            metadata = json.loads(metadata_raw) if metadata_raw else {}
        except json.JSONDecodeError:
            metadata = {}
        return {
            "pmid": row["pmid"],
            "headline": row["headline"] or "",
            "standfirst": row["standfirst"] or "",
            "story": story,
            "prompt_text": row["prompt_text"] or "",
            "abstract_snapshot": row["abstract_snapshot"] or "",
            "metadata_snapshot": metadata,
            "featured_rank": row["featured_rank"],
            "published_at": row["published_at"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> Dict[str, Any]:
        authors = row["authors_json"]
        publication_types = row["publication_types_json"]
        return {
            "pmid": row["pmid"],
            "title": row["title"],
            "abstract": row["abstract"],
            "journal": row["journal"],
            "year": row["year"],
            "authors": json.loads(authors) if authors else [],
            "doi": row["doi"],
            "pmcid": row["pmcid"],
            "publication_types": json.loads(publication_types) if publication_types else [],
        }
