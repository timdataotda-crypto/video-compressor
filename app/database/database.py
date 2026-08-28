from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from app.models.job import Job, JobStatus
from app.utils.paths import ensure_dir, get_database_path


class Database:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or get_database_path()
        ensure_dir(self.path.parent)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        # timeout + WAL mencegah "database is locked" saat beberapa worker
        # menulis progress bersamaan (penguncian di Windows lebih ketat).
        conn = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
            timeout=30.0,
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.DatabaseError:
            pass
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_path TEXT NOT NULL,
                    output_path TEXT NOT NULL,
                    duration REAL DEFAULT 0,
                    original_size INTEGER DEFAULT 0,
                    output_size INTEGER DEFAULT 0,
                    video_bitrate INTEGER DEFAULT 0,
                    resolution TEXT DEFAULT '',
                    status TEXT DEFAULT 'PENDING',
                    progress REAL DEFAULT 0,
                    attempt INTEGER DEFAULT 0,
                    error TEXT DEFAULT '',
                    created_at TEXT,
                    started_at TEXT,
                    completed_at TEXT
                )
                """
            )
            conn.commit()

    def clear_jobs(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM jobs")
            conn.commit()

    def insert_job(self, job: Job) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO jobs (
                    source_path, output_path, duration, original_size, output_size,
                    video_bitrate, resolution, status, progress, attempt, error,
                    created_at, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.source_path,
                    job.output_path,
                    job.duration,
                    job.original_size,
                    job.output_size,
                    job.video_bitrate,
                    job.resolution,
                    job.status.value,
                    job.progress,
                    job.attempt,
                    job.error,
                    job.created_at,
                    job.started_at,
                    job.completed_at,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def update_job(self, job: Job) -> None:
        if job.id is None:
            return
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs SET
                    source_path=?, output_path=?, duration=?, original_size=?,
                    output_size=?, video_bitrate=?, resolution=?, status=?,
                    progress=?, attempt=?, error=?, created_at=?, started_at=?,
                    completed_at=?
                WHERE id=?
                """,
                (
                    job.source_path,
                    job.output_path,
                    job.duration,
                    job.original_size,
                    job.output_size,
                    job.video_bitrate,
                    job.resolution,
                    job.status.value,
                    job.progress,
                    job.attempt,
                    job.error,
                    job.created_at,
                    job.started_at,
                    job.completed_at,
                    job.id,
                ),
            )
            conn.commit()

    def list_jobs(
        self,
        statuses: Optional[Iterable[JobStatus]] = None,
    ) -> list[Job]:
        with self._connect() as conn:
            if statuses:
                placeholders = ",".join("?" for _ in statuses)
                rows = conn.execute(
                    f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY id",
                    [s.value for s in statuses],
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()
        return [self._row_to_job(r) for r in rows]

    def count_incomplete(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c FROM jobs
                WHERE status IN ('PENDING', 'FAILED', 'CANCELLED',
                                 'ANALYZING', 'COMPRESSING', 'VALIDATING')
                """
            ).fetchone()
        return int(row["c"]) if row else 0

    def reset_interrupted_jobs(self) -> int:
        """Crash-safe: in-flight jobs become PENDING again on startup."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE jobs
                SET status='PENDING', progress=0, error=''
                WHERE status IN ('ANALYZING', 'COMPRESSING', 'VALIDATING')
                """
            )
            conn.commit()
            return int(cur.rowcount)

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            source_path=row["source_path"],
            output_path=row["output_path"],
            duration=row["duration"] or 0.0,
            original_size=row["original_size"] or 0,
            output_size=row["output_size"] or 0,
            video_bitrate=row["video_bitrate"] or 0,
            resolution=row["resolution"] or "",
            status=JobStatus(row["status"]),
            progress=row["progress"] or 0.0,
            attempt=row["attempt"] or 0,
            error=row["error"] or "",
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )
