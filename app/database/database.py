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
            self._migrate_columns(conn)

    def _migrate_columns(self, conn: sqlite3.Connection) -> None:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        additions = {
            "geopas_paket_id": "INTEGER",
            "geopas_paket_nama": "TEXT DEFAULT ''",
            "batch_source": "TEXT DEFAULT ''",
        }
        for name, ddl in additions.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {ddl}")
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
                    created_at, started_at, completed_at,
                    geopas_paket_id, geopas_paket_nama, batch_source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    job.geopas_paket_id,
                    job.geopas_paket_nama,
                    job.batch_source,
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
                    completed_at=?, geopas_paket_id=?, geopas_paket_nama=?,
                    batch_source=?
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
                    job.geopas_paket_id,
                    job.geopas_paket_nama,
                    job.batch_source,
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
                                 'ANALYZING', 'COMPRESSING', 'VALIDATING',
                                 'UPLOADING', 'UPLOAD_FAILED')
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
            conn.execute(
                """
                UPDATE jobs
                SET status='COMPLETED'
                WHERE status='UPLOADING'
                """
            )
            conn.commit()
            return int(cur.rowcount)

    def delete_jobs_for_batch(
        self, batch_source: str, paket_id: Optional[int]
    ) -> int:
        with self._connect() as conn:
            if paket_id is None:
                cur = conn.execute(
                    """
                    DELETE FROM jobs
                    WHERE batch_source=? AND geopas_paket_id IS NULL
                    """,
                    (batch_source,),
                )
            else:
                cur = conn.execute(
                    """
                    DELETE FROM jobs
                    WHERE batch_source=? AND geopas_paket_id=?
                    """,
                    (batch_source, paket_id),
                )
            conn.commit()
            return int(cur.rowcount)

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        keys = set(row.keys())
        paket_raw = row["geopas_paket_id"] if "geopas_paket_id" in keys else None
        paket_id = int(paket_raw) if paket_raw not in (None, "") else None
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
            geopas_paket_id=paket_id,
            geopas_paket_nama=(
                str(row["geopas_paket_nama"] or "")
                if "geopas_paket_nama" in keys
                else ""
            ),
            batch_source=(
                str(row["batch_source"] or "") if "batch_source" in keys else ""
            ),
        )
